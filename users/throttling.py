"""Throttles for the authentication/account-security API.

Password change is the natural target for a logged-in attacker who has stolen
an access token and wants to lock the real owner out (or to brute-force the
current password from inside an authenticated session). It is limited per
authenticated user. The rate is configured once in
``settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']``.
"""

from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class PasswordChangeThrottle(UserRateThrottle):
    """Rate-limit password changes per authenticated user."""

    scope = 'password_change'


class AuthIPThrottle(SimpleRateThrottle):
    """Rate-limit an authentication endpoint per client IP.

    ``AnonRateThrottle`` skips authenticated requests, which would let a caller
    who sends any valid access token bypass the login/registration/refresh
    limits. These endpoints are public, so the limit must always be keyed by
    the client address instead.

    ``get_ident`` honours ``REST_FRAMEWORK['NUM_PROXIES']``. Keep that at ``0``
    unless Django is behind a trusted reverse proxy that overwrites
    ``X-Forwarded-For``; otherwise the header is client-controlled and would
    let an attacker rotate throttle keys.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class LoginThrottle(AuthIPThrottle):
    """Rate-limit login attempts per client IP."""

    scope = 'login'


class RegisterThrottle(AuthIPThrottle):
    """Rate-limit registration attempts per client IP."""

    scope = 'register'


class TokenRefreshThrottle(AuthIPThrottle):
    """Rate-limit token refresh attempts per client IP."""

    scope = 'token_refresh'
