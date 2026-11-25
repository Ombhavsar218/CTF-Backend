import time
from typing import Dict, Any


class MockAuditSink:
    def __init__(self):
        self.events = []

    def log(self, event_type: str, req: Dict[str, Any] = None, details: Dict[str, Any] = None):
        req = req or {}
        event = {
            "event_type": event_type,
            "timestamp": time.time(),
            "request_id": req.get("request_id"),
            "operation_id": req.get("operation_id"),
            "policy_id": req.get("policy_id"),
            "policy_version": req.get("policy_version"),
            "details": details or {},
        }
        # Never log secrets/tokens
        self.events.append(event)
        return event
