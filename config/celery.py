"""The Celery application for this Django project.

Only Redis, the Celery worker and Celery Beat run in Docker (see the
``docker-compose.yml`` at the repository root); Django itself keeps running on
the host against SQLite.

Nothing here opens a network connection: building the app object is pure
configuration, and both broker connections and task-module imports are lazy.
That is what keeps ordinary management commands working when Redis is down
(``manage.py check``, ``makemigrations``, ``test`` and so on never touch the
broker).

Settings come from Django with the ``CELERY_`` prefix, so ``CELERY_BROKER_URL``
in ``config/settings.py`` becomes ``app.conf.broker_url`` here.
"""

import os

from celery import Celery

# Allow ``celery -A config ...`` to run without manage.py.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Read every ``CELERY_*`` Django setting. Reading settings does not connect.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Discover ``tasks.py`` in every installed app (currently ``ops.tasks``).
# Discovery is lazy: the modules are imported when the worker/beat finalises,
# not when ``manage.py`` imports this module.
app.autodiscover_tasks()
