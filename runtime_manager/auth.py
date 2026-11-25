"""Service authentication for the runtime manager.

Uses a shared bearer token from environment configuration. Optionally verifies
an HMAC signature and timestamp for request freshness/replay protection.
Secrets are never logged or returned in errors.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from .errors import AuthError


def _safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def authenticate(headers: dict[str, str], config) -> None:
    token = (config.auth_token or "").strip()
    if not token:
        # Fail closed: an unconfigured manager must not accept requests.
        raise AuthError("Manager authentication is not configured")

    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthError("Authentication required")
    provided = auth[len("Bearer "):].strip()
    if not provided or not _safe_eq(provided, token):
        raise AuthError("Authentication failed")

    signing_key = (config.signing_key or "").strip()
    if not signing_key:
        return

    ts_raw = headers.get("x-runtime-timestamp", "")
    sig = headers.get("x-runtime-signature", "")
    nonce = headers.get("x-runtime-nonce", "")
    body_hash = headers.get("x-runtime-body-sha256", "")
    if not ts_raw or not sig or not nonce or not body_hash:
        raise AuthError("Authentication failed")
    try:
        ts = int(ts_raw)
    except (TypeError, ValueError):
        raise AuthError("Authentication failed")
    now = int(time.time())
    if abs(now - ts) > max(5, int(config.request_max_age_seconds)):
        raise AuthError("Authentication failed")

    message = f"{ts}.{nonce}.{body_hash}".encode("utf-8")
    expected = hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not _safe_eq(expected, sig):
        raise AuthError("Authentication failed")
