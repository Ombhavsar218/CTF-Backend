"""Focused Stage 3 submission/hint tests for Decode Me."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from challenges.models import Category, Challenge, ChallengeFlag, ChallengeHint
from submissions.models import HintUnlock, Solve, Submission

User = get_user_model()

CORRECT_FLAG = 'CTF{correct_horse_battery_staple}'
FLAG_CORRECT = 'FLAG{base64_is_not_a_lock}'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DecodeMeSubmissionHintTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.category = Category.objects.create(name='Crypto')
        self.student = User.objects.create_user('student', 'student@example.com', 'pass12345')
        self.student.learning_mode = User.LEARNING_MODE_STUDENT
        self.student.points = 100
        self.student.save(update_fields=['learning_mode', 'points'])
        self.competitor = User.objects.create_user('competitor', 'competitor@example.com', 'pass12345')
        self.competitor.learning_mode = User.LEARNING_MODE_COMPETITOR
        self.competitor.points = 100
        self.competitor.save(update_fields=['learning_mode', 'points'])

        self.challenge = Challenge.objects.create(
            title='Decode Me Mode Aware',
            category=self.category,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=100,
            status=Challenge.STATUS_PUBLISHED,
            mode_content={
                'student': {'introduction': 'Guided'},
                'competitor': {'objective': 'Independent'},
                'solution': {'explanation': 'Because Base64 is encoding'},
            },
        )
        flag = ChallengeFlag(challenge=self.challenge)
        flag.set_flag(FLAG_CORRECT)
        flag.save()
        self.hint = ChallengeHint.objects.create(
            challenge=self.challenge, text='Student progressive hint', cost=10, order=0
        )

        self.plain = Challenge.objects.create(
            title='Plain Challenge',
            category=self.category,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=50,
            status=Challenge.STATUS_PUBLISHED,
        )
        plain_flag = ChallengeFlag(challenge=self.plain)
        plain_flag.set_flag(CORRECT_FLAG)
        plain_flag.save()
        self.plain_hint = ChallengeHint.objects.create(
            challenge=self.plain, text='Plain hint', cost=10, order=0
        )

    def submit_url(self, challenge):
        return f'/api/v1/challenges/{challenge.pk}/submit/'

    def reveal_url(self, challenge, hint):
        return f'/api/v1/challenges/{challenge.pk}/hints/{hint.pk}/reveal/'

    def test_flag_prefix_submission_verification_is_case_sensitive(self):
        self.client.force_authenticate(user=self.student)
        wrong_case = self.client.post(self.submit_url(self.challenge), {'flag': FLAG_CORRECT.lower()}, format='json')
        self.assertEqual(wrong_case.status_code, 200)
        self.assertFalse(wrong_case.json()['correct'])

        correct = self.client.post(self.submit_url(self.challenge), {'flag': f'  {FLAG_CORRECT}  '}, format='json')
        self.assertEqual(correct.status_code, 200, correct.content)
        self.assertTrue(correct.json()['correct'])
        self.assertTrue(Solve.objects.filter(user=self.student, challenge=self.challenge).exists())

    def test_competitor_cannot_reveal_hint_on_mode_aware_challenge(self):
        self.client.force_authenticate(user=self.competitor)
        response = self.client.post(self.reveal_url(self.challenge, self.hint), {}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(HintUnlock.objects.filter(user=self.competitor, hint=self.hint).exists())
        self.competitor.refresh_from_db()
        self.assertEqual(self.competitor.points, 100)

    def test_student_can_reveal_hint_on_mode_aware_challenge(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.post(self.reveal_url(self.challenge, self.hint), {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body['revealed'])
        self.assertEqual(body['hint']['text'], 'Student progressive hint')
        self.assertTrue(HintUnlock.objects.filter(user=self.student, hint=self.hint).exists())
        self.student.refresh_from_db()
        self.assertEqual(self.student.points, 90)

    def test_non_mode_aware_challenge_hint_reveal_unchanged(self):
        self.client.force_authenticate(user=self.competitor)
        response = self.client.post(self.reveal_url(self.plain, self.plain_hint), {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['hint']['text'], 'Plain hint')

    def test_existing_submission_solve_behavior_regression(self):
        self.client.force_authenticate(user=self.student)
        ok = self.client.post(self.submit_url(self.plain), {'flag': CORRECT_FLAG}, format='json')
        self.assertTrue(ok.json()['correct'])
        again = self.client.post(self.submit_url(self.plain), {'flag': CORRECT_FLAG}, format='json')
        self.assertTrue(again.json()['alreadySolved'])
        self.assertEqual(Solve.objects.filter(user=self.student, challenge=self.plain).count(), 1)
        self.assertTrue(Submission.objects.filter(user=self.student, challenge=self.plain, correct=True).exists())
