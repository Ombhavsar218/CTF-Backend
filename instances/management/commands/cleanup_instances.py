"""Run challenge-instance expiry cleanup from cron or an operator shell."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from instances.services import InstanceService


class Command(BaseCommand):
    help = 'Stop/remove expired challenge instances and reconcile live state.'

    def handle(self, *args, **options):
        InstanceService().cleanup()
        self.stdout.write(self.style.SUCCESS('instance cleanup complete'))
