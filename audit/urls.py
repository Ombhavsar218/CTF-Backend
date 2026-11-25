from django.urls import path

from .views import AdminAuditLogListView

app_name = 'audit_admin'

urlpatterns = [
    path(
        'audit-logs/',
        AdminAuditLogListView.as_view(),
        name='audit-log-list',
    ),
]
