"""Database-backed platform settings.

Only settings with an implemented application effect belong in this model.
Deployment configuration (hosts, CORS, credentials, mail transport) stays in
the environment; this model must never become a store for secrets or arbitrary
Django configuration.

The row is a singleton. Callers use :meth:`PlatformSettings.load`, which returns
the stored row when present and an unsaved default instance otherwise, so a
fresh database needs no seed migration.
"""

from django.db import models


class PlatformSettings(models.Model):
    """The small set of settings administrators can change at runtime."""

    allow_registration = models.BooleanField(default=True)
    public_leaderboard = models.BooleanField(default=True)
    allow_hints = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'platform settings'
        verbose_name_plural = 'platform settings'

    def save(self, *args, **kwargs):
        # Enforce the singleton at the model boundary as well as in the view.
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the stored settings, or an unsaved instance with defaults."""
        return cls.objects.filter(pk=1).first() or cls(pk=1)
