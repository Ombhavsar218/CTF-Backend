"""Tests for the persistent admin audit trail and its read-only API."""

import json
import os
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from challenges.models import (
    Category, Challenge, ChallengeAttachment, ChallengeFlag,
)
from users.permissions import DjangoModelPermissionsWithView

from .models import AuditLog
from .services import AuditAction, log_admin_action

User = get_user_model()

AUDIT_URL = '/api/v1/admin/audit-logs/'


class AuditTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_groups', stdout=StringIO(), no_color=True)

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            'audit_admin', 'audit_admin@example.com', 'pass12345',
        )
        self.admin.groups.add(Group.objects.get(name='Admin'))
        self.ordinary = User.objects.create_user(
            'audit_user', 'audit_user@example.com', 'pass12345',
        )
        self.ordinary.groups.add(Group.objects.get(name='User'))
        self.client.force_authenticate(self.admin)

    def add_log(self, **overrides):
        data = {
            'actor': self.admin,
            'action': AuditAction.USER_CREATE,
            'target_type': 'user',
            'target_id': '99',
            'target_label': 'created-user',
        }
        data.update(overrides)
        return log_admin_action(**data)


class AuditApiAccessTests(AuditTestBase):
    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(AUDIT_URL)
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_user_without_permission_is_rejected(self):
        self.client.force_authenticate(self.ordinary)
        response = self.client.get(AUDIT_URL)
        self.assertEqual(response.status_code, 403)

    def test_admin_group_member_can_read_the_trail(self):
        self.add_log()
        response = self.client.get(AUDIT_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['count'], 1)
        row = response.data['results'][0]
        self.assertEqual(
            set(row),
            {
                'id', 'actor', 'action', 'target_type', 'target_id',
                'target_label', 'metadata', 'created_at',
            },
        )
        self.assertEqual(row['actor'], 'audit_admin')

    def test_endpoint_is_read_only(self):
        self.add_log()
        before = AuditLog.objects.count()
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.client, method)(
                AUDIT_URL, {}, format='json',
            )
            # The Admin group has only view_auditlog, so DRF refuses the
            # method before the generic list view's 405; either way the row is
            # never mutated.
            self.assertIn(
                response.status_code, (403, 405),
                f'{method} should be rejected',
            )
        self.assertEqual(AuditLog.objects.count(), before)

    def test_only_the_view_permission_is_needed(self):
        self.assertTrue(
            self.admin.has_perm('audit.view_auditlog')
        )
        self.assertFalse(
            self.admin.has_perm('audit.change_auditlog')
        )


