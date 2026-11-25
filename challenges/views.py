"""Challenge API views.

Two surfaces:

* Public (``AllowAny``): the published challenge list, a published challenge's
  detail, and the category list. Both challenge endpoints return a plain JSON
  array / object (no DRF pagination) to match the existing frontend service.
* Admin (Django model permissions): full challenge CRUD, publish/unpublish,
  scheduling, attachment management, and category write operations. Reads
  require the matching ``view_*`` permission; writes require the matching
  ``add_*`` / ``change_*`` / ``delete_*`` permission.

Public category reads remain on ``GET /api/v1/categories/``; only the missing
category create/update/delete operations were added under ``/admin/categories/``.
Deleting a category never cascades: a category still referenced by a challenge
or an achievement rule is refused instead.
"""

import mimetypes

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import (
    AuditAction,
    changed_fields,
    log_admin_action,
)
from users.permissions import DjangoModelPermissionsWithView

from .models import Category, Challenge, ChallengeAttachment
from .mode_content import (
    get_mode_visible_content,
    get_solution_content,
    is_mode_aware,
    resolve_learning_mode,
)
from .permissions import (
    VIEW_CHALLENGE_PERMISSION,
    HasChallengeChangePermission,
)
from .serializers import (
    AttachmentSerializer,
    CategorySerializer,
    CategoryWriteSerializer,
    ChallengeAdminSerializer,
    ChallengePublicSerializer,
    ChallengeWriteSerializer,
    human_size,
)

PUBLISHED = Challenge.STATUS_PUBLISHED


def _solved_ids(user):
    """Ids of the challenges ``user`` has solved (empty for anonymous)."""
    if user is None or not user.is_authenticated:
        return set()
    from submissions.models import Solve

    return set(
        Solve.objects.filter(user=user).values_list('challenge_id', flat=True)
    )


def _revealed_hint_ids(user):
    """Ids of the hints ``user`` has unlocked (empty for anonymous).

    Used so a published challenge can show the text of hints the requesting
    user already paid for, while never exposing anyone else's/undeocked text.
    """
    if user is None or not user.is_authenticated:
        return set()
    from submissions.models import HintUnlock

    return set(
        HintUnlock.objects.filter(user=user).values_list('hint_id', flat=True)
    )


class SolvedContextMixin:
    """Add request-scoped challenge state to serializer context.

    Includes solved/revealed-hint ids for efficient serialization and the
    persisted learning mode for backend mode-aware content/hint gating.
    """

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        context['solved_ids'] = _solved_ids(user)
        context['revealed_hint_ids'] = _revealed_hint_ids(user)
        context['learning_mode'] = resolve_learning_mode(user)
        return context


def _published_queryset():
    return (
        Challenge.objects.published()
        .select_related('category')
        .prefetch_related('hints', 'attachments')
    )


def _visible_for_mode(queryset, user):
    """Filter challenges by the caller's learning mode.

    Challenges marked 'both' are always visible. Challenges marked 'student'
    or 'competitor' are visible only to users in that mode. Anonymous users
    resolve to competitor (least disclosure).
    """
    mode = resolve_learning_mode(user)
    return queryset.filter(
        Q(challenge_mode=Challenge.MODE_BOTH) | Q(challenge_mode=mode)
    )


def _is_visible_for_user(challenge, user):
    mode = getattr(challenge, 'challenge_mode', Challenge.MODE_BOTH) or Challenge.MODE_BOTH
    if mode == Challenge.MODE_BOTH:
        return True
    return mode == resolve_learning_mode(user)


class PublicChallengeListView(SolvedContextMixin, generics.ListAPIView):
    """GET /api/v1/challenges/ - every published challenge as a plain array."""

    serializer_class = ChallengePublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        queryset = _visible_for_mode(_published_queryset(), self.request.user)
        params = self.request.query_params

        category = params.get('category')
        if category and category != 'All':
            queryset = queryset.filter(category__name=category)

        difficulty = params.get('difficulty')
        if difficulty and difficulty != 'All':
            queryset = queryset.filter(difficulty=difficulty)

        search = (params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(category__name__icontains=search)
            )
        return queryset


class PublicChallengeDetailView(SolvedContextMixin, generics.RetrieveAPIView):
    """GET /api/v1/challenges/{id}/ - a published challenge, else 404."""

    serializer_class = ChallengePublicSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return _visible_for_mode(_published_queryset(), self.request.user)


