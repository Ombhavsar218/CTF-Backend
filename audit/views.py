"""Read-only administrative audit-log API.

    GET /api/v1/admin/audit-logs/

Requires the ``audit.view_auditlog`` Django permission, which ``setup_groups``
grants to the Admin group. The view is list/read-only: no endpoint accepts a
create, update or delete, so the trail cannot be rewritten through the API.

Supported query parameters:

* ``page`` / ``page_size`` (default 20, maximum 100)
* ``actor`` (username, exact, case-insensitive)
* ``action`` (exact, e.g. ``user.status_change``)
* ``target_type`` (exact, e.g. ``user``)
* ``search`` (actor, action, target label/id/type)
* ``date_from`` / ``date_to`` (``YYYY-MM-DD``, inclusive)
"""

from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from users.permissions import DjangoModelPermissionsWithView

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _date_param(request, name):
    raw = (request.query_params.get(name) or '').strip()
    if not raw:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise ValidationError({name: 'Use a date in YYYY-MM-DD format.'})
    return parsed


class AdminAuditLogListView(generics.ListAPIView):
    """GET /api/v1/admin/audit-logs/ - paginated, filterable, read-only."""

    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    pagination_class = AuditLogPagination
    serializer_class = AuditLogSerializer
    http_method_names = ['get', 'head', 'options']
    queryset = AuditLog.objects.all()

    def get_queryset(self):
        queryset = AuditLog.objects.all()
        params = self.request.query_params

        actor = (params.get('actor') or '').strip()
        if actor:
            queryset = queryset.filter(actor_username__iexact=actor)

        action = (params.get('action') or '').strip()
        if action:
            queryset = queryset.filter(action=action)

        target_type = (params.get('target_type') or '').strip()
        if target_type:
            queryset = queryset.filter(target_type=target_type)

        search = (params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(actor_username__icontains=search)
                | Q(action__icontains=search)
                | Q(target_type__icontains=search)
                | Q(target_id__icontains=search)
                | Q(target_label__icontains=search)
            )

        date_from = _date_param(self.request, 'date_from')
        if date_from is not None:
            queryset = queryset.filter(created_at__date__gte=date_from)

        date_to = _date_param(self.request, 'date_to')
        if date_to is not None:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset
