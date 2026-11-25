"""Enqueue the ``ops.heartbeat`` task from the local Django environment.

This is the documented way to push one message through the real broker:

    python manage.py enqueue_heartbeat --note "hello"
    python manage.py enqueue_heartbeat --wait --timeout 10   # needs a backend

The command itself never touches the database or any business record; it only
hands a message to Redis. Whether the message is executed is visible in the
worker logs (``Task ops.heartbeat[...] succeeded``).

``--wait`` is only meaningful when ``CELERY_RESULT_BACKEND`` is configured;
by default results are ignored and the command says so instead of hanging.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.observability import redact_sensitive
from ops.tasks import heartbeat


class Command(BaseCommand):
    help = (
        'Enqueue one ops.heartbeat task through the configured Celery broker '
        'and print its task id.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--note',
            default='',
            help='Free-text note recorded in the worker log line.',
        )
        parser.add_argument(
            '--source',
            default='cli',
            help='Value for the task "source" argument (default: cli).',
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help=(
                'Block until the worker returns a result. Requires '
                'CELERY_RESULT_BACKEND; without one this is an error.'
            ),
        )
        parser.add_argument(
            '--timeout',
            type=float,
            default=10.0,
            help='Seconds to wait with --wait (default: 10).',
        )

    def handle(self, *args, **options):
        if options['wait'] and not settings.CELERY_RESULT_BACKEND:
            raise CommandError(
                '--wait needs a result backend. Set CELERY_RESULT_BACKEND '
                '(e.g. redis://127.0.0.1:6379/1) or check the worker log '
                'instead, which is the default verification path.'
            )

        result = heartbeat.delay(
            source=options['source'], note=options['note']
        )

        # Never print credentials embedded in redis:// URLs to a terminal or CI
        # log. The host/db are useful; the userinfo is not.
        self.stdout.write(
            f'broker: {redact_sensitive(str(settings.CELERY_BROKER_URL))}'
        )
        self.stdout.write(self.style.SUCCESS(f'enqueued ops.heartbeat id={result.id}'))
        self.stdout.write(
            'Verify with: docker compose logs --tail=20 celery-worker'
        )

        if options['wait']:
            self.stdout.write('waiting for the worker result...')
            try:
                value = result.get(timeout=options['timeout'])
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                raise CommandError(f'task did not return: {exc}') from exc
            self.stdout.write(self.style.SUCCESS(f'result: {value}'))
