"""Mock-only unit tests for the challenge Docker runtime (no daemon needed)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from challenges.models import Category, Challenge
from instances.models import ChallengeInstance

from challenge_runtime.config import RuntimeConfig
from challenge_runtime.docker_adapter import DockerAdapter
from challenge_runtime.errors import ContainerLaunchFailed, ImageUnavailable
from challenge_runtime.service import (
    ChallengeRuntimeService,
    build_connection_meta,
)


User = get_user_model()
CONFIG = RuntimeConfig(publish_host='127.0.0.1', duration_minutes=45)


class FakeAdapter:
    def __init__(self, *, fail_image=False, fail_launch=False,
                 info=None, inspect_error=None, found_by_name=None):
        self.fail_image = fail_image
        self.fail_launch = fail_launch
        self.info = info or {}
        self.inspect_error = inspect_error
        self.found_by_name = found_by_name
        self.ensure_image_calls = []
        self.network_calls = []
        self.container_kwargs = []
        self.inspect_calls = []
        self.stopped = []
        self.removed = []
        self.networks_removed = []

    def ensure_image(self, image):
        self.ensure_image_calls.append(image)
        if self.fail_image:
            raise ImageUnavailable('Docker image is unavailable: missing/image')

    def create_network(self, name, labels):
        self.network_calls.append((name, labels))
        return SimpleNamespace(id='net-1', name=name)

    def create_container(self, **kwargs):
        self.container_kwargs.append(kwargs)
        if self.fail_launch:
            raise ContainerLaunchFailed('Could not create challenge container')
        return SimpleNamespace(id='container-1', name=kwargs['name'])

    def inspect_container(self, container_id):
        self.inspect_calls.append(container_id)
        if self.inspect_error:
            raise self.inspect_error
        return {
            'id': container_id,
            'name': 'flaghunt-test',
            'status': 'running',
            'ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '32771'}]},
            'labels': {},
            'networks': ['flaghunt-net'],
            **self.info,
        }

    def find_container_by_name(self, name):
        return self.found_by_name

    def stop_container(self, container_id):
        self.stopped.append(container_id)

    def remove_container(self, container_id):
        self.removed.append(container_id)

    def remove_network(self, network_id):
        self.networks_removed.append(network_id)


class RuntimeMockedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('rt1', 'rt1@example.com', 'pass12345')
        self.cat = Category.objects.create(name='Runtime', slug='runtime')
        self.challenge = Challenge.objects.create(
            title='Runtime challenge',
            slug='runtime-challenge',
            category=self.cat,
            status=Challenge.STATUS_PUBLISHED,
            runtime_enabled=True,
            runtime_image='example/challenge:latest',
            runtime_internal_port=8080,
            runtime_connection_type='http',
            runtime_command='sh -c "sleep 3600"',
            runtime_cpu_limit=0.25,
            runtime_memory_mb=128,
            runtime_pids_limit=32,
            runtime_read_only=True,
        )
        self.instance = ChallengeInstance.objects.create(
            user=self.user,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_REQUESTED,
            expires_at=timezone.now() + timedelta(minutes=45),
        )

    def test_start_creates_confined_container_and_publishes_real_port(self):
        adapter = FakeAdapter()
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        result = service.start(self.instance, self.challenge)
        self.instance.refresh_from_db()
        self.assertEqual(result.status, ChallengeInstance.STATUS_RUNNING)
        self.assertEqual(self.instance.internal_container_id, 'container-1')
        self.assertEqual(self.instance.connection_meta['url'], 'http://127.0.0.1:32771')
        self.assertEqual(adapter.ensure_image_calls, ['example/challenge:latest'])
        kwargs = adapter.container_kwargs[0]
        self.assertEqual(kwargs['cpu_limit'], 0.25)
        self.assertEqual(kwargs['memory_mb'], 128)
        self.assertEqual(kwargs['pids_limit'], 32)
        self.assertTrue(kwargs['read_only'])
        self.assertEqual(kwargs['internal_port'], 8080)
        self.assertTrue(adapter.network_calls[0][0].startswith('flaghunt-'))

    def test_start_with_exited_container_fails_and_cleans_up(self):
        adapter = FakeAdapter(info={'status': 'exited'})
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        with self.assertRaises(Exception):
            service.start(self.instance, self.challenge)
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_FAILED)
        self.assertIn('running state', self.instance.failure_reason)
        self.assertIsNone(self.instance.connection_meta)
        self.assertIn('container-1', adapter.removed)
        self.assertIn('net-1', adapter.networks_removed)

    def test_start_with_image_failure_marks_failed(self):
        adapter = FakeAdapter(fail_image=True)
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        with self.assertRaises(ImageUnavailable):
            service.start(self.instance, self.challenge)
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_FAILED)
        self.assertIn('image', self.instance.failure_reason.lower())

    def test_start_without_published_port_fails(self):
        adapter = FakeAdapter(info={'ports': {}})
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        with self.assertRaises(Exception):
            service.start(self.instance, self.challenge)
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_FAILED)
        self.assertIn('port', self.instance.failure_reason.lower())

    def test_stop_removes_container_and_network(self):
        self.instance.status = ChallengeInstance.STATUS_RUNNING
        self.instance.internal_container_id = 'container-1'
        self.instance.internal_network_id = 'net-1'
        self.instance.connection_meta = {'port': 32771}
        self.instance.save()
        adapter = FakeAdapter()
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        result = service.stop(self.instance)
        self.instance.refresh_from_db()
        self.assertEqual(result.status, ChallengeInstance.STATUS_STOPPED)
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_STOPPED)
        self.assertIsNone(self.instance.connection_meta)
        self.assertEqual(adapter.stopped, ['container-1'])
        self.assertEqual(adapter.removed, ['container-1'])
        self.assertEqual(adapter.networks_removed, ['net-1'])

    def test_stop_with_missing_container_id_adopts_by_name(self):
        self.instance.status = ChallengeInstance.STATUS_RUNNING
        self.instance.internal_name = 'flaghunt-recovered'
        self.instance.save()
        adapter = FakeAdapter(found_by_name=SimpleNamespace(id='container-recovered'))
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        service.stop(self.instance)
        self.assertEqual(adapter.removed, ['container-recovered'])

    def test_expire_marks_expired(self):
        self.instance.status = ChallengeInstance.STATUS_RUNNING
        self.instance.internal_container_id = 'container-1'
        self.instance.save()
        service = ChallengeRuntimeService(adapter=FakeAdapter(), config=CONFIG)
        result = service.expire(self.instance)
        self.instance.refresh_from_db()
        self.assertEqual(result.status, ChallengeInstance.STATUS_EXPIRED)
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_EXPIRED)
        self.assertIsNotNone(self.instance.stopped_at)

    def test_reconcile_updates_connection_after_restart(self):
        self.instance.status = ChallengeInstance.STATUS_RUNNING
        self.instance.internal_container_id = 'container-1'
        self.instance.connection_meta = None
        self.instance.save()
        adapter = FakeAdapter(info={
            'ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '40001'}]}
        })
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        service.reconcile()
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.connection_meta['port'], 40001)

    def test_reconcile_marks_missing_container_failed(self):
        from challenge_runtime.errors import ContainerInspectionFailed

        self.instance.status = ChallengeInstance.STATUS_RUNNING
        self.instance.internal_container_id = 'container-gone'
        self.instance.connection_meta = {'port': 32771}
        self.instance.save()
        adapter = FakeAdapter(inspect_error=ContainerInspectionFailed('Challenge container is missing'))
        service = ChallengeRuntimeService(adapter=adapter, config=CONFIG)
        service.reconcile()
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.status, ChallengeInstance.STATUS_FAILED)
        self.assertIsNone(self.instance.connection_meta)
        self.assertIn('missing', self.instance.failure_reason.lower())

    def test_build_connection_meta_uses_only_confirmed_port(self):
        info = {'id': 'container-1', 'ports': {'8080/tcp': [
            {'HostIp': '127.0.0.1', 'HostPort': '50000'}
        ]}}
        meta = build_connection_meta(self.challenge, info, CONFIG)
        self.assertEqual(meta, {
            'type': 'http', 'host': '127.0.0.1', 'port': 50000,
            'target': '127.0.0.1:50000', 'container_id': 'container-1',
            'url': 'http://127.0.0.1:50000',
        })
        self.assertIsNone(build_connection_meta(self.challenge, {'ports': {}}, CONFIG))


class AdapterMockedTests(TestCase):
    def test_create_container_applies_security_and_resource_limits(self):
        client = MagicMock()
        client.containers.run.return_value = SimpleNamespace(id='container-1')
        adapter = DockerAdapter(client=client, config=CONFIG)
        adapter.create_container(
            image='example/challenge:latest',
            name='flaghunt-1',
            network_name='flaghunt-1-net',
            command='sh -c "sleep 60"',
            internal_port=8080,
            labels={'flaghunt.managed': 'true'},
            cpu_limit=0.25,
            memory_mb=128,
            pids_limit=32,
            read_only=True,
        )
        kwargs = client.containers.run.call_args.kwargs
        self.assertFalse(kwargs['privileged'])
        self.assertEqual(kwargs['cap_drop'], ['ALL'])
        self.assertEqual(kwargs['security_opt'], ['no-new-privileges:true'])
        self.assertEqual(kwargs['pids_limit'], 32)
        self.assertEqual(kwargs['mem_limit'], '128m')
        self.assertTrue(kwargs['read_only'])
        self.assertEqual(kwargs['cpu_period'], 100000)
        self.assertEqual(kwargs['cpu_quota'], 25000)
        self.assertEqual(kwargs['ports']['8080/tcp'][0], '127.0.0.1')
        self.assertIsNone(kwargs['ports']['8080/tcp'][1])
        self.assertEqual(kwargs['network'], 'flaghunt-1-net')
        self.assertFalse(kwargs['auto_remove'])

    def test_ensure_image_pulls_when_missing(self):
        from docker.errors import ImageNotFound

        client = MagicMock()
        client.images.get.side_effect = [ImageNotFound('missing'), SimpleNamespace(id='sha256:abc')]
        adapter = DockerAdapter(client=client, config=CONFIG)
        adapter.ensure_image('example/challenge:latest')
        client.images.pull.assert_called_once_with('example/challenge:latest')
        self.assertEqual(client.images.get.call_count, 2)

    def test_remove_container_ignores_missing_container(self):
        from docker.errors import NotFound

        client = MagicMock()
        client.containers.get.side_effect = NotFound('gone')
        adapter = DockerAdapter(client=client, config=CONFIG)
        adapter.remove_container('container-gone')
