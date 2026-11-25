"""Deployment configuration validation.

The helpers in this module are deliberately free of Django imports so
``config.settings`` can call them while the settings module is being imported.
Each helper returns a list of human-readable problems; the caller raises
``ImproperlyConfigured`` when that list is not empty.

Development is intentionally permissive so a fresh checkout keeps working with
no ``.env``. Production (``ENVIRONMENT=production``) and any ``DEBUG=False``
run must be explicit and fail closed.
"""

from urllib.parse import urlparse

# The fallback used only for local development. It is never accepted for a
# non-debug or production configuration.
DEV_SECRET_KEY = (
    'django-insecure-st#z6#-^0&=7jkkenfk!yja*fwv7=$=$lu3v@$dq%7mf#5$3+%'
)

VALID_ENVIRONMENTS = {'development', 'production'}

_PLACEHOLDER_SECRETS = {
    'change-me',
    'changeme',
    'replace-with-a-random-50-character-string',
    'secret',
    'your-secret-key',
}


def _is_placeholder_secret(value):
    lowered = value.strip().lower()
    return (
        lowered in _PLACEHOLDER_SECRETS
        or lowered.startswith('replace-with-')
        or lowered.startswith('django-insecure-')
    )


def _origin_errors(label, origin, *, require_https, allow_wildcard):
    if not isinstance(origin, str) or not origin.strip():
        return [f'{label} must not contain an empty origin.']

    try:
        parsed = urlparse(origin)
    except ValueError:
        return [f'{label} entry {origin!r} is not a valid origin.']

    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return [f'{label} entry {origin!r} must be an absolute http(s) origin.']
    if parsed.path:
        return [
            f'{label} entry {origin!r} must not include a path or trailing slash.'
        ]
    if parsed.params or parsed.query or parsed.fragment:
        return [
            f'{label} entry {origin!r} must not include a query, fragment, '
            'or parameters.'
        ]
    if parsed.username or parsed.password:
        return [f'{label} entry {origin!r} must not contain credentials.']
    if not allow_wildcard and '*' in parsed.netloc:
        return [f'{label} entry {origin!r} must not contain a wildcard.']
    if require_https and parsed.scheme != 'https':
        return [f'{label} entry {origin!r} must use https in production.']
    return []


def _host_errors(host):
    if not isinstance(host, str) or not host.strip():
        return ['ALLOWED_HOSTS must not contain an empty entry.']
    if host == '*':
        return [
            'ALLOWED_HOSTS must not contain "*"; list the actual hostnames.'
        ]
    if '://' in host or '/' in host or any(char.isspace() for char in host):
        return [
            f'ALLOWED_HOSTS entry {host!r} must be a bare hostname without a '
            'scheme or path.'
        ]
    return []


def _redis_url_errors(label, url):
    if not url:
        return [f'{label} must be set.']
    try:
        parsed = urlparse(url)
    except ValueError:
        return [f'{label} is not a valid URL.']
    if parsed.scheme not in {'redis', 'rediss'} or not parsed.netloc:
        return [f'{label} must be a redis:// or rediss:// URL.']
    return []


