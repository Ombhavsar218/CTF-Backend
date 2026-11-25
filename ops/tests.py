"""Tests for background-task plumbing and health probes (no broker required)."""

import io
import time
from unittest.mock import ANY, MagicMock, patch

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from ops import health
from ops.tasks import heartbeat


@override_settings(CELERY_HEARTBEAT_TRACKING_ENABLED=False)
class HeartbeatTaskTests(TestCase):
    def test_heartbeat_returns_and_logs_its_source(self):
        with self.assertLogs('ops.tasks', level='INFO') as captured:
            result = heartbeat(source='test', note='hello')

        self.assertEqual(result, 'ok source=test note=hello')
        joined = '\n'.join(captured.output)
        self.assertIn('heartbeat source=test note=hello', joined)
        # The resolved database path is part of the evidence trail.
        self.assertIn('db=', joined)

    def test_heartbeat_does_not_touch_the_database(self):
        with self.assertNumQueries(0):
            heartbeat(source='test')

    def test_heartbeat_sanitises_free_text_before_logging_or_returning(self):
        with self.assertLogs('ops.tasks', level='INFO') as captured:
            result = heartbeat(source='test', note='hello\r\nforged line')

        self.assertEqual(result, 'ok source=test note=hello??forged line')
        self.assertNotIn('hello\r\nforged', '\n'.join(captured.output))

    @override_settings(CELERY_HEARTBEAT_TRACKING_ENABLED=True)
    def test_heartbeat_records_tracking_best_effort(self):
        with patch('ops.tasks.record_heartbeat', return_value=True) as record:
            with self.assertLogs('ops.tasks', level='INFO'):
                heartbeat(source='beat')

        record.assert_called_once_with('beat')

    @override_settings(CELERY_HEARTBEAT_TRACKING_ENABLED=True)
    def test_a_tracking_failure_does_not_fail_the_task(self):
        with patch('ops.tasks.record_heartbeat', return_value=False):
            result = heartbeat(source='test')

        self.assertEqual(result, 'ok source=test note=-')

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_management_command_enqueues_the_task(self):
        stdout = io.StringIO()
        with self.assertLogs('ops.tasks', level='INFO') as captured:
            call_command(
                'enqueue_heartbeat', '--note', 'from-test', stdout=stdout
            )

        printed = stdout.getvalue()
        self.assertIn('enqueued ops.heartbeat id=', printed)
        self.assertIn('Verify with:', printed)
        self.assertIn('note=from-test', '\n'.join(captured.output))

    @override_settings(
        CELERY_BROKER_URL='redis://worker:broker-secret@redis:6379/0',
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_management_command_does_not_print_broker_credentials(self):
        stdout = io.StringIO()
        call_command('enqueue_heartbeat', '--note', 'redaction', stdout=stdout)

        printed = stdout.getvalue()
        self.assertNotIn('broker-secret', printed)
        self.assertIn('[REDACTED]@redis:6379/0', printed)

    @override_settings(
        CELERY_RESULT_BACKEND=None, CELERY_TASK_ALWAYS_EAGER=True
    )
    def test_management_command_refuses_wait_without_a_result_backend(self):
        with self.assertRaises(CommandError):
            call_command('enqueue_heartbeat', '--wait', stdout=io.StringIO())

    def test_task_is_registered_under_its_public_name(self):
        self.assertTrue(apps.is_installed('ops'))
        self.assertIn('ops.heartbeat', heartbeat.app.tasks)


class HealthViewTests(TestCase):
    def test_liveness_does_not_touch_a_dependency(self):
        with self.assertNumQueries(0):
            response = self.client.get('/health/live/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'checks': {'django': 'ok'}})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_readiness_reports_ok_when_both_dependencies_answer(self):
        with patch('ops.views.check_database', return_value=True), patch(
            'ops.views.check_redis', return_value=True
        ):
            response = self.client.get('/health/ready/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'status': 'ok',
                'checks': {'database': 'ok', 'redis': 'ok'},
            },
        )

    def test_readiness_is_503_when_the_database_fails(self):
        with patch('ops.views.check_database', return_value=False), patch(
            'ops.views.check_redis', return_value=True
        ):
            response = self.client.get('/health/ready/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'unavailable')
        self.assertEqual(response.json()['checks']['database'], 'unavailable')
        self.assertNotIn('sqlite', response.content.decode('utf-8').lower())

    def test_readiness_is_503_when_redis_fails(self):
        with patch('ops.views.check_database', return_value=True), patch(
            'ops.views.check_redis', return_value=False
        ):
            response = self.client.get('/health/ready/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['redis'], 'unavailable')
        self.assertNotIn('redis://', response.content.decode('utf-8'))

    def test_celery_health_requires_worker_and_fresh_beat(self):
        with patch('ops.views.worker_status', return_value='ok'), patch(
            'ops.views.beat_status', return_value='ok'
        ):
            response = self.client.get('/health/celery/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'status': 'ok', 'checks': {'worker': 'ok', 'beat': 'ok'}},
        )

    def test_celery_health_is_503_for_a_stale_beat(self):
        with patch('ops.views.worker_status', return_value='ok'), patch(
            'ops.views.beat_status', return_value='stale'
        ):
            response = self.client.get('/health/celery/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['checks']['beat'], 'stale')

    def test_health_responses_do_not_expose_infrastructure(self):
        with patch('ops.views.worker_status', return_value='unavailable'), patch(
            'ops.views.beat_status', return_value='unavailable'
        ):
            response = self.client.get('/health/celery/')

        body = response.content.decode('utf-8')
        for secret in ('redis://', '127.0.0.1', 'password', 'Traceback', 'sqlite'):
            self.assertNotIn(secret, body)


class HealthProbeTests(SimpleTestCase):
    @override_settings(CELERY_BROKER_URL='memory://')
    def test_a_non_redis_broker_is_not_reported_as_healthy(self):
        self.assertFalse(health.check_redis())

    def test_beat_status_is_missing_without_a_marker(self):
        client = MagicMock()
        client.get.return_value = None
        with patch('ops.health._redis_client', return_value=client):
            self.assertEqual(health.beat_status(), health.STATUS_MISSING)

    def test_beat_status_is_stale_for_an_old_marker(self):
        client = MagicMock()
        client.get.return_value = str(int(time.time()) - 1000).encode()
        with patch('ops.health._redis_client', return_value=client), override_settings(
            CELERY_BEAT_STALE_AFTER_SECONDS=180
        ):
            self.assertEqual(health.beat_status(), health.STATUS_STALE)

    def test_beat_status_is_ok_for_a_fresh_marker(self):
        client = MagicMock()
        client.get.return_value = str(int(time.time())).encode()
        with patch('ops.health._redis_client', return_value=client), override_settings(
            CELERY_BEAT_STALE_AFTER_SECONDS=180
        ):
            self.assertEqual(health.beat_status(), health.STATUS_OK)

    @override_settings(
        CELERY_HEARTBEAT_TRACKING_ENABLED=True,
        CELERY_HEARTBEAT_KEY_PREFIX='test:heartbeat',
        CELERY_HEARTBEAT_TTL_SECONDS=300,
    )
    def test_record_heartbeat_writes_worker_and_beat_markers(self):
        client = MagicMock()
        pipeline = MagicMock()
        client.pipeline.return_value = pipeline
        with patch('ops.health._redis_client', return_value=client):
            self.assertTrue(health.record_heartbeat('beat'))

        pipeline.set.assert_any_call('test:heartbeat:worker', ANY, ex=300)
        pipeline.set.assert_any_call('test:heartbeat:beat', ANY, ex=300)
        pipeline.execute.assert_called_once_with()

    @override_settings(CELERY_HEARTBEAT_TRACKING_ENABLED=True)
    def test_tracking_failure_is_swallowed_without_logging_the_broker_url(self):
        client = MagicMock()
        client.pipeline.return_value.execute.side_effect = ConnectionError(
            'cannot connect to redis://user:hunter2@redis:6379/0'
        )
        with patch('ops.health._redis_client', return_value=client):
            with self.assertLogs('ops.health', level='WARNING') as captured:
                self.assertFalse(health.record_heartbeat('worker'))

        logs = '\n'.join(captured.output)
        self.assertIn('ConnectionError', logs)
        self.assertNotIn('hunter2', logs)
        self.assertNotIn('redis://', logs)

    @override_settings(CELERY_HEARTBEAT_TRACKING_ENABLED=False)
    def test_tracking_can_be_disabled(self):
        with patch('ops.health._redis_client') as client:
            self.assertFalse(health.record_heartbeat('beat'))
        client.assert_not_called()


class CeleryHealthCommandTests(SimpleTestCase):
    @patch(
        'ops.management.commands.check_celery_health.worker_status',
        return_value='ok',
    )
    @patch(
        'ops.management.commands.check_celery_health.beat_status',
        return_value='ok',
    )
    def test_command_succeeds_when_both_are_healthy(self, _beat, _worker):
        stdout = io.StringIO()
        call_command('check_celery_health', stdout=stdout)

        self.assertIn('celery healthy worker=ok beat=ok', stdout.getvalue())

    @patch(
        'ops.management.commands.check_celery_health.worker_status',
        return_value='ok',
    )
    @patch(
        'ops.management.commands.check_celery_health.beat_status',
        return_value='stale',
    )
    def test_command_fails_for_a_stale_beat(self, _beat, _worker):
        with self.assertRaises(CommandError) as caught:
            call_command('check_celery_health', stdout=io.StringIO())

        self.assertIn('worker=ok beat=stale', str(caught.exception))


class CelerySettingsTests(TestCase):
    def test_broker_and_serialization_contract(self):
        from django.conf import settings

        self.assertTrue(settings.CELERY_BROKER_URL.startswith('redis://'))
        self.assertEqual(settings.CELERY_TASK_SERIALIZER, 'json')
        self.assertEqual(settings.CELERY_RESULT_SERIALIZER, 'json')
        self.assertEqual(settings.CELERY_ACCEPT_CONTENT, ['json'])
        # Results are ignored unless an operator opts into a backend.
        self.assertTrue(settings.CELERY_TASK_IGNORE_RESULT)
        # Keep Django's redaction/request-ID logging filters on the worker.
        self.assertFalse(settings.CELERY_WORKER_HIJACK_ROOT_LOGGER)

    def test_timezone_matches_django(self):
        from django.conf import settings

        self.assertEqual(settings.CELERY_TIMEZONE, settings.TIME_ZONE)
        self.assertTrue(settings.CELERY_ENABLE_UTC)

    def test_beat_schedule_contains_expected_tasks(self):
        from django.conf import settings

        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertEqual(
            list(schedule),
            [
                'phase14-heartbeat',
                'stage1c-instance-cleanup',
                'stage1d2-terminal-cleanup',
            ],
        )
        entry = schedule['phase14-heartbeat']
        self.assertEqual(entry['task'], 'ops.heartbeat')
        self.assertEqual(entry['args'], ('beat',))
        self.assertGreater(entry['schedule'], 0)
        self.assertEqual(
            schedule['stage1c-instance-cleanup']['task'], 'instances.cleanup_expired'
        )
        self.assertEqual(
            schedule['stage1d2-terminal-cleanup']['task'], 'terminal.cleanup_stale'
        )
        self.assertGreater(schedule['stage1d2-terminal-cleanup']['schedule'], 0)

    def test_heartbeat_tracking_has_bounded_defaults(self):
        from django.conf import settings

        self.assertTrue(settings.CELERY_HEARTBEAT_TRACKING_ENABLED)
        self.assertGreaterEqual(settings.CELERY_HEARTBEAT_TTL_SECONDS, 180)
        self.assertGreaterEqual(settings.CELERY_BEAT_STALE_AFTER_SECONDS, 180)
        self.assertGreater(settings.CELERY_HEALTH_TIMEOUT_SECONDS, 0)
