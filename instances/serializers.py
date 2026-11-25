from django.utils import timezone
from rest_framework import serializers

from .models import ChallengeInstance


class ChallengeInstancePublicSerializer(serializers.ModelSerializer):
    challenge_id = serializers.IntegerField(source='challenge.id', read_only=True)
    challenge_title = serializers.CharField(source='challenge.title', read_only=True)
    remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = ChallengeInstance
        fields = (
            'id',
            'challenge_id',
            'challenge_title',
            'status',
            'expires_at',
            'remaining_seconds',
            'created_at',
            'stopped_at',
            'connection_meta',
            'failure_reason',
        )
        read_only_fields = fields

    def get_remaining_seconds(self, obj):
        if not obj.expires_at:
            return 0
        delta = obj.expires_at - timezone.now()
        return max(0, int(delta.total_seconds()))
