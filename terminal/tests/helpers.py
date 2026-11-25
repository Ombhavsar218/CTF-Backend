import threading
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from challenges.models import Category, Challenge
from instances.models import ChallengeInstance
from terminal.models import TerminalTicket

User = get_user_model()


def make_user(name):
    return User.objects.create_user(name, f'{name}@example.com', 'pass12345')


def make_challenge(mode='terminal', **kwargs):
    category, _ = Category.objects.get_or_create(name='Terminal', slug='terminal')
    defaults = dict(
        title=f'Terminal {mode}',
        slug=f'terminal-{mode}',
        category=category,
        difficulty='Easy',
        points=100,
        status=Challenge.STATUS_PUBLISHED,
        runtime_enabled=True,
        runtime_image='example/challenge:latest',
        runtime_internal_port=8080,
        runtime_access_mode=mode,
    )
    defaults.update(kwargs)
    return Challenge.objects.create(**defaults)


def make_instance(user, challenge, status=ChallengeInstance.STATUS_RUNNING,
                  minutes=30, container_id='gateway-test-container'):
    return ChallengeInstance.objects.create(
        user=user,
        challenge=challenge,
        status=status,
        expires_at=timezone.now() + timedelta(minutes=minutes),
        internal_name='flaghunt-gateway-test',
        internal_container_id=container_id,
        connection_meta={'type': 'http', 'host': '127.0.0.1', 'port': 32768},
    )


def issue_token(user, instance, ttl=30):
    return TerminalTicket.issue(user, instance, ttl)


class FakeExecStream:
    """Deterministic in-memory stand-in for a Docker exec stream."""

    def __init__(self, outputs=None):
        self.outputs = list(outputs or [])
        self.writes = []
        self.resizes = []
        self.closed = False
        self._condition = threading.Condition()

    def read(self, amount=4096):
        while True:
            with self._condition:
                if self.closed:
                    return b''
                if self.outputs:
                    return self.outputs.pop(0)
                self._condition.wait(timeout=0.05)
            time.sleep(0)

    def write(self, data):
        if self.closed:
            raise AssertionError('write after close')
        self.writes.append(bytes(data))

    def resize(self, rows, cols):
        if self.closed:
            raise AssertionError('resize after close')
        self.resizes.append((int(rows), int(cols)))

    def close(self):
        with self._condition:
            self.closed = True
            self._condition.notify_all()
