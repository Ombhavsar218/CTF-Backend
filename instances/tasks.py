"""Celery tasks for challenge-instance expiry and restart reconciliation."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='instances.cleanup_expired', bind=True, max_retries=0)
def cleanup_expired_instances(self):
    """Stop/remove expired instances and reconcile DB state with Docker.

    This task is safe to run repeatedly and is also exposed as the
    ``cleanup_instances`` management command for hosts without a worker.
    """
    from .services import InstanceService

    try:
        InstanceService().cleanup()
    except Exception as exc:
        logger.warning('instance cleanup failed: %s', exc)
        return {'ok': False, 'error': str(exc)[:255]}
    return {'ok': True}
