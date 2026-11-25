from django.urls import path

from .auth import TicketAuthMiddleware
from .consumers import TerminalGatewayConsumer

websocket_urlpatterns = [
    path(
        'ws/challenges/instances/terminal/',
        TicketAuthMiddleware(TerminalGatewayConsumer.as_asgi()),
        name='terminal-websocket',
    ),
]
