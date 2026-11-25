"""Tests for the challenges app: models, serializers and both API surfaces.

The security-critical invariants get the most attention:

* a flag is only ever stored as a hash and is never serialized;
* ordinary users can only ever see *published* challenges, and never a flag,
  a flag hash/note or a hint's text;
* admin-only mutations are gated by Django model permissions.
"""

import json
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from achievements.models import Achievement
from audit.models import AuditLog
from submissions.models import Solve

from .models import Category, Challenge, ChallengeAttachment, ChallengeFlag, ChallengeHint

User = get_user_model()


class ChallengeTestMixin:
    """Shared fixtures: two categories, a published and a draft challenge."""

    def setUp(self):
        self.web = Category.objects.create(name='Web', order=0)
        self.crypto = Category.objects.create(name='Crypto', order=1)

        self.published = Challenge.objects.create(
            title='Published One',
            category=self.web,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=100,
            status=Challenge.STATUS_PUBLISHED,
            tags=['web'],
        )
        flag = ChallengeFlag(challenge=self.published, note='the real one')
        flag.set_flag('CTF{published_flag}')
        flag.save()
        ChallengeHint.objects.create(
            challenge=self.published, text='Secret hint text', cost=10, order=0
        )

        self.draft = Challenge.objects.create(
            title='Draft One',
            category=self.web,
            difficulty=Challenge.DIFFICULTY_MEDIUM,
            points=200,
            status=Challenge.STATUS_DRAFT,
        )
        draft_flag = ChallengeFlag(challenge=self.draft)
        draft_flag.set_flag('CTF{draft_flag}')
        draft_flag.save()

        self.client = APIClient()

    def grant(self, user, *refs):
        for ref in refs:
            app_label, codename = ref.split('.')
            permission = Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
            user.user_permissions.add(permission)
        return user

    def _make_user(self, username, *refs):
        user = User.objects.create_user(
            username=username, email=f'{username}@example.com', password='pass12345'
        )
        if refs:
            self.grant(user, *refs)
        return user

    def make_admin(self):
        return self._make_user(
            'ch_admin',
            'challenges.view_challenge',
            'challenges.add_challenge',
            'challenges.change_challenge',
            'challenges.delete_challenge',
        )

    def make_creator(self):
        return self._make_user(
            'ch_creator',
            'challenges.view_challenge',
            'challenges.add_challenge',
            'challenges.change_challenge',
        )

    def make_plain_user(self):
        return self._make_user('ch_plain')

    def payload(self, **overrides):
        data = {
            'title': 'New Challenge',
            'category': 'Web',
            'difficulty': 'Hard',
            'points': 400,
            'description': 'Do the thing',
            'status': 'draft',
            'flag': 'CTF{brand_new_flag}',
            'hints': [{'text': 'look closer', 'cost': 5}],
        }
        data.update(overrides)
        return data


class CategoryModelTests(TestCase):
    def test_slug_is_generated_and_unique(self):
        first = Category.objects.create(name='Web Exploitation')
        second = Category.objects.create(name='Web Exploitation!!')
        self.assertEqual(first.slug, 'web-exploitation')
        self.assertEqual(second.slug, 'web-exploitation-2')


