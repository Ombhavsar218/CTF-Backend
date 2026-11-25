"""Unauthenticated health endpoints for liveness, readiness, and Celery."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .health import (
    STATUS_OK,
    beat_status,
    check_database,
    check_redis,
    worker_status,
)


def _response(payload, status=200):
    response = JsonResponse(payload, status=status)
    # Health responses must not be cached by a proxy or browser.
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def liveness(request):
    """The Django process can answer HTTP; no dependencies are contacted."""
    return _response({'status': 'ok', 'checks': {'django': 'ok'}})


@require_GET
def readiness(request):
    """The API can serve requests: Django's database and Redis are reachable."""
    database = check_database()
    redis_ok = check_redis()
    checks = {
        'database': STATUS_OK if database else 'unavailable',
        'redis': STATUS_OK if redis_ok else 'unavailable',
    }
    healthy = database and redis_ok
    return _response(
        {'status': 'ok' if healthy else 'unavailable', 'checks': checks},
        status=200 if healthy else 503,
    )


@require_GET
def celery_health(request):
    """Worker and Beat are both proven alive, not merely containerised.

    The worker answers a Celery control ping. Beat freshness comes from the
    existing heartbeat task's idempotent Redis timestamp, so a schedule file or
    running container alone is not accepted as proof of life.
    """
    worker = worker_status()
    beat = beat_status()
    healthy = worker == STATUS_OK and beat == STATUS_OK
    return _response(
        {
            'status': 'ok' if healthy else 'unavailable',
            'checks': {'worker': worker, 'beat': beat},
        },
        status=200 if healthy else 503,
    )
