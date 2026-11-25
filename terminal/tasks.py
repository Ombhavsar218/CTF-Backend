from celery import shared_task

from .services import SessionRegistry


@shared_task(name='terminal.cleanup_stale')
def cleanup_stale_terminal_state():
    """Periodic, idempotent cleanup of stale tickets and sessions."""
    try:
        result = SessionRegistry.cleanup_stale()
    except Exception as exc:
        return {'ok': False, 'error': (str(exc) or exc.__class__.__name__)[:255]}
    return {'ok': True, **result}
