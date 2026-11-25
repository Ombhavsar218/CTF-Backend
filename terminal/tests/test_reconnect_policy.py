"""Deterministic mocked tests for the Stage 1D.5 fresh-shell reconnect policy.

The Docker exec stream is never resumed: WebSocket disconnect closes it and
releases the DB session. A later connection must use a fresh ticket and starts
a new shell. These tests exercise that contract without Docker.
"""
import asyncio
from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from challenge_runtime.docker_adapter import DockerAdapter
from config.asgi import application
from instances.models import ChallengeInstance
from instances.services import InstanceService
from terminal.exceptions import TerminalTicketError
from terminal.models import TerminalSession, TerminalTicket
from terminal.services import SessionRegistry
from terminal.tasks import cleanup_stale_terminal_state

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
class FreshShellReconnectTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = make_user('reconnect-user')
        self.other = make_user('reconnect-other')
        self.challenge = make_challenge(slug='reconnect-challenge')
        self.instance = make_instance(self.user, self.challenge)
        self.streams = []

        runtime_patcher = patch('terminal.consumers.ChallengeRuntimeService')
        runtime_cls = runtime_patcher.start()
        self.addCleanup(runtime_patcher.stop)
        self.runtime = runtime_cls.return_value
        self.runtime.open_terminal_session.side_effect = self._open_stream
        self.runtime.confirm_running.return_value = {
            'id': self.instance.internal_container_id,
            'status': 'running',
            'labels': {
                'flaghunt.managed': 'true',
                'flaghunt.instance-id': str(self.instance.pk),
                'flaghunt.user-id': str(self.user.pk),
            },
        }
        self.runtime.close_terminal_session.side_effect = lambda stream: stream.close()

        stop_patcher = patch.object(InstanceService, 'stop')
        self.service_stop = stop_patcher.start()
        self.addCleanup(stop_patcher.stop)
        docker_stop_patcher = patch.object(DockerAdapter, 'stop_container')
        self.docker_stop = docker_stop_patcher.start()
        self.addCleanup(docker_stop_patcher.stop)
        docker_remove_patcher = patch.object(DockerAdapter, 'remove_container')
        self.docker_remove = docker_remove_patcher.start()
        self.addCleanup(docker_remove_patcher.stop)
        create_patcher = patch.object(DockerAdapter, 'create_container')
        self.docker_create = create_patcher.start()
        self.addCleanup(create_patcher.stop)

    def _open_stream(self, instance, user, command, rows, cols):
        stream = FakeExecStream()
        self.streams.append(stream)
        return stream, f'internal-exec-{len(self.streams)}', instance.internal_container_id

    async def _connect(self, token):
        communicator = WebsocketCommunicator(
            application,
            WS_PATH,
            headers=[(b'origin', ORIGIN.encode())],
            subprotocols=[settings.TERMINAL_SUBPROTOCOL, token],
        )
        connected, code = await communicator.connect()
        return communicator, connected, code

    async def _issue(self):
        token, ticket = await sync_to_async(issue_token)(self.user, self.instance)
        return token, ticket

    async def _sessions(self):
        return await sync_to_async(
            lambda: list(TerminalSession.objects.filter(user=self.user).order_by('pk'))
        )()

    async def test_disconnect_then_fresh_ticket_starts_a_new_shell(self):
        first_token, _ = await self._issue()
        first, connected, _ = await self._connect(first_token)
        self.assertTrue(connected)
        await first.receive_json_from()
        await first.disconnect()
        await asyncio.sleep(0.05)

        self.assertTrue(self.streams[0].closed)
        sessions = await self._sessions()
        self.assertEqual(sessions[0].status, TerminalSession.STATUS_CLOSED)

        second_token, _ = await self._issue()
        second, connected, _ = await self._connect(second_token)
        self.assertTrue(connected)
        try:
            status = await second.receive_json_from()
            self.assertEqual(status['state'], 'connected')
            self.assertEqual(len(self.streams), 2)
            self.assertFalse(self.streams[1].closed)
            self.assertIsNot(self.streams[0], self.streams[1])
            sessions = await self._sessions()
            self.assertEqual(len(sessions), 2)
            self.assertEqual(sessions[0].exec_id, 'internal-exec-1')
            self.assertEqual(sessions[1].exec_id, 'internal-exec-2')
            self.assertEqual(
                [s.status for s in sessions],
                [TerminalSession.STATUS_CLOSED, TerminalSession.STATUS_CONNECTED],
            )
        finally:
            await second.disconnect()

        self.service_stop.assert_not_called()
        self.docker_stop.assert_not_called()
        self.docker_remove.assert_not_called()
        self.docker_create.assert_not_called()

    async def test_replay_of_the_previous_ticket_is_rejected(self):
        token, _ = await self._issue()
        first, connected, _ = await self._connect(token)
        self.assertTrue(connected)
        await first.receive_json_from()
        await first.disconnect()

        replay, connected, code = await self._connect(token)
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await replay.wait()
        self.assertEqual(len(self.streams), 1)

    async def test_expired_reconnect_authorization_is_rejected(self):
        token, ticket = await self._issue()
        await sync_to_async(
            lambda: TerminalTicket.objects.filter(pk=ticket.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1)
            )
        )()
        communicator, connected, code = await self._connect(token)
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await communicator.wait()
        self.assertEqual(self.runtime.open_terminal_session.call_count, 0)

    async def test_ticket_is_bound_to_its_owner(self):
        token, _ = await sync_to_async(issue_token)(self.user, self.instance)
        with self.assertRaises(TerminalTicketError):
            await sync_to_async(TerminalTicket.consume)(token, user=self.other)
        self.assertEqual(self.runtime.open_terminal_session.call_count, 0)

    async def test_stopped_instance_rejects_a_fresh_reconnect_ticket(self):
        token, _ = await self._issue()
        first, connected, _ = await self._connect(token)
        self.assertTrue(connected)
        await first.receive_json_from()
        await first.disconnect()

        await sync_to_async(
            lambda: ChallengeInstance.objects.filter(pk=self.instance.pk).update(
                status=ChallengeInstance.STATUS_STOPPED
            )
        )()
        fresh_token, _ = await self._issue()
        communicator, connected, code = await self._connect(fresh_token)
        self.assertFalse(connected)
        self.assertEqual(code, 4403)
        await communicator.wait()
        self.assertEqual(self.runtime.open_terminal_session.call_count, 1)

    async def test_duplicate_reconnect_attempt_is_rejected_while_session_is_active(self):
        first_token, _ = await self._issue()
        second_token, _ = await self._issue()
        first, connected, _ = await self._connect(first_token)
        self.assertTrue(connected)
        await first.receive_json_from()
        try:
            duplicate, connected, code = await self._connect(second_token)
            self.assertFalse(connected)
            self.assertEqual(code, 4409)
            await duplicate.wait()
            self.assertEqual(self.runtime.open_terminal_session.call_count, 1)
            sessions = await self._sessions()
            self.assertEqual(
                [s.status for s in sessions], [TerminalSession.STATUS_CONNECTED]
            )
        finally:
            await first.disconnect()

    async def test_abandoned_reconnect_session_is_cleaned_up(self):
        ticket_token, ticket = await self._issue()
        session = await sync_to_async(SessionRegistry.acquire)(
            self.user, self.instance, ticket
        )
        await sync_to_async(
            lambda: TerminalSession.objects.filter(pk=session.pk).update(
                created_at=timezone.now() - timedelta(hours=2)
            )
        )()

        result = await sync_to_async(cleanup_stale_terminal_state)()
        self.assertTrue(result['ok'])
        session = await sync_to_async(TerminalSession.objects.get)(pk=session.pk)
        self.assertEqual(session.status, TerminalSession.STATUS_EXPIRED)
        self.assertNotIn(self.user.pk, [
            row.user_id for row in await sync_to_async(
                lambda: list(TerminalSession.objects.filter(
                    user=self.user, status__in=TerminalSession.ACTIVE_STATUSES
                ))
            )()
        ])
        self.assertIsNotNone(ticket_token)

        fresh_token, _ = await self._issue()
        communicator, connected, _ = await self._connect(fresh_token)
        self.assertTrue(connected)
        await communicator.receive_json_from()
        await communicator.disconnect()

    async def test_exec_exit_closes_session_without_touching_container(self):
        token, _ = await self._issue()
        communicator, connected, _ = await self._connect(token)
        self.assertTrue(connected)
        await communicator.receive_json_from()

        # Simulate the PTY process exiting while the browser is connected.
        self.streams[0].close()
        await communicator.wait()
        await asyncio.sleep(0.05)
        # The consumer already closed the WebSocket with 4000; do not send a
        # second disconnect frame through the finished communicator.

        sessions = await self._sessions()
        self.assertEqual(sessions[0].status, TerminalSession.STATUS_CLOSED)
        self.service_stop.assert_not_called()
        self.docker_stop.assert_not_called()
        self.docker_remove.assert_not_called()
        self.assertEqual(self.runtime.close_terminal_session.call_count, 1)

    async def test_reconnect_does_not_replay_old_output_or_reuse_exec(self):
        token, _ = await self._issue()
        first, connected, _ = await self._connect(token)
        self.assertTrue(connected)
        await first.receive_json_from()
        await first.send_json_to({
            'type': 'input', 'data': 'YW5jaWVudCBzZWNyZXQ=',
        })
        await asyncio.sleep(0.05)
        self.assertEqual(self.streams[0].writes, [b'ancient secret'])
        await first.disconnect()

        fresh_token, _ = await self._issue()
        second, connected, _ = await self._connect(fresh_token)
        self.assertTrue(connected)
        try:
            frame = await second.receive_json_from()
            self.assertEqual(frame['type'], 'status')
            self.assertEqual(frame['state'], 'connected')
            self.assertNotIn('ancient secret', str(frame))
            self.assertEqual(self.streams[1].writes, [])
            self.assertNotEqual(self.streams[0], self.streams[1])
        finally:
            await second.disconnect()
