from rest_framework.throttling import UserRateThrottle


class TerminalTicketThrottle(UserRateThrottle):
    """Per-user rate limit for short-lived terminal ticket issuance."""

    scope = 'terminal_ticket'
