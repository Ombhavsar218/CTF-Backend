"""Only used by config.tests to exercise the API exception contract."""

from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError


@api_view(['GET'])
def unhandled(request):
    raise RuntimeError(
        'database failed at /srv/secret/db.sqlite3 password=hunter2 '
        'flag=CTF{do_not_leak}'
    )


@api_view(['GET'])
def validation_error(request):
    raise ValidationError({'username': ['This field is required.']})


@api_view(['GET'])
def permission_denied(request):
    raise PermissionDenied('You do not have permission to do that.')


class InternalServerError(APIException):
    status_code = 500
    default_detail = 'internal database path /srv/secret/db.sqlite3'
    default_code = 'internal'


class SafeServiceUnavailable(APIException):
    status_code = 503
    default_detail = (
        'The default "User" group is not configured. '
        'Run: python manage.py setup_groups'
    )
    default_code = 'default_group_not_configured'


@api_view(['GET'])
def server_error(request):
    raise InternalServerError()


@api_view(['GET'])
def service_unavailable(request):
    raise SafeServiceUnavailable()


urlpatterns = [
    path('test/unhandled/', unhandled),
    path('test/validation/', validation_error),
    path('test/denied/', permission_denied),
    path('test/server-error/', server_error),
    path('test/service-unavailable/', service_unavailable),
]
