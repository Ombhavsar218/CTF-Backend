"""Challenge domain models.

The module is the write side of the platform: categories, challenges, their
flags, hints and downloadable attachments. Submitted flags / submissions /
leaderboards are deliberately *not* modelled here - they are a later stage.

Security notes:

* A challenge flag is never stored in plaintext. ``ChallengeFlag`` holds a
  Django password hash (PBKDF2-SHA256, salted) produced by ``make_password``
  and verified with ``check_password`` (constant-time). The plaintext is not
  recoverable, so an admin can set or replace a flag but can never read it back.
* ``ChallengeFlag`` and the hash are never serialized by any API. Only a
  boolean ``has_flag`` is exposed to administrators.
"""

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import slugify


def unique_slug(model, value, instance_pk=None, queryset=None):
    """Return a slug for ``value`` that is unique within ``model``.

    The frontend addresses challenges by numeric id, so slugs are only a
    human-friendly extra. They are still kept unique to avoid surprising
    collisions if they are ever used in a URL.

    ``queryset`` lets a caller widen the clash check beyond the model's default
    manager (e.g. ``Achievement.all_objects`` so soft-deleted rows, which still
    occupy their slug in the database, are taken into account).
    """
    base = slugify(value) or 'item'
    slug = base
    if queryset is None:
        queryset = model.objects.all()
    if instance_pk is not None:
        queryset = queryset.exclude(pk=instance_pk)
    suffix = 2
    while queryset.filter(slug=slug).exists():
        slug = f'{base}-{suffix}'
        suffix += 1
    return slug


class Category(models.Model):
    """A challenge category (Web Exploitation, Cryptography, ...).

    Seeded from the frontend's existing category definitions. Public reads are
    open; administrators create/update/delete through the admin API. Deletion is
    blocked while any challenge or achievement rule still references the row.
    """

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    icon = models.CharField(max_length=60, blank=True, default='')
    color = models.CharField(max_length=20, blank=True, default='')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self.pk)
        super().save(*args, **kwargs)


class ChallengeQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Challenge.STATUS_PUBLISHED)


class Challenge(models.Model):
    """A single CTF challenge."""

    DIFFICULTY_EASY = 'Easy'
    DIFFICULTY_MEDIUM = 'Medium'
    DIFFICULTY_HARD = 'Hard'
    DIFFICULTY_INSANE = 'Insane'
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY, 'Easy'),
        (DIFFICULTY_MEDIUM, 'Medium'),
        (DIFFICULTY_HARD, 'Hard'),
        (DIFFICULTY_INSANE, 'Insane'),
    ]

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_SCHEDULED = 'scheduled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_SCHEDULED, 'Scheduled'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    scenario = models.TextField(blank=True, default='')
    objectives = models.JSONField(default=list, blank=True)
    instructions = models.TextField(blank=True, default='')

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='challenges',
    )
    difficulty = models.CharField(
        max_length=10,
        choices=DIFFICULTY_CHOICES,
        default=DIFFICULTY_EASY,
    )
    points = models.PositiveIntegerField(default=100)
    author = models.CharField(max_length=120, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_challenges',
    )
    tags = models.JSONField(default=list, blank=True)

    featured = models.BooleanField(default=False)
    trial = models.BooleanField(default=False)

    # Denormalised solve counter. There is no Submission model yet, so this is
    # seeded / adjusted administratively rather than derived.
    solves = models.PositiveIntegerField(default=0)

    # Descriptive connection details shown to players on static challenges.
    # Real instance connection details are returned per instance instead.
    connection_info = models.JSONField(null=True, blank=True)

    # Stage 1C: optional local Docker runtime configuration. A challenge is
    # only startable when runtime_enabled, runtime_image and (for published
    # ports) runtime_internal_port are configured by an administrator.
    runtime_enabled = models.BooleanField(default=False)
    runtime_image = models.CharField(max_length=255, blank=True, default='')
    runtime_command = models.TextField(blank=True, default='')
    runtime_connection_type = models.CharField(
        max_length=8,
        choices=(
            ('http', 'HTTP'),
            ('https', 'HTTPS'),
            ('tcp', 'TCP'),
            ('other', 'Other'),
        ),
        default='http',
    )
    runtime_internal_port = models.PositiveIntegerField(null=True, blank=True)
    runtime_cpu_limit = models.FloatField(default=0.5)
    runtime_memory_mb = models.PositiveIntegerField(default=256)
    runtime_pids_limit = models.PositiveIntegerField(default=64)
    runtime_read_only = models.BooleanField(default=True)
    runtime_duration_minutes = models.PositiveIntegerField(default=0)
    # Stage 1D: access mode. Existing challenges keep the Stage 1C HTTP flow.
    runtime_access_mode = models.CharField(
        max_length=10,
        choices=(('http', 'HTTP'), ('terminal', 'Terminal')),
        default='http',
    )

    # The public "cheatsheet" tab: a list of {command, description, category}.
    cheatsheet = models.JSONField(default=list, blank=True)

    # Optional, mode-gated challenge content (student/competitor/solution).
    # This is never returned through ordinary public challenge serializers.
    # Existing challenges default to an empty object for backwards
    # compatibility.
    mode_content = models.JSONField(default=dict, blank=True)

    # Which learning mode this challenge is intended for. 'both' keeps the
    # challenge visible to student and competitor users (backward-compatible
    # default for existing challenges).
    MODE_STUDENT = 'student'
    MODE_COMPETITOR = 'competitor'
    MODE_BOTH = 'both'
    CHALLENGE_MODE_CHOICES = [
        (MODE_STUDENT, 'Student'),
        (MODE_COMPETITOR, 'Competitor'),
        (MODE_BOTH, 'Both'),
    ]
    challenge_mode = models.CharField(
        max_length=16,
        choices=CHALLENGE_MODE_CHOICES,
        default=MODE_BOTH,
    )

    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    publish_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ChallengeQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['difficulty']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Challenge, self.title or 'challenge', self.pk)
        super().save(*args, **kwargs)

    @property
    def has_flag(self):
        return hasattr(self, 'flag') and bool(self.flag.hash)

    def verify_flag(self, raw):
        """Verify a submitted flag against this challenge's stored hash.

        Returns ``False`` when the challenge has no flag. Intended to be reused
        by the submissions stage.
        """
        stored = getattr(self, 'flag', None)
        return bool(stored) and stored.verify(raw)

    @property
    def has_mode_content(self):
        """True when the challenge carries non-empty mode-gated content."""
        content = self.mode_content
        return isinstance(content, dict) and bool(content)