def deployment_errors(config):
    """Return every problem with a resolved deployment configuration.

    ``config`` is a plain mapping built by ``config.settings``. Keeping this
    function pure makes the fail-fast rules testable without reloading Django.
    """
    errors = []

    environment = str(config.get('environment') or '').strip().lower()
    if environment not in VALID_ENVIRONMENTS:
        errors.append("ENVIRONMENT must be 'development' or 'production'.")

    production = environment == 'production'
    debug = bool(config.get('debug'))
    secret_key = config.get('secret_key') or ''
    allowed_hosts = config.get('allowed_hosts') or []
    cors_allowed_origins = config.get('cors_allowed_origins') or []
    csrf_trusted_origins = config.get('csrf_trusted_origins') or []
    websocket_allowed_origins = config.get('websocket_allowed_origins') or []

    if production and debug:
        errors.append('DEBUG must be False when ENVIRONMENT=production.')

    # A deployment that turns DEBUG off - with or without the production flag -
    # must not rely on the checked-in development secret or an empty host list.
    require_explicit = production or not debug
    if require_explicit:
        if not secret_key:
            errors.append(
                'SECRET_KEY must be set explicitly when DEBUG=False or '
                'ENVIRONMENT=production.'
            )
        else:
            if secret_key == DEV_SECRET_KEY or _is_placeholder_secret(secret_key):
                errors.append(
                    'SECRET_KEY must not be the development key or a '
                    'placeholder value.'
                )
            if len(secret_key) < 50:
                errors.append('SECRET_KEY must be at least 50 characters long.')
        if not allowed_hosts:
            errors.append(
                'ALLOWED_HOSTS must contain at least one host when DEBUG=False '
                'or ENVIRONMENT=production.'
            )

    for host in allowed_hosts:
        errors.extend(_host_errors(host))

    for origin in cors_allowed_origins:
        errors.extend(
            _origin_errors(
                'CORS_ALLOWED_ORIGINS',
                origin,
                require_https=production,
                allow_wildcard=False,
            )
        )

    for origin in csrf_trusted_origins:
        errors.extend(
            _origin_errors(
                'CSRF_TRUSTED_ORIGINS',
                origin,
                require_https=production,
                allow_wildcard=True,
            )
        )

    for origin in websocket_allowed_origins:
        errors.extend(
            _origin_errors(
                'WEBSOCKET_ALLOWED_ORIGINS',
                origin,
                require_https=production,
                allow_wildcard=False,
            )
        )

    if production:
        errors.extend(
            _redis_url_errors('CACHE_URL', config.get('cache_url'))
        )
        errors.extend(
            _redis_url_errors(
                'CELERY_BROKER_URL', config.get('celery_broker_url')
            )
        )

        cache_url = (config.get('cache_url') or '').rstrip('/')
        broker_url = (config.get('celery_broker_url') or '').rstrip('/')
        if cache_url and cache_url == broker_url:
            errors.append(
                'CACHE_URL must not be the same Redis URL as '
                'CELERY_BROKER_URL; use a separate database or instance so '
                'cache eviction cannot remove broker messages.'
            )

        if not config.get('secure_ssl_redirect'):
            errors.append('SECURE_SSL_REDIRECT must be True in production.')
        if not config.get('session_cookie_secure'):
            errors.append('SESSION_COOKIE_SECURE must be True in production.')
        if not config.get('csrf_cookie_secure'):
            errors.append('CSRF_COOKIE_SECURE must be True in production.')
        try:
            hsts_seconds = int(config.get('hsts_seconds') or 0)
        except (TypeError, ValueError):
            hsts_seconds = 0
        if hsts_seconds <= 0:
            errors.append('SECURE_HSTS_SECONDS must be greater than 0.')

        csp_policy = str(config.get('csp_policy') or '').strip()
        if not csp_policy:
            errors.append('CSP_POLICY must not be empty in production.')
        else:
            lowered = csp_policy.lower()
            if any(
                token in lowered
                for token in ('localhost', '127.0.0.1', '[::1]')
            ):
                errors.append(
                    'CSP_POLICY must not contain development origins '
                    '(localhost/127.0.0.1) in production.'
                )
            if 'http://' in lowered:
                errors.append(
                    'CSP_POLICY must not contain insecure http:// origins in '
                    'production.'
                )

    database_engine = str(config.get('database_engine') or '')
    if production and database_engine.endswith('sqlite3'):
        errors.append(
            'SQLite is not allowed when ENVIRONMENT=production; configure '
            'DATABASE_URL or PostgreSQL DB_* settings.'
        )
    if (
        database_engine
        and not database_engine.endswith('sqlite3')
        and not config.get('database_name')
    ):
        errors.append('DB_NAME must be set for a non-SQLite database.')

    return errors