class AuditApiFilterTests(AuditTestBase):
    def test_pagination_envelope_and_page_size(self):
        for index in range(3):
            self.add_log(target_label=f'user-{index}')
        response = self.client.get(f'{AUDIT_URL}?page_size=2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])

    def test_filters_by_action_target_type_actor_and_search(self):
        self.add_log()
        challenge_log = self.add_log(
            action=AuditAction.CHALLENGE_CREATE,
            target_type='challenge',
            target_id='7',
            target_label='Web Puzzle',
        )

        by_action = self.client.get(
            f'{AUDIT_URL}?action=challenge.create'
        ).json()
        self.assertEqual(by_action['count'], 1)
        self.assertEqual(by_action['results'][0]['id'], challenge_log.id)

        by_type = self.client.get(
            f'{AUDIT_URL}?target_type=challenge'
        ).json()
        self.assertEqual(by_type['count'], 1)

        by_actor = self.client.get(
            f'{AUDIT_URL}?actor=AUDIT_ADMIN'
        ).json()
        self.assertEqual(by_actor['count'], 2)

        by_search = self.client.get(f'{AUDIT_URL}?search=Puzzle').json()
        self.assertEqual(by_search['count'], 1)
        self.assertEqual(by_search['results'][0]['target_label'], 'Web Puzzle')

    def test_date_filters_are_inclusive_and_invalid_dates_are_rejected(self):
        self.add_log()
        today = timezone.localdate().isoformat()
        response = self.client.get(
            f'{AUDIT_URL}?date_from={today}&date_to={today}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

        invalid = self.client.get(f'{AUDIT_URL}?date_from=not-a-date')
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('date_from', invalid.data)

    def test_old_rows_are_outside_the_requested_date_range(self):
        old = self.add_log()
        AuditLog.objects.filter(pk=old.pk).update(
            created_at=old.created_at - timedelta(days=10)
        )
        self.add_log()
        cutoff = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.client.get(f'{AUDIT_URL}?date_from={cutoff}')
        self.assertEqual(response.data['count'], 1)


class AuditSanitisationTests(AuditTestBase):
    def test_sensitive_metadata_keys_are_dropped_and_values_bounded(self):
        log = self.add_log(
            metadata={
                'fields': ['first_name'],
                'password': 'SuperSecret123!',
                'flag': 'CTF{do_not_store}',
                'token': 'jwt-token',
                'cookie': 'session=abc',
                'status_note': 'private note',
                'safe': 'x' * 400,
                'nested': {'authorization': 'Bearer abc', 'visible': True},
            }
        )
        serialised = json.dumps(log.metadata)
        self.assertNotIn('SuperSecret123!', serialised)
        self.assertNotIn('CTF{do_not_store}', serialised)
        self.assertNotIn('jwt-token', serialised)
        self.assertNotIn('session=abc', serialised)
        self.assertNotIn('private note', serialised)
        self.assertNotIn('Bearer abc', serialised)
        self.assertEqual(log.metadata['fields'], ['first_name'])
        self.assertEqual(log.metadata['nested'], {'visible': True})
        self.assertEqual(len(log.metadata['safe']), 300)

    def test_changed_fields_excludes_password_and_flag_material(self):
        from .services import changed_fields

        fields = changed_fields(
            {
                'username': 'x',
                'password': 'secret',
                'flag': 'CTF{x}',
                'flag_note': 'hint',
                'points': 100,
            }
        )
        self.assertIn('username', fields)
        self.assertIn('points', fields)
        self.assertNotIn('password', fields)
        self.assertNotIn('flag', fields)
        self.assertNotIn('flag_note', fields)


class AuditUserInstrumentationTests(AuditTestBase):
    def test_create_update_status_groups_delete_and_restore_are_audited(self):
        created = self.client.post(
            '/api/v1/admin/users/',
            {
                'username': 'created_by_admin',
                'email': 'created@example.com',
                'password': 'StrongPass!2345',
            },
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        target = User.objects.get(username='created_by_admin')
        create_log = AuditLog.objects.get(action=AuditAction.USER_CREATE)
        self.assertEqual(create_log.target_label, 'created_by_admin')
        self.assertNotIn('StrongPass!2345', json.dumps(create_log.metadata))

        updated = self.client.patch(
            f'/api/v1/admin/users/{target.pk}/',
            {'first_name': 'Ada', 'email': 'ada@example.com'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        update_log = AuditLog.objects.get(action=AuditAction.USER_UPDATE)
        self.assertEqual(update_log.metadata['fields'], ['email', 'first_name'])
        self.assertNotIn('ada@example.com', json.dumps(update_log.metadata))

        status = self.client.patch(
            f'/api/v1/admin/users/{target.pk}/status/',
            {'status': 'suspended', 'status_note': 'private moderation note'},
            format='json',
        )
        self.assertEqual(status.status_code, 200, status.content)
        status_log = AuditLog.objects.get(
            action=AuditAction.USER_STATUS_CHANGE
        )
        self.assertEqual(
            status_log.metadata,
            {'old_status': 'active', 'new_status': 'suspended'},
        )
        self.assertNotIn('private moderation note', json.dumps(status_log.metadata))

        admin_group = Group.objects.get(name='Admin')
        groups = self.client.patch(
            f'/api/v1/admin/users/{target.pk}/groups/',
            {'groups': [admin_group.pk]},
            format='json',
        )
        self.assertEqual(groups.status_code, 200, groups.content)
        groups_log = AuditLog.objects.get(
            action=AuditAction.USER_GROUPS_CHANGE
        )
        self.assertEqual(groups_log.metadata['added_groups'], ['Admin'])
        self.assertEqual(groups_log.metadata['removed_groups'], ['User'])

        deleted = self.client.delete(f'/api/v1/admin/users/{target.pk}/')
        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.USER_DELETE).exists()
        )

        restored = self.client.post(
            f'/api/v1/admin/users/{target.pk}/restore/', {}, format='json',
        )
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.USER_RESTORE).exists()
        )

    def test_failed_mutation_writes_no_audit_row(self):
        response = self.client.post(
            '/api/v1/admin/users/',
            {'username': '', 'email': 'bad', 'password': 'x'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_audit_failure_rolls_back_the_user_create(self):
        with patch(
            'audit.services.AuditLog.objects.create',
            side_effect=RuntimeError('audit unavailable'),
        ):
            response = self.client.post(
                '/api/v1/admin/users/',
                {
                    'username': 'must_not_exist',
                    'email': 'must_not_exist@example.com',
                    'password': 'StrongPass!2345',
                },
                format='json',
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('audit unavailable', str(response.data))
        self.assertFalse(
            User.all_objects.filter(username='must_not_exist').exists()
        )


class AuditChallengeInstrumentationTests(AuditTestBase):
    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(name='Web')

    def payload(self, **overrides):
        data = {
            'title': 'Audit Challenge',
            'category': 'Web',
            'difficulty': 'Hard',
            'points': 400,
            'status': 'draft',
            'flag': 'CTF{audit_secret_flag}',
        }
        data.update(overrides)
        return data

    def test_challenge_create_update_status_delete_are_audited(self):
        created = self.client.post(
            '/api/v1/admin/challenges/', self.payload(), format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        challenge = Challenge.objects.get(title='Audit Challenge')
        create_log = AuditLog.objects.get(
            action=AuditAction.CHALLENGE_CREATE
        )
        self.assertEqual(create_log.target_label, 'Audit Challenge')
        self.assertNotIn(
            'CTF{audit_secret_flag}', json.dumps(create_log.metadata)
        )

        updated = self.client.patch(
            f'/api/v1/admin/challenges/{challenge.pk}/',
            {'points': 500, 'flag': 'CTF{replacement_secret}'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        update_log = AuditLog.objects.get(
            action=AuditAction.CHALLENGE_UPDATE
        )
        self.assertIn('points', update_log.metadata['fields'])
        self.assertNotIn(
            'replacement_secret', json.dumps(update_log.metadata)
        )

        status = self.client.patch(
            f'/api/v1/admin/challenges/{challenge.pk}/status/',
            {'status': 'published'},
            format='json',
        )
        self.assertEqual(status.status_code, 200, status.content)
        status_log = AuditLog.objects.get(
            action=AuditAction.CHALLENGE_STATUS_CHANGE
        )
        self.assertEqual(status_log.metadata['old_status'], 'draft')
        self.assertEqual(status_log.metadata['new_status'], 'published')

        # Unpublish first: only drafts may be deleted.
        self.client.patch(
            f'/api/v1/admin/challenges/{challenge.pk}/status/',
            {'status': 'draft'},
            format='json',
        )
        deleted = self.client.delete(
            f'/api/v1/admin/challenges/{challenge.pk}/'
        )
        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.CHALLENGE_DELETE
            ).exists()
        )

    def test_attachment_upload_and_delete_are_audited(self):
        challenge = Challenge.objects.create(
            title='Attachment Challenge',
            category=self.category,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=100,
            status=Challenge.STATUS_DRAFT,
        )
        flag = ChallengeFlag(challenge=challenge)
        flag.set_flag('CTF{attachment_flag}')
        flag.save()

        tmp = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=tmp):
                uploaded = self.client.post(
                    f'/api/v1/admin/challenges/{challenge.pk}/attachments/',
                    {'file': SimpleUploadedFile('notes.txt', b'hello')},
                    format='multipart',
                )
                self.assertEqual(uploaded.status_code, 201, uploaded.content)
                attachment_id = uploaded.json()['id']
                add_log = AuditLog.objects.get(
                    action=AuditAction.CHALLENGE_ATTACHMENT_ADD
                )
                self.assertEqual(
                    add_log.metadata['attachment_id'], attachment_id
                )

                removed = self.client.delete(
                    f'/api/v1/admin/challenges/{challenge.pk}/'
                    f'attachments/{attachment_id}/'
                )
                self.assertEqual(removed.status_code, 204, removed.content)
                self.assertTrue(
                    AuditLog.objects.filter(
                        action=AuditAction.CHALLENGE_ATTACHMENT_DELETE
                    ).exists()
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failed_challenge_create_writes_no_audit_row(self):
        response = self.client.post(
            '/api/v1/admin/challenges/',
            self.payload(flag='not-a-flag'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_audit_failure_on_delete_keeps_challenge_and_files(self):
        challenge = Challenge.objects.create(
            title='Delete Must Roll Back',
            category=self.category,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=100,
            status=Challenge.STATUS_DRAFT,
        )
        tmp = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=tmp):
                attachment = ChallengeAttachment.objects.create(
                    challenge=challenge,
                    file=SimpleUploadedFile('keep.txt', b'keep me'),
                )
                path = attachment.file.path
                self.assertTrue(os.path.exists(path))

                with patch(
                    'audit.services.AuditLog.objects.create',
                    side_effect=RuntimeError('audit unavailable'),
                ):
                    response = self.client.delete(
                        f'/api/v1/admin/challenges/{challenge.pk}/'
                    )
                self.assertEqual(response.status_code, 500)
                self.assertNotIn('audit unavailable', str(response.data))

                self.assertTrue(
                    Challenge.objects.filter(pk=challenge.pk).exists()
                )
                self.assertTrue(
                    ChallengeAttachment.objects.filter(pk=attachment.pk).exists()
                )
                self.assertTrue(os.path.exists(path))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_audit_failure_on_upload_removes_orphan_file(self):
        challenge = Challenge.objects.create(
            title='Upload Must Roll Back',
            category=self.category,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=100,
            status=Challenge.STATUS_DRAFT,
        )
        tmp = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=tmp):
                with patch(
                    'audit.services.AuditLog.objects.create',
                    side_effect=RuntimeError('audit unavailable'),
                ):
                    response = self.client.post(
                        f'/api/v1/admin/challenges/{challenge.pk}/'
                        'attachments/',
                        {'file': SimpleUploadedFile('orphan.txt', b'data')},
                        format='multipart',
                    )
                self.assertEqual(response.status_code, 500)
                self.assertNotIn('audit unavailable', str(response.data))

                self.assertFalse(
                    ChallengeAttachment.objects.filter(challenge=challenge).exists()
                )
                files = [
                    name
                    for _, _, names in os.walk(tmp)
                    for name in names
                ]
                self.assertEqual(files, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class AuditCategoryInstrumentationTests(AuditTestBase):
    def test_category_create_update_delete_are_audited(self):
        created = self.client.post(
            '/api/v1/admin/categories/',
            {
                'name': 'Audit Category',
                'description': 'Created by the audit test',
                'order': 12,
            },
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        category_id = created.json()['id']

        updated = self.client.patch(
            f'/api/v1/admin/categories/{category_id}/',
            {'description': 'Changed'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)

        deleted = self.client.delete(
            f'/api/v1/admin/categories/{category_id}/'
        )
        self.assertEqual(deleted.status_code, 204, deleted.content)

        logs = AuditLog.objects.filter(target_type='category')
        self.assertEqual(
            set(logs.values_list('action', flat=True)),
            {
                AuditAction.CATEGORY_CREATE,
                AuditAction.CATEGORY_UPDATE,
                AuditAction.CATEGORY_DELETE,
            },
        )
        update_log = logs.get(action=AuditAction.CATEGORY_UPDATE)
        self.assertEqual(update_log.metadata['fields'], ['description'])
        self.assertFalse(
            Category.objects.filter(pk=category_id).exists()
        )

    def test_refused_category_delete_writes_no_audit_row(self):
        category = Category.objects.create(name='Referenced')
        Challenge.objects.create(
            title='Uses Referenced',
            category=category,
            difficulty=Challenge.DIFFICULTY_EASY,
            points=100,
            status=Challenge.STATUS_DRAFT,
        )

        response = self.client.delete(
            f'/api/v1/admin/categories/{category.pk}/'
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_audit_failure_on_category_create_rolls_back(self):
        with patch(
            'audit.services.AuditLog.objects.create',
            side_effect=RuntimeError('audit unavailable'),
        ):
            response = self.client.post(
                '/api/v1/admin/categories/',
                {'name': 'Must Not Exist'},
                format='json',
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('audit unavailable', str(response.data))
        self.assertFalse(Category.objects.filter(name='Must Not Exist').exists())

    def test_audit_failure_on_category_delete_keeps_category(self):
        category = Category.objects.create(name='Keep On Audit Failure')

        with patch(
            'audit.services.AuditLog.objects.create',
            side_effect=RuntimeError('audit unavailable'),
        ):
            response = self.client.delete(
                f'/api/v1/admin/categories/{category.pk}/'
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('audit unavailable', str(response.data))

        self.assertTrue(Category.objects.filter(pk=category.pk).exists())
        self.assertEqual(AuditLog.objects.count(), 0)


class AuditAchievementAnnouncementInstrumentationTests(AuditTestBase):
    def test_achievement_create_update_delete_are_audited(self):
        created = self.client.post(
            '/api/v1/admin/achievements/',
            {
                'name': 'Audited Badge',
                'description': 'Test',
                'criteria_type': 'first_solve',
                'criteria_config': {},
            },
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        achievement_id = created.json()['id']

        updated = self.client.patch(
            f'/api/v1/admin/achievements/{achievement_id}/',
            {'description': 'Updated'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)

        deleted = self.client.delete(
            f'/api/v1/admin/achievements/{achievement_id}/'
        )
        self.assertEqual(deleted.status_code, 204, deleted.content)

        actions = set(
            AuditLog.objects.filter(target_type='achievement').values_list(
                'action', flat=True
            )
        )
        self.assertEqual(
            actions,
            {
                AuditAction.ACHIEVEMENT_CREATE,
                AuditAction.ACHIEVEMENT_UPDATE,
                AuditAction.ACHIEVEMENT_DELETE,
            },
        )

    def test_announcement_create_update_delete_are_audited(self):
        created = self.client.post(
            '/api/v1/admin/announcements/',
            {'title': 'Audited Notice', 'body': 'Body', 'status': 'draft'},
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        announcement_id = created.json()['id']

        updated = self.client.patch(
            f'/api/v1/admin/announcements/{announcement_id}/',
            {'status': 'published'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        update_log = AuditLog.objects.get(
            action=AuditAction.ANNOUNCEMENT_UPDATE
        )
        self.assertEqual(update_log.metadata['old_status'], 'draft')
        self.assertEqual(update_log.metadata['new_status'], 'published')
        self.assertNotIn('Body', json.dumps(update_log.metadata))

        deleted = self.client.delete(
            f'/api/v1/admin/announcements/{announcement_id}/'
        )
        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.ANNOUNCEMENT_DELETE
            ).exists()
        )


class AuditPermissionWiringTests(TestCase):
    def test_admin_group_receives_the_audit_view_permission(self):
        call_command('setup_groups', stdout=StringIO(), no_color=True)
        permission = Group.objects.get(name='Admin').permissions.filter(
            content_type__app_label='audit',
            codename='view_auditlog',
        )
        self.assertTrue(permission.exists())

    def test_read_permission_class_maps_get_to_view(self):
        # Keeps the audit endpoint fail-closed if someone later swaps the
        # permission class for stock DRF DjangoModelPermissions.
        self.assertEqual(
            DjangoModelPermissionsWithView.perms_map['GET'],
            ['%(app_label)s.view_%(model_name)s'],
        )
