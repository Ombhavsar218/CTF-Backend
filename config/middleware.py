"""Security and observability middleware."""

import logging
import time

from django.conf import settings

from .observability import (
    REQUEST_ID_HEADER,
    bind_request_id,
    get_request_id,
    new_request_id,
    normalise_request_id,
    reset_request_id,
    sanitize_log_value,
)

logger = logging.getLogger('config.request')


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # CSP is report-only by default; set CSP_REPORT_ONLY=False to enforce.
        if getattr(settings, 'CSP_REPORT_ONLY', True):
            header_name = 'Content-Security-Policy-Report-Only'
        else:
            header_name = 'Content-Security-Policy'
        csp = getattr(settings, 'CSP_POLICY', None)
        if csp and header_name not in response:
            response[header_name] = csp
        return response


class RequestIDMiddleware:
    """Attach a validated/generated request ID to the request, response, and logs.

    The incoming value is only echoed when it matches the safe request-ID
    grammar. The request body, query string, and headers are never logged.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get('HTTP_X_REQUEST_ID')
        request_id = normalise_request_id(incoming) or new_request_id()
        request.request_id = request_id

        token = bind_request_id(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            # Always overwrite: a view must not be able to spoof or split the
            # correlation header with an attacker-controlled value.
            response[REQUEST_ID_HEADER] = request_id
            self._log_request(request, response, started, request_id)
            return response
        finally:
            reset_request_id(token)

    def _log_request(self, request, response, started, request_id):
        if not getattr(settings, 'REQUEST_LOG_ENABLED', True):
            return

        user = getattr(request, 'user', None)
        user_id = getattr(user, 'pk', '-') if getattr(user, 'is_authenticated', False) else '-'
        logger.info(
            'request method=%s path=%s status=%s duration_ms=%.2f user_id=%s request_id=%s',
            sanitize_log_value(request.method, 16),
            sanitize_log_value(request.path, 300),
            response.status_code,
            (time.perf_counter() - started) * 1000,
            user_id if user_id not in (None, '') else '-',
            get_request_id(),
        )
