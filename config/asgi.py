"""
ASGI config for config project.

HTTP traffic keeps using the standard Django application. The WebSocket
namespace is reserved for the Stage 1D authenticated terminal gateway; no
terminal execution is exposed yet.
"""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

from terminal.routing import websocket_urlpatterns  # noqa: E402

django_asgi_application = get_asgi_application()

application = ProtocolTypeRouter({
    'http': django_asgi_application,
    'websocket': URLRouter(websocket_urlpatterns),
})
