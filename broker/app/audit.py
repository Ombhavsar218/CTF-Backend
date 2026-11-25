import json
import logging
from datetime import datetime
from typing import Any, Dict


logger = logging.getLogger("broker.audit")


class AuditLogger:
    def __init__(self):
        self.enabled = True

    def log(self, event_type: str, details: Dict[str, Any] | None = None, request_id: str | None = None) -> None:
        if not self.enabled:
            return
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "request_id": request_id,
        }
        if details:
            # Never log secrets/tokens/env
            sanitized = {}
            for k, v in details.items():
                kl = str(k).lower()
                if any(x in kl for x in ['token', 'secret', 'password', 'key', 'env', 'authorization']):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = v
            event["details"] = sanitized
        try:
            logger.info(json.dumps(event))
        except Exception:
            logger.info(f"audit.{event_type}")


audit_logger = AuditLogger()
