"""REAL Docker exec/PTY integration test.

Skipped unless ``FLAGHUNT_REAL_DOCKER_TESTS=1`` is set. The test uses a
disposable, unprivileged Alpine container, drives a real interactive shell with
a PTY, verifies resize, then removes the container and network. It is separate
from the deterministic mocked suite.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import unittest

from django.contrib.auth import get_user_model
from django.test import TestCase

from challenges.models import Category, Challenge
from challenge_runtime.errors import ContainerInspectionFailed
from challenge_runtime.service import ChallengeRuntimeService
from instances.models import ChallengeInstance
from instances.services import InstanceService

REAL_DOCKER = os.environ.get('FLAGHUNT_REAL_DOCKER_TESTS') == '1'


@unittest.skipUnless(
    REAL_DOCKER,
    'Set FLAGHUNT_REAL_DOCKER_TESTS=1 to run real Docker terminal tests',
)
class RealDockerExecIntegrationTests(TestCase):
    def test_interactive_shell_input_output_resize_and_cleanup(self):
        user = get_user_model().objects.create_user(
            'real-exec', 'real-exec@example.com', 'pass12345'
        )
        category, _ = Category.objects.get_or_create(
            name='RealExec', slug='real-exec'
        )
        challenge = Challenge.objects.create(
            title='Real Exec',
            slug='real-exec',
            category=category,
            status=Challenge.STATUS_PUBLISHED,
            runtime_enabled=True,
            runtime_image='alpine:3.20',
            runtime_command=json.dumps(['/bin/sh', '-c', 'sleep 3600']),
            runtime_connection_type='tcp',
            runtime_internal_port=None,
            runtime_access_mode='terminal',
            runtime_cpu_limit=0.25,
            runtime_memory_mb=128,
            runtime_pids_limit=32,
            runtime_read_only=True,
        )
        service = InstanceService()
        instance = None
        runtime = ChallengeRuntimeService()
        stream = None
        reader_stop = threading.Event()
        output_queue = queue.Queue()

        try:
            instance, created = service.start(user, challenge)
            self.assertTrue(created)
            instance.refresh_from_db()
            self.assertEqual(instance.status, ChallengeInstance.STATUS_RUNNING)
            self.assertTrue(instance.internal_container_id)

            stream, exec_id, container_id = runtime.open_terminal_session(
                instance, user, ['/bin/sh'], 24, 80
            )
            self.assertTrue(exec_id)
            self.assertEqual(container_id, instance.internal_container_id)

            def reader():
                while not reader_stop.is_set():
                    try:
                        chunk = stream.read(4096)
                    except Exception as exc:  # forwarded to the main thread
                        output_queue.put(exc)
                        return
                    if not chunk:
                        output_queue.put(None)
                        return
                    output_queue.put(chunk)

            reader_thread = threading.Thread(target=reader, daemon=True)
            reader_thread.start()

            def write_and_expect(command: bytes, marker: bytes):
                stream.write(command)
                collected = b''
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        item = output_queue.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if item is None:
                        self.fail('Exec stream reached EOF before expected output')
                    if isinstance(item, Exception):
                        raise item
                    collected += item
                    if marker in collected:
                        return collected
                self.fail(f'Expected {marker!r} was not received')

            write_and_expect(b'echo STAGE1D3_PTY_OK\n', b'STAGE1D3_PTY_OK')

            # Rows/columns order matches `stty size` output.
            stream.resize(40, 100)
            write_and_expect(b'stty size\n', b'40 100')

            reader_stop.set()
            runtime.close_terminal_session(stream)
            stream = None

            # Closing the exec must leave the Stage 1C container untouched.
            info = service.runtime.adapter.inspect_container(container_id)
            self.assertEqual(info['status'], 'running')
        finally:
            reader_stop.set()
            if stream is not None:
                try:
                    runtime.close_terminal_session(stream)
                except Exception:
                    pass
            if instance is not None:
                fresh = ChallengeInstance.objects.filter(pk=instance.pk).first()
                if fresh is not None:
                    service.stop(user)
                else:
                    service.runtime.adapter.remove_container(
                        instance.internal_container_id
                    )
                    service.runtime.adapter.remove_network(
                        instance.internal_network_id
                    )

            if instance is not None and instance.pk:
                client = service.runtime.adapter.client
                label = f'flaghunt.instance-id={instance.pk}'
                self.assertEqual(
                    client.containers.list(all=True, filters={'label': [label]}), []
                )
                self.assertEqual(
                    client.networks.list(filters={'label': [label]}), []
                )
                with self.assertRaises(ContainerInspectionFailed):
                    service.runtime.adapter.inspect_container(
                        instance.internal_container_id
                    )
