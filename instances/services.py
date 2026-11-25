"""Application-level instance lifecycle rules.

Docker-specific work lives in ``challenge_runtime``. This module owns
ownership checks, the single-active-instance invariant and API-facing errors.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from challenge_runtime.config import RuntimeConfig
from challenge_runtime.errors import RuntimeErrorBase
from challenge_runtime.service import ChallengeRuntimeService, duration_for

from .models import ChallengeInstance


class InstanceError(Exception):
    code = 'INSTANCE_ERROR'

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InstanceConflict(InstanceError):
    code = 'INSTANCE_CONFLICT'


class InstanceNotEligible(InstanceError):
    code = 'INSTANCE_NOT_ELIGIBLE'


class InstanceRuntimeFailure(InstanceError):
    code = 'INSTANCE_RUNTIME_FAILURE'


class InstanceService:
    def __init__(self, runtime=None, config=None):
        self.config = config or RuntimeConfig.from_env()
        self.runtime = runtime or ChallengeRuntimeService(config=self.config)

    def start(self, user, challenge):
        """Reserve and start an instance. Returns ``(instance, created)``."""
        if challenge.status != 'published':
            raise InstanceNotEligible('Only published challenges can be started.')
        if not challenge.runtime_enabled:
            raise InstanceNotEligible('This challenge does not have a Docker runtime configured.')
        if not (challenge.runtime_image or '').strip():
            raise InstanceNotEligible('This challenge has no runtime image configured.')
        # HTTP challenges keep the Stage 1C port requirement exactly. Terminal
        # challenges intentionally need no published port.
        if (getattr(challenge, 'runtime_access_mode', 'http') == 'http'
                and not challenge.runtime_internal_port):
            raise InstanceNotEligible('This challenge has no runtime port configured.')

        # Retire expired rows first so a fresh start is possible without a
        # background worker having run. Cleanup errors are non-fatal here.
        now = timezone.now()
        expired = list(ChallengeInstance.objects.filter(
            user=user,
            status__in=[
                ChallengeInstance.STATUS_REQUESTED,
                ChallengeInstance.STATUS_STARTING,
                ChallengeInstance.STATUS_RUNNING,
                ChallengeInstance.STATUS_STOPPING,
            ],
            expires_at__lte=now,
        ))
        for stale in expired:
            try:
                self.runtime.expire(stale)
            except Exception:
                ChallengeInstance.objects.filter(pk=stale.pk).update(
                    status=ChallengeInstance.STATUS_EXPIRED,
                    stopped_at=timezone.now(),
                    connection_meta=None,
                )

        try:
            with transaction.atomic():
                active = ChallengeInstance.objects.select_for_update().filter(
                    user=user,
                ).exclude(status__in=ChallengeInstance.TERMINAL_STATUSES).first()
                if active is not None:
                    if active.challenge_id != challenge.pk:
                        raise InstanceConflict(
                            'You already have an active instance for a different challenge.'
                        )
                    # Idempotent retry for the same challenge: report the
                    # existing state rather than creating a second container.
                    return active, False

                instance = ChallengeInstance.objects.create(
                    user=user,
                    challenge=challenge,
                    status=ChallengeInstance.STATUS_REQUESTED,
                    expires_at=timezone.now() + timedelta(
                        minutes=duration_for(challenge, self.config)
                    ),
                    failure_reason='',
                    connection_meta=None,
                )
        except InstanceConflict:
            raise
        except IntegrityError as exc:
            raise InstanceConflict(
                'You already have an active challenge instance.'
            ) from exc

        try:
            instance = self.runtime.start(instance, challenge)
        except RuntimeErrorBase as exc:
            self._mark_start_failed(instance.pk, exc.message)
            raise InstanceRuntimeFailure(exc.message) from exc
        except Exception as exc:
            message = str(exc)[:255] or exc.__class__.__name__
            self._mark_start_failed(instance.pk, message)
            raise InstanceRuntimeFailure(message) from exc
        return instance, True

    @staticmethod
    def _mark_start_failed(instance_id, message):
        """Fail closed so a failed start never blocks the next attempt."""
        ChallengeInstance.objects.filter(pk=instance_id).update(
            status=ChallengeInstance.STATUS_FAILED,
            stopped_at=timezone.now(),
            connection_meta=None,
            failure_reason=(message or 'Runtime start failed')[:255],
        )

    def stop(self, user):
        """Stop the caller's own active instance, if any."""
        instance = ChallengeInstance.objects.filter(user=user).exclude(
            status__in=ChallengeInstance.TERMINAL_STATUSES
        ).select_related('challenge').order_by('-created_at').first()
        if instance is None:
            return None
        try:
            return self.runtime.stop(instance)
        except RuntimeErrorBase as exc:
            raise InstanceRuntimeFailure(exc.message) from exc

    def active(self, user):
        instance = ChallengeInstance.objects.filter(user=user).exclude(
            status__in=ChallengeInstance.TERMINAL_STATUSES
        ).select_related('challenge').order_by('-created_at').first()
        if instance is None:
            return None
        if instance.is_expired:
            try:
                self.runtime.expire(instance)
            except Exception:
                ChallengeInstance.objects.filter(pk=instance.pk).update(
                    status=ChallengeInstance.STATUS_EXPIRED,
                    stopped_at=timezone.now(),
                    connection_meta=None,
                )
            return None
        return instance

    def cleanup(self):
        self.runtime.reconcile()
