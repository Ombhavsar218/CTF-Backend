"""Background tasks that verify the Redis + Celery + Beat pipeline.

Deliberately boring: every task here only writes a log line. Nothing in this
module reads or writes user scores, solves, submissions, achievements, tokens
or any other persisted record, so re-running a task can never duplicate a side
effect. That matters because Beat re-delivers the heartbeat on a timer and
because SQLite is shared with the host Django process.
"""

import logging
import os

from celery import shared_task
from django.conf import settings

from config.observability import sanitize_log_value

from .health import record_heartbeat

logger = logging.getLogger(__name__)


@shared_task(name='ops.heartbeat', ignore_result=True)
def heartbeat(source='manual', note=''):
    """Log one heartbeat and return a short confirmation string.

    ``source`` identifies how the heartbeat was produced (``cli`` for the
    management command, ``beat`` for the scheduler). ``note`` is free text.

    The log line includes the resolved SQLite path so the worker logs prove
    which database file the container is actually using. The path is read from
    settings only - the database is never opened here.
    """
    database_name = settings.DATABASES['default']['NAME']
    safe_source = sanitize_log_value(source, 64)
    safe_note = sanitize_log_value(note, 300) if note else '-'
    logger.info(
        'heartbeat source=%s note=%s pid=%s db=%s',
        safe_source,
        safe_note,
        os.getpid(),
        sanitize_log_value(database_name, 300),
    )
    # Idempotent timestamp for the /health/celery/ probe. This is best effort:
    # a Redis hiccup must not turn a successful heartbeat into a task failure.
    record_heartbeat(source)
    return f'ok source={safe_source} note={safe_note}'
