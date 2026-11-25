"""Read helpers for enforced platform settings."""

from .models import PlatformSettings


def get_platform_settings():
    """Return the effective settings, falling back to model defaults."""
    return PlatformSettings.load()
