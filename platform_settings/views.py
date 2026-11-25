"""Administrative platform-settings API.

    GET   /api/v1/admin/settings/
    PATCH /api/v1/admin/settings/

Reads and writes require the model permissions held only by the ``Admin``
group. The response is deliberately limited to the three settings that have
enforced application behavior; arbitrary Django configuration is never
serialized.
"""

from django.db import transaction
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.services import (
    AuditAction,
    changed_fields,
    log_admin_action,
)
from users.permissions import DjangoModelPermissionsWithView

from .models import PlatformSettings
from .serializers import PlatformSettingsSerializer


class AdminPlatformSettingsView(generics.GenericAPIView):
    """Read or partially update the singleton platform settings."""

    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    serializer_class = PlatformSettingsSerializer
    queryset = PlatformSettings.objects.all()
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return PlatformSettings.load()

    def get(self, request):
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)

    @transaction.atomic
    def patch(self, request):
        instance, _ = PlatformSettings.objects.select_for_update().get_or_create(
            pk=1
        )
        serializer = self.get_serializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        fields = changed_fields(serializer.validated_data)
        serializer.save()
        log_admin_action(
            actor=request.user,
            action=AuditAction.SETTINGS_UPDATE,
            target_type='settings',
            target_id=str(instance.pk),
            target_label='Platform settings',
            metadata={'fields': fields},
        )
        return Response(serializer.data)
