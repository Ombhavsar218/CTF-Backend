"""Read-only wire shape for the admin audit-log endpoint."""

from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """A closed, read-only representation of one audit row.

    ``actor`` is the stored username snapshot, not a live user relation, so a
    later rename or soft delete cannot rewrite history.
    """

    actor = serializers.CharField(source='actor_username')

    class Meta:
        model = AuditLog
        fields = (
            'id',
            'actor',
            'action',
            'target_type',
            'target_id',
            'target_label',
            'metadata',
            'created_at',
        )
        read_only_fields = fields