class ChallengeModeContentView(APIView):
    """GET /api/v1/challenges/{id}/content/ - mode-allowed learning content.

    Authenticated and permission-protected. The effective learning mode is
    resolved exclusively from the caller's persisted user record; request
    parameters never influence it. Only the caller's own mode section is
    returned and solutions are never included here.
    """

    permission_classes = [IsAuthenticated]
    http_method_names = ['get']

    def get(self, request, pk):
        challenge = get_object_or_404(
            Challenge.objects.prefetch_related('hints', 'attachments'),
            pk=pk,
        )
        if challenge.status != PUBLISHED:
            if not request.user.has_perm(VIEW_CHALLENGE_PERMISSION):
                raise Http404
        elif not _is_visible_for_user(challenge, request.user):
            if not request.user.has_perm(VIEW_CHALLENGE_PERMISSION):
                raise Http404
        return Response(get_mode_visible_content(challenge, request.user))


class ChallengeSolutionView(APIView):
    """GET /api/v1/challenges/{id}/solution/ - solve-gated solution content.

    The caller must be authenticated and must have a Solve record for this
    exact challenge. Client-supplied completion flags are ignored.
    """

    permission_classes = [IsAuthenticated]
    http_method_names = ['get']

    def get(self, request, pk):
        challenge = get_object_or_404(
            Challenge.objects.prefetch_related('hints', 'attachments'),
            pk=pk,
        )
        if challenge.status != PUBLISHED:
            if not request.user.has_perm(VIEW_CHALLENGE_PERMISSION):
                raise Http404
        elif not _is_visible_for_user(challenge, request.user):
            if not request.user.has_perm(VIEW_CHALLENGE_PERMISSION):
                raise Http404

        # Access to the solution depends only on persisted state: the caller's
        # learning mode and a Solve row for this exact (user, challenge).
        result = get_solution_content(challenge, request.user)
        if not result['solution_available']:
            # Use a standard permission error. Do not disclose whether another
            # user's solve exists or whether content differs for other modes.
            return Response(
                {
                    'detail': (
                        'Solution content is available only after you solve this '
                        'challenge in Student Mode.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(result)


class ChallengeAttachmentDownloadView(APIView):
    """GET /api/v1/challenges/{id}/attachments/{attachment_id}/download/.

    Published challenge files are public, matching the public challenge API.
    Attachments on drafts and scheduled challenges are visible only to users
    who hold ``challenges.view_challenge``. Everyone else receives a 404, not a
    403, so the endpoint does not disclose that an unreleased file exists.
    """

    permission_classes = [AllowAny]
    http_method_names = ['get']

    def get(self, request, pk, attachment_pk):
        attachment = get_object_or_404(
            ChallengeAttachment.objects.select_related('challenge'),
            pk=attachment_pk,
            challenge_id=pk,
        )
        challenge = attachment.challenge
        if challenge.status != PUBLISHED:
            user = request.user
            if not (
                user
                and user.is_authenticated
                and user.has_perm(VIEW_CHALLENGE_PERMISSION)
            ):
                raise Http404
        elif not _is_visible_for_user(challenge, request.user):
            user = request.user
            if not (
                user
                and user.is_authenticated
                and user.has_perm(VIEW_CHALLENGE_PERMISSION)
            ):
                raise Http404

        try:
            file_handle = attachment.file.open('rb')
        except (FileNotFoundError, OSError, ValueError):
            # The row exists but the backing file is gone. Treat it as missing
            # rather than returning a server error or an empty download.
            raise Http404

        filename = attachment.display_name
        content_type = (
            mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        )
        response = FileResponse(
            file_handle,
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )
        # Challenge files are user-uploaded and may be private. Do not let a
        # browser or intermediary keep a copy after the authorization check.
        response['Cache-Control'] = 'private, no-store'
        return response


class PublicCategoryListView(generics.ListAPIView):
    """GET /api/v1/categories/ - the configured categories."""

    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        return Category.objects.annotate(
            challenge_count=Count(
                'challenges',
                filter=Q(challenges__status=PUBLISHED),
            )
        )


def _achievement_category_references(category_id):
    """Names of active achievement definitions that point at ``category_id``.

    Achievement rules are JSON, not a foreign key, so Django's ``PROTECT``
    cannot enforce this. The delete endpoint checks the application-level
    reference and refuses rather than silently leaving a broken rule.
    """
    from achievements.models import Achievement

    references = []
    definitions = Achievement.all_objects.filter(
        deleted_at__isnull=True,
        criteria_type=Achievement.CRITERIA_CATEGORY_SOLVES,
    )
    for achievement in definitions:
        raw = (achievement.criteria_config or {}).get('category')
        try:
            referenced_id = int(raw)
        except (TypeError, ValueError):
            continue
        if referenced_id == category_id:
            references.append(achievement.name)
    return sorted(references)


class AdminCategoryListCreateView(generics.CreateAPIView):
    """POST /api/v1/admin/categories/ - create a category.

    Reads deliberately stay on the public ``GET /api/v1/categories/`` endpoint,
    so there is no duplicate admin list. The response uses the public read
    shape, including the published challenge count.
    """

    serializer_class = CategoryWriteSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    queryset = Category.objects.all()

    @transaction.atomic
    def perform_create(self, serializer):
        category = serializer.save()
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.CATEGORY_CREATE,
            target_type='category',
            target_id=category.pk,
            target_label=category.name,
            metadata={'fields': changed_fields(serializer.validated_data)},
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            CategorySerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )


class AdminCategoryDetailView(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView,
):
    """PATCH/DELETE /api/v1/admin/categories/{id}/."""

    serializer_class = CategoryWriteSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    queryset = Category.objects.all()

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)

    @transaction.atomic
    def perform_update(self, serializer):
        category = serializer.instance
        fields = changed_fields(serializer.validated_data)
        serializer.save()
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.CATEGORY_UPDATE,
            target_type='category',
            target_id=category.pk,
            target_label=category.name,
            metadata={'fields': fields},
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(CategorySerializer(serializer.instance).data)

    @transaction.atomic
    def perform_destroy(self, instance):
        challenge_count = instance.challenges.count()
        if challenge_count:
            raise ValidationError({
                'detail': (
                    f'Cannot delete "{instance.name}" because '
                    f'{challenge_count} challenge(s) still use this category. '
                    'Move those challenges to another category first; they '
                    'were not changed.'
                )
            })

        achievements = _achievement_category_references(instance.pk)
        if achievements:
            names = ', '.join(f'"{name}"' for name in achievements[:3])
            if len(achievements) > 3:
                names += f' and {len(achievements) - 3} more'
            raise ValidationError({
                'detail': (
                    f'Cannot delete "{instance.name}" because the achievement '
                    f'{names} references it. Update those achievement rules '
                    'first; nothing was changed.'
                )
            })

        target_id = instance.pk
        target_label = instance.name
        try:
            instance.delete()
        except ProtectedError:
            # Race-safe fallback: a challenge could have been attached after
            # the count above. It still must never be reassigned or deleted.
            raise ValidationError({
                'detail': (
                    f'Cannot delete "{instance.name}" because a challenge was '
                    'just assigned to it. Reload the page and try again; '
                    'nothing was changed.'
                )
            })

        # Deletion and audit commit together. If the audit write fails, the
        # category (and every challenge) is rolled back intact.
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.CATEGORY_DELETE,
            target_type='category',
            target_id=target_id,
            target_label=target_label,
        )


