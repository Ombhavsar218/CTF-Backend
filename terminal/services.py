"""Application services for terminal tickets and session coordination."""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from challenge_runtime.errors import RuntimeErrorBase
from instances.models import ChallengeInstance
from instances.services import InstanceService

from .exceptions import (
    TerminalDisabled,
    TerminalNotAvailable,
    TerminalRuntimeUnavailable,
    TerminalSessionLimit,
)
from .models import TerminalSession, TerminalTicket


def instance_group(instance_id) -> str:
    """Channel group used only for lifecycle notifications, never terminal I/O."""
    return f'terminal.instance.{instance_id}'


# Retain fire-and-forget tasks until they finish; asyncio can garbage-collect
# unreferenced tasks mid-send. Only opaque reason strings are ever broadcast.
_PENDING_NOTIFICATIONS = set()


def _notify_instance(instance_id, reason: str) -> None:
    """Best-effort, cross-worker close signal. No ticket or secret is included."""
    layer = get_channel_layer()
    if layer is None:
        return
    message = {'type': 'terminal.revoked', 'reason': reason}
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            async_to_sync(layer.group_send)(instance_group(instance_id), message)
        else:
            # Called from an ASGI worker (e.g. a revocation during an async
            # test): schedule the broadcast instead of blocking the loop.
            task = asyncio.create_task(
                layer.group_send(instance_group(instance_id), message)
            )
            _PENDING_NOTIFICATIONS.add(task)
            task.add_done_callback(_PENDING_NOTIFICATIONS.discard)
    except Exception:
        # Losing a notification is safe: the database session row is already
        # closed and the periodic cleanup task will converge state.
        pass


class TicketIssuer:
    """Issue a ticket only for an owned, active, running terminal instance."""

    def __init__(self, instance_service=None):
        self.instances = instance_service or InstanceService()

    def issue(self, user):
        if not settings.TERMINAL_ENABLED:
            raise TerminalDisabled('Terminal access is disabled.')

        instance = self.instances.active(user)
        if instance is None:
            raise TerminalNotAvailable('No active challenge instance was found.')
        if instance.status != ChallengeInstance.STATUS_RUNNING:
            raise TerminalNotAvailable('The challenge instance is not running.')
        if instance.is_expired:
            raise TerminalNotAvailable('The challenge instance has expired.')
        if getattr(instance.challenge, 'runtime_access_mode', 'http') != 'terminal':
            raise TerminalNotAvailable('This challenge is not configured for terminal access.')

        try:
            self.instances.runtime.confirm_running(instance)
        except RuntimeErrorBase as exc:
            raise TerminalRuntimeUnavailable('The challenge container is unavailable.') from exc
        except Exception as exc:  # never leak daemon details to the browser
            raise TerminalRuntimeUnavailable('The challenge container is unavailable.') from exc

        token, ticket = TerminalTicket.issue(
            user, instance, settings.TERMINAL_TICKET_TTL_SECONDS
        )
        return token, ticket


