"""Read-only runtime confirmation test with a mocked Docker adapter."""
from unittest.mock import Mock

from challenge_runtime.errors import RuntimeErrorBase
from challenge_runtime.service import ChallengeRuntimeService
from django.test import SimpleTestCase


class FakeInstance:
    pk = 42
    internal_container_id = 'container-42'
    internal_name = ''


class ConfirmRunningTests(SimpleTestCase):
    def _service(self, info):
        adapter = Mock()
        adapter.inspect_container.return_value = info
        adapter.find_container_by_name.assert_not_called()
        return ChallengeRuntimeService(adapter=adapter), adapter

    def test_confirm_running_checks_managed_ownership(self):
        info = {
            'id': 'container-42',
            'status': 'running',
            'labels': {
                'flaghunt.managed': 'true',
                'flaghunt.instance-id': '42',
            },
        }
        service, adapter = self._service(info)
        self.assertEqual(service.confirm_running(FakeInstance()), info)
        adapter.inspect_container.assert_called_once_with('container-42')
        adapter.stop_container.assert_not_called()

    def test_confirm_running_rejects_foreign_container(self):
        info = {
            'id': 'container-42',
            'status': 'running',
            'labels': {
                'flaghunt.managed': 'true',
                'flaghunt.instance-id': '99',
            },
        }
        service, _ = self._service(info)
        with self.assertRaises(RuntimeErrorBase):
            service.confirm_running(FakeInstance())

    def test_confirm_running_rejects_stopped_container(self):
        info = {
            'id': 'container-42',
            'status': 'exited',
            'labels': {
                'flaghunt.managed': 'true',
                'flaghunt.instance-id': '42',
            },
        }
        service, _ = self._service(info)
        with self.assertRaises(RuntimeErrorBase):
            service.confirm_running(FakeInstance())
