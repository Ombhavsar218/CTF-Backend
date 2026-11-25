"""Mocked Docker exec/PTY WebSocket streaming tests."""
import asyncio
import base64
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import TransactionTestCase, override_settings

from challenge_runtime.docker_adapter import DockerAdapter
from challenge_runtime.errors import RuntimeErrorBase
from config.asgi import application
from instances.models import ChallengeInstance
from instances.services import InstanceService
from terminal.models import TerminalSession

from .helpers import FakeExecStream, issue_token, make_challenge, make_instance, make_user

WS_PATH = '/ws/challenges/instances/terminal/'
ORIGIN = 'http://localhost:5173'
IN_MEMORY_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(
    CHANNEL_LAYERS=IN_MEMORY_LAYERS,
    WEBSOCKET_ALLOWED_ORIGINS=[ORIGIN],
    TERMINAL_MAX_SESSIONS_PER_USER=1,
    TERMINAL_MAX_SESSIONS_PER_INSTANCE=1,
    TERMINAL_MAX_FRAME_BYTES=512,
    TERMINAL_SESSION_CHECK_INTERVAL_SECONDS=60,
    TERMINAL_STALE_SESSION_SECONDS=300,
)
class ExecStreamTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = make_user('exec-user')
        self.challenge = make_challenge(slug='exec-challenge')
        self.instance = make_instance(self.user, self.challenge)
        patcher = patch('terminal.consumers.ChallengeRuntimeService')
        runtime_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = runtime_cls.return_value
        self.stream = FakeExecStream()
        self.runtime.open_terminal_session.return_value = (
            self.stream, 'internal-exec-id', self.instance.internal_container_id
        )
        self.runtime.confirm_running.return_value = {
            'id': self.instance.internal_container_id, 'status': 'running',
        }
        self.runtime.close_terminal_session.side_effect = lambda session: session.close()

    async def _connect(self, outputs=None):
        if outputs is not None:
            self.stream.outputs = list(outputs)
        token, _ = await self._sync(issue_token)(self.user, self.instance)
        communicator = WebsocketCommunicator(
            application,
            WS_PATH,
            headers=[(b'origin', ORIGIN.encode())],
            subprotocols=[settings.TERMINAL_SUBPROTOCOL, token],
        )
        connected, selected = await communicator.connect()
        self.assertTrue(connected)
        self.assertEqual(selected, 'flaghunt-terminal-v1')
        return communicator

    @staticmethod
    def _sync(func):
        from asgiref.sync import sync_to_async
        return sync_to_async(func)

    def _set_instance_status(self, status):
        self.instance.status = status
        self.instance.save(update_fields=['status', 'updated_at'])

    async def test_docker_output_is_forwarded_as_base64(self):
        communicator = await self._connect(outputs=[b'PTY-READY'])
        try:
            status = await communicator.receive_json_from()
            self.assertEqual(status['state'], 'connected')
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['type'], 'output')
            self.assertEqual(base64.b64decode(frame['data']), b'PTY-READY')
            self.assertNotIn('internal-exec-id', str(frame))
        finally:
            await communicator.disconnect()

    async def test_websocket_input_is_forwarded_to_exec_stdin(self):
        communicator = await self._connect()
        try:
            await communicator.receive_json_from()
            await communicator.send_json_to({
                'type': 'input', 'data': base64.b64encode(b'echo hi\n').decode(),
            })
            await asyncio.sleep(0.05)
            self.assertEqual(self.stream.writes, [b'echo hi\n'])
        finally:
            await communicator.disconnect()

    async def test_resize_is_validated_bounded_and_forwarded(self):
        communicator = await self._connect()
        try:
            await communicator.receive_json_from()
            await communicator.send_json_to({'type': 'resize', 'rows': 40, 'cols': 100})
            await asyncio.sleep(0.05)
            self.assertEqual(self.stream.resizes, [(40, 100)])
            session = await self._sync(
                lambda: TerminalSession.objects.get(user=self.user)
            )()
            self.assertEqual((session.rows, session.cols), (40, 100))

            for bad in (
                {'rows': 0, 'cols': 80},
                {'rows': 24, 'cols': -1},
                {'rows': '24', 'cols': 80},
                {'rows': True, 'cols': 80},
                {'rows': 10000, 'cols': 80},
                {'rows': 24, 'cols': 100000},
            ):
                await communicator.send_json_to({'type': 'resize', **bad})
                frame = await communicator.receive_json_from()
                self.assertEqual(frame['code'], 'invalid_dimensions')
            self.assertEqual(len(self.stream.resizes), 1)
        finally:
            await communicator.disconnect()

    async def test_disconnect_closes_only_exec_stream(self):
        with patch.object(InstanceService, 'stop') as stop, \
                patch.object(DockerAdapter, 'stop_container') as docker_stop, \
                patch.object(DockerAdapter, 'remove_container') as docker_remove:
            communicator = await self._connect()
            await communicator.receive_json_from()
            await communicator.disconnect()
            self.assertTrue(self.stream.closed)
            self.runtime.close_terminal_session.assert_called_once()
            stop.assert_not_called()
            docker_stop.assert_not_called()
            docker_remove.assert_not_called()
        session = await self._sync(lambda: TerminalSession.objects.get(user=self.user))()
        self.assertEqual(session.status, TerminalSession.STATUS_CLOSED)

    async def test_instance_stop_closes_stream_and_notifies_client(self):
        communicator = await self._connect()
        await communicator.receive_json_from()
        await self._sync(
            lambda: self._set_instance_status(ChallengeInstance.STATUS_STOPPED)
        )()
        frame = await communicator.receive_json_from()
        self.assertEqual(frame['state'], 'revoked')
        await asyncio.sleep(0.05)
        self.assertTrue(self.stream.closed)
        session = await self._sync(
            lambda: TerminalSession.objects.get(user=self.user)
        )()
        self.assertEqual(session.status, TerminalSession.STATUS_REVOKED)
        await communicator.wait()

    async def test_docker_failure_never_leaks_daemon_details(self):
        self.runtime.open_terminal_session.side_effect = RuntimeErrorBase(
            '/var/run/docker.sock denied'
        )
        communicator = await self._connect()
        try:
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['state'], 'error')
            self.assertEqual(frame['reason'], 'terminal_unavailable')
            self.assertNotIn('docker.sock', str(frame))
            self.assertNotIn('internal-exec-id', str(frame))
        finally:
            await communicator.disconnect()

    async def test_container_disappearance_closes_stream(self):
        communicator = await self._connect()
        try:
            await communicator.receive_json_from()
            self.runtime.confirm_running.side_effect = RuntimeErrorBase('container gone')
            await communicator.send_json_to({
                'type': 'input', 'data': base64.b64encode(b'x').decode(),
            })
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['reason'], 'container_unavailable')
            await asyncio.sleep(0.05)
            self.assertTrue(self.stream.closed)
        finally:
            await communicator.disconnect()

    async def test_ping_and_pong_preserve_heartbeat(self):
        communicator = await self._connect()
        try:
            await communicator.receive_json_from()
            await communicator.send_json_to({'type': 'ping'})
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['type'], 'pong')
            session = await self._sync(lambda: TerminalSession.objects.get(user=self.user))()
            self.assertIsNotNone(session.last_seen)
        finally:
            await communicator.disconnect()
