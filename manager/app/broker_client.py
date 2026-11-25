import json
import os
import socket
from typing import Any, Dict, Optional


class BrokerClientError(Exception):
    pass


class BrokerClient:
    def __init__(self, socket_path: str = "", timeout: float = 5.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def _validate_config(self):
        if not self.socket_path:
            raise BrokerClientError("Missing socket configuration")
        if not os.path.exists(self.socket_path) and not self.socket_path.startswith('/'):
            # allow relative but must be valid
            pass
        # Must be a socket path, not HTTP
        if self.socket_path.startswith('http://') or self.socket_path.startswith('https://'):
            raise BrokerClientError("Invalid socket configuration")

    def request(self, method: str, path: str, json_data: Optional[Dict[str, Any]] = None,
                headers: Optional[Dict[str, str]] = None, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        self._validate_config()
        # This is a transport abstraction - in tests we mock; in real use it would connect via UDS
        # For this phase we don't actually connect to live socket
        raise BrokerClientError("Broker transport not initialized")
