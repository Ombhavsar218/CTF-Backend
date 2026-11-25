"""Pre-accept WebSocket authentication for the terminal gateway."""
from __future__ import annotations

from urllib.parse import urlparse

from asgiref.sync import sync_to_async
from django.conf import settings

from instances.models import ChallengeInstance
from instances.services import InstanceService

from .exceptions import TerminalTicketError, WebSocketAuthError
from .models import TerminalTicket


def _header_value(scope, name: bytes) -> str:
    for key, value in scope.get('headers', []):
        if key.lower() == name:
            if isinstance(value, bytes):
                return value.decode('latin-1').strip()
            return str(value).strip()
    return ''


def _validate_origin(scope) -> str:
    """Require an exact http(s) origin from the configured allowlist."""
    raw = _header_value(scope, b'origin')
    if not raw or raw.lower() == 'null':
        raise WebSocketAuthError('invalid_origin', 4403)

    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    # Browsers send the page origin; tolerate ws(s) only for non-browser clients
    # by mapping it to the documented http(s) equivalent.
    if scheme in ('ws', 'wss'):
        scheme = 'http' if scheme == 'ws' else 'https'
    if (scheme not in ('http', 'https') or not parsed.netloc
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise WebSocketAuthError('invalid_origin', 4403)
    origin = f'{scheme}://{parsed.netloc}'.rstrip('/')

    allowed = {
        str(value).rstrip('/')
        for value in settings.WEBSOCKET_ALLOWED_ORIGINS
        if value and value != '*'
    }
    if not allowed or origin not in allowed:
        raise WebSocketAuthError('invalid_origin', 4403)
    return origin


def _ticket_from_subprotocols(scope) -> str:
    """Read the opaque ticket from ``['flaghunt-terminal-v1', <ticket>]``."""
    protocols = list(scope.get('subprotocols') or [])
    if len(protocols) != 2 or protocols[0] != settings.TERMINAL_SUBPROTOCOL:
        raise WebSocketAuthError('invalid_subprotocol', 4400)
    token = protocols[1]
    if not TerminalTicket.is_well_formed(token):
        raise WebSocketAuthError('invalid_ticket', 4401)
    return token


class TicketAuthMiddleware:
    """Consume a ticket and resolve user/instance before the consumer runs.

    The raw ticket is never placed in ``scope`` for downstream code or logs;
    only the server-side ticket row id is retained.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'websocket':
            await self.inner(scope, receive, send)
            return

        try:
            _validate_origin(scope)
            token = _ticket_from_subprotocols(scope)
            user, instance, ticket = await sync_to_async(self._authenticate)(token)
        except WebSocketAuthError as exc:
            await self._reject(send, exc)
            return
        except TerminalTicketError:
            await self._reject(send, WebSocketAuthError('invalid_ticket', 4401))
            return
        except Exception:
            # Fail closed with a generic reason; never leak database or daemon
            # details into the handshake.
            await self._reject(send, WebSocketAuthError('authentication_failed', 4401))
            return

        scope['terminal_user'] = user
        scope['terminal_instance'] = instance
        scope['terminal_ticket_id'] = ticket.pk
        scope['terminal_subprotocol'] = settings.TERMINAL_SUBPROTOCOL
        await self.inner(scope, receive, send)

    @staticmethod
    def _authenticate(token):
        ticket = TerminalTicket.consume(token)
        user = ticket.user
        instance = ticket.instance
        active = InstanceService().active(user)
        if active is None or active.pk != instance.pk:
            raise WebSocketAuthError('instance_unavailable', 4403)
        if active.status != ChallengeInstance.STATUS_RUNNING or active.is_expired:
            raise WebSocketAuthError('instance_unavailable', 4403)
        if getattr(active.challenge, 'runtime_access_mode', 'http') != 'terminal':
            raise WebSocketAuthError('instance_unavailable', 4403)
        return user, instance, ticket

    @staticmethod
    async def _reject(send, error: WebSocketAuthError):
        # websocket.close before accept is a valid, pre-establishment rejection.
        await send({
            'type': 'websocket.close',
            'code': error.ws_code,
            'reason': error.reason,
        })
