"""Dependency and background-worker health probes.

No secrets, broker URLs, hostnames, exception messages, or filesystem paths are
returned to callers. A probe reports only a small status word per dependency.
"""

import logging
import time
from urllib.parse import urlparse

import redis
from django.conf import settings
from django.db import connection

logger = logging.getLogger('ops.health')

STATUS_OK = 'ok'
STATUS_UNAVAILABLE = 'unavailable'
STATUS_MISSING = 'missing'
STATUS_STALE = 'stale'
STATUS_DISABLED = 'disabled'


def _redis_url():
    url = getattr(settings, 'CELERY_BROKER_URL', '') or ''
    if urlparse(url).scheme not in {'redis', 'rediss'}:
        return None
    return url


def _health_timeout():
    try:
        return max(0.1, float(getattr(settings, 'CELERY_HEALTH_TIMEOUT_SECONDS', 2)))
    except (TypeError, ValueError):
        return 2.0


def _redis_client():
    url = _redis_url()
    if url is None:
        return None
    timeout = _health_timeout()
    return redis.Redis.from_url(
        url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )


def check_database():
    """Return True when Django can execute a trivial query."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return True
    except Exception:
        logger.warning('database_health_check_failed')
        return False


def check_redis():
    """Return True when the configured Celery broker answers PING."""
    client = _redis_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        logger.warning('redis_health_check_failed')
        return False


def check_worker():
    """Ask live Celery workers to answer a control ping.

    This is deliberately a worker-level check, not a check that a container
    exists: an idle or wedged worker must not be reported as healthy.
    """
    try:
        from config.celery import app

        replies = app.control.ping(timeout=_health_timeout(), limit=1)
        return bool(replies)
    except Exception:
        logger.warning('celery_worker_health_check_failed')
        return False


def worker_status():
    return STATUS_OK if check_worker() else STATUS_UNAVAILABLE


def _heartbeat_key(source):
    prefix = getattr(settings, 'CELERY_HEARTBEAT_KEY_PREFIX', 'flaghunt:ops:heartbeat')
    return f'{prefix}:{source}'


def _heartbeat_ttl():
    try:
        interval = int(getattr(settings, 'CELERY_HEARTBEAT_INTERVAL_SECONDS', 60))
    except (TypeError, ValueError):
        interval = 60
    try:
        configured = int(getattr(settings, 'CELERY_HEARTBEAT_TTL_SECONDS', 0))
    except (TypeError, ValueError):
        configured = 0
    return max(180, configured if configured > 0 else interval * 3)


def record_heartbeat(source):
    """Record a heartbeat timestamp in Redis, best effort.

    This is an idempotent state write, so a duplicate delivery cannot duplicate
    a business side effect. Failure to record must not fail the heartbeat task:
    the task itself remains a log-only proof of the pipeline.
    """
    if not getattr(settings, 'CELERY_HEARTBEAT_TRACKING_ENABLED', True):
        return False

    source_key = 'beat' if source == 'beat' else 'worker'
    client = _redis_client()
    if client is None:
        return False

    now = int(time.time())
    ttl = _heartbeat_ttl()
    try:
        pipe = client.pipeline(transaction=False)
        pipe.set(_heartbeat_key('worker'), now, ex=ttl)
        if source_key == 'beat':
            pipe.set(_heartbeat_key('beat'), now, ex=ttl)
        pipe.execute()
        return True
    except Exception as exc:
        # Log only the exception class: connection errors can contain broker
        # URLs or credentials.
        logger.warning(
            'celery_heartbeat_tracking_failed source=%s error=%s',
            source_key,
            type(exc).__name__,
        )
        return False


def beat_status():
    """Return ok/stale/missing for the most recent Beat heartbeat."""
    if not getattr(settings, 'CELERY_HEARTBEAT_TRACKING_ENABLED', True):
        return STATUS_DISABLED

    client = _redis_client()
    if client is None:
        return STATUS_UNAVAILABLE

    try:
        raw = client.get(_heartbeat_key('beat'))
    except Exception:
        logger.warning('celery_beat_health_check_failed')
        return STATUS_UNAVAILABLE

    if raw is None:
        return STATUS_MISSING

    try:
        timestamp = int(raw)
    except (TypeError, ValueError):
        return STATUS_STALE

    try:
        stale_after = max(
            30, int(getattr(settings, 'CELERY_BEAT_STALE_AFTER_SECONDS', 180))
        )
    except (TypeError, ValueError):
        stale_after = 180

    age = max(0, int(time.time()) - timestamp)
    return STATUS_OK if age <= stale_after else STATUS_STALE
