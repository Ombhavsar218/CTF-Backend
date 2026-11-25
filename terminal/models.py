"""Server-only ticket and session records.

Nothing in this module is serialized to clients. Tickets are stored as SHA-256
hashes; the raw secret exists only in the REST response and the WebSocket
subprotocol handshake.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, models, transaction
from django.db.models import Q
from django.utils import timezone

from instances.models import ChallengeInstance

from .exceptions import TerminalTicketError


class TerminalTicket(models.Model):
    # token_urlsafe(32) produces 43 URL-safe characters. Allow a little slack
    # for future rotation while still rejecting junk before any DB/CPU work.
    TICKET_PATTERN = re.compile(r'^[A-Za-z0-9_-]{32,128}$')

    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='terminal_tickets',
    )
    instance = models.ForeignKey(
        ChallengeInstance,
        on_delete=models.CASCADE,
        related_name='terminal_tickets',
    )
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['user', 'expires_at'], name='terminal_ticket_user_idx'),
            models.Index(fields=['instance', 'used_at'], name='terminal_ticket_instance_idx'),
        ]

    def __str__(self):
        return f'terminal ticket {self.pk} user={self.user_id} instance={self.instance_id}'

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @classmethod
    def is_well_formed(cls, token) -> bool:
        return isinstance(token, str) and bool(cls.TICKET_PATTERN.fullmatch(token))

    @classmethod
    def issue(cls, user, instance, ttl_seconds: int):
        """Create a ticket and return ``(raw_token, ticket_row)``."""
        token = secrets.token_urlsafe(32)
        ticket = cls.objects.create(
            token_hash=cls.hash_token(token),
            user=user,
            instance=instance,
            expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
        )
        return token, ticket

    @classmethod
    def _consume_once(cls, token_hash: str, user, now):
        with transaction.atomic():
            ticket = (
                cls.objects.select_related('user', 'instance__challenge')
                .select_for_update()
                .filter(token_hash=token_hash)
                .first()
            )
            if ticket is None:
                raise TerminalTicketError('Invalid terminal ticket.')
            if user is not None and ticket.user_id != user.pk:
                raise TerminalTicketError('Invalid terminal ticket.')
            if ticket.used_at or ticket.revoked_at or ticket.expires_at <= now:
                raise TerminalTicketError('Terminal ticket is no longer valid.')
            # The conditional UPDATE is the single-use gate. It is safe even
            # where select_for_update is a no-op: a losing transaction cannot
            # satisfy used_at IS NULL after the winner commits.
            updated = cls.objects.filter(
                pk=ticket.pk,
                used_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=now,
            ).update(used_at=now)
            if updated != 1:
                raise TerminalTicketError('Terminal ticket is no longer valid.')
            ticket.used_at = now
        return ticket

    @classmethod
    def consume(cls, token: str, user=None):
        """Atomically consume an unused, unexpired, unrevoked ticket.

        A short retry handles SQLite's coarse table locks in local tests; on
        row-locking databases the first attempt normally decides the race.
        """
        if not cls.is_well_formed(token):
            raise TerminalTicketError('Malformed terminal ticket.')
        now = timezone.now()
        token_hash = cls.hash_token(token)
        for attempt in range(5):
            try:
                return cls._consume_once(token_hash, user, now)
            except OperationalError:
                if attempt == 4:
                    raise TerminalTicketError('Terminal ticket is no longer valid.')
                time.sleep(0.02 * (attempt + 1))
        raise TerminalTicketError('Terminal ticket is no longer valid.')


class TerminalSession(models.Model):
    STATUS_CONNECTING = 'connecting'
    STATUS_CONNECTED = 'connected'
    STATUS_CLOSED = 'closed'
    STATUS_REVOKED = 'revoked'
    STATUS_EXPIRED = 'expired'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_CONNECTING, 'Connecting'),
        (STATUS_CONNECTED, 'Connected'),
        (STATUS_CLOSED, 'Closed'),
        (STATUS_REVOKED, 'Revoked'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_FAILED, 'Failed'),
    ]
    ACTIVE_STATUSES = {STATUS_CONNECTING, STATUS_CONNECTED}
    CLOSED_STATUSES = {STATUS_CLOSED, STATUS_REVOKED, STATUS_EXPIRED, STATUS_FAILED}

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='terminal_sessions',
    )
    instance = models.ForeignKey(
        ChallengeInstance,
        on_delete=models.CASCADE,
        related_name='terminal_sessions',
    )
    ticket = models.ForeignKey(
        TerminalTicket,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sessions',
    )
    channel_name = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_CONNECTING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    # Internal exec coordination state. Never serialised to any API client.
    exec_id = models.CharField(max_length=255, blank=True, default='')
    container_id = models.CharField(max_length=255, blank=True, default='')
    rows = models.PositiveSmallIntegerField(default=24)
    cols = models.PositiveSmallIntegerField(default=80)
    worker_id = models.CharField(max_length=128, blank=True, default='')
    close_requested = models.BooleanField(default=False)
    close_reason = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['user', 'status'], name='terminal_session_user_idx'),
            models.Index(fields=['instance', 'status'], name='terminal_session_instance_idx'),
            models.Index(fields=['last_seen', 'status'], name='terminal_session_seen_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status__in=['connecting', 'connected']),
                name='unique_active_terminal_session_per_user',
            ),
            models.UniqueConstraint(
                fields=['instance'],
                condition=Q(status__in=['connecting', 'connected']),
                name='unique_active_terminal_session_per_instance',
            ),
        ]

    def __str__(self):
        return f'terminal session {self.pk} user={self.user_id} instance={self.instance_id} {self.status}'

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES
