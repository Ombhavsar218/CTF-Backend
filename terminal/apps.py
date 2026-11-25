from django.apps import AppConfig


class TerminalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'terminal'
    verbose_name = 'Terminal gateway'

    def ready(self):
        # Instance status changes close/revoke terminal state. Imported here to
        # avoid importing ORM models while apps are still loading.
        from . import signals  # noqa: F401
