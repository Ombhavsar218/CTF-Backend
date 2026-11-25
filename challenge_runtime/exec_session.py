"""Internal wrapper around a Docker exec stream.

This module is deliberately part of ``challenge_runtime``: the Docker SDK and
its transport-specific socket objects must never escape this boundary. The
object returned to callers exposes only bounded read/write/resize/close
operations and never logs or serialises the exec ID.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from .errors import (
    ExecInspectionFailed,
    ExecResizeFailed,
    ExecSessionError,
    ExecStreamClosed,
)


def _read_from_socket(sock: Any, amount: int) -> bytes:
    """Read through the SDK's transport-aware helper.

    ``exec_start(socket=True)`` can return a normal socket, a ``SocketIO``, an
    SSH channel, or a named-pipe wrapper depending on ``DOCKER_HOST``. The SDK
    helper handles those variants; raw ``recv()`` must not be assumed.
    """
    from docker.utils.socket import read as docker_socket_read  # local import

    return docker_socket_read(sock, amount)


def _write_to_socket(sock: Any, data: bytes) -> None:
    """Write all bytes using whichever transport primitive the SDK returned."""
    view = memoryview(data)
    if hasattr(sock, 'sendall'):
        sock.sendall(data)
        return
    if hasattr(sock, 'send'):
        while view:
            written = sock.send(view)
            if written is None:
                written = len(view)
            if written <= 0:
                raise ExecStreamClosed('Terminal stream closed while writing')
            view = view[written:]
        return
    if hasattr(sock, 'write'):
        while view:
            written = sock.write(view)
            if written is None:
                written = len(view)
            if written <= 0:
                raise ExecStreamClosed('Terminal stream closed while writing')
            view = view[written:]
        return
    # Last-resort POSIX fallback for a bare file descriptor.
    fd = sock.fileno()
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise ExecStreamClosed('Terminal stream closed while writing')
        view = view[written:]


class ExecSession:
    """A single interactive Docker exec session. Internal use only.

    Read and write/control operations use separate locks. A blocking output
    read must never hold the lock needed to write input, resize, or close.
    """

    def __init__(self, exec_id: str, sock: Any, api: Any):
        self._exec_id = exec_id
        self._sock = sock
        self._api = api
        self._state_lock = threading.RLock()
        self._read_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = False

    def __repr__(self):  # pragma: no cover - safety guard
        return '<ExecSession internal>'

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    @property
    def exec_id(self) -> str:
        """Internal identifier for DB coordination; never sent to a client."""
        return self._exec_id

    def _socket_if_open(self):
        with self._state_lock:
            if self._closed:
                return None
            return self._sock

    def read(self, amount: int = 4096) -> bytes:
        """Return up to ``amount`` output bytes; b'' means EOF."""
        with self._read_lock:
            sock = self._socket_if_open()
            if sock is None:
                return b''
            try:
                data = _read_from_socket(sock, max(1, int(amount)))
            except ExecStreamClosed:
                raise
            except (BrokenPipeError, ConnectionError, OSError) as exc:
                raise ExecStreamClosed('Terminal stream closed') from exc
            except Exception as exc:
                raise ExecSessionError('Terminal output failed') from exc
        return data or b''

    def write(self, data: bytes) -> None:
        """Write a terminal input chunk to exec stdin."""
        if not data:
            return
        with self._write_lock:
            sock = self._socket_if_open()
            if sock is None:
                raise ExecStreamClosed('Terminal stream is closed')
            try:
                _write_to_socket(sock, bytes(data))
            except ExecStreamClosed:
                raise
            except (BrokenPipeError, ConnectionError, OSError) as exc:
                raise ExecStreamClosed('Terminal stream closed') from exc
            except Exception as exc:
                raise ExecSessionError('Terminal input failed') from exc

    def resize(self, rows: int, cols: int) -> None:
        """Resize the PTY using Docker's exec resize API."""
        with self._write_lock:
            if self._socket_if_open() is None:
                raise ExecStreamClosed('Terminal stream is closed')
            try:
                self._api.exec_resize(self._exec_id, height=int(rows), width=int(cols))
            except Exception as exc:
                raise ExecResizeFailed('Terminal resize failed') from exc

    def inspect(self) -> dict:
        """Return a bounded exec-state summary, never a raw SDK response."""
        with self._write_lock:
            if self._socket_if_open() is None:
                return {'running': False, 'exit_code': None}
            try:
                result = self._api.exec_inspect(self._exec_id) or {}
            except Exception as exc:
                raise ExecInspectionFailed('Terminal state is unavailable') from exc
        return {
            'running': bool(result.get('Running')),
            'exit_code': result.get('ExitCode'),
        }

    def close(self) -> None:
        """Close the stream and release SDK resources. Safe to call twice."""
        with self._write_lock:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True
                sock = self._sock
            try:
                if sock is not None and hasattr(sock, 'close'):
                    sock.close()
            except Exception:
                pass
            # The SDK attaches the HTTP response to the raw socket for TLS
            # lifetime. Closing it releases the upgrade connection cleanly.
            response = getattr(sock, '_response', None) if sock is not None else None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
