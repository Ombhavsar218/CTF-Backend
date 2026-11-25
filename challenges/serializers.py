"""Serializers for the challenge API.

There are three families:

* ``ChallengePublicSerializer`` - what an ordinary (or anonymous) user sees for
  a *published* challenge. It never contains a flag, a flag hash, a flag note,
  a hint's text, or any draft-only field.
* ``ChallengeAdminSerializer`` - the administrative view. It adds status,
  scheduling, ``has_flag`` and hint text, but still never exposes a flag.
* ``ChallengeWriteSerializer`` - create/update input. It accepts the plaintext
  flag and immediately hands it to ``ChallengeFlag.set_flag`` (which hashes it);
  the plaintext is never persisted or returned.

``CategorySerializer`` is the public read shape. ``CategoryWriteSerializer`` is
the small administrator input shape: the slug is always derived server-side.
"""

import re

from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from .models import (
    Category,
    Challenge,
    ChallengeAttachment,
    ChallengeFlag,
    ChallengeHint,
)
from .mode_content import (
    MODE_COMPETITOR,
    is_mode_aware,
    validate_mode_content,
)

User = get_user_model()

# Challenge authors may supply either the historical CTF{...} prefix or the
# newer FLAG{...} prefix. Both are stored as salted hashes and verified with
# the same case-sensitive, constant-time comparison.
FLAG_PATTERN = re.compile(r'^(?:CTF|FLAG)\{.+\}$')


def human_size(num):
    """Format a byte count the way the frontend's file list expects."""
    num = float(num)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if num < 1024 or unit == 'TB':
            if unit == 'B':
                return f'{int(num)} B'
            return f'{num:.1f} {unit}'
        num /= 1024


class CategorySerializer(serializers.ModelSerializer):
    count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ('id', 'name', 'slug', 'description', 'icon', 'color', 'order', 'count')

    def get_count(self, obj):
        annotated = getattr(obj, 'challenge_count', None)
        if annotated is not None:
            return annotated
        return obj.challenges.filter(status=Challenge.STATUS_PUBLISHED).count()


class CategoryWriteSerializer(serializers.ModelSerializer):
    """Administrator input for a category.

    ``slug`` is intentionally absent: it is derived once from ``name`` by the
    model and remains stable when the display name is later edited. The
    project's public IDs are numeric, so a category's slug is not an address.
    """

    class Meta:
        model = Category
        fields = ('name', 'description', 'icon', 'color', 'order')

    def validate_name(self, value):
        name = (value or '').strip()
        if not name:
            raise serializers.ValidationError('Enter a category name.')

        # The model's unique constraint is case-sensitive on SQLite; enforce the
        # user-facing rule here as well so "Web" and "web" cannot both exist.
        matches = Category.objects.filter(name__iexact=name)
        if self.instance is not None:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise serializers.ValidationError(
                'A category with this name already exists.'
            )
        return name

    def validate_description(self, value):
        return (value or '').strip()

    def validate_icon(self, value):
        return (value or '').strip()

    def validate_color(self, value):
        return (value or '').strip()


class PublicHintSerializer(serializers.ModelSerializer):
    """A hint as seen by players.

    Only metadata (``id``, ``order``, ``cost``) plus an unlock ``revealed`` flag
    is exposed. ``text`` is returned *only* for hints the requesting user has
    already unlocked (the reveal endpoint injects ``revealed_hint_ids``); an
    unrevealed hint always serialises ``text`` as an empty string.
    """

    revealed = serializers.SerializerMethodField()
    text = serializers.SerializerMethodField()

    class Meta:
        model = ChallengeHint
        fields = ('id', 'cost', 'order', 'revealed', 'text')

    def _revealed_ids(self):
        return self.context.get('revealed_hint_ids') or set()

    def get_revealed(self, obj):
        return obj.pk in self._revealed_ids()

    def get_text(self, obj):
        if obj.pk in self._revealed_ids():
            return obj.text
        return ''


class AdminHintSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChallengeHint
        fields = ('id', 'text', 'cost', 'order')


class AttachmentSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = ChallengeAttachment
        fields = ('id', 'name', 'size', 'type', 'url')

    def get_name(self, obj):
        return obj.display_name

    def get_size(self, obj):
        try:
            return human_size(obj.file.size)
        except (OSError, ValueError):
            return ''

    def get_type(self, obj):
        return obj.extension

    def get_url(self, obj):
        # Never expose the storage URL directly: challenge files live under
        # MEDIA_ROOT and must go through the authorization endpoint so draft
        # attachments are not publicly enumerable.
        try:
            url = reverse(
                'challenges_api:attachment-download',
                args=[obj.challenge_id, obj.pk],
            )
        except NoReverseMatch:
            return ''
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class ChallengePublicSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source='category.name', read_only=True)
    category_id = serializers.IntegerField(read_only=True)
    connectionInfo = serializers.JSONField(source='connection_info', read_only=True)
    instanceMode = serializers.CharField(source='runtime_access_mode', read_only=True)
    createdAt = serializers.SerializerMethodField()
    solved = serializers.SerializerMethodField()
    has_mode_content = serializers.SerializerMethodField()
    hints = PublicHintSerializer(many=True, read_only=True)
    files = AttachmentSerializer(source='attachments', many=True, read_only=True)

    class Meta:
        model = Challenge
        fields = (
            'id', 'slug', 'title', 'category', 'category_id', 'difficulty',
            'points', 'description', 'scenario', 'objectives', 'instructions',
            'author', 'tags', 'featured', 'trial', 'solves', 'solved',
            'has_mode_content', 'challenge_mode', 'connectionInfo', 'instanceMode', 'cheatsheet',
            'hints', 'files', 'createdAt', 'status',
        )

    def get_createdAt(self, obj):
        return obj.created_at.date().isoformat() if obj.created_at else None

    def get_solved(self, obj):
        # The list/detail views inject the requesting user's solved challenge
        # ids as ``solved_ids`` to avoid a query per row. When absent (e.g. an
        # anonymous request) fall back to a single check.
        solved_ids = self.context.get('solved_ids')
        if solved_ids is not None:
            return obj.pk in solved_ids
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        from submissions.models import Solve
        return Solve.objects.filter(user=user, challenge_id=obj.pk).exists()

    def get_has_mode_content(self, obj):
        return is_mode_aware(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Mode-aware challenges reserve progressive paid hints for student mode.
        # Competitors (and unauthenticated callers) must not receive hint
        # metadata or text. Existing non-mode-aware challenges are unchanged.
        mode = self.context.get('learning_mode') or MODE_COMPETITOR
        if is_mode_aware(instance) and mode != 'student':
            data['hints'] = []
        # Mode-gated content and solutions are only served by dedicated,
        # permission-checked endpoints.
        data.pop('mode_content', None)
        return data


class ChallengeAdminSerializer(ChallengePublicSerializer):
    hints = AdminHintSerializer(many=True, read_only=True)
    has_flag = serializers.BooleanField(read_only=True)
    flag_note = serializers.SerializerMethodField()
    publishAt = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(read_only=True)
    mode_content = serializers.JSONField(read_only=True)

    class Meta(ChallengePublicSerializer.Meta):
        fields = ChallengePublicSerializer.Meta.fields + (
            'publishAt', 'has_flag', 'flag_note', 'created_by', 'updated_at',
            'mode_content',
        )

    def get_flag_note(self, obj):
        flag = getattr(obj, 'flag', None)
        return flag.note if flag else ''

    def get_publishAt(self, obj):
        return obj.publish_at.strftime('%Y-%m-%dT%H:%M') if obj.publish_at else ''

    def get_created_by(self, obj):
        return obj.created_by.username if obj.created_by else ''

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Admin views may inspect/edit mode-gated content, but never the flag.
        data['mode_content'] = instance.mode_content or {}
        return data


class ChallengeHintWriteSerializer(serializers.Serializer):
    text = serializers.CharField()
    cost = serializers.IntegerField(min_value=0, required=False, default=0)


class ChallengeWriteSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        slug_field='name',
        queryset=Category.objects.all(),
    )
    objectives = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
    )
    tags = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
    )
    connectionInfo = serializers.JSONField(
        source='connection_info',
        required=False,
        allow_null=True,
    )
    # Stage 1C runtime configuration is admin-only. Public/player serializers
    # deliberately omit image, command and internal port details.
    runtime_enabled = serializers.BooleanField(required=False)
    runtime_image = serializers.CharField(max_length=255, required=False, allow_blank=True)
    runtime_command = serializers.CharField(required=False, allow_blank=True)
    runtime_connection_type = serializers.ChoiceField(
        choices=(('http', 'HTTP'), ('https', 'HTTPS'), ('tcp', 'TCP'), ('other', 'Other')),
        required=False,
    )
    runtime_internal_port = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=65535,
    )
    runtime_cpu_limit = serializers.FloatField(required=False, min_value=0.05, max_value=8.0)
    runtime_memory_mb = serializers.IntegerField(required=False, min_value=64, max_value=4096)
    runtime_pids_limit = serializers.IntegerField(required=False, min_value=16, max_value=1024)
    runtime_read_only = serializers.BooleanField(required=False)
    runtime_duration_minutes = serializers.IntegerField(required=False, min_value=0, max_value=1440)
    runtime_access_mode = serializers.ChoiceField(
        choices=(('http', 'HTTP'), ('terminal', 'Terminal')),
        required=False,
    )
    publishAt = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
    )
    flag = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=True,
    )
    flag_note = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        max_length=255,
    )
    hints = ChallengeHintWriteSerializer(many=True, required=False, write_only=True)
    mode_content = serializers.JSONField(required=False)
    challenge_mode = serializers.ChoiceField(
        choices=Challenge.CHALLENGE_MODE_CHOICES,
        required=False,
    )

    class Meta:
        model = Challenge
        fields = (
            'title', 'category', 'difficulty', 'points', 'description',
            'scenario', 'objectives', 'instructions', 'author', 'tags',
            'featured', 'trial', 'connectionInfo', 'cheatsheet', 'status',
            'runtime_enabled', 'runtime_image', 'runtime_command',
            'runtime_connection_type', 'runtime_internal_port',
            'runtime_cpu_limit', 'runtime_memory_mb', 'runtime_pids_limit',
            'runtime_read_only', 'runtime_duration_minutes',
            'runtime_access_mode',
            'publishAt', 'flag', 'flag_note', 'hints', 'mode_content', 'challenge_mode',
        )

    def validate_mode_content(self, value):
        return validate_mode_content(value)

    def validate(self, attrs):
        flag = attrs.get('flag')
        if self.instance is None and not (flag or '').strip():
            raise serializers.ValidationError(
                {'flag': 'A flag is required to create a challenge.'}
            )
        if flag and not FLAG_PATTERN.match(flag.strip()):
            raise serializers.ValidationError(
                {'flag': 'The flag must be of the form CTF{...} or FLAG{...}.'}
            )

        runtime_enabled = attrs.get(
            'runtime_enabled',
            getattr(self.instance, 'runtime_enabled', False),
        )
        runtime_image = attrs.get(
            'runtime_image',
            getattr(self.instance, 'runtime_image', ''),
        )
        runtime_port = attrs.get(
            'runtime_internal_port',
            getattr(self.instance, 'runtime_internal_port', None),
        )
        runtime_mode = attrs.get(
            'runtime_access_mode',
            getattr(self.instance, 'runtime_access_mode', 'http'),
        )
        if runtime_enabled and not (runtime_image or '').strip():
            raise serializers.ValidationError(
                {'runtime_image': 'A Docker image is required when runtime is enabled.'}
            )
        # Terminal-mode containers do not publish a host port. HTTP mode keeps
        # the exact Stage 1C validation, so existing challenges are unaffected.
        if runtime_enabled and runtime_mode == 'http' and not runtime_port:
            raise serializers.ValidationError(
                {'runtime_internal_port': 'An internal port is required when runtime is enabled.'}
            )

        if 'publishAt' in attrs:
            raw = (attrs.pop('publishAt') or '').strip()
            if not raw:
                attrs['publish_at'] = None
            else:
                parsed = parse_datetime(raw)
                if parsed is None:
                    raise serializers.ValidationError(
                        {'publishAt': 'Invalid date/time value.'}
                    )
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(
                        parsed, timezone.get_current_timezone()
                    )
                attrs['publish_at'] = parsed

        status_value = attrs.get(
            'status',
            self.instance.status if self.instance else Challenge.STATUS_DRAFT,
        )
        if 'publish_at' in attrs:
            publish_at = attrs['publish_at']
        elif self.instance is not None:
            publish_at = self.instance.publish_at
        else:
            publish_at = None
        if status_value == Challenge.STATUS_SCHEDULED and publish_at is None:
            raise serializers.ValidationError(
                {'publishAt': 'A publish time is required to schedule a challenge.'}
            )
        return attrs

    def _write_hints(self, challenge, hints):
        challenge.hints.all().delete()
        ChallengeHint.objects.bulk_create([
            ChallengeHint(
                challenge=challenge,
                text=item['text'],
                cost=item.get('cost', 0),
                order=index,
            )
            for index, item in enumerate(hints)
        ])

    def create(self, validated_data):
        flag = (validated_data.pop('flag', '') or '').strip()
        flag_note = validated_data.pop('flag_note', '')
        hints = validated_data.pop('hints', [])
        challenge = Challenge.objects.create(**validated_data)
        if flag:
            stored = ChallengeFlag(challenge=challenge, note=flag_note or '')
            stored.set_flag(flag)
            stored.save()
        self._write_hints(challenge, hints)
        return challenge

    def update(self, instance, validated_data):
        flag = validated_data.pop('flag', None)
        flag_note = validated_data.pop('flag_note', None)
        hints = validated_data.pop('hints', None)

        instance = super().update(instance, validated_data)

        if flag is not None and flag.strip():
            stored, _ = ChallengeFlag.objects.get_or_create(challenge=instance)
            if flag_note is not None:
                stored.note = flag_note
            stored.set_flag(flag)
            stored.save()
        elif flag_note is not None:
            stored = getattr(instance, 'flag', None)
            if stored is not None:
                stored.note = flag_note
                stored.save(update_fields=['note', 'updated_at'])

        if hints is not None:
            self._write_hints(instance, hints)

        return instance

    def to_representation(self, instance):
        return ChallengeAdminSerializer(instance, context=self.context).data
