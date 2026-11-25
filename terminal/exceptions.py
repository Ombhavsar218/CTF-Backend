"""Small exception hierarchy shared by the ticket API and WS middleware."""


class TerminalError(Exception):
    """REST-facing terminal gateway error."""

    code = 'TERMINAL_ERROR'
    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class TerminalDisabled(TerminalError):
    code = 'TERMINAL_DISABLED'
    status_code = 404


class TerminalNotAvailable(TerminalError):
    code = 'TERMINAL_NOT_AVAILABLE'


class TerminalRuntimeUnavailable(TerminalError):
    code = 'TERMINAL_RUNTIME_UNAVAILABLE'
    status_code = 503


class TerminalTicketError(TerminalError):
    code = 'TERMINAL_TICKET_ERROR'


class TerminalSessionLimit(TerminalError):
    code = 'TERMINAL_SESSION_LIMIT'
    status_code = 409


class WebSocketAuthError(Exception):
    """Pre-accept WebSocket rejection with a stable, non-secret reason."""

    def __init__(self, reason: str, ws_code: int = 4401):
        self.reason = reason
        self.ws_code = ws_code
        super().__init__(reason)