class AdminCategoryApiTests(ChallengeTestMixin, TestCase):
    """The category write endpoints and their non-cascading delete policy."""

    URL = '/api/v1/admin/categories/'

    def make_category_admin(self, *extra):
        return self._make_user(
            'cat_admin',
            'challenges.view_category',
            'challenges.add_category',
            'challenges.change_category',
            'challenges.delete_category',
            *extra,
        )

    def make_category_viewer(self):
        return self._make_user('cat_viewer', 'challenges.view_category')

    def payload(self, **overrides):
        data = {
            'name': 'Cloud Security',
            'description': 'Cloud-native attacks and defences',
            'icon': 'Cloud',
            'color': '#3DD9D0',
            'order': 7,
        }
        data.update(overrides)
        return data

    # -- access ----------------------------------------------------------

    def test_category_writes_require_authentication(self):
        response = self.client.post(self.URL, self.payload(), format='json')
        self.assertIn(response.status_code, (401, 403))

    def test_plain_user_cannot_create_edit_or_delete(self):
        unused = Category.objects.create(name='Unused')
        self.client.force_authenticate(user=self.make_plain_user())

        self.assertEqual(
            self.client.post(self.URL, self.payload(), format='json').status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                f'{self.URL}{unused.pk}/',
                {'description': 'changed'},
                format='json',
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f'{self.URL}{unused.pk}/').status_code,
            403,
        )

    def test_view_permission_alone_cannot_write(self):
        unused = Category.objects.create(name='Viewer Target')
        user = self.make_category_viewer()
        self.client.force_authenticate(user=user)

        self.assertEqual(
            self.client.post(self.URL, self.payload(), format='json').status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                f'{self.URL}{unused.pk}/',
                {'description': 'changed'},
                format='json',
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f'{self.URL}{unused.pk}/').status_code,
            403,
        )

    # -- create ----------------------------------------------------------

    def test_create_returns_the_read_shape_and_audits_field_names(self):
        self.client.force_authenticate(user=self.make_category_admin())
        response = self.client.post(
            self.URL,
            self.payload(name='  Cloud Security  ', description='  Short text  '),
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(
            set(body),
            {'id', 'name', 'slug', 'description', 'icon', 'color', 'order', 'count'},
        )
        self.assertEqual(body['name'], 'Cloud Security')
        self.assertEqual(body['slug'], 'cloud-security')
        self.assertEqual(body['description'], 'Short text')
        self.assertEqual(body['count'], 0)
        self.assertEqual(body['order'], 7)

        category = Category.objects.get(pk=body['id'])
        self.assertEqual(category.slug, 'cloud-security')
        log = AuditLog.objects.get(action='category.create')
        self.assertEqual(log.target_type, 'category')
        self.assertEqual(log.target_id, str(category.pk))
        self.assertEqual(log.target_label, 'Cloud Security')
        self.assertEqual(
            log.metadata['fields'],
            ['color', 'description', 'icon', 'name', 'order'],
        )
        self.assertNotIn('Cloud-native attacks', json.dumps(log.metadata))

    def test_create_requires_a_name(self):
        self.client.force_authenticate(user=self.make_category_admin())
        for name in ('', '   '):
            response = self.client.post(
                self.URL, self.payload(name=name), format='json'
            )
            self.assertEqual(response.status_code, 400, response.content)
            self.assertIn('name', response.json())
        self.assertFalse(Category.objects.filter(name='').exists())
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_create_rejects_a_duplicate_name_case_insensitively(self):
        self.client.force_authenticate(user=self.make_category_admin())
        response = self.client.post(
            self.URL, self.payload(name='web'), format='json'
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('name', response.json())
        self.assertEqual(Category.objects.filter(name__iexact='web').count(), 1)
        self.assertEqual(AuditLog.objects.count(), 0)

    # -- update ----------------------------------------------------------

    def test_update_returns_the_read_shape_and_keeps_the_slug(self):
        original_slug = self.web.slug
        self.client.force_authenticate(user=self.make_category_admin())
        response = self.client.patch(
            f'{self.URL}{self.web.pk}/',
            {'name': 'Web Security', 'description': 'Updated', 'order': 4},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['name'], 'Web Security')
        self.assertEqual(body['slug'], original_slug)
        self.assertEqual(body['description'], 'Updated')
        self.assertEqual(body['order'], 4)
        # Web still owns one *published* challenge; the read serializer's count
        # only includes published rows.
        self.assertEqual(body['count'], 1)

        self.web.refresh_from_db()
        self.assertEqual(self.web.slug, original_slug)
        log = AuditLog.objects.get(action='category.update')
        self.assertEqual(log.metadata['fields'], ['description', 'name', 'order'])

    def test_update_rejects_a_duplicate_name_but_allows_its_own_name(self):
        self.client.force_authenticate(user=self.make_category_admin())
        duplicate = self.client.patch(
            f'{self.URL}{self.web.pk}/',
            {'name': 'Crypto'},
            format='json',
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.content)
        self.assertIn('name', duplicate.json())
        self.web.refresh_from_db()
        self.assertEqual(self.web.name, 'Web')

        unchanged = self.client.patch(
            f'{self.URL}{self.web.pk}/',
            {'name': 'Web'},
            format='json',
        )
        self.assertEqual(unchanged.status_code, 200, unchanged.content)

    def test_update_missing_category_is_404(self):
        self.client.force_authenticate(user=self.make_category_admin())
        response = self.client.patch(
            f'{self.URL}999999/', {'description': 'x'}, format='json'
        )
        self.assertEqual(response.status_code, 404)

    # -- delete ----------------------------------------------------------

    def test_delete_unused_category_removes_it_and_audits(self):
        unused = Category.objects.create(name='Unused')
        self.client.force_authenticate(user=self.make_category_admin())
        response = self.client.delete(f'{self.URL}{unused.pk}/')
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(Category.objects.filter(pk=unused.pk).exists())
        log = AuditLog.objects.get(action='category.delete')
        self.assertEqual(log.target_id, str(unused.pk))
        self.assertEqual(log.target_label, 'Unused')

    def test_delete_referenced_by_challenge_is_refused_without_cascades(self):
        solver = self.make_plain_user()
        Solve.objects.create(
            challenge=self.published, user=solver, points=self.published.points
        )
        self.client.force_authenticate(user=self.make_category_admin())

        response = self.client.delete(f'{self.URL}{self.web.pk}/')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('challenge(s) still use', response.json()['detail'])

        self.assertTrue(Category.objects.filter(pk=self.web.pk).exists())
        self.assertEqual(
            set(Challenge.objects.filter(category=self.web).values_list('pk', flat=True)),
            {self.published.pk, self.draft.pk},
        )
        self.assertEqual(
            Solve.objects.filter(challenge=self.published, user=solver).count(),
            1,
        )
        self.assertFalse(AuditLog.objects.filter(action='category.delete').exists())

    def test_delete_referenced_by_an_achievement_rule_is_refused(self):
        achievement = Achievement.objects.create(
            name='Crypto Expert',
            criteria_type=Achievement.CRITERIA_CATEGORY_SOLVES,
            criteria_config={'category': self.crypto.pk, 'target': 2},
        )
        self.client.force_authenticate(user=self.make_category_admin())

        response = self.client.delete(f'{self.URL}{self.crypto.pk}/')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('achievement', response.json()['detail'])
        self.assertTrue(Category.objects.filter(pk=self.crypto.pk).exists())
        self.assertTrue(Achievement.objects.filter(pk=achievement.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='category.delete').exists())

    def test_soft_deleted_achievement_does_not_block_delete(self):
        achievement = Achievement.objects.create(
            name='Old Crypto Rule',
            criteria_type=Achievement.CRITERIA_CATEGORY_SOLVES,
            criteria_config={'category': self.crypto.pk, 'target': 2},
        )
        achievement.delete()  # soft delete
        self.client.force_authenticate(user=self.make_category_admin())

        response = self.client.delete(f'{self.URL}{self.crypto.pk}/')
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(Category.objects.filter(pk=self.crypto.pk).exists())
        self.assertTrue(Achievement.all_objects.filter(pk=achievement.pk).exists())

    def test_delete_race_is_reported_and_writes_no_audit_row(self):
        unused = Category.objects.create(name='Race Target')
        self.client.force_authenticate(user=self.make_category_admin())

        with patch.object(
            Category,
            'delete',
            side_effect=ProtectedError('protected', {self.published}),
        ):
            response = self.client.delete(f'{self.URL}{unused.pk}/')

        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Category.objects.filter(pk=unused.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='category.delete').exists())

    # -- challenge integration ------------------------------------------

    def test_new_category_works_for_challenge_creation_filtering_and_detail(self):
        self.client.force_authenticate(
            user=self.make_category_admin(
                'challenges.view_challenge',
                'challenges.add_challenge',
                'challenges.change_challenge',
            )
        )
        created = self.client.post(self.URL, self.payload(), format='json')
        self.assertEqual(created.status_code, 201, created.content)
        category_id = created.json()['id']

        challenge_response = self.client.post(
            '/api/v1/admin/challenges/',
            {
                'title': 'Cloud Break',
                'category': 'Cloud Security',
                'difficulty': 'Hard',
                'points': 350,
                'status': 'published',
                'flag': 'CTF{cloud_break}',
            },
            format='json',
        )
        self.assertEqual(
            challenge_response.status_code, 201, challenge_response.content
        )
        challenge_id = challenge_response.json()['id']

        public = self.client.get(
            '/api/v1/challenges/', {'category': 'Cloud Security'}
        )
        self.assertEqual(public.status_code, 200)
        self.assertEqual([row['id'] for row in public.json()], [challenge_id])
        self.assertEqual(public.json()[0]['category_id'], category_id)

        renamed = self.client.patch(
            f'{self.URL}{category_id}/',
            {'name': 'Cloud Native'},
            format='json',
        )
        self.assertEqual(renamed.status_code, 200, renamed.content)

        detail = self.client.get(f'/api/v1/challenges/{challenge_id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['category'], 'Cloud Native')
        self.assertEqual(detail.json()['category_id'], category_id)

        admin_list = self.client.get('/api/v1/admin/challenges/')
        self.assertEqual(admin_list.status_code, 200)
        self.assertIn(challenge_id, [row['id'] for row in admin_list.json()])

        refused = self.client.delete(f'{self.URL}{category_id}/')
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertTrue(Challenge.objects.filter(pk=challenge_id).exists())


class ChallengeModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Web')

    def test_slug_is_generated(self):
        challenge = Challenge.objects.create(title='Hello World', category=self.category)
        self.assertEqual(challenge.slug, 'hello-world')

    def test_has_flag_reflects_stored_flag(self):
        challenge = Challenge.objects.create(title='No Flag', category=self.category)
        self.assertFalse(challenge.has_flag)
        flag = ChallengeFlag(challenge=challenge)
        flag.set_flag('CTF{abc}')
        flag.save()
        self.assertTrue(Challenge.objects.get(pk=challenge.pk).has_flag)


class ChallengeFlagTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Crypto')
        self.challenge = Challenge.objects.create(title='Flag', category=self.category)

    def test_flag_is_hashed_not_stored_in_plaintext(self):
        flag = ChallengeFlag(challenge=self.challenge)
        flag.set_flag('CTF{super_secret}')
        flag.save()
        self.assertNotEqual(flag.hash, 'CTF{super_secret}')
        self.assertNotIn('super_secret', flag.hash)

    def test_verify_accepts_the_exact_flag(self):
        flag = ChallengeFlag(challenge=self.challenge)
        flag.set_flag('CTF{super_secret}')
        flag.save()
        self.assertTrue(flag.verify('CTF{super_secret}'))

    def test_verify_strips_surrounding_whitespace(self):
        flag = ChallengeFlag(challenge=self.challenge)
        flag.set_flag('CTF{super_secret}')
        flag.save()
        self.assertTrue(flag.verify('  CTF{super_secret}\n'))

    def test_verify_is_case_sensitive(self):
        flag = ChallengeFlag(challenge=self.challenge)
        flag.set_flag('CTF{Super_Secret}')
        flag.save()
        self.assertFalse(flag.verify('CTF{super_secret}'))

    def test_verify_rejects_a_wrong_flag(self):
        flag = ChallengeFlag(challenge=self.challenge)
        flag.set_flag('CTF{super_secret}')
        flag.save()
        self.assertFalse(flag.verify('CTF{nope}'))
        self.assertFalse(flag.verify(''))


class AttachmentModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Misc')
        self.challenge = Challenge.objects.create(title='Files', category=self.category)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_display_name_and_extension(self):
        with override_settings(MEDIA_ROOT=self.tmp):
            attachment = ChallengeAttachment.objects.create(
                challenge=self.challenge,
                file=SimpleUploadedFile('sample.zip', b'data'),
            )
            self.assertEqual(attachment.display_name, 'sample.zip')
            self.assertEqual(attachment.extension, 'zip')

    def test_file_is_deleted_with_the_row(self):
        import os

        with override_settings(MEDIA_ROOT=self.tmp):
            attachment = ChallengeAttachment.objects.create(
                challenge=self.challenge,
                file=SimpleUploadedFile('gone.txt', b'data'),
            )
            path = attachment.file.path
            self.assertTrue(os.path.exists(path))
            attachment.delete()
            self.assertFalse(os.path.exists(path))


class PublicChallengeApiTests(ChallengeTestMixin, TestCase):
    def test_list_is_a_plain_array_of_published_only(self):
        response = self.client.get('/api/v1/challenges/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body, list)
        ids = [item['id'] for item in body]
        self.assertIn(self.published.id, ids)
        self.assertNotIn(self.draft.id, ids)

    def test_list_never_exposes_flag_or_hint_text(self):
        response = self.client.get('/api/v1/challenges/')
        item = next(
            row for row in response.json() if row['id'] == self.published.id
        )
        self.assertNotIn('flag', item)
        self.assertNotIn('hash', item)
        self.assertNotIn('flag_note', item)
        for hint in item['hints']:
            self.assertEqual(
                set(hint), {'id', 'cost', 'order', 'revealed', 'text'}
            )
            # Anonymous callers never see any hint text.
            self.assertFalse(hint['revealed'])
            self.assertEqual(hint['text'], '')
        self.assertFalse(item['solved'])
        self.assertIn('category', item)
        self.assertIn('createdAt', item)

    def test_filter_by_category_and_search(self):
        by_category = self.client.get('/api/v1/challenges/', {'category': 'Web'}).json()
        self.assertEqual([c['id'] for c in by_category], [self.published.id])

        by_search = self.client.get(
            '/api/v1/challenges/', {'search': 'Published'}
        ).json()
        self.assertEqual([c['id'] for c in by_search], [self.published.id])

        misses = self.client.get('/api/v1/challenges/', {'search': 'Draft'}).json()
        self.assertEqual(misses, [])

    def test_detail_returns_published_and_hides_sensitive_fields(self):
        response = self.client.get(f'/api/v1/challenges/{self.published.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('hash', response.json())

    def test_detail_of_a_draft_is_404(self):
        response = self.client.get(f'/api/v1/challenges/{self.draft.id}/')
        self.assertEqual(response.status_code, 404)

    def test_categories_list(self):
        response = self.client.get('/api/v1/categories/')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)


class AdminChallengeApiTests(ChallengeTestMixin, TestCase):
    def test_anonymous_is_denied(self):
        response = self.client.get('/api/v1/admin/challenges/')
        self.assertIn(response.status_code, (401, 403))

    def test_plain_user_is_denied(self):
        self.client.force_authenticate(user=self.make_plain_user())
        response = self.client.get('/api/v1/admin/challenges/')
        self.assertEqual(response.status_code, 403)

    def test_admin_sees_drafts_too(self):
        self.client.force_authenticate(user=self.make_admin())
        body = self.client.get('/api/v1/admin/challenges/').json()
        self.assertIsInstance(body, list)
        ids = [row['id'] for row in body]
        self.assertIn(self.draft.id, ids)
        self.assertIn(self.published.id, ids)

    def test_creator_can_create_and_flag_is_hashed(self):
        self.client.force_authenticate(user=self.make_creator())
        response = self.client.post(
            '/api/v1/admin/challenges/', self.payload(), format='json'
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertNotIn('flag', body)
        self.assertNotIn('hash', body)
        self.assertTrue(body['has_flag'])

        challenge = Challenge.objects.get(pk=body['id'])
        self.assertTrue(challenge.verify_flag('CTF{brand_new_flag}'))
        self.assertNotIn('CTF{brand_new_flag}', challenge.flag.hash)
        self.assertEqual(challenge.hints.count(), 1)

    def test_create_requires_a_well_formed_flag(self):
        self.client.force_authenticate(user=self.make_admin())
        missing = self.payload(flag='')
        self.assertEqual(
            self.client.post(
                '/api/v1/admin/challenges/', missing, format='json'
            ).status_code,
            400,
        )
        malformed = self.payload(flag='not-a-flag')
        self.assertEqual(
            self.client.post(
                '/api/v1/admin/challenges/', malformed, format='json'
            ).status_code,
            400,
        )

    def test_update_does_not_require_the_flag_again(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.patch(
            f'/api/v1/admin/challenges/{self.published.id}/',
            {'points': 999},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.published.refresh_from_db()
        self.assertEqual(self.published.points, 999)
        self.assertTrue(self.published.has_flag)

    def test_update_can_replace_the_flag(self):
        self.client.force_authenticate(user=self.make_admin())
        self.client.patch(
            f'/api/v1/admin/challenges/{self.published.id}/',
            {'flag': 'CTF{replaced}'},
            format='json',
        )
        self.published.refresh_from_db()
        self.assertTrue(self.published.verify_flag('CTF{replaced}'))
        self.assertFalse(self.published.verify_flag('CTF{published_flag}'))

    def test_scheduling_requires_a_publish_time(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.post(
            '/api/v1/admin/challenges/',
            self.payload(status='scheduled', flag='CTF{x}'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_status_endpoint_publishes(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.patch(
            f'/api/v1/admin/challenges/{self.draft.id}/status/',
            {'status': 'published'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Challenge.STATUS_PUBLISHED)

    def test_delete_draft_cascades_and_removes_files(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with override_settings(MEDIA_ROOT=tmp):
            attachment = ChallengeAttachment.objects.create(
                challenge=self.draft,
                file=SimpleUploadedFile('payload.txt', b'data'),
            )
            path = attachment.file.path
            self.client.force_authenticate(user=self.make_admin())
            response = self.client.delete(f'/api/v1/admin/challenges/{self.draft.id}/')
            self.assertEqual(response.status_code, 204, response.content)
            self.assertFalse(Challenge.objects.filter(pk=self.draft.pk).exists())
            self.assertFalse(ChallengeAttachment.objects.filter(pk=attachment.pk).exists())
            self.assertFalse(__import__('os').path.exists(path))

    def test_delete_published_is_refused(self):
        self.client.force_authenticate(user=self.make_admin())
        response = self.client.delete(
            f'/api/v1/admin/challenges/{self.published.id}/'
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Challenge.objects.filter(pk=self.published.pk).exists())

    def test_creator_without_delete_permission_is_refused(self):
        self.client.force_authenticate(user=self.make_creator())
        response = self.client.delete(f'/api/v1/admin/challenges/{self.draft.id}/')
        self.assertEqual(response.status_code, 403)

    def test_attachment_upload_and_delete(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with override_settings(MEDIA_ROOT=tmp):
            self.client.force_authenticate(user=self.make_admin())
            response = self.client.post(
                f'/api/v1/admin/challenges/{self.draft.id}/attachments/',
                {'file': SimpleUploadedFile('notes.txt', b'hello')},
                format='multipart',
            )
            self.assertEqual(response.status_code, 201, response.content)
            attachment_id = response.json()['id']

            deleted = self.client.delete(
                f'/api/v1/admin/challenges/{self.draft.id}/'
                f'attachments/{attachment_id}/'
            )
            self.assertEqual(deleted.status_code, 204)
            self.assertFalse(
                ChallengeAttachment.objects.filter(pk=attachment_id).exists()
            )


class ChallengeAttachmentDownloadTests(ChallengeTestMixin, TestCase):
    """Per-file authorization for challenge attachments."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        media_override = override_settings(MEDIA_ROOT=self.tmp)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.published_attachment = ChallengeAttachment.objects.create(
            challenge=self.published,
            file=SimpleUploadedFile('public.txt', b'published-data'),
        )
        self.draft_attachment = ChallengeAttachment.objects.create(
            challenge=self.draft,
            file=SimpleUploadedFile('private.txt', b'draft-data'),
        )

    def url_for(self, attachment):
        return (
            f'/api/v1/challenges/{attachment.challenge_id}/attachments/'
            f'{attachment.pk}/download/'
        )

    def body(self, response):
        return b''.join(response.streaming_content)

    def test_published_attachment_is_public(self):
        response = self.client.get(self.url_for(self.published_attachment))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('public.txt', response['Content-Disposition'])
        self.assertEqual(self.body(response), b'published-data')

    def test_serializer_returns_the_gated_url_not_a_media_url(self):
        response = self.client.get(f'/api/v1/challenges/{self.published.id}/')

        files = response.json()['files']
        self.assertEqual(len(files), 1)
        self.assertTrue(
            files[0]['url'].endswith(self.url_for(self.published_attachment))
        )
        self.assertNotIn('/media/', files[0]['url'])

    def test_draft_attachment_is_hidden_from_anonymous_users(self):
        response = self.client.get(self.url_for(self.draft_attachment))

        self.assertEqual(response.status_code, 404)

    def test_draft_attachment_is_hidden_from_plain_users(self):
        self.client.force_authenticate(user=self.make_plain_user())
        response = self.client.get(self.url_for(self.draft_attachment))

        self.assertEqual(response.status_code, 404)

    def test_draft_attachment_is_visible_to_challenge_viewers(self):
        self.client.force_authenticate(user=self.make_creator())
        response = self.client.get(self.url_for(self.draft_attachment))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response), b'draft-data')

    def test_attachment_cannot_be_fetched_through_another_challenge(self):
        response = self.client.get(
            f'/api/v1/challenges/{self.published.id}/attachments/'
            f'{self.draft_attachment.pk}/download/'
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_backing_file_returns_404(self):
        self.published_attachment.file.delete(save=False)

        response = self.client.get(self.url_for(self.published_attachment))

        self.assertEqual(response.status_code, 404)

    def test_upload_over_the_configured_limit_is_rejected(self):
        self.client.force_authenticate(user=self.make_admin())
        with override_settings(MAX_CHALLENGE_ATTACHMENT_BYTES=4):
            response = self.client.post(
                f'/api/v1/admin/challenges/{self.draft.id}/attachments/',
                {'file': SimpleUploadedFile('big.txt', b'12345')},
                format='multipart',
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('too large', str(response.json()['file']))
        self.assertEqual(self.draft.attachments.count(), 1)
