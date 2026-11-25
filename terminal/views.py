from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import (
    TerminalDisabled,
    TerminalError,
    TerminalRuntimeUnavailable,
    TerminalSessionLimit,
)
from .services import TicketIssuer
from .throttling import TerminalTicketThrottle

WS_TERMINAL_PATH = '/ws/challenges/instances/terminal/'


def _websocket_url(request) -> str:
    scheme = 'wss' if request.is_secure() else 'ws'
    return f'{scheme}://{request.get_host()}{WS_TERMINAL_PATH}'


class TerminalTicketView(APIView):
    """Issue a opaque, short-lived ticket for the authenticated user's instance."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [TerminalTicketThrottle]
    throttle_scope = 'terminal_ticket'

    def post(self, request):
        try:
            token, ticket = TicketIssuer().issue(request.user)
        except TerminalDisabled as exc:
            return Response(
                {'detail': exc.message, 'code': exc.code},
                status=status.HTTP_404_NOT_FOUND,
            )
        except TerminalRuntimeUnavailable as exc:
            return Response(
                {'detail': exc.message, 'code': exc.code},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except TerminalSessionLimit as exc:
            return Response(
                {'detail': exc.message, 'code': exc.code},
                status=status.HTTP_409_CONFLICT,
            )
        except TerminalError as exc:
            return Response(
                {'detail': exc.message, 'code': exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # No instance id, container id or exec id is included. The WS ticket
        # resolves every resource server-side.
        return Response(
            {
                'ticket': token,
                'url': _websocket_url(request),
                'subprotocol': settings.TERMINAL_SUBPROTOCOL,
                'expiresIn': settings.TERMINAL_TICKET_TTL_SECONDS,
            },
            status=status.HTTP_201_CREATED,
        )
