"""Safe, standardised API error responses.

DRF's default handler produces useful validation, authentication, permission,
not-found, and throttling responses. We keep those unchanged and only add:

* a generic JSON response for unexpected exceptions (instead of allowing a
  Django debug traceback or an HTML error page to reach an API client), and
* a sanitised body for handled 5xx responses: an intentional, operator-safe
  message may survive, but anything containing traceback/storage/path detail is
  replaced with the generic message.

The request ID is returned in the ``X-Request-ID`` response header by the
middleware; it is also added here for callers that invoke the handler directly.
"""

import logging
import re

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .observability import REQUEST_ID_HEADER, get_request_id, sanitize_log_value

logger = logging.getLogger('config.exceptions')

GENERIC_SERVER_ERROR = (
    'An unexpected server error occurred. Please try again later.'
)

# Deliberately raised APIExceptions may carry an operator-facing explanation
# (for example "run setup_groups"). Preserve only details that contain no
# traceback, storage engine, filesystem path, or exception text.
_UNSAFE_5XX_DETAIL = re.compile(
    r'(?i)(traceback|stack trace|file "|exception|sqlite|postgres|mysql|'
    r'database|no such table|relation .+ does not exist|operationalerror|'
    r'integrityerror|/srv/|/home/|/var/|/app/|[a-z]:\\|redis://|rediss://|'
    r'select\s+.+\s+from)'
)


def _is_public_5xx_detail(response):
    data = response.data
    if not isinstance(data, dict):
        return False
    detail = data.get('detail')
    if not isinstance(detail, str) or not detail.strip():
        return False
    return not _UNSAFE_5XX_DETAIL.search(detail)


def _request_context(context):
    request = context.get('request') if context else None
    method = sanitize_log_value(getattr(request, 'method', '-'), 16)
    path = sanitize_log_value(getattr(request, 'path', '-'), 300)
    return request, method, path


def safe_exception_handler(exc, context):
    request, method, path = _request_context(context)
    response = drf_exception_handler(exc, context)

    if response is None:
        # The redaction filter configured on the logging handlers scrubs
        # credential/flag shapes from the rendered traceback.
        logger.error(
            'unhandled_api_exception type=%s method=%s path=%s',
            type(exc).__name__,
            method,
            path,
            exc_info=True,
        )
        response = Response({'detail': GENERIC_SERVER_ERROR}, status=500)
    elif response.status_code >= 500:
        logger.error(
            'api_server_error type=%s status=%s method=%s path=%s',
            type(exc).__name__,
            response.status_code,
            method,
            path,
        )
        # Preserve an intentional, safe operator message (e.g. a missing
        # default group). Anything containing internal detail becomes generic.
        if not _is_public_5xx_detail(response):
            response.data = {'detail': GENERIC_SERVER_ERROR}

    request_id = get_request_id()
    if not request_id or request_id == '-':
        request_id = getattr(request, 'request_id', None)
    if request_id and request_id != '-':
        response[REQUEST_ID_HEADER] = request_id

    return response
