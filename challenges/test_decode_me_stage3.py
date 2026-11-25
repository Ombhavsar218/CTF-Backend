"""Focused Stage 3 backend tests for Decode Me.

Covers flag compatibility, learning mode/content authorization, solution
gating, mode-aware hints in challenge APIs, and regression-sensitive cases
required for backend enforcement.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from submissions.models import HintUnlock, Solve

from .models import Challenge, ChallengeFlag, ChallengeHint
from .tests import ChallengeTestMixin

User = get_user_model()

CTF_FLAG = 'CTF{decode_me_ctf}'
FLAG_FLAG = 'FLAG{base64_is_not_a_lock}'


class DecodeMeFlagCompatibilityTests(ChallengeTestMixin, TestCase):
    def test_admin_can_create_challenge_with_ctf_prefix(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.post(
            '/api/v1/admin/challenges/',
            self.payload(flag=CTF_FLAG, title='CTF Prefix'),
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        challenge = Challenge.objects.get(pk=response.json()['id'])
        self.assertTrue(challenge.verify_flag(CTF_FLAG))
        self.assertNotIn(CTF_FLAG, challenge.flag.hash)

    def test_admin_can_create_challenge_with_flag_prefix(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.post(
            '/api/v1/admin/challenges/',
            self.payload(flag=FLAG_FLAG, title='FLAG Prefix'),
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body['has_flag'])
        self.assertNotIn('flag', body)
        challenge = Challenge.objects.get(pk=body['id'])
        self.assertTrue(challenge.verify_flag(FLAG_FLAG))
        self.assertFalse(challenge.verify_flag(FLAG_FLAG.lower()))
        self.assertNotIn(FLAG_FLAG, challenge.flag.hash)

    def test_admin_can_replace_flag_with_flag_prefix(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.patch(
            f'/api/v1/admin/challenges/{self.published.id}/',
            {'flag': FLAG_FLAG},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.published.refresh_from_db()
        self.assertTrue(self.published.verify_flag(FLAG_FLAG))
        self.assertFalse(self.published.verify_flag('CTF{published_flag}'))

    def test_invalid_flag_prefixes_and_malformed_braces_are_rejected(self):
        self.client.force_authenticate(user=self.make_admin())
        invalid = [
            'flag{nope}',
            'FLAG{}',
            'CTF{}',
            'CTF{missing',
            'FLAG missing',
            'PREFIX{test}',
        ]
        for value in invalid:
            response = self.client.post(
                '/api/v1/admin/challenges/',
                self.payload(flag=value, title=f'Bad {value[:10]}'),
                format='json',
            )
            self.assertEqual(response.status_code, 400, (value, response.content))
            self.assertIn('flag', response.json())

    def test_flag_redaction_accepts_flag_prefix(self):
        # Validate the helper redacts FLAG{...} the same as CTF{...}.
        from config.observability import redact_sensitive

        text = f'leaked {FLAG_FLAG} and {CTF_FLAG}'
        redacted = redact_sensitive(text)
        self.assertNotIn(FLAG_FLAG, redacted)
        self.assertNotIn(CTF_FLAG, redacted)
        self.assertIn('[REDACTED_FLAG]', redacted)


class DecodeMeModeAndContentTests(ChallengeTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.student = self.make_plain_user()
        self.student.learning_mode = User.LEARNING_MODE_STUDENT
        self.student.save(update_fields=['learning_mode'])
        self.competitor = User.objects.create_user(
            username='ch_competitor',
            email='ch_competitor@example.com',
            password='pass12345',
        )
        self.competitor.learning_mode = User.LEARNING_MODE_COMPETITOR
        self.competitor.save(update_fields=['learning_mode'])

        self.published.mode_content = {
            'student': {
                'introduction': 'Student intro',
                'scenario': 'Student scenario',
                'learning_objectives': ['Learn Base64'],
                'tasks': [{'title': 'Inspect file', 'description': 'Open artifact'}],
                'checkpoints': [{'title': 'Recognized encoding'}],
                'guidance': [{'text': 'Look for padding'}],
                'review_questions': [{'question': 'Why not encryption?'}],
                'common_mistakes': [{'mistake': 'Treat as hash'}],
                'remediation_guidance': [{'guidance': 'Try decoding'}],
            },
            'competitor': {
                'challenge_rules': ['No external services'],
                'objective': 'Decode the artifact',
                'time_limit': {'minutes': 30},
                'submission_instructions': 'Submit FLAG{...}',
            },
            'solution': {
                'explanation': 'It is Base64',
                'walkthrough': ['Decode the message'],
                'expected_result': 'Recovered message',
                'learning_takeaways': ['Encoding is reversible'],
            },
        }
        self.published.save(update_fields=['mode_content'])

        ChallengeHint.objects.create(
            challenge=self.published, text='Student-only progressive hint', cost=5, order=1
        )

    def mode_content_url(self, challenge):
        return f'/api/v1/challenges/{challenge.pk}/content/'

    def solution_url(self, challenge):
        return f'/api/v1/challenges/{challenge.pk}/solution/'

    def test_admin_can_store_valid_mode_content_and_it_is_hidden_from_public(self):
        self.client.force_authenticate(user=self.make_admin())
        payload = self.payload(title='Mode Content Challenge', flag=FLAG_FLAG)
        payload['mode_content'] = {
            'student': {'introduction': 'Intro', 'learning_objectives': ['Obj']},
            'competitor': {'objective': 'Compete', 'challenge_rules': ['Rule']},
            'solution': {'explanation': 'Solve it', 'learning_takeaways': ['Lesson']},
        }
        response = self.client.post('/api/v1/admin/challenges/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body['mode_content']['student']['introduction'], 'Intro')

        challenge = Challenge.objects.get(pk=body['id'])
        challenge.status = Challenge.STATUS_PUBLISHED
        challenge.save(update_fields=['status'])

        public = self.client.get(f'/api/v1/challenges/{challenge.pk}/')
        self.assertEqual(public.status_code, 200)
        self.assertNotIn('mode_content', public.json())

    def test_mode_content_rejects_unknown_keys_flags_and_oversized_content(self):
        self.client.force_authenticate(user=self.make_admin())
        cases = [
            {'student': {'unknown': 'x'}},
            {'unknown_section': {}},
            {'student': {'introduction': FLAG_FLAG}},
            {'solution': {'explanation': 'password: hunter2'}},
            {'student': {'learning_objectives': ['x' * 5000]}},
        ]
        for mode_content in cases:
            payload = self.payload(title='Bad Mode Content', flag=CTF_FLAG)
            payload['mode_content'] = mode_content
            response = self.client.post('/api/v1/admin/challenges/', payload, format='json')
            self.assertEqual(response.status_code, 400, (mode_content, response.content))

    def test_mode_content_endpoint_requires_authentication(self):
        response = self.client.get(self.mode_content_url(self.published))
        self.assertIn(response.status_code, (401, 403))

    def test_student_receives_only_student_content(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(self.mode_content_url(self.published))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['mode'], 'student')
        self.assertIn('student', self.published.mode_content)
        self.assertEqual(body['content'], self.published.mode_content['student'])
        self.assertNotIn('competitor', body)
        self.assertNotIn('solution', body)
        self.assertFalse(body['solution_available'])

    def test_competitor_receives_only_competitor_content(self):
        self.client.force_authenticate(user=self.competitor)
        response = self.client.get(self.mode_content_url(self.published))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['mode'], 'competitor')
        self.assertEqual(body['content'], self.published.mode_content['competitor'])
        self.assertNotIn('student', str(body))
        self.assertNotIn('solution', body)

    def test_client_supplied_mode_is_ignored(self):
        self.client.force_authenticate(user=self.competitor)
        response = self.client.get(
            self.mode_content_url(self.published) + '?mode=student',
            HTTP_X_LEARNING_MODE='student',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'competitor')
        self.assertEqual(response.json()['content'], self.published.mode_content['competitor'])

        post_like = self.client.post(
            self.mode_content_url(self.published),
            {'mode': 'student'},
            format='json',
        )
        self.assertEqual(post_like.status_code, 405)

    def test_mode_content_for_draft_is_not_exposed_to_unauthorized_user(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(self.mode_content_url(self.draft))
        self.assertEqual(response.status_code, 404)

    def test_solution_requires_authentication(self):
        response = self.client.get(self.solution_url(self.published))
        self.assertIn(response.status_code, (401, 403))

    def test_unsolved_student_cannot_access_solution(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(self.solution_url(self.published))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Base64', str(response.json()))

    def test_solved_student_can_access_solution_only(self):
        Solve.objects.create(user=self.student, challenge=self.published, points=self.published.points)
        self.client.force_authenticate(user=self.student)
        response = self.client.get(self.solution_url(self.published))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body['solution_available'])
        self.assertEqual(body['solution'], self.published.mode_content['solution'])

        # Ensure no cross-mode/ordinary leakage via this endpoint.
        self.assertNotIn('content', body)

    def test_solved_competitor_cannot_access_solution(self):
        Solve.objects.create(user=self.competitor, challenge=self.published, points=self.published.points)
        self.client.force_authenticate(user=self.competitor)
        response = self.client.get(self.solution_url(self.published))
        self.assertEqual(response.status_code, 403)

    def test_other_users_or_other_challenge_solves_do_not_grant_access(self):
        Solve.objects.create(user=self.student, challenge=self.published, points=self.published.points)
        other_student = User.objects.create_user('other_student', 'os@example.com', 'pass12345')
        other_student.learning_mode = User.LEARNING_MODE_STUDENT
        other_student.save(update_fields=['learning_mode'])
        self.client.force_authenticate(user=other_student)
        response = self.client.get(self.solution_url(self.published))
        self.assertEqual(response.status_code, 403)

        Solve.objects.create(user=other_student, challenge=self.draft, points=self.draft.points)
        # draft not published and user lacks view perm -> 404; still no grant path.
        response = self.client.get(self.solution_url(self.draft))
        self.assertEqual(response.status_code, 404)

    def test_public_challenge_payload_hides_mode_content_and_mode_aware_hints_for_competitor(self):
        self.client.force_authenticate(user=self.competitor)
        response = self.client.get(f'/api/v1/challenges/{self.published.pk}/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn('mode_content', body)
        self.assertEqual(body['hints'], [])

        self.client.force_authenticate(user=self.student)
        student_resp = self.client.get(f'/api/v1/challenges/{self.published.pk}/')
        self.assertEqual(student_resp.status_code, 200)
        self.assertGreaterEqual(len(student_resp.json()['hints']), 1)
        self.assertNotIn('mode_content', student_resp.json())

    def test_existing_non_mode_aware_challenge_hints_unchanged(self):
        plain = Challenge.objects.create(
            title='Plain Published',
            category=self.web,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=50,
            status=Challenge.STATUS_PUBLISHED,
        )
        ChallengeFlag.objects.create(challenge=plain, hash='x')
        ChallengeHint.objects.create(challenge=plain, text='Visible metadata', cost=1, order=0)

        self.client.force_authenticate(user=self.competitor)
        response = self.client.get(f'/api/v1/challenges/{plain.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['hints']), 1)

    def test_public_serializer_has_mode_content_indicator_without_sensitive_data(self):
        # Ordinary published challenge: no mode content.
        plain = Challenge.objects.create(
            title='Plain Indicator',
            category=self.web,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=50,
            status=Challenge.STATUS_PUBLISHED,
        )
        ChallengeFlag.objects.create(challenge=plain, hash='x')

        plain_resp = self.client.get(f'/api/v1/challenges/{plain.pk}/')
        self.assertEqual(plain_resp.status_code, 200)
        plain_body = plain_resp.json()
        self.assertIs(plain_body['has_mode_content'], False)
        self.assertNotIn('mode_content', plain_body)
        self.assertNotIn('solution', plain_body)

        # Mode-aware published challenge: indicator true, but no sensitive content.
        mode_resp = self.client.get(f'/api/v1/challenges/{self.published.pk}/')
        self.assertEqual(mode_resp.status_code, 200)
        mode_body = mode_resp.json()
        self.assertIs(mode_body['has_mode_content'], True)
        self.assertNotIn('mode_content', mode_body)
        self.assertNotIn('solution', mode_body)
        # Existing public fields remain intact.
        self.assertEqual(mode_body['id'], self.published.pk)
        self.assertEqual(mode_body['title'], self.published.title)
        self.assertEqual(mode_body['category'], self.web.name)
        self.assertIn('hints', mode_body)

        # Mode-specific content remains only on authenticated content endpoint.
        anon_content = self.client.get(self.mode_content_url(self.published))
        self.assertEqual(anon_content.status_code, 401)

        self.client.force_authenticate(user=self.student)
        student_content = self.client.get(self.mode_content_url(self.published))
        self.assertEqual(student_content.status_code, 200)
        self.assertEqual(student_content.json()['content'], self.published.mode_content['student'])

        self.client.force_authenticate(user=self.competitor)
        competitor_content = self.client.get(self.mode_content_url(self.published))
        self.assertEqual(competitor_content.status_code, 200)
        self.assertEqual(competitor_content.json()['content'], self.published.mode_content['competitor'])
