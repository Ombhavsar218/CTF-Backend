"""Stage 1D.3 terminal-mode start compatibility tests."""
from unittest.mock import Mock

from django.test import SimpleTestCase, TestCase

from challenge_runtime.config import RuntimeConfig
from challenge_runtime.service import build_connection_meta
from instances.services import InstanceNotEligible, InstanceService
from terminal.tests.helpers import make_challenge, make_user


class BuildConnectionMetaTests(SimpleTestCase):
    def test_terminal_mode_has_no_container_id_and_no_port(self):
        challenge = Mock(runtime_access_mode='terminal', runtime_internal_port=None)
        meta = build_connection_meta(
            challenge, {'id': 'secret-container-id', 'ports': {}}, RuntimeConfig()
        )
        self.assertEqual(meta, {'type': 'terminal'})
        self.assertNotIn('secret-container-id', str(meta))

    def test_http_mode_keeps_stage_1c_shape(self):
        challenge = Mock(runtime_access_mode='http', runtime_internal_port=8080,
                         runtime_connection_type='http')
        info = {
            'id': 'secret-container-id',
            'ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '32768'}]},
        }
        meta = build_connection_meta(challenge, info, RuntimeConfig())
        self.assertEqual(meta['url'], 'http://127.0.0.1:32768')
        self.assertEqual(meta['port'], 32768)
        self.assertIn('container_id', meta)


class TerminalStartValidationTests(TestCase):
    def test_terminal_challenge_can_start_without_published_port(self):
        user = make_user('terminal-start')
        challenge = make_challenge(
            slug='terminal-no-port', mode='terminal', runtime_internal_port=None
        )
        runtime = Mock()
        service = InstanceService(runtime=runtime)
        service.start(user, challenge)
        runtime.start.assert_called_once()

    def test_http_challenge_still_requires_published_port(self):
        user = make_user('http-start')
        challenge = make_challenge(
            slug='http-no-port', mode='http', runtime_internal_port=None
        )
        runtime = Mock()
        with self.assertRaises(InstanceNotEligible):
            InstanceService(runtime=runtime).start(user, challenge)
        runtime.start.assert_not_called()
