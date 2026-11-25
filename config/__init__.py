"""Project package.

Importing the Celery application here means ``@shared_task`` resolves against
the configured app and ``celery -A config`` finds it, while also guaranteeing
that Django has loaded its settings first.
"""

from .celery import app as celery_app

__all__ = ('celery_app',)
