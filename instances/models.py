from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ChallengeInstance(models.Model):
    STATUS_REQUESTED = 'requested'
    STATUS_STARTING = 'starting'
    STATUS_RUNNING = 'running'
    STATUS_STOPPING = 'stopping'
    STATUS_STOPPED = 'stopped'
    STATUS_EXPIRED = 'expired'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_REQUESTED, 'Requested'),
        (STATUS_STARTING, 'Starting'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_STOPPING, 'Stopping'),
        (STATUS_STOPPED, 'Stopped'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_FAILED, 'Failed'),
    ]

    TERMINAL_STATUSES = {STATUS_STOPPED, STATUS_EXPIRED, STATUS_FAILED}

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='challenge_instances',
    )
    challenge = models.ForeignKey(
        'challenges.Challenge',
        on_delete=models.CASCADE,
        related_name='instances',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    expires_at = models.DateTimeField()
    stopped_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True, default='')
    # Internal runtime identifiers - never serialized to normal API clients
    internal_name = models.CharField(max_length=255, blank=True, default='')
    internal_container_id = models.CharField(max_length=255, blank=True, default='')
    internal_network_id = models.CharField(max_length=255, blank=True, default='')
    # Safe public connection metadata only (no secrets/daemon details)
    connection_meta = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['challenge', 'status']),
            models.Index(fields=['expires_at']),
        ]
        constraints = [
            # Enforce at most one non-terminal instance per user (DB-level invariant)
            models.UniqueConstraint(
                fields=['user'],
                condition=~Q(status__in=['stopped', 'expired', 'failed']),
                name='unique_active_instance_per_user',
            ),
        ]

    def __str__(self):
        return f'instance {self.pk} user={self.user_id} challenge={self.challenge_id} {self.status}'

    @property
    def is_active(self):
        return self.status not in self.TERMINAL_STATUSES

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return timezone.now() >= self.expires_at
