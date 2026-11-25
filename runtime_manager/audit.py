"""Minimal audit logging for runtime manager operations."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("runtime_manager.audit")


def configure_audit(path: str = "") -> None:
    _logger.setLevel(logging.INFO)
    _logger.handlers.clear()
    handler: logging.Handler
    if path:
        handler = logging.FileHandler(path, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.propagate = False


def audit(event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    # Never log secrets/tokens.
    for k in list(payload.keys()):
        if any(s in k.lower() for s in ["token", "secret", "authorization", "password"]):
            payload[k] = "[REDACTED]"
    try:
        _logger.info(json.dumps(payload, sort_keys=True, default=str))
    except Exception:
        pass
