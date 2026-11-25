import threading
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from challenges.models import Category, Challenge
from instances.models import ChallengeInstance
from instances.services import InstanceService


User = get_user_model()


def _runtime_challenge(**kwargs):
    defaults = dict(
        runtime_enabled=True,
        runtime_image='example/challenge:latest',
        runtime_internal_port=8080,
        runtime_connection_type='http',
    )
    defaults.update(kwargs)
    return defaults


class InstanceRoutingTests(SimpleTestCase):
    def test_instance_urls_match_frontend_contract(self):
        # Regression guard: the SPA used to call /api/v1/instances/active/,
        # which is not a registered route and produced a misleading 404.
        self.assertEqual(
            reverse('instances:instance-active'),
            '/api/v1/challenges/instances/active/',
        )
        self.assertEqual(
            reverse('instances:instance-start', kwargs={'pk': 7}),
            '/api/v1/challenges/7/instances/start/',
        )


class InstanceModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u1', 'u1@example.com', 'pass12345')
        self.cat = Category.objects.create(name='Web', slug='web')
        self.challenge = Challenge.objects.create(
            title='Test',
            slug='test',
            category=self.cat,
            difficulty='Easy',
            points=100,
            status=Challenge.STATUS_PUBLISHED,
        )

    def test_create_instance_defaults(self):
        now = timezone.now()
        inst = ChallengeInstance.objects.create(
            user=self.user,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_REQUESTED,
            expires_at=now + timedelta(minutes=60),
        )
        self.assertTrue(inst.is_active)
        self.assertFalse(inst.is_expired)

    def test_unique_active_per_user_constraint(self):
        now = timezone.now()
        ChallengeInstance.objects.create(
            user=self.user,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_RUNNING,
            expires_at=now + timedelta(minutes=60),
        )
        with self.assertRaises(Exception):
            ChallengeInstance.objects.create(
                user=self.user,
                challenge=self.challenge,
                status=ChallengeInstance.STATUS_STARTING,
                expires_at=now + timedelta(minutes=60),
            )


class InstanceAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u2', 'u2@example.com', 'pass12345')
        self.cat = Category.objects.create(name='Crypto', slug='crypto')
        self.challenge = Challenge.objects.create(
            title='Test2',
            slug='test2',
            category=self.cat,
            difficulty='Easy',
            points=50,
            status=Challenge.STATUS_PUBLISHED,
            **_runtime_challenge(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @staticmethod
    def _start_side_effect(instance, challenge):
        instance.status = ChallengeInstance.STATUS_RUNNING
        instance.internal_container_id = 'container-abc'
        instance.connection_meta = {
            'type': 'http', 'host': '127.0.0.1', 'port': 32768,
            'url': 'http://127.0.0.1:32768',
        }
        return instance

    def test_start_returns_real_running_instance(self):
        with patch('instances.services.ChallengeRuntimeService') as runtime_cls:
            runtime_cls.return_value.start.side_effect = self._start_side_effect
            url = reverse('instances:instance-start', kwargs={'pk': self.challenge.pk})
            resp = self.client.post(url)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], ChallengeInstance.STATUS_RUNNING)
        self.assertEqual(resp.data['connection_meta']['port'], 32768)
        self.assertIn('remaining_seconds', resp.data)

    def test_start_not_eligible_without_runtime_config(self):
        self.challenge.runtime_enabled = False
        self.challenge.save(update_fields=['runtime_enabled'])
        url = reverse('instances:instance-start', kwargs={'pk': self.challenge.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'INSTANCE_NOT_ELIGIBLE')
        self.assertEqual(ChallengeInstance.objects.count(), 0)

    def test_start_failure_is_503_and_marks_instance_failed(self):
        from challenge_runtime.errors import ContainerLaunchFailed

        with patch('instances.services.ChallengeRuntimeService') as runtime_cls:
            runtime_cls.return_value.start.side_effect = ContainerLaunchFailed('launch refused')
            url = reverse('instances:instance-start', kwargs={'pk': self.challenge.pk})
            resp = self.client.post(url)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'INSTANCE_RUNTIME_FAILURE')
        failed = ChallengeInstance.objects.get(user=self.user)
        self.assertEqual(failed.status, ChallengeInstance.STATUS_FAILED)
        self.assertEqual(failed.failure_reason, 'launch refused')

    def test_active_none_returns_204(self):
        url = reverse('instances:instance-active')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 204)

    def test_active_returns_owned_instance(self):
        inst = ChallengeInstance.objects.create(
            user=self.user,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_RUNNING,
            expires_at=timezone.now() + timedelta(minutes=30),
            connection_meta={'port': 40000},
        )
        resp = self.client.get(reverse('instances:instance-active'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['id'], inst.pk)
        self.assertEqual(resp.data['connection_meta']['port'], 40000)

    def test_active_expires_and_cleans_up(self):
        inst = ChallengeInstance.objects.create(
            user=self.user,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_RUNNING,
            expires_at=timezone.now() - timedelta(seconds=1),
            connection_meta={'port': 40000},
        )
        def expire_side_effect(obj):
            obj.status = ChallengeInstance.STATUS_EXPIRED
            obj.save(update_fields=['status', 'updated_at'])
            return obj

        with patch('instances.services.ChallengeRuntimeService') as runtime_cls:
            runtime_cls.return_value.expire.side_effect = expire_side_effect
            resp = self.client.get(reverse('instances:instance-active'))
        self.assertEqual(resp.status_code, 204)
        inst.refresh_from_db()
        self.assertEqual(inst.status, ChallengeInstance.STATUS_EXPIRED)

    def test_stop_when_none_returns_204(self):
        url = reverse('instances:instance-active')
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)

    def test_stop_uses_runtime_and_returns_stopped(self):
        inst = ChallengeInstance.objects.create(
            user=self.user,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_RUNNING,
            expires_at=timezone.now() + timedelta(minutes=30),
            internal_container_id='container-abc',
            connection_meta={'port': 40000},
        )
        stopped = False

        def stop_side_effect(obj):
            nonlocal stopped
            stopped = True
            obj.status = ChallengeInstance.STATUS_STOPPED
            obj.connection_meta = None
            obj.save(update_fields=['status', 'connection_meta', 'updated_at'])
            return obj

        with patch('instances.services.ChallengeRuntimeService') as runtime_cls:
            runtime_cls.return_value.stop.side_effect = stop_side_effect
            resp = self.client.delete(reverse('instances:instance-active'))
        self.assertTrue(stopped)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], ChallengeInstance.STATUS_STOPPED)
        self.assertIsNone(resp.data['connection_meta'])
        inst.refresh_from_db()
        self.assertEqual(inst.status, ChallengeInstance.STATUS_STOPPED)

    def test_cannot_stop_another_users_instance(self):
        other = User.objects.create_user('u3', 'u3@example.com', 'pass12345')
        ChallengeInstance.objects.create(
            user=other,
            challenge=self.challenge,
            status=ChallengeInstance.STATUS_RUNNING,
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        with patch('instances.services.ChallengeRuntimeService') as runtime_cls:
            resp = self.client.delete(reverse('instances:instance-active'))
        self.assertEqual(resp.status_code, 204)
        runtime_cls.return_value.stop.assert_not_called()

    def test_unauthenticated_forbidden(self):
        self.client.force_authenticate(user=None)
        url = reverse('instances:instance-start', kwargs={'pk': self.challenge.pk})
        resp = self.client.post(url)
        self.assertIn(resp.status_code, [401, 403])


class InstanceConcurrencyTests(TransactionTestCase):
    def test_concurrent_start_creates_only_one_instance(self):
        user = User.objects.create_user('concurrent', 'c@example.com', 'pass12345')
        cat = Category.objects.create(name='Concurrent', slug='concurrent')
        challenge = Challenge.objects.create(
            title='Concurrent', slug='concurrent', category=cat,
            status=Challenge.STATUS_PUBLISHED, **_runtime_challenge(),
        )
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_start(instance, selected_challenge):
            calls.append(instance.pk)
            entered.set()
            release.wait(timeout=5)
            return instance

        results = []
        errors = []

        def worker():
            try:
                results.append(InstanceService().start(user, challenge))
            except Exception as exc:
                errors.append(exc)

        with patch('instances.services.ChallengeRuntimeService') as runtime_cls:
            runtime_cls.return_value.start.side_effect = slow_start
            first = threading.Thread(target=worker)
            first.start()
            self.assertTrue(entered.wait(timeout=5))
            second = threading.Thread(target=worker)
            second.start()
            second.join(timeout=10)
            release.set()
            first.join(timeout=10)

        # Only one request starts a container; the overlapping request receives
        # the existing reservation instead of creating a duplicate.
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(errors), 0)
        self.assertEqual(sorted(created for _, created in results), [False, True])
        self.assertEqual(ChallengeInstance.objects.filter(user=user).count(), 1)
