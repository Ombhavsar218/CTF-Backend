"""REAL Docker integration test.

Skipped unless ``FLAGHUNT_REAL_DOCKER_TESTS=1`` is set. This test creates a real
container, publishes a loopback port, performs a real HTTP request and removes
the container/network. It is deliberately separate from the mock-only suite.
"""
from __future__ import annotations

import json
import os
import time
import unittest
import urllib.request

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from challenges.models import Category, Challenge
from instances.models import ChallengeInstance
from instances.services import InstanceService

from challenge_runtime.errors import ContainerInspectionFailed


REAL_DOCKER = os.environ.get('FLAGHUNT_REAL_DOCKER_TESTS') == '1'
pytestmark = pytest.mark.skipif(
    not REAL_DOCKER,
    reason='Set FLAGHUNT_REAL_DOCKER_TESTS=1 to run real Docker tests',
)


@unittest.skipUnless(
    REAL_DOCKER,
    'Set FLAGHUNT_REAL_DOCKER_TESTS=1 to run real Docker tests',
)
class RealDockerIntegrationTests(TestCase):
    def test_start_serve_http_and_stop_real_container(self):
        user = get_user_model().objects.create_user(
            'real-docker', 'real-docker@example.com', 'pass12345'
        )
        category = Category.objects.create(name='RealDocker', slug='real-docker')
        command = json.dumps([
            '/bin/sh', '-c',
            'mkdir -p /tmp/www && echo FLAG{REAL_DOCKER_OK} > /tmp/www/index.html '
            '&& python -m http.server 8080 --bind 0.0.0.0 --directory /tmp/www',
        ])
        challenge = Challenge.objects.create(
            title='Real Docker',
            slug='real-docker',
            category=category,
            status=Challenge.STATUS_PUBLISHED,
            runtime_enabled=True,
            runtime_image='python:3.12-alpine',
            runtime_command=command,
            runtime_connection_type='http',
            runtime_internal_port=8080,
            runtime_cpu_limit=0.25,
            runtime_memory_mb=128,
            runtime_pids_limit=32,
            runtime_read_only=True,
        )
        service = InstanceService()
        instance = None
        try:
            instance, created = service.start(user, challenge)
            self.assertTrue(created)
            instance.refresh_from_db()
            self.assertEqual(instance.status, ChallengeInstance.STATUS_RUNNING)
            self.assertTrue(instance.internal_container_id)
            self.assertTrue(instance.internal_network_id)
            self.assertTrue(instance.connection_meta['url'].startswith('http://127.0.0.1:'))

            body = ''
            last_error = None
            for _ in range(20):
                try:
                    with urllib.request.urlopen(
                        instance.connection_meta['url'], timeout=2
                    ) as response:
                        body = response.read().decode('utf-8', 'replace')
                        break
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.25)
            self.assertIn('FLAG{REAL_DOCKER_OK}', body,
                          msg=f'HTTP server never responded: {last_error}')
        finally:
            if instance is not None:
                fresh = ChallengeInstance.objects.filter(pk=instance.pk).first()
                if fresh is not None:
                    service.runtime.stop(fresh)
                else:
                    adapter = service.runtime.adapter
                    try:
                        adapter.remove_container(instance.internal_container_id)
                        adapter.remove_network(instance.internal_network_id)
                    except Exception:
                        pass

        if instance is not None:
            with self.assertRaises(ContainerInspectionFailed):
                service.runtime.adapter.inspect_container(instance.internal_container_id)
