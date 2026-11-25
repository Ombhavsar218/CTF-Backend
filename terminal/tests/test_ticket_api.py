"""Mocked REST ticket-issuance tests. No Docker daemon is contacted."""
from unittest.mock import patch

from challenge_runtime.errors import RuntimeErrorBase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .helpers import make_challenge, make_instance, make_user

User = get_user_model()
TICKET_URL = reverse('terminal:ticket-create')


class TicketRoutingTests(SimpleTestCase):
    def test_ticket_url_matches_contract(self):
        self.assertEqual(
            TICKET_URL, '/api/v1/challenges/instances/terminal-ticket/'
        )


class TicketAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user('ticket-user')
        self.other = make_user('ticket-other')
        self.challenge = make_challenge()
        self.instance = make_instance(self.user, self.challenge)
        self.client = APIClient()

    def _auth(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def _patch_runtime(self, running=True):
        patcher = patch('terminal.services.InstanceService')
        mock_cls = patcher.start()
        self.addCleanup(patcher.stop)
        mock_cls.return_value.active.return_value = self.instance
        if running:
            mock_cls.return_value.runtime.confirm_running.return_value = {
                'status': 'running'
            }
        else:
            mock_cls.return_value.runtime.confirm_running.side_effect = (
                RuntimeErrorBase('container missing')
            )
        return mock_cls

    def test_unauthenticated_request_is_rejected(self):
        resp = self.client.post(TICKET_URL)
        self.assertIn(resp.status_code, (401, 403))

    def test_authenticated_request_returns_opaque_short_lived_ticket(self):
        self._auth()
        mock_cls = self._patch_runtime()
        resp = self.client.post(TICKET_URL)

        self.assertEqual(resp.status_code, 201)
        body = resp.data
        self.assertEqual(body['subprotocol'], 'flaghunt-terminal-v1')
        self.assertEqual(body['expiresIn'], 30)
        self.assertTrue(body['ticket'])
        self.assertTrue(body['url'].endswith('/ws/challenges/instances/terminal/'))
        self.assertNotIn('?', body['url'])
        # No internal identifiers are returned in the ticket payload.
        for key in (
            'container_id', 'instance_id', 'internal_container_id',
            'exec_id', 'user_id', 'internal_name',
        ):
            self.assertNotIn(key, body)
        mock_cls.return_value.runtime.confirm_running.assert_called_once_with(
            self.instance
        )

    def test_cross_user_instance_access_is_not_possible(self):
        self._auth(self.other)
        # A browser-supplied instance id is ignored; ownership is resolved
        # server-side from the authenticated user.
        resp = self.client.post(TICKET_URL, {'instance_id': self.instance.pk})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'TERMINAL_NOT_AVAILABLE')
        self.assertNotIn('container', str(resp.data).lower())

    def test_inactive_instance_is_rejected(self):
        self._auth()
        self.instance.status = 'starting'
        self.instance.save(update_fields=['status'])
        resp = self.client.post(TICKET_URL)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'TERMINAL_NOT_AVAILABLE')

    def test_non_terminal_challenge_is_rejected(self):
        self._auth()
        self.challenge.runtime_access_mode = 'http'
        self.challenge.save(update_fields=['runtime_access_mode'])
        resp = self.client.post(TICKET_URL)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'TERMINAL_NOT_AVAILABLE')

    def test_container_must_be_confirmed_running(self):
        self._auth()
        self._patch_runtime(running=False)
        resp = self.client.post(TICKET_URL)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'TERMINAL_RUNTIME_UNAVAILABLE')
        self.assertNotIn('missing', str(resp.data).lower())

    def test_ticket_endpoint_is_throttled(self):
        self._auth()
        self._patch_runtime()
        last = None
        for _ in range(11):
            last = self.client.post(TICKET_URL)
        self.assertEqual(last.status_code, 429)