class AdminChallengeListCreateView(SolvedContextMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/admin/challenges/ - list all, or create."""

    serializer_class = ChallengeAdminSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    pagination_class = None
    queryset = Challenge.objects.all()

    def get_queryset(self):
        queryset = (
            Challenge.objects.all()
            .select_related('category', 'created_by')
            .prefetch_related('hints', 'attachments', 'flag')
        )
        status_filter = self.request.query_params.get('status')
        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)

        search = (self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(category__name__icontains=search)
                | Q(author__icontains=search)
            )
        return queryset

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ChallengeWriteSerializer
        return ChallengeAdminSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        challenge = serializer.save(created_by=self.request.user)
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.CHALLENGE_CREATE,
            target_type='challenge',
            target_id=challenge.pk,
            target_label=challenge.title,
            metadata={'fields': changed_fields(serializer.validated_data)},
        )


class AdminChallengeDetailView(SolvedContextMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/admin/challenges/{id}/."""

    queryset = Challenge.objects.all()
    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return (
            Challenge.objects.all()
            .select_related('category', 'created_by')
            .prefetch_related('hints', 'attachments', 'flag')
        )

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return ChallengeWriteSerializer
        return ChallengeAdminSerializer

    @transaction.atomic
    def perform_update(self, serializer):
        challenge = serializer.instance
        fields = changed_fields(serializer.validated_data)
        serializer.save()
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.CHALLENGE_UPDATE,
            target_type='challenge',
            target_id=challenge.pk,
            target_label=challenge.title,
            metadata={'fields': fields},
        )

    def destroy(self, request, *args, **kwargs):
        challenge = self.get_object()
        if challenge.status != Challenge.STATUS_DRAFT:
            raise ValidationError({
                'detail': (
                    'Only draft challenges can be deleted. Unpublish this '
                    'challenge first.'
                )
            })
        # ChallengeFlag, ChallengeHint and ChallengeAttachment are owned by the
        # challenge and cascade-delete safely; attachment files are removed by
        # a post_delete signal. Only drafts reach this point, and draft solves
        # are not reachable through the public submission endpoint.
        return super().destroy(request, *args, **kwargs)

    @transaction.atomic
    def perform_destroy(self, instance):
        target_id = instance.pk
        target_label = instance.title
        # Write the audit row before deleting: attachment files are removed by
        # a post_delete signal, which cannot be rolled back. If the delete (or
        # the commit) fails, this row rolls back with it; if the audit write
        # fails, the challenge and its files are untouched.
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.CHALLENGE_DELETE,
            target_type='challenge',
            target_id=target_id,
            target_label=target_label,
        )
        instance.delete()