class SessionRegistry:
    """Database-backed registry shared by all ASGI workers."""

    ACTIVE_STATUSES = TerminalSession.ACTIVE_STATUSES

    @classmethod
    def acquire(cls, user, instance, ticket, channel_name: str = '',
                worker_id: str = ''):
        """Reserve a session slot, enforcing configurable per-user/instance caps."""
        try:
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=user.pk)
                ChallengeInstance.objects.select_for_update().get(pk=instance.pk)

                user_count = TerminalSession.objects.filter(
                    user_id=user.pk, status__in=cls.ACTIVE_STATUSES
                ).count()
                if user_count >= settings.TERMINAL_MAX_SESSIONS_PER_USER:
                    raise TerminalSessionLimit(
                        'Terminal session limit reached for this user.'
                    )

                instance_count = TerminalSession.objects.filter(
                    instance_id=instance.pk, status__in=cls.ACTIVE_STATUSES
                ).count()
                if instance_count >= settings.TERMINAL_MAX_SESSIONS_PER_INSTANCE:
                    raise TerminalSessionLimit(
                        'Terminal session limit reached for this instance.'
                    )

                session = TerminalSession.objects.create(
                    user_id=user.pk,
                    instance_id=instance.pk,
                    ticket_id=getattr(ticket, 'pk', ticket),
                    channel_name=channel_name or '',
                    worker_id=worker_id or str(os.getpid()),
                    status=TerminalSession.STATUS_CONNECTING,
                )
        except IntegrityError as exc:
            # Conditional DB unique constraints are the cross-worker authority
            # when SQLite's SELECT FOR UPDATE is a no-op.
            raise TerminalSessionLimit('Terminal session limit reached.') from exc
        return session

    @staticmethod
    def mark_connected(session_id, channel_name: str = ''):
        now = timezone.now()
        TerminalSession.objects.filter(
            pk=session_id, status__in=TerminalSession.ACTIVE_STATUSES
        ).update(
            status=TerminalSession.STATUS_CONNECTED,
            channel_name=channel_name or '',
            connected_at=now,
            last_seen=now,
        )

    @staticmethod
    def mark_exec_started(session_id, exec_id: str, container_id: str,
                          rows: int, cols: int, worker_id: str = ''):
        return TerminalSession.objects.filter(
            pk=session_id, status__in=TerminalSession.ACTIVE_STATUSES
        ).update(
            exec_id=exec_id,
            container_id=container_id,
            rows=int(rows),
            cols=int(cols),
            worker_id=worker_id or str(os.getpid()),
            last_seen=timezone.now(),
        )

    @staticmethod
    def update_dimensions(session_id, rows: int, cols: int):
        return TerminalSession.objects.filter(
            pk=session_id, status__in=TerminalSession.ACTIVE_STATUSES
        ).update(rows=int(rows), cols=int(cols), last_seen=timezone.now())

    @staticmethod
    def heartbeat(session_id):
        TerminalSession.objects.filter(
            pk=session_id, status__in=TerminalSession.ACTIVE_STATUSES
        ).update(last_seen=timezone.now())

    @staticmethod
    def stream_context(session_id):
        """Return a fresh, relationship-loaded context for stream decisions."""
        try:
            session = (
                TerminalSession.objects.select_related('instance__challenge', 'user')
                .get(pk=session_id)
            )
        except TerminalSession.DoesNotExist:
            return None
        return {
            'session': session,
            'active': session.status in TerminalSession.ACTIVE_STATUSES,
            'close_requested': session.close_requested,
            'reason': session.close_reason,
            'instance': session.instance,
            'challenge_mode': getattr(
                session.instance.challenge, 'runtime_access_mode', 'http'
            ),
        }

    @staticmethod
    def request_close(session_id, reason: str):
        return TerminalSession.objects.filter(
            pk=session_id, status__in=TerminalSession.ACTIVE_STATUSES
        ).update(close_requested=True, close_reason=reason[:64], last_seen=timezone.now())

    @classmethod
    def pending_close_sessions(cls):
        return list(TerminalSession.objects.filter(
            status__in=cls.ACTIVE_STATUSES, close_requested=True
        ).select_related('instance'))

    @staticmethod
    def release(session_id, status: str = TerminalSession.STATUS_CLOSED):
        if status not in TerminalSession.CLOSED_STATUSES:
            status = TerminalSession.STATUS_CLOSED
        now = timezone.now()
        updated = TerminalSession.objects.filter(
            pk=session_id, status__in=TerminalSession.ACTIVE_STATUSES
        ).update(status=status, closed_at=now)
        return updated

    @classmethod
    def revoke_for_instance(cls, instance, reason: str = 'instance_unavailable'):
        """Close sessions and unused tickets when an instance stops or fails."""
        now = timezone.now()
        instance_id = instance.pk if hasattr(instance, 'pk') else instance
        closed = TerminalSession.objects.filter(
            instance_id=instance_id, status__in=cls.ACTIVE_STATUSES
        ).update(
            status=TerminalSession.STATUS_REVOKED,
            closed_at=now,
            close_requested=True,
            close_reason=reason[:64],
        )
        TerminalTicket.objects.filter(
            instance_id=instance_id, used_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=now)
        if closed:
            _notify_instance(instance_id, reason)
        return closed

    @classmethod
    def revoke_for_user(cls, user, reason: str = 'user_disabled'):
        user_id = user.pk if hasattr(user, 'pk') else user
        sessions = list(TerminalSession.objects.filter(
            user_id=user_id, status__in=cls.ACTIVE_STATUSES
        ))
        instance_ids = {session.instance_id for session in sessions}
        now = timezone.now()
        TerminalSession.objects.filter(pk__in=[s.pk for s in sessions]).update(
            status=TerminalSession.STATUS_REVOKED,
            closed_at=now,
            close_requested=True,
            close_reason=reason[:64],
        )
        TerminalTicket.objects.filter(
            user_id=user_id, used_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=now)
        for instance_id in instance_ids:
            _notify_instance(instance_id, reason)
        return len(sessions)

    @classmethod
    def cleanup_stale(cls):
        """Periodic defence-in-depth cleanup of expired state."""
        now = timezone.now()
        stale_tickets_cutoff = now - timedelta(
            seconds=max(settings.TERMINAL_TICKET_TTL_SECONDS, 30) + 60
        )
        revoked_tickets = TerminalTicket.objects.filter(
            expires_at__lte=now, used_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=now)
        deleted_tickets, _ = TerminalTicket.objects.filter(
            created_at__lt=now - timedelta(days=1)
        ).delete()

        stale_sessions = list(TerminalSession.objects.filter(
            status__in=cls.ACTIVE_STATUSES,
        ).select_related('instance').filter(
            Q(instance__status__in=[
                ChallengeInstance.STATUS_STOPPING,
                ChallengeInstance.STATUS_STOPPED,
                ChallengeInstance.STATUS_EXPIRED,
                ChallengeInstance.STATUS_FAILED,
            ]) | Q(instance__expires_at__lte=now)
        ))
        for session in stale_sessions:
            cls.revoke_for_instance(session.instance_id, 'instance_unavailable')

        # A connection that never became usable must not hold a slot forever.
        stranded = TerminalSession.objects.filter(
            status=TerminalSession.STATUS_CONNECTING,
            created_at__lt=stale_tickets_cutoff,
        ).update(status=TerminalSession.STATUS_EXPIRED, closed_at=now)

        # Reclaim sessions owned by a crashed ASGI worker. The client heartbeat
        # and the consumer watchdog both refresh last_seen while healthy.
        unresponsive_cutoff = now - timedelta(
            seconds=max(settings.TERMINAL_STALE_SESSION_SECONDS, 30)
        )
        unresponsive = list(TerminalSession.objects.filter(
            status=TerminalSession.STATUS_CONNECTED,
        ).exclude(pk__in=[s.pk for s in stale_sessions]).filter(
            Q(last_seen__lt=unresponsive_cutoff)
            | Q(last_seen__isnull=True, created_at__lt=unresponsive_cutoff)
        ))
        for session in unresponsive:
            TerminalSession.objects.filter(pk=session.pk, status__in=cls.ACTIVE_STATUSES).update(
                status=TerminalSession.STATUS_EXPIRED,
                closed_at=now,
                close_requested=True,
                close_reason='session_unresponsive',
            )
            _notify_instance(session.instance_id, 'session_unresponsive')

        return {
            'revoked_tickets': revoked_tickets,
            'deleted_tickets': deleted_tickets,
            'revoked_sessions': len(stale_sessions),
            'expired_sessions': stranded,
            'stale_connections': len(unresponsive),
        }
