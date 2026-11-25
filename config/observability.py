"""Request correlation and log-hygiene helpers.

Request IDs are accepted from ``X-Request-ID`` only when they match a small,
safe character set. Anything else is replaced with a server-generated UUID, so
a client cannot inject newlines (or other control characters) into log lines.

The logging filters configured in ``settings.LOGGING`` attach the current
request ID to every record and redact common secret shapes. These are
defence-in-depth measures, not a reason to log request bodies or credentials.
"""

from __future__ import annotations

import logging
import re
import traceback
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = 'X-Request-ID'
REQUEST_ID_MAX_LENGTH = 64

# Letters/digits followed by letters/digits and a few separator characters.
# Leading whitespace, newlines, quotes, semicolons, and braces are rejected.
_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f-\x9f]')

_SECRET_ASSIGNMENT_RE = re.compile(
    r'(?i)\b(password|passwd|pwd|token|access|refresh|authorization|secret|'
    r'api[_-]?key)\b(\s*[=:]\s*)(?:"[^"]*"|\'[^\']*\'|[^\s,;&]+)'
)
_BEARER_RE = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+')
# Challenge flags are never meant for logs. Accept both historical CTF{...}
# and FLAG{...} prefixes and redact the whole token.
_FLAG_RE = re.compile(r'\b(?:CTF|FLAG)\{[^}\r\n]*\}', re.IGNORECASE)
_URL_CREDENTIALS_RE = re.compile(r'(?i)\b(redis|rediss|amqp|https?)://[^@\s]+@')

_request_id_var: ContextVar[str] = ContextVar('request_id', default='-')


def new_request_id() -> str:
    """Return a fresh, unguessable correlation ID."""
    return uuid.uuid4().hex


def normalise_request_id(value: object) -> str | None:
    """Return a safe incoming request ID, or ``None`` when it is unusable."""
    if not isinstance(value, str):
        return None
    if not value or len(value) > REQUEST_ID_MAX_LENGTH:
        return None
    if not _REQUEST_ID_RE.fullmatch(value):
        return None
    return value


def get_request_id() -> str:
    return _request_id_var.get()


def bind_request_id(value: str):
    """Bind an ID to the current execution context (returns a reset token)."""
    return _request_id_var.set(value or '-')


def reset_request_id(token) -> None:
    _request_id_var.reset(token)


def sanitize_log_value(value: object, max_length: int = 300) -> str:
    """Make an untrusted value safe to place in a single log field.

    Control characters are replaced rather than removed so a newline cannot
    split one record into two. The result is truncated to keep a malicious URL
    from filling the log.
    """
    text = _CONTROL_RE.sub('?', str(value))
    if len(text) > max_length:
        return text[:max_length] + '...'
    return text


def redact_sensitive(value: str) -> str:
    """Redact common credential and flag shapes from a log string."""
    if not value:
        return value
    text = _BEARER_RE.sub('Bearer [REDACTED]', value)
    text = _SECRET_ASSIGNMENT_RE.sub(r'\1\2[REDACTED]', text)
    text = _FLAG_RE.sub('[REDACTED_FLAG]', text)
    text = _URL_CREDENTIALS_RE.sub(r'\1://[REDACTED]@', text)
    return text


class RequestIDFilter(logging.Filter):
    """Attach the active request ID to every log record.

    Django's ``django.request`` logger runs after the response middleware stack
    and passes the request in ``record.request``; falling back to that attribute
    keeps its error summary correlated without trusting arbitrary log extras.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request = getattr(record, 'request', None)
        candidate = (
            getattr(request, 'request_id', None)
            or getattr(record, 'request_id', None)
            or get_request_id()
        )
        record.request_id = normalise_request_id(candidate) or '-'
        return True


class RedactingFilter(logging.Filter):
    """Redact secret-looking values before a record is formatted.

    Logging configuration attaches this to every handler. It deliberately
    leaves the traceback's structure intact while scrubbing the rendered
    exception text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed logging call
            return True

        redacted = redact_sensitive(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()

        if record.exc_info and not record.exc_text:
            try:
                trace = ''.join(traceback.format_exception(*record.exc_info))
                record.exc_text = redact_sensitive(trace)
            except Exception:  # pragma: no cover - defensive
                record.exc_text = '[traceback unavailable]'

        return True
