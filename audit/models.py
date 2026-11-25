"""Persistent audit records for successful administrative operations.

The audit trail is deliberately append-only from the application's point of
view: the API exposes a read-only list, and nothing in the codebase updates or
deletes a row. The actor's username is stored as a snapshot so a later rename
(or a soft delete) does not rewrite history; the optional FK is only for
database integrity and convenient filtering.

Only an explicit, sanitised ``metadata`` object is stored. Passwords, flags,
tokens, cookies, status notes and request/network data are never written here
(see ``audit.services``).
"""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """One successful administrative mutation."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    # Snapshot: the actor's username at the time of the action.
    actor_username = models.CharField(max_length=150, blank=True, default='')

    # Stable action vocabulary, e.g. "user.status_change".
    action = models.CharField(max_length=64, db_index=True)
    # Logical target, kept generic so a deleted object can still be described.
    target_type = models.CharField(max_length=32, db_index=True)
    target_id = models.CharField(max_length=64, blank=True, default='')
    target_label = models.CharField(max_length=255, blank=True, default='')

    # Explicit, already-sanitised details (changed field names, old/new status,
    # group names, attachment id). Never raw request data.
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['actor', '-created_at']),
            models.Index(fields=['action', '-created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]
        verbose_name = 'audit log'
        verbose_name_plural = 'audit logs'

    def __str__(self):
        return f'{self.actor_username or "unknown"} {self.action} {self.target_type}:{self.target_id}'
