"""Mocked WebSocket handshake/session tests.

These tests exercise the ASGI gateway with an in-memory channel layer and mocked
runtime confirmation. They do not create a Docker exec or PTY.
"""
import asyncio
from datetime import timedelta
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from challenge_runtime.docker_adapter import DockerAdapter
from config.asgi import application
from instances.models import ChallengeInstance
from instances.services import InstanceService
from terminal.models import TerminalSession, TerminalTicket

from .helpers import FakeExecStream, issue_token, make_challenge, make_instance, make_user

WS_PATH = '/ws/challenges/instances/terminal/'
ORIGIN = 'http://localhost:5173'
IN_MEMORY_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(
    CHANNEL_LAYERS=IN_MEMORY_LAYERS,
    WEBSOCKET_ALLOWED_ORIGINS=[ORIGIN],
    TERMINAL_MAX_SESSIONS_PER_USER=1,
    TERMINAL_MAX_SESSIONS_PER_INSTANCE=1,
    TERMINAL_MAX_FRAME_BYTES=128,
)
class GatewayHandshakeTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = make_user('ws-user')
        self.challenge = make_challenge()
        self.instance = make_instance(self.user, self.challenge)
        # PTY execution is mocked throughout this gateway suite. The consumer
        # must still be exercised end to end with a fake exec stream.
        patcher = patch('terminal.consumers.ChallengeRuntimeService')
        runtime_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = runtime_cls.return_value
        self.stream = FakeExecStream()
        self.runtime.open_terminal_session.return_value = (
            self.stream, 'internal-exec-id', self.instance.internal_container_id
        )
        self.runtime.confirm_running.return_value = {
            'id': self.instance.internal_container_id,
            'status': 'running',
        }

    async def _connect(self, token, origin=ORIGIN, subprotocols=None):
        if subprotocols is None:
            subprotocols = [settings.TERMINAL_SUBPROTOCOL, token]
        communicator = WebsocketCommunicator(
            application,
            WS_PATH,
            headers=[(b'origin', origin.encode('utf-8'))],
            subprotocols=subprotocols,
        )
        result = await communicator.connect()
        return communicator, result

    async def test_valid_ticket_connects_and_never_echoes_ticket(self):
        token, ticket = await self.async_to_sync_if_needed(issue_token)(
            self.user, self.instance
        )
        communicator, (connected, selected) = await self._connect(token)
        self.assertTrue(connected)
        try:
            self.assertEqual(selected, 'flaghunt-terminal-v1')
            self.assertNotIn(token, selected or '')
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['type'], 'status')
            self.assertEqual(frame['state'], 'connected')
            self.assertNotIn(self.instance.internal_container_id, str(frame))
            await self.async_to_sync_if_needed(ticket.refresh_from_db)()
            self.assertIsNotNone(ticket.used_at)
            session = await self.async_to_sync_if_needed(
                lambda: TerminalSession.objects.get(ticket=ticket)
            )()
            self.assertEqual(session.status, TerminalSession.STATUS_CONNECTED)
        finally:
            await communicator.disconnect()

    @staticmethod
    def async_to_sync_if_needed(func):
        """Compatibility shim kept intentionally tiny for ORM calls in tests."""
        from asgiref.sync import sync_to_async
        return sync_to_async(func)

    async def test_ticket_is_single_use(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, ticket = await issue(self.user, self.instance)
        communicator, (connected, _) = await self._connect(token)
        self.assertTrue(connected)
        await communicator.disconnect()

        replay, (connected, code) = await self._connect(token)
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await replay.wait()
        await self.async_to_sync_if_needed(ticket.refresh_from_db)()
        self.assertIsNotNone(ticket.used_at)

    async def test_expired_ticket_is_rejected(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, ticket = await issue(self.user, self.instance)
        await self.async_to_sync_if_needed(
            lambda: TerminalTicket.objects.filter(pk=ticket.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1)
            )
        )()
        communicator, (connected, code) = await self._connect(token)
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await communicator.wait()

    async def test_wrong_origin_is_rejected_before_ticket_consumption(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, ticket = await issue(self.user, self.instance)
        communicator, (connected, code) = await self._connect(
            token, origin='https://attacker.example'
        )
        self.assertFalse(connected)
        self.assertEqual(code, 4403)
        await communicator.wait()
        await self.async_to_sync_if_needed(ticket.refresh_from_db)()
        self.assertIsNone(ticket.used_at)

    async def test_null_origin_is_rejected(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, _ = await issue(self.user, self.instance)
        communicator, (connected, code) = await self._connect(token, origin='null')
        self.assertFalse(connected)
        self.assertEqual(code, 4403)
        await communicator.wait()

    async def test_invalid_subprotocol_is_rejected(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, ticket = await issue(self.user, self.instance)
        communicator, (connected, code) = await self._connect(
            token, subprotocols=['not-flaghunt', token]
        )
        self.assertFalse(connected)
        self.assertEqual(code, 4400)
        await communicator.wait()
        await self.async_to_sync_if_needed(ticket.refresh_from_db)()
        self.assertIsNone(ticket.used_at)

    async def test_malformed_ticket_is_rejected(self):
        communicator, (connected, code) = await self._connect('not-a-ticket')
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await communicator.wait()

    async def test_session_limit_is_enforced(self):
        issue = self.async_to_sync_if_needed(issue_token)
        first_token, _ = await issue(self.user, self.instance)
        second_token, _ = await issue(self.user, self.instance)
        first, (connected, _) = await self._connect(first_token)
        self.assertTrue(connected)
        try:
            second, (connected, code) = await self._connect(second_token)
            self.assertFalse(connected)
            self.assertEqual(code, 4409)
            await second.wait()
        finally:
            await first.disconnect()

    async def test_oversized_frame_is_rejected(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, _ = await issue(self.user, self.instance)
        communicator, (connected, _) = await self._connect(token)
        self.assertTrue(connected)
        try:
            await communicator.receive_json_from()
            await communicator.send_to(text_data='x' * 129)
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['code'], 'frame_too_large')
        finally:
            await communicator.disconnect()

    async def test_disconnect_closes_session_but_not_container(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, _ = await issue(self.user, self.instance)
        with patch.object(InstanceService, 'stop') as stop, \
                patch.object(DockerAdapter, 'stop_container') as docker_stop, \
                patch.object(DockerAdapter, 'remove_container') as docker_remove:
            communicator, (connected, _) = await self._connect(token)
            self.assertTrue(connected)
            await communicator.disconnect()
            stop.assert_not_called()
            docker_stop.assert_not_called()
            docker_remove.assert_not_called()
        get_session = self.async_to_sync_if_needed(
            lambda: TerminalSession.objects.get(user=self.user)
        )
        session = await get_session()
        self.assertEqual(session.status, TerminalSession.STATUS_CLOSED)
        refresh = self.async_to_sync_if_needed(self.instance.refresh_from_db)
        await refresh()
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_RUNNING)

    async def test_instance_stop_revokes_active_session(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, _ = await issue(self.user, self.instance)
        communicator, (connected, _) = await self._connect(token)
        self.assertTrue(connected)
        try:
            await communicator.receive_json_from()
            save = self.async_to_sync_if_needed(
                lambda: (setattr(self.instance, 'status', ChallengeInstance.STATUS_STOPPED),
                         self.instance.save(update_fields=['status', 'updated_at']))
            )
            await save()
            get_session = self.async_to_sync_if_needed(
                lambda: TerminalSession.objects.get(user=self.user)
            )
            session = await get_session()
            self.assertEqual(session.status, TerminalSession.STATUS_REVOKED)
            frame = await communicator.receive_json_from()
            self.assertEqual(frame['state'], 'revoked')
        finally:
            await communicator.disconnect()

    async def test_browser_supplied_identifiers_are_ignored(self):
        issue = self.async_to_sync_if_needed(issue_token)
        token, _ = await issue(self.user, self.instance)
        communicator, (connected, _) = await self._connect(token)
        self.assertTrue(connected)
        try:
            status = await communicator.receive_json_from()
            self.assertEqual(status['state'], 'connected')
            self.assertNotIn('internal-exec-id', str(status))
            await communicator.send_json_to({
                'type': 'input',
                'data': 'aWQ=',  # base64("id")
                'container_id': 'cid-x',
                'exec_id': 'exec-x',
                'user_id': 1,
                'command': '/bin/sh',
            })
            await asyncio.sleep(0.05)
            self.assertEqual(self.stream.writes, [b'id'])
            args = self.runtime.open_terminal_session.call_args.args
            self.assertEqual(args[1].pk, self.user.pk)
            self.assertNotIn('cid-x', str(args))
            self.assertNotIn('exec-x', str(args))
            self.assertEqual(args[2], ['/bin/sh'])
        finally:
            await communicator.disconnect()
