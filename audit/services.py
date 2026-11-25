"""Write-side helpers for the administrative audit trail.

The caller must run a mutation and :func:`log_admin_action` inside the same
database transaction (the admin views do this with ``transaction.atomic``).
Audit writing is intentionally fail-closed: if the row cannot be written, the
surrounding transaction rolls the mutation back rather than committing an
unrecorded administrative action.

The service never accepts or derives request metadata. Callers pass a small,
explicit dictionary of facts; :func:`sanitize_metadata` is a final safety net
that drops sensitive keys (passwords, flags, tokens, cookies, notes, request
addresses) and bounds the stored shape.
"""

from django.contrib.auth import get_user_model

from .models import AuditLog

User = get_user_model()

# Lower-case, punctuation-normalised key fragments that must never be stored.
SENSITIVE_KEY_FRAGMENTS = (
    'password',
    'passwd',
    'passphrase',
    'token',
    'secret',
    'cookie',
    'authorization',
    'flag',
    'statusnote',
    'status_note',
    'privatekey',
    'api_key',
    'apikey',
    'jwt',
    'sessionid',
    'ipaddress',
    'ip_address',
    'remoteaddr',
    'remote_addr',
)

MAX_STRING_LENGTH = 300
MAX_LIST_ITEMS = 50
MAX_METADATA_DEPTH = 4


class AuditAction:
    """Stable action names used by the admin views and the UI filter."""

    USER_CREATE = 'user.create'
    USER_UPDATE = 'user.update'
    USER_STATUS_CHANGE = 'user.status_change'
    USER_GROUPS_CHANGE = 'user.groups_change'
    USER_DELETE = 'user.delete'
    USER_RESTORE = 'user.restore'

    CHALLENGE_CREATE = 'challenge.create'
    CHALLENGE_UPDATE = 'challenge.update'
    CHALLENGE_STATUS_CHANGE = 'challenge.status_change'
    CHALLENGE_DELETE = 'challenge.delete'
    CHALLENGE_ATTACHMENT_ADD = 'challenge.attachment_add'
    CHALLENGE_ATTACHMENT_DELETE = 'challenge.attachment_delete'

    CATEGORY_CREATE = 'category.create'
    CATEGORY_UPDATE = 'category.update'
    CATEGORY_DELETE = 'category.delete'

    ACHIEVEMENT_CREATE = 'achievement.create'
    ACHIEVEMENT_UPDATE = 'achievement.update'
    ACHIEVEMENT_DELETE = 'achievement.delete'

    ANNOUNCEMENT_CREATE = 'announcement.create'
    ANNOUNCEMENT_UPDATE = 'announcement.update'
    ANNOUNCEMENT_DELETE = 'announcement.delete'

    SETTINGS_UPDATE = 'settings.update'

    ALL = (
        USER_CREATE,
        USER_UPDATE,
        USER_STATUS_CHANGE,
        USER_GROUPS_CHANGE,
        USER_DELETE,
        USER_RESTORE,
        CHALLENGE_CREATE,
        CHALLENGE_UPDATE,
        CHALLENGE_STATUS_CHANGE,
        CHALLENGE_DELETE,
        CHALLENGE_ATTACHMENT_ADD,
        CHALLENGE_ATTACHMENT_DELETE,
        CATEGORY_CREATE,
        CATEGORY_UPDATE,
        CATEGORY_DELETE,
        ACHIEVEMENT_CREATE,
        ACHIEVEMENT_UPDATE,
        ACHIEVEMENT_DELETE,
        ANNOUNCEMENT_CREATE,
        ANNOUNCEMENT_UPDATE,
        ANNOUNCEMENT_DELETE,
        SETTINGS_UPDATE,
    )


def _normalise_key(key):
    return str(key).strip().lower().replace('-', '_').replace(' ', '')


def is_sensitive_key(key):
    """Whether a metadata key names a value the audit trail must not store."""
    normalised = _normalise_key(key)
    compact = normalised.replace('_', '')
    return any(
        fragment in normalised or fragment in compact
        for fragment in SENSITIVE_KEY_FRAGMENTS
    )


def sanitize_metadata(value, depth=0):
    """Return a JSON-safe copy with sensitive keys removed and sizes bounded.

    This is a defence-in-depth layer, not a place to put raw request data. The
    views only pass explicit facts (changed field names, old/new status, group
    names, attachment ids).
    """
    if depth > MAX_METADATA_DEPTH:
        return None

    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str) or is_sensitive_key(key):
                continue
            safe_key = key[:64]
            safe_value = sanitize_metadata(item, depth + 1)
            if safe_value is not None:
                cleaned[safe_key] = safe_value
        return cleaned

    if isinstance(value, (list, tuple)):
        return [
            sanitize_metadata(item, depth + 1)
            for item in list(value)[:MAX_LIST_ITEMS]
            if sanitize_metadata(item, depth + 1) is not None
        ]

    if isinstance(value, str):
        return value[:MAX_STRING_LENGTH]

    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
        return value

    if value is None:
        return None

    return str(value)[:MAX_STRING_LENGTH]


def changed_fields(validated_data):
    """Safe field names from a serializer's validated input.

    Values are never returned: the audit trail records *what* an administrator
    changed, not the submitted password, email, flag or other field content.
    """
    if not validated_data:
        return []
    return sorted(
        {
            str(key)
            for key in validated_data.keys()
            if not is_sensitive_key(key)
        }
    )


def log_admin_action(
    *,
    actor,
    action,
    target_type,
    target_id='',
    target_label='',
    metadata=None,
):
    """Create one audit row. Call inside the mutation's transaction.

    Raises whatever the database raises, so the caller's transaction can roll
    back. There is no Celery/background path: a successful response means both
    the mutation and its audit row committed together.
    """
    if not action or not target_type:
        raise ValueError('An audit action and target type are required.')

    actor_id = getattr(actor, 'pk', None)
    if not getattr(actor, 'is_authenticated', False):
        actor_id = None
        actor_username = ''
    else:
        actor_username = getattr(actor, 'username', '') or ''

    return AuditLog.objects.create(
        actor_id=actor_id,
        actor_username=str(actor_username)[:150],
        action=str(action)[:64],
        target_type=str(target_type)[:32],
        target_id=str(target_id or '')[:64],
        target_label=str(target_label or '')[:255],
        metadata=sanitize_metadata(metadata or {}),
    )