class AdminChallengeStatusView(APIView):
    """PATCH /api/v1/admin/challenges/{id}/status/ - publish/unpublish/schedule."""

    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    queryset = Challenge.objects.all()

    def patch(self, request, pk):
        challenge = get_object_or_404(Challenge, pk=pk)
        new_status = request.data.get('status')
        valid = dict(Challenge.STATUS_CHOICES)
        if new_status not in valid:
            raise ValidationError({
                'status': f'Choose one of: {", ".join(valid)}.'
            })

        publish_at = challenge.publish_at
        if 'publishAt' in request.data:
            from django.utils import timezone
            from django.utils.dateparse import parse_datetime

            raw = (request.data.get('publishAt') or '').strip()
            if not raw:
                publish_at = None
            else:
                parsed = parse_datetime(raw)
                if parsed is None:
                    raise ValidationError({'publishAt': 'Invalid date/time value.'})
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(
                        parsed, timezone.get_current_timezone()
                    )
                publish_at = parsed

        if new_status == Challenge.STATUS_SCHEDULED and publish_at is None:
            raise ValidationError({
                'publishAt': 'A publish time is required to schedule a challenge.'
            })

        old_status = challenge.status
        with transaction.atomic():
            challenge.status = new_status
            challenge.publish_at = publish_at
            challenge.save(
                update_fields=['status', 'publish_at', 'updated_at']
            )
            log_admin_action(
                actor=request.user,
                action=AuditAction.CHALLENGE_STATUS_CHANGE,
                target_type='challenge',
                target_id=challenge.pk,
                target_label=challenge.title,
                metadata={
                    'old_status': old_status,
                    'new_status': new_status,
                    'publish_at': (
                        publish_at.isoformat() if publish_at else None
                    ),
                },
            )
        return Response(ChallengeAdminSerializer(challenge).data)


class AdminChallengeAttachmentView(APIView):
    """POST /api/v1/admin/challenges/{id}/attachments/ - upload a file."""

    permission_classes = [IsAuthenticated, HasChallengeChangePermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        challenge = get_object_or_404(Challenge, pk=pk)
        upload = request.FILES.get('file')
        if upload is None:
            raise ValidationError({'file': 'A file is required.'})
        max_bytes = settings.MAX_CHALLENGE_ATTACHMENT_BYTES
        if upload.size > max_bytes:
            raise ValidationError(
                {
                    'file': (
                        'File is too large. The maximum size is '
                        f'{human_size(max_bytes)}.'
                    )
                }
            )
        name = (request.data.get('name') or '').strip()
        attachment = None
        try:
            with transaction.atomic():
                attachment = ChallengeAttachment.objects.create(
                    challenge=challenge,
                    file=upload,
                    name=name,
                )
                log_admin_action(
                    actor=request.user,
                    action=AuditAction.CHALLENGE_ATTACHMENT_ADD,
                    target_type='challenge',
                    target_id=challenge.pk,
                    target_label=challenge.title,
                    metadata={'attachment_id': attachment.pk},
                )
        except Exception:
            # The DB row rolls back, but Django has already written the file.
            # Remove that orphan so a failed audit write leaves no mutation.
            if attachment is not None and attachment.file:
                attachment.file.delete(save=False)
            raise
        return Response(
            AttachmentSerializer(attachment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class AdminChallengeAttachmentDetailView(APIView):
    """DELETE /api/v1/admin/challenges/{id}/attachments/{attachment_id}/."""

    permission_classes = [IsAuthenticated, HasChallengeChangePermission]

    def delete(self, request, pk, attachment_pk):
        attachment = get_object_or_404(
            ChallengeAttachment, pk=attachment_pk, challenge_id=pk
        )
        challenge = attachment.challenge
        attachment_id = attachment.pk
        with transaction.atomic():
            # Audit first: deleting the row removes the file immediately via a
            # post_delete signal, and that file removal is not transactional.
            # An audit failure must therefore leave the attachment untouched.
            log_admin_action(
                actor=request.user,
                action=AuditAction.CHALLENGE_ATTACHMENT_DELETE,
                target_type='challenge',
                target_id=challenge.pk,
                target_label=challenge.title,
                metadata={'attachment_id': attachment_id},
            )
            attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
