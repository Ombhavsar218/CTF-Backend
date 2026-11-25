"""Authenticated WebSocket consumer bridged to a Docker exec PTY.

The ticket/session context established by Stage 1D.2 is reused unchanged. This
consumer resolves the container only from that server-side context, opens one
dedicated interactive exec session per connection, and bridges bounded
JSON/base64 frames to the exec stream. It never calls a container lifecycle
operation: disconnect closes only its own exec stream.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import threading

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from challenge_runtime.errors import ExecSessionError, ExecStreamClosed
from challenge_runtime.service import ChallengeRuntimeService

from .exceptions import TerminalSessionLimit
from .models import TerminalSession
from .ratelimits import TokenBucket
from .services import SessionRegistry, instance_group

# Only an absolute path with conservative characters is accepted. No shell
# metacharacters, whitespace, arguments, host paths or relative traversal.
_SHELL_PATTERN = re.compile(r'^/[A-Za-z0-9_./-]{1,127}$')


def _configured_shell_command():
    shell = str(settings.TERMINAL_SHELL_PATH or '').strip()
    if not _SHELL_PATTERN.fullmatch(shell) or '..' in shell:
        raise ExecSessionError('Configured terminal shell is not valid')
    return [shell]


def _valid_dimension(value, minimum: int, maximum: int) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and minimum <= value <= maximum)


class TerminalGatewayConsumer(AsyncJsonWebsocketConsumer):
    """Owns one authenticated gateway session and one Docker exec stream."""

    async def connect(self):
        self.user = self.scope['terminal_user']
        self.instance = self.scope['terminal_instance']
        self.ticket_id = self.scope['terminal_ticket_id']
        self.session_id = None
        self.stream = None
        self.exec_id = ''
        self.container_id = ''
        self.runtime = ChallengeRuntimeService()
        self.loop = asyncio.get_running_loop()
        self.read_chunk = settings.TERMINAL_READ_CHUNK_BYTES
        self._closing = False
        self._cleaned = False
        self._group_added = False
        self._stop_reader = threading.Event()
        self._reader_thread = None
        self._sender_task = None
        self._watchdog_task = None
        queue_size = max(4, min(128, settings.TERMINAL_OUTPUT_BUFFER_BYTES // self.read_chunk))
        self._output_queue = asyncio.Queue(maxsize=queue_size)
        self._output_buffered = 0
        self._input_bucket = TokenBucket(
            settings.TERMINAL_INPUT_RATE_BYTES_PER_SECOND,
            settings.TERMINAL_MAX_FRAME_BYTES,
        )
        self._output_bucket = TokenBucket(
            settings.TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND,
            max(settings.TERMINAL_MAX_FRAME_BYTES, self.read_chunk * 4),
        )
        self._resize_bucket = TokenBucket(
            settings.TERMINAL_RESIZE_RATE_PER_SECOND,
            max(1, settings.TERMINAL_RESIZE_RATE_PER_SECOND * 2),
        )

        try:
            session = await database_sync_to_async(SessionRegistry.acquire)(
                self.user, self.instance, self.ticket_id, self.channel_name,
                worker_id=str(os.getpid()),
            )
        except TerminalSessionLimit:
            await self.close(4409, 'session_limit')
            return

        self.session_id = session.pk
        await self.channel_layer.group_add(
            instance_group(self.instance.pk), self.channel_name
        )
        self._group_added = True
        await self.accept(subprotocol=settings.TERMINAL_SUBPROTOCOL)
        await database_sync_to_async(SessionRegistry.mark_connected)(
            self.session_id, self.channel_name
        )

        try:
            command = _configured_shell_command()
            stream, exec_id, container_id = await database_sync_to_async(
                self.runtime.open_terminal_session
            )(
                self.instance, self.user, command,
                settings.TERMINAL_ROWS_MIN, settings.TERMINAL_COLS_MIN,
            )
        except Exception:
            await self.send_json({
                'type': 'status', 'state': 'error', 'reason': 'terminal_unavailable',
            })
            await self._cleanup(status=TerminalSession.STATUS_FAILED)
            await self.close(4403, 'terminal_unavailable')
            return

        self.stream = stream
        self.exec_id = exec_id
        self.container_id = container_id
        await database_sync_to_async(SessionRegistry.mark_exec_started)(
            self.session_id, exec_id, container_id,
            settings.TERMINAL_ROWS_MIN, settings.TERMINAL_COLS_MIN,
            worker_id=str(os.getpid()),
        )

        self._reader_thread = threading.Thread(
            target=self._read_loop, name=f'terminal-exec-{self.session_id}', daemon=True,
        )
        self._reader_thread.start()
        self._sender_task = asyncio.create_task(self._output_sender())
        self._watchdog_task = asyncio.create_task(self._watchdog())

        await self.send_json({
            'type': 'status',
            'state': 'connected',
            'rows': settings.TERMINAL_ROWS_MIN,
            'cols': settings.TERMINAL_COLS_MIN,
        })

    # ------------------------------------------------------------------
    # Inbound WebSocket frames
    # ------------------------------------------------------------------
    async def websocket_receive(self, message):
        """Reject oversized and binary frames before JSON decoding."""
        text = message.get('text')
        payload = message.get('bytes')
        size = len(text.encode('utf-8')) if text is not None else len(payload or b'')
        if size > settings.TERMINAL_MAX_FRAME_BYTES:
            await self.send_json({
                'type': 'error',
                'code': 'frame_too_large',
                'limit': settings.TERMINAL_MAX_FRAME_BYTES,
            })
            await self.close(4409, 'frame_too_large')
            return
        if text is None:
            await self.send_json({'type': 'error', 'code': 'binary_frames_unsupported'})
            await self.close(4403, 'binary_frames_unsupported')
            return
        await self.receive(text_data=text)

    async def receive(self, text_data=None, bytes_data=None):
        """Decode JSON explicitly so malformed frames cannot raise unhandled."""
        if not text_data:
            await self.send_json({'type': 'error', 'code': 'invalid_frame'})
            return
        try:
            content = json.loads(text_data)
        except (TypeError, ValueError, json.JSONDecodeError):
            await self.send_json({'type': 'error', 'code': 'invalid_json'})
            return
        await self.receive_json(content)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({'type': 'error', 'code': 'invalid_frame'})
            return

        kind = content.get('type')
        if kind == 'ping':
            if self.session_id:
                await database_sync_to_async(SessionRegistry.heartbeat)(self.session_id)
            await self.send_json({'type': 'pong'})
            return
        if self._closing or self.stream is None:
            return
        if not await self._verify_stream_context():
            return
        if kind == 'input':
            await self._handle_input(content.get('data'))
        elif kind == 'resize':
            await self._handle_resize(content.get('rows'), content.get('cols'))
        else:
            await self.send_json({'type': 'error', 'code': 'invalid_frame_type'})

    async def _handle_input(self, data):
        encoded_limit = settings.TERMINAL_MAX_FRAME_BYTES * 2 + 4
        if not isinstance(data, str) or len(data) > encoded_limit:
            await self.send_json({'type': 'error', 'code': 'invalid_input'})
            return
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            await self.send_json({'type': 'error', 'code': 'invalid_input'})
            return
        if not raw or len(raw) > settings.TERMINAL_MAX_FRAME_BYTES:
            await self.send_json({'type': 'error', 'code': 'frame_too_large'})
            return
        if not self._input_bucket.consume(len(raw)):
            await self._close_with(4409, 'input_rate_exceeded')
            return
        try:
            await asyncio.to_thread(self.stream.write, raw)
        except ExecStreamClosed:
            await self._close_with(4403, 'stream_closed')
            return
        except Exception:
            await self._close_with(4403, 'stream_error')
            return
        await database_sync_to_async(SessionRegistry.heartbeat)(self.session_id)

    async def _handle_resize(self, rows, cols):
        if not _valid_dimension(rows, settings.TERMINAL_ROWS_MIN, settings.TERMINAL_ROWS_MAX):
            await self.send_json({'type': 'error', 'code': 'invalid_dimensions'})
            return
        if not _valid_dimension(cols, settings.TERMINAL_COLS_MIN, settings.TERMINAL_COLS_MAX):
            await self.send_json({'type': 'error', 'code': 'invalid_dimensions'})
            return
        if not self._resize_bucket.consume(1):
            await self._close_with(4409, 'resize_rate_exceeded')
            return
        try:
            await asyncio.to_thread(self.stream.resize, rows, cols)
        except Exception:
            await self._close_with(4403, 'resize_failed')
            return
        await database_sync_to_async(SessionRegistry.update_dimensions)(
            self.session_id, rows, cols
        )

    # ------------------------------------------------------------------
    # Exec output and lifecycle
    # ------------------------------------------------------------------
    def _read_loop(self):
        while not self._stop_reader.is_set():
            try:
                chunk = self.stream.read(self.read_chunk)
            except ExecStreamClosed:
                self.loop.call_soon_threadsafe(self._deliver_output, None)
                return
            except Exception:
                self.loop.call_soon_threadsafe(self._schedule_close, 'stream_error')
                return
            if not chunk:
                self.loop.call_soon_threadsafe(self._deliver_output, None)
                return
            self.loop.call_soon_threadsafe(self._deliver_output, chunk)

    def _deliver_output(self, chunk):
        if self._closing:
            return
        if chunk is None:
            try:
                self._output_queue.put_nowait(None)
            except asyncio.QueueFull:
                self._schedule_close('output_buffer_overflow')
            return
        if self._output_buffered + len(chunk) > settings.TERMINAL_OUTPUT_BUFFER_BYTES:
            self._schedule_close('output_buffer_overflow')
            return
        try:
            self._output_queue.put_nowait(chunk)
            self._output_buffered += len(chunk)
        except asyncio.QueueFull:
            self._schedule_close('output_buffer_overflow')

    def _schedule_close(self, reason):
        if self._closing:
            return
        asyncio.create_task(self._close_with(4409, reason))

    async def _output_sender(self):
        try:
            while True:
                chunk = await self._output_queue.get()
                if self._closing:
                    return
                if chunk is None:
                    await self._close_with(4000, 'exec_exited')
                    return
                if not self._output_bucket.consume(len(chunk)):
                    await self._close_with(4409, 'output_rate_exceeded')
                    return
                await self.send_json({
                    'type': 'output',
                    'data': base64.b64encode(chunk).decode('ascii'),
                })
                self._output_buffered = max(0, self._output_buffered - len(chunk))
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def _watchdog(self):
        try:
            while True:
                await asyncio.sleep(settings.TERMINAL_SESSION_CHECK_INTERVAL_SECONDS)
                if self._closing:
                    return
                if not await self._verify_stream_context():
                    return
        except asyncio.CancelledError:
            return

    async def _verify_stream_context(self):
        context = await database_sync_to_async(SessionRegistry.stream_context)(
            self.session_id
        )
        if context is None or not context['active'] or context['close_requested']:
            await self._close_with(
                4003, context.get('reason', 'session_revoked') if context else 'session_revoked',
                TerminalSession.STATUS_REVOKED,
            )
            return False
        instance = context['instance']
        if (instance.status != 'running' or instance.is_expired
                or context['challenge_mode'] != 'terminal'):
            await self._close_with(4003, 'instance_unavailable', TerminalSession.STATUS_REVOKED)
            return False
        try:
            await database_sync_to_async(self.runtime.confirm_running)(instance)
        except Exception:
            await self._close_with(4403, 'container_unavailable', TerminalSession.STATUS_FAILED)
            return False
        await database_sync_to_async(SessionRegistry.heartbeat)(self.session_id)
        return True

    async def terminal_revoked(self, event):
        if self._closing:
            return
        reason = event.get('reason', 'instance_unavailable')
        await self.send_json({'type': 'status', 'state': 'revoked', 'reason': reason})
        await self._close_with(4003, reason, TerminalSession.STATUS_REVOKED)

    async def _close_with(self, code, reason, status=TerminalSession.STATUS_CLOSED):
        if self._closing:
            return
        self._closing = True
        self._stop_reader.set()
        if code >= 4400:
            await self.send_json({'type': 'status', 'state': 'error', 'reason': reason})
        await self._cleanup(status=status)
        try:
            await self.close(code, reason)
        except Exception:
            pass

    async def disconnect(self, code):
        await self._cleanup()

    async def _cleanup(self, status=TerminalSession.STATUS_CLOSED):
        """Close only this exec stream and its DB session. Idempotent."""
        if self._cleaned:
            return
        self._cleaned = True
        self._stop_reader.set()

        # _close_with() can be awaited from inside _output_sender(); cancelling
        # and gathering the current task there recursively cancels its own
        # cancellation chain. Never join the caller of cleanup.
        current = asyncio.current_task()
        tasks = (self._sender_task, self._watchdog_task)
        for task in tasks:
            if task is not None and task is not current and not task.done():
                task.cancel()
        pending = [t for t in tasks if t is not None and t is not current]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        if self.stream is not None:
            try:
                await asyncio.to_thread(self.runtime.close_terminal_session, self.stream)
            except Exception:
                pass
            self.stream = None

        if self.session_id:
            await database_sync_to_async(SessionRegistry.release)(self.session_id, status)

        if self._group_added:
            await self.channel_layer.group_discard(
                instance_group(self.instance.pk), self.channel_name
            )
            self._group_added = False
