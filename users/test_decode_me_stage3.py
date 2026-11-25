"""Focused Stage 3 user learning-mode tests (including Stage 3.1 correction)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class DecodeMeLearningModeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='learner',
            email='learner@example.com',
            password='pass12345',
        )
        self.client.force_authenticate(user=self.user)

    def prefs_url(self):
        return '/api/v1/auth/me/preferences/'

    def me_url(self):
        return '/api/v1/auth/me/'

    def onboarding_url(self):
        return '/api/v1/auth/onboarding/'

    def onboarding_payload(self, user_type='student', **overrides):
        payload = {
            'skillLevel': 'beginner',
            'teamInterest': 'solo',
            'focusAreas': ['web'],
            'purpose': 'learning',
            'experienceType': 'student',
            'userType': user_type,
        }
        payload.update(overrides)
        return payload

    def test_default_learning_mode_is_competitor_and_exposed(self):
        self.assertEqual(self.user.learning_mode, User.LEARNING_MODE_COMPETITOR)
        self.assertFalse(self.user.learning_mode_user_selected)
        response = self.client.get(self.me_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['learning_mode'], 'competitor')

    def test_user_can_update_learning_mode_via_preferences(self):
        response = self.client.patch(self.prefs_url(), {'learning_mode': 'student'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['learning_mode'], 'student')
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertTrue(self.user.learning_mode_user_selected)

        response = self.client.patch(self.prefs_url(), {'learning_mode': 'competitor'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'competitor')
        self.assertTrue(self.user.learning_mode_user_selected)

    def test_invalid_learning_mode_is_rejected(self):
        response = self.client.patch(self.prefs_url(), {'learning_mode': 'admin'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, User.LEARNING_MODE_COMPETITOR)
        self.assertFalse(self.user.learning_mode_user_selected)

    def test_learning_mode_update_does_not_change_role_or_permissions(self):
        self.user.is_staff = False
        self.user.is_superuser = False
        self.user.role = User.ROLE_USER
        self.user.save(update_fields=['is_staff', 'is_superuser', 'role'])

        response = self.client.patch(
            self.prefs_url(),
            {'learning_mode': 'student', 'role': 'admin', 'is_staff': True, 'is_superuser': True},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertEqual(self.user.role, User.ROLE_USER)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.groups.exists())

    def test_effective_learning_mode_falls_back_to_competitor_for_invalid_persisted_value(self):
        User.objects.filter(pk=self.user.pk).update(learning_mode='invalid')
        self.user.refresh_from_db()
        self.assertEqual(self.user.effective_learning_mode, 'competitor')
        response = self.client.get(self.me_url())
        self.assertEqual(response.json()['learning_mode'], 'competitor')

    def test_onboarding_can_sync_learning_mode_without_overwriting_account_role(self):
        payload = self.onboarding_payload(user_type='student')
        response = self.client.post(self.onboarding_url(), payload, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.onboardingCompleted)
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertEqual(self.user.role, User.ROLE_USER)
        self.assertFalse(self.user.learning_mode_user_selected)

    # Stage 3.1 regression tests
    def test_first_onboarding_user_type_student_initializes_student_mode(self):
        user = User.objects.create_user('first_student', 'first_student@example.com', 'pass12345')
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(self.onboarding_url(), self.onboarding_payload('student'), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        user.refresh_from_db()
        self.assertEqual(user.learning_mode, 'student')
        self.assertFalse(user.learning_mode_user_selected)
        self.assertTrue(user.onboardingCompleted)

    def test_first_onboarding_user_type_competitor_initializes_competitor_mode(self):
        user = User.objects.create_user('first_comp', 'first_comp@example.com', 'pass12345')
        client = APIClient()
        client.force_authenticate(user=user)
        # Default is competitor; onboarding with competitor should keep/init as competitor.
        response = client.post(self.onboarding_url(), self.onboarding_payload('competitor'), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        user.refresh_from_db()
        self.assertEqual(user.learning_mode, 'competitor')
        self.assertFalse(user.learning_mode_user_selected)
        self.assertTrue(user.onboardingCompleted)

    def test_onboarding_resubmission_does_not_overwrite_explicit_student_to_competitor(self):
        # First onboarding initializes student.
        self.client.post(self.onboarding_url(), self.onboarding_payload('student'), format='json')
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertFalse(self.user.learning_mode_user_selected)

        # User explicitly changes to competitor via preferences.
        response = self.client.patch(self.prefs_url(), {'learning_mode': 'competitor'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'competitor')
        self.assertTrue(self.user.learning_mode_user_selected)

        # Resubmitting onboarding with userType=student must not overwrite.
        response = self.client.post(self.onboarding_url(), self.onboarding_payload('student'), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'competitor')
        self.assertTrue(self.user.learning_mode_user_selected)

    def test_onboarding_resubmission_does_not_overwrite_explicit_competitor_to_student(self):
        # First onboarding initializes competitor.
        self.client.post(self.onboarding_url(), self.onboarding_payload('competitor'), format='json')
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'competitor')
        self.assertFalse(self.user.learning_mode_user_selected)

        # User explicitly changes to student via preferences.
        response = self.client.patch(self.prefs_url(), {'learning_mode': 'student'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertTrue(self.user.learning_mode_user_selected)

        # Resubmitting onboarding with userType=competitor must not overwrite.
        response = self.client.post(self.onboarding_url(), self.onboarding_payload('competitor'), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertTrue(self.user.learning_mode_user_selected)

    def test_invalid_onboarding_user_type_does_not_change_existing_mode(self):
        self.user.learning_mode = 'student'
        self.user.learning_mode_user_selected = True
        self.user.save(update_fields=['learning_mode', 'learning_mode_user_selected'])

        payload = self.onboarding_payload(user_type='invalid-mode')
        response = self.client.post(self.onboarding_url(), payload, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertTrue(self.user.learning_mode_user_selected)

    def test_onboarding_resubmission_preserves_existing_onboarding_data_shape_and_values(self):
        first = self.onboarding_payload('student', focusAreas=['web', 'crypto'], purpose='learning')
        response = self.client.post(self.onboarding_url(), first, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding['skillLevel'], 'beginner')
        self.assertEqual(self.user.onboarding['teamInterest'], 'solo')
        self.assertEqual(self.user.onboarding['focusAreas'], ['web', 'crypto'])
        self.assertEqual(self.user.onboarding['purpose'], 'learning')
        self.assertEqual(self.user.onboarding['experienceType'], 'student')
        self.assertEqual(self.user.onboarding['userType'], 'student')

        # Resubmission replaces onboarding payload with the new explicit submission
        # (existing view behavior) while preserving learning-mode safety.
        self.client.patch(self.prefs_url(), {'learning_mode': 'competitor'}, format='json')
        second = self.onboarding_payload('student', focusAreas=['forensics'], purpose='career')
        response = self.client.post(self.onboarding_url(), second, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding['focusAreas'], ['forensics'])
        self.assertEqual(self.user.onboarding['purpose'], 'career')
        self.assertEqual(self.user.onboarding['userType'], 'student')
        self.assertEqual(self.user.learning_mode, 'competitor')

    def test_onboarding_resubmission_does_not_modify_account_role_or_permissions(self):
        self.user.is_staff = False
        self.user.is_superuser = False
        self.user.role = User.ROLE_USER
        self.user.save(update_fields=['is_staff', 'is_superuser', 'role'])
        self.client.patch(self.prefs_url(), {'learning_mode': 'student'}, format='json')

        response = self.client.post(self.onboarding_url(), self.onboarding_payload('competitor'), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.learning_mode, 'student')
        self.assertEqual(self.user.role, User.ROLE_USER)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.groups.exists())
