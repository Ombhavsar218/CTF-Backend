"""Manager-backed exec session with the same interface as Docker ExecSession."""
from __future__ import annotations

import base64
import threading

from .errors import ExecInspectionFailed, ExecResizeFailed, ExecSessionError, ExecStreamClosed


class ManagerExecSession:
    def __init__(self, client, instance_id: str, exec_id: str, user_id: str | None = None):
        self._client = client
        self._instance_id = str(instance_id)
        self._exec_id = str(exec_id)
        self._user_id = str(user_id) if user_id is not None else None
        self._closed = False
        self._lock = threading.Lock()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def exec_id(self) -> str:
        return self._exec_id

    def read(self, amount: int = 4096) -> bytes:
        if self.closed:
            return b""
        try:
            res = self._client.read_terminal(
                self._instance_id, self._exec_id, max_bytes=int(amount), user_id=self._user_id
            )
        except Exception as exc:
            raise ExecSessionError("Terminal read failed") from exc
        data_b64 = res.get("data_b64", "")
        if data_b64:
            try:
                return base64.b64decode(data_b64.encode("ascii"), validate=False)
            except Exception as exc:
                raise ExecSessionError("Terminal read failed") from exc
        if res.get("eof"):
            return b""
        return b""

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ExecStreamClosed("Terminal session is closed")
        if not data:
            return
        payload = base64.b64encode(bytes(data)).decode("ascii")
        try:
            self._client.write_terminal(self._instance_id, self._exec_id, payload, user_id=self._user_id)
        except Exception as exc:
            raise ExecSessionError("Terminal write failed") from exc

    def resize(self, rows: int, cols: int) -> None:
        if self.closed:
            raise ExecStreamClosed("Terminal session is closed")
        try:
            self._client.resize_terminal(
                self._instance_id, self._exec_id, int(rows), int(cols), user_id=self._user_id
            )
        except Exception as exc:
            raise ExecResizeFailed("Terminal resize failed") from exc

    def inspect(self) -> dict:
        if self.closed:
            return {"running": False, "exit_code": None}
        try:
            res = self._client.inspect_terminal(self._instance_id, self._exec_id, user_id=self._user_id)
        except Exception as exc:
            raise ExecInspectionFailed("Terminal inspect failed") from exc
        return {"running": bool(res.get("running")), "exit_code": res.get("exit_code")}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._client.close_terminal(self._instance_id, self._exec_id, user_id=self._user_id)
        except Exception:
            pass
