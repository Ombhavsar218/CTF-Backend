"""Mocked ticket/session registry tests, including a real DB concurrency race."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from challenge_runtime.errors import RuntimeErrorBase
from instances.models import ChallengeInstance
from instances.services import InstanceService
from terminal.exceptions import (
    TerminalNotAvailable,
    TerminalRuntimeUnavailable,
    TerminalSessionLimit,
    TerminalTicketError,
)
from terminal.models import TerminalSession, TerminalTicket
from terminal.services import SessionRegistry, TicketIssuer
from terminal.tasks import cleanup_stale_terminal_state

from .helpers import issue_token, make_challenge, make_instance, make_user

User = get_user_model()
IN_MEMORY_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


class TicketModelTests(TestCase):
    def setUp(self):
        self.user = make_user('model-user')
        self.challenge = make_challenge()
        self.instance = make_instance(self.user, self.challenge)

    def test_ticket_stores_only_a_hash(self):
        token, ticket = issue_token(self.user, self.instance)
        self.assertNotEqual(token, ticket.token_hash)
        self.assertEqual(len(ticket.token_hash), 64)
        self.assertNotIn(token, ticket.token_hash)

    def test_replay_is_rejected(self):
        token, _ = issue_token(self.user, self.instance)
        TerminalTicket.consume(token)
        with self.assertRaises(TerminalTicketError):
            TerminalTicket.consume(token)

    def test_expired_ticket_is_rejected(self):
        token, ticket = issue_token(self.user, self.instance)
        TerminalTicket.objects.filter(pk=ticket.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(TerminalTicketError):
            TerminalTicket.consume(token)

    def test_revoked_ticket_is_rejected(self):
        token, ticket = issue_token(self.user, self.instance)
        TerminalTicket.objects.filter(pk=ticket.pk).update(
            revoked_at=timezone.now()
        )
        with self.assertRaises(TerminalTicketError):
            TerminalTicket.consume(token)

    def test_malformed_ticket_is_rejected(self):
        with self.assertRaises(TerminalTicketError):
            TerminalTicket.consume('bad ticket!')

    def test_ticket_is_bound_to_user(self):
        other = make_user('model-other')
        token, _ = issue_token(self.user, self.instance)
        with self.assertRaises(TerminalTicketError):
            TerminalTicket.consume(token, user=other)


class TicketConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_only_one_concurrent_consumption_can_succeed(self):
        user = make_user('race-user')
        challenge = make_challenge(slug='race-challenge')
        instance = make_instance(user, challenge)
        token, _ = issue_token(user, instance)
        barrier = Barrier(2)

        def consume_once(_):
            connections.close_all()
            barrier.wait()
            try:
                TerminalTicket.consume(token)
                return 'consumed'
            except TerminalTicketError:
                return 'rejected'

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(consume_once, range(2)))
        self.assertEqual(outcomes, ['consumed', 'rejected'])


@override_settings(
    CHANNEL_LAYERS=IN_MEMORY_LAYERS,
    TERMINAL_MAX_SESSIONS_PER_USER=1,
    TERMINAL_MAX_SESSIONS_PER_INSTANCE=1,
)
class SessionRegistryTests(TestCase):
    def setUp(self):
        self.user = make_user('session-user')
        self.challenge = make_challenge(slug='session-challenge')
        self.instance = make_instance(self.user, self.challenge)
        self.token, self.ticket = issue_token(self.user, self.instance)

    def test_limits_are_enforced(self):
        SessionRegistry.acquire(self.user, self.instance, self.ticket)
        with self.assertRaises(TerminalSessionLimit):
            SessionRegistry.acquire(self.user, self.instance, self.ticket)

    def test_release_allows_a_new_session(self):
        session = SessionRegistry.acquire(self.user, self.instance, self.ticket)
        SessionRegistry.release(session.pk)
        _, replacement = issue_token(self.user, self.instance)
        self.assertIsNotNone(
            SessionRegistry.acquire(self.user, self.instance, replacement)
        )

    def test_revoke_for_instance_closes_tickets_and_sessions(self):
        SessionRegistry.acquire(self.user, self.instance, self.ticket)
        closed = SessionRegistry.revoke_for_instance(self.instance, 'instance_stopped')
        self.assertEqual(closed, 1)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.revoked_at)
        self.assertEqual(
            TerminalSession.objects.get(user=self.user).status,
            TerminalSession.STATUS_REVOKED,
        )

    def test_cleanup_reaps_unresponsive_connections(self):
        session = SessionRegistry.acquire(self.user, self.instance, self.ticket)
        SessionRegistry.mark_exec_started(
            session.pk, 'internal-exec', 'server-container', 24, 80
        )
        TerminalSession.objects.filter(pk=session.pk).update(
            status=TerminalSession.STATUS_CONNECTED,
            last_seen=timezone.now() - timedelta(hours=1),
        )
        result = cleanup_stale_terminal_state()
        self.assertTrue(result['ok'])
        self.assertEqual(result['stale_connections'], 1)
        session.refresh_from_db()
        self.assertEqual(session.status, TerminalSession.STATUS_EXPIRED)
        self.assertTrue(session.close_requested)

    def test_repeated_cleanup_is_idempotent(self):
        SessionRegistry.acquire(self.user, self.instance, self.ticket)
        self.instance.status = ChallengeInstance.STATUS_STOPPED
        self.instance.save(update_fields=['status', 'updated_at'])
        first = cleanup_stale_terminal_state()
        second = cleanup_stale_terminal_state()
        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        self.assertEqual(
            TerminalSession.objects.get(user=self.user).status,
            TerminalSession.STATUS_REVOKED,
        )

    def test_cleanup_expires_stale_state(self):
        stale_token, stale_ticket = issue_token(self.user, self.instance)
        TerminalTicket.objects.filter(pk=stale_ticket.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        session = SessionRegistry.acquire(self.user, self.instance, self.ticket)
        TerminalSession.objects.filter(pk=session.pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        self.instance.status = ChallengeInstance.STATUS_EXPIRED
        self.instance.save(update_fields=['status', 'updated_at'])
        result = cleanup_stale_terminal_state()
        self.assertTrue(result['ok'])
        stale_ticket.refresh_from_db()
        self.assertIsNotNone(stale_ticket.revoked_at)
        session.refresh_from_db()
        self.assertIn(
            session.status,
            {TerminalSession.STATUS_REVOKED, TerminalSession.STATUS_EXPIRED},
        )
        self.assertIsNotNone(stale_token)


class TicketIssuerTests(TestCase):
    def setUp(self):
        self.user = make_user('issuer-user')
        self.challenge = make_challenge(slug='issuer-challenge')
        self.instance = make_instance(self.user, self.challenge)

    def test_runtime_failure_never_leaks_details(self):
        with patch('terminal.services.InstanceService') as service_cls:
            service_cls.return_value.active.return_value = self.instance
            service_cls.return_value.runtime.confirm_running.side_effect = (
                RuntimeErrorBase('/var/run/docker.sock denied')
            )
            with self.assertRaises(TerminalRuntimeUnavailable) as raised:
                TicketIssuer().issue(self.user)
        self.assertNotIn('docker.sock', str(raised.exception))

    def test_terminal_mode_is_required(self):
        self.challenge.runtime_access_mode = 'http'
        self.challenge.save(update_fields=['runtime_access_mode'])
        with patch('terminal.services.InstanceService') as service_cls:
            service_cls.return_value.active.return_value = self.instance
            service_cls.return_value.runtime.confirm_running.side_effect = (
                AssertionError('Docker must not be checked for non-terminal mode')
            )
            with self.assertRaises(TerminalNotAvailable):
                TicketIssuer().issue(self.user)
