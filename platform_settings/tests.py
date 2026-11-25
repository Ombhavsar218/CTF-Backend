"""Tests for database-backed platform settings and their enforcement."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from audit.models import AuditLog
from audit.services import AuditAction
from challenges.models import Category, Challenge, ChallengeHint
from submissions.models import HintUnlock

from .models import PlatformSettings

User = get_user_model()

SETTINGS_URL = '/api/v1/admin/settings/'
REGISTER_URL = '/api/v1/auth/register/'
LEADERBOARD_URL = '/api/v1/leaderboard/'
PASSWORD = 'pass12345'


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']
)
class PlatformSettingsTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_groups', stdout=StringIO(), no_color=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            'settings_admin', 'settings-admin@example.com', PASSWORD,
        )
        self.admin.groups.add(Group.objects.get(name='Admin'))
        self.player = User.objects.create_user(
            'settings_player', 'settings-player@example.com', PASSWORD,
        )
        self.client = APIClient()

    def authenticate_admin(self):
        self.client.force_authenticate(self.admin)

    def authenticate_player(self):
        self.client.force_authenticate(self.player)

    def patch_settings(self, payload):
        self.authenticate_admin()
        return self.client.patch(SETTINGS_URL, payload, format='json')


class PlatformSettingsApiTests(PlatformSettingsTestBase):
    def test_defaults_are_returned_without_creating_a_row(self):
        self.authenticate_admin()
        response = self.client.get(SETTINGS_URL)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.data,
            {
                'allow_registration': True,
                'public_leaderboard': True,
                'allow_hints': True,
            },
        )
        self.assertEqual(set(response.data), {
            'allow_registration', 'public_leaderboard', 'allow_hints',
        })
        self.assertFalse(PlatformSettings.objects.exists())

    def test_unauthenticated_access_is_rejected(self):
        self.assertIn(self.client.get(SETTINGS_URL).status_code, (401, 403))
        response = self.client.patch(
            SETTINGS_URL, {'allow_hints': False}, format='json',
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(PlatformSettings.objects.exists())

    def test_non_admin_without_model_permission_is_rejected(self):
        self.authenticate_player()
        self.assertEqual(self.client.get(SETTINGS_URL).status_code, 403)
        response = self.client.patch(
            SETTINGS_URL, {'allow_hints': False}, format='json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PlatformSettings.objects.exists())

    def test_admin_can_read_and_partially_update(self):
        response = self.patch_settings({'allow_hints': False})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['allow_hints'], False)
        self.assertEqual(response.data['allow_registration'], True)
        self.assertEqual(response.data['public_leaderboard'], True)

    def test_update_persists_across_independent_requests(self):
        self.patch_settings({
            'allow_registration': False,
            'public_leaderboard': False,
        })

        # A fresh client and authentication session must read stored values.
        second_client = APIClient()
        second_client.force_authenticate(self.admin)
        response = second_client.get(SETTINGS_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['allow_registration'], False)
        self.assertEqual(response.data['public_leaderboard'], False)
        self.assertEqual(response.data['allow_hints'], True)
        stored = PlatformSettings.objects.get(pk=1)
        self.assertFalse(stored.allow_registration)
        self.assertFalse(stored.public_leaderboard)
        self.assertTrue(stored.allow_hints)

    def test_unknown_fields_are_rejected_without_writing(self):
        response = self.patch_settings({'debug': False})

        self.assertEqual(response.status_code, 400)
        self.assertIn('debug', response.data)
        self.assertEqual(response.data['debug'][0], 'Unknown setting.')
        self.assertFalse(PlatformSettings.objects.exists())

    def test_invalid_values_are_rejected_without_writing(self):
        response = self.patch_settings({'allow_hints': 'not-a-boolean'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('allow_hints', response.data)
        self.assertFalse(PlatformSettings.objects.exists())

    def test_empty_update_is_rejected(self):
        response = self.patch_settings({})

        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.data)
        self.assertFalse(PlatformSettings.objects.exists())

    def test_post_and_delete_are_not_exposed(self):
        self.authenticate_admin()
        self.assertIn(
            self.client.post(SETTINGS_URL, {}, format='json').status_code,
            (403, 405),
        )
        self.assertIn(self.client.delete(SETTINGS_URL).status_code, (403, 405))

    def test_successful_update_is_audited_without_storing_values(self):
        response = self.patch_settings({
            'allow_registration': False,
            'allow_hints': False,
        })
        self.assertEqual(response.status_code, 200)

        log = AuditLog.objects.get(action=AuditAction.SETTINGS_UPDATE)
        self.assertEqual(log.target_type, 'settings')
        self.assertEqual(log.target_id, '1')
        self.assertEqual(log.target_label, 'Platform settings')
        self.assertEqual(
            log.metadata['fields'],
            ['allow_hints', 'allow_registration'],
        )
        self.assertNotIn('False', str(log.metadata))

    def test_audit_failure_rolls_back_the_settings_update(self):
        with patch(
            'audit.services.AuditLog.objects.create',
            side_effect=RuntimeError('audit unavailable'),
        ):
            response = self.patch_settings({'allow_hints': False})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('audit unavailable', str(response.data))

        self.assertFalse(PlatformSettings.objects.exists())
        self.assertFalse(
            AuditLog.objects.filter(action=AuditAction.SETTINGS_UPDATE).exists()
        )


class PlatformSettingsEnforcementTests(PlatformSettingsTestBase):
    def test_registration_can_be_disabled_and_re_enabled(self):
        PlatformSettings.objects.create(pk=1, allow_registration=False)
        payload = {
            'username': 'blocked_player',
            'email': 'blocked@example.com',
            'password': PASSWORD,
            'password2': PASSWORD,
        }

        response = self.client.post(REGISTER_URL, payload, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], 'Registration is currently disabled.')
        self.assertFalse(User.objects.filter(username='blocked_player').exists())

        PlatformSettings.objects.filter(pk=1).update(allow_registration=True)
        payload['username'] = 'allowed_player'
        payload['email'] = 'allowed@example.com'
        response = self.client.post(REGISTER_URL, payload, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(User.objects.filter(username='allowed_player').exists())

    def test_public_leaderboard_can_require_authentication(self):
        self.assertEqual(self.client.get(LEADERBOARD_URL).status_code, 200)

        PlatformSettings.objects.create(pk=1, public_leaderboard=False)
        anonymous = self.client.get(LEADERBOARD_URL)
        self.assertIn(anonymous.status_code, (401, 403))

        self.authenticate_player()
        authenticated = self.client.get(LEADERBOARD_URL)
        self.assertEqual(authenticated.status_code, 200, authenticated.content)

    def test_hints_can_be_disabled_without_charging_or_unlocking(self):
        category = Category.objects.create(name='Settings category')
        challenge = Challenge.objects.create(
            title='Settings challenge',
            category=category,
            points=100,
            status=Challenge.STATUS_PUBLISHED,
        )
        hint = ChallengeHint.objects.create(
            challenge=challenge, text='Hidden clue', cost=30, order=0,
        )
        self.player.points = 100
        self.player.save(update_fields=['points'])
        PlatformSettings.objects.create(pk=1, allow_hints=False)

        self.authenticate_player()
        url = f'/api/v1/challenges/{challenge.pk}/hints/{hint.pk}/reveal/'
        response = self.client.post(url, {}, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], 'Hints are currently disabled.')
        self.assertEqual(HintUnlock.objects.count(), 0)
        self.player.refresh_from_db()
        self.assertEqual(self.player.points, 100)

        PlatformSettings.objects.filter(pk=1).update(allow_hints=True)
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(HintUnlock.objects.count(), 1)
        self.player.refresh_from_db()
        self.assertEqual(self.player.points, 70)

    def test_missing_settings_row_uses_safe_defaults(self):
        self.assertFalse(PlatformSettings.objects.exists())
        self.assertEqual(self.client.get(LEADERBOARD_URL).status_code, 200)

        response = self.client.post(REGISTER_URL, {
            'username': 'defaults_player',
            'email': 'defaults@example.com',
            'password': PASSWORD,
            'password2': PASSWORD,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
