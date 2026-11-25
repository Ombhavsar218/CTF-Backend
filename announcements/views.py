"""Announcement API.

    GET    /api/v1/announcements/                 (AllowAny, active published)
    GET    /api/v1/admin/announcements/           (admin, all rows)
    POST   /api/v1/admin/announcements/           (admin, create)
    GET    /api/v1/admin/announcements/{id}/      (admin, retrieve)
    PATCH  /api/v1/admin/announcements/{id}/      (admin, partial update)
    DELETE /api/v1/admin/announcements/{id}/      (admin, delete)

The public surface exposes only currently-active published rows; the filter runs
in the database, so drafts, future and expired announcements never leak. The
administrative surface reuses the platform's established admin authorization
(``DjangoModelPermissionsWithView`` on the ``Admin`` group) rather than
introducing a new rule, and derives ``created_by`` from the caller.
"""

from django.db import transaction
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated

from audit.services import (
    AuditAction,
    changed_fields,
    log_admin_action,
)
from users.permissions import DjangoModelPermissionsWithView

from .models import Announcement
from .serializers import (
    AnnouncementAdminSerializer,
    AnnouncementPublicSerializer,
    AnnouncementWriteSerializer,
)


class PublicAnnouncementListView(generics.ListAPIView):
    """GET /api/v1/announcements/ - active published announcements."""

    serializer_class = AnnouncementPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        # All rows here are published, so ``published_at`` is never null and
        # this ordering is deterministic on every backend.
        return Announcement.objects.active().order_by('-published_at', '-id')


class AdminAnnouncementListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/admin/announcements/ - list every row, or create."""

    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    pagination_class = None

    def get_queryset(self):
        return Announcement.objects.select_related('created_by').order_by(
            '-created_at', '-id'
        )

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AnnouncementWriteSerializer
        return AnnouncementAdminSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        # The creator is the authenticated administrator, never the payload.
        announcement = serializer.save(created_by=self.request.user)
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.ANNOUNCEMENT_CREATE,
            target_type='announcement',
            target_id=announcement.pk,
            target_label=announcement.title,
            metadata={'fields': changed_fields(serializer.validated_data)},
        )


class AdminAnnouncementDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/admin/announcements/{id}/."""

    queryset = Announcement.objects.select_related('created_by')
    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return AnnouncementWriteSerializer
        return AnnouncementAdminSerializer

    @transaction.atomic
    def perform_update(self, serializer):
        announcement = serializer.instance
        old_status = announcement.status
        fields = changed_fields(serializer.validated_data)
        serializer.save()
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.ANNOUNCEMENT_UPDATE,
            target_type='announcement',
            target_id=announcement.pk,
            target_label=announcement.title,
            metadata={
                'fields': fields,
                'old_status': old_status,
                'new_status': announcement.status,
            },
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        target_id = instance.pk
        target_label = instance.title
        instance.delete()
        log_admin_action(
            actor=self.request.user,
            action=AuditAction.ANNOUNCEMENT_DELETE,
            target_type='announcement',
            target_id=target_id,
            target_label=target_label,
        )
