"""Exit non-zero unless the Celery worker/Beat pipeline is actually alive.

Used by the Docker Compose healthchecks and available to operators:

    python manage.py check_celery_health
    python manage.py check_celery_health --component beat --quiet
"""

from django.core.management.base import BaseCommand, CommandError

from ops.health import STATUS_OK, beat_status, worker_status


class Command(BaseCommand):
    help = 'Check the Celery worker (control ping) and Beat (heartbeat freshness).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--component',
            choices=('worker', 'beat', 'all'),
            default='all',
            help='Which component to check (default: all).',
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Print nothing when the check succeeds.',
        )

    def handle(self, *args, **options):
        component = options['component']
        checks = {}
        if component in ('worker', 'all'):
            checks['worker'] = worker_status()
        if component in ('beat', 'all'):
            checks['beat'] = beat_status()

        healthy = all(value == STATUS_OK for value in checks.values())
        summary = ' '.join(f'{name}={value}' for name, value in checks.items())

        if healthy:
            if not options['quiet']:
                self.stdout.write(self.style.SUCCESS(f'celery healthy {summary}'))
            return

        raise CommandError(f'celery health check failed {summary}')
