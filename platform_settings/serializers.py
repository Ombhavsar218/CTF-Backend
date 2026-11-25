from rest_framework import serializers

from .models import PlatformSettings


class PlatformSettingsSerializer(serializers.ModelSerializer):
    """Expose only the explicitly approved runtime settings."""

    class Meta:
        model = PlatformSettings
        fields = (
            'allow_registration',
            'public_leaderboard',
            'allow_hints',
        )

    def to_internal_value(self, data):
        if not hasattr(data, 'keys'):
            raise serializers.ValidationError(
                {'detail': 'Expected a JSON object of platform settings.'}
            )

        unknown = sorted(set(data.keys()) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {field: ['Unknown setting.'] for field in unknown}
            )

        return super().to_internal_value(data)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                {'detail': 'Provide at least one setting to update.'}
            )
        return attrs