class ChallengeFlag(models.Model):
    """The (hashed) flag for a challenge.

    ``hash`` is written through ``set_flag`` and checked through ``check``. The
    plaintext value is never stored, so it can never be serialized or logged.
    """

    challenge = models.OneToOneField(
        Challenge,
        on_delete=models.CASCADE,
        related_name='flag',
    )
    hash = models.CharField(max_length=255)
    note = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'flag for {self.challenge_id}'

    @staticmethod
    def normalize(raw):
        """Normalise a submitted flag without altering its meaning.

        Surrounding whitespace/newlines are stripped; the case is preserved
        because flag matching is case-sensitive.
        """
        return str(raw).strip()

    def set_flag(self, raw):
        """Hash and store ``raw``. The plaintext is deliberately discarded."""
        self.hash = make_password(self.normalize(raw))

    def verify(self, raw):
        """Constant-time verification of a submitted flag."""
        if not self.hash:
            return False
        return check_password(self.normalize(raw), self.hash)


class ChallengeHint(models.Model):
    """An ordered hint attached to a challenge.

    Hint text is withheld from public responses (only ``id`` and ``cost`` are
    exposed) and is returned solely to administrators/creators. Revealing a
    hint to a player (and deducting points) belongs to the submissions stage.
    """

    challenge = models.ForeignKey(
        Challenge,
        on_delete=models.CASCADE,
        related_name='hints',
    )
    text = models.TextField()
    cost = models.PositiveIntegerField(default=0)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'hint {self.pk} for {self.challenge_id}'


class ChallengeAttachment(models.Model):
    """A downloadable file attached to a challenge."""

    challenge = models.ForeignKey(
        Challenge,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    file = models.FileField(upload_to='challenge_files/')
    name = models.CharField(max_length=255, blank=True, default='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.name or self.file.name.rsplit('/', 1)[-1]

    @property
    def extension(self):
        name = self.display_name
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


@receiver(post_delete, sender=ChallengeAttachment)
def _delete_attachment_file(sender, instance, **kwargs):
    """Remove the underlying file when an attachment row is deleted.

    A signal is used (instead of overriding ``delete``) so the file is also
    cleaned up when the parent challenge is removed via cascade, a path where
    Django does not call individual ``delete()`` methods.
    """
    if instance.file:
        instance.file.delete(save=False)
