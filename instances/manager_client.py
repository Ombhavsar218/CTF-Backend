"""Narrow Django client for the dedicated challenge runtime manager.

Django uses this client instead of talking to Docker directly in manager mode.
The client enforces loopback/private URL validation, service authentication,
request timeouts, and bounded error handling.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings


ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_LOOPBACK_PORTS = {8081, 8091, 18081}


@dataclass
class ManagerClientConfig:
    base_url: str = ""
    token: str = field(default="", repr=False)
    signing_key: str = field(default="", repr=False)
    connect_timeout: float = 2.0
    read_timeout: float = 5.0
    enabled: bool = False


def get_manager_config() -> ManagerClientConfig:
    base_url = getattr(settings, "MANAGER_BASE_URL", "") or ""
    token = getattr(settings, "MANAGER_TOKEN", "") or ""
    signing_key = getattr(settings, "MANAGER_SIGNING_KEY", "") or ""
    connect_timeout = float(getattr(settings, "MANAGER_CONNECT_TIMEOUT", 2.0))
    read_timeout = float(
        getattr(settings, "MANAGER_READ_TIMEOUT", getattr(settings, "MANAGER_TOTAL_TIMEOUT", 5.0))
    )
    enabled = bool(base_url and token)
    return ManagerClientConfig(
        base_url=base_url.rstrip("/"),
        token=token,
        signing_key=signing_key,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        enabled=enabled,
    )


class ManagerError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ManagerClient:
    def __init__(self, config: ManagerClientConfig | None = None):
        self.config = config or get_manager_config()

    def _headers(self, body: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, str]:
        body = body or {}
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body_hash = hashlib.sha256(raw).hexdigest()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid.uuid4()),
            "X-Runtime-Body-SHA256": body_hash,
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        signing_key = (self.config.signing_key or "").strip()
        if signing_key:
            ts = str(int(time.time()))
            nonce = uuid.uuid4().hex
            msg = f"{ts}.{nonce}.{body_hash}".encode("utf-8")
            sig = hmac.new(signing_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
            headers["X-Runtime-Timestamp"] = ts
            headers["X-Runtime-Nonce"] = nonce
            headers["X-Runtime-Signature"] = sig
        return headers

    def _validate_base_url(self) -> None:
        if not self.config.enabled or not self.config.base_url:
            raise ManagerError("Manager not configured", status_code=503)

        parsed = urlparse(self.config.base_url)
        if parsed.username or parsed.password:
            raise ManagerError("Manager URL not allowed", status_code=400)
        if parsed.fragment or parsed.query:
            raise ManagerError("Manager URL not allowed", status_code=400)
        if parsed.scheme != "http":
            raise ManagerError("Manager URL not allowed", status_code=400)
        host = parsed.hostname
        if not host or host.lower() not in ALLOWED_LOOPBACK_HOSTS:
            raise ManagerError("Manager URL not allowed", status_code=400)
        if parsed.path and parsed.path != "/":
            raise ManagerError("Manager URL not allowed", status_code=400)
        try:
            port = parsed.port
        except ValueError:
            raise ManagerError("Manager URL not allowed", status_code=400)
        if port is not None and port not in ALLOWED_LOOPBACK_PORTS:
            raise ManagerError("Manager URL not allowed", status_code=400)

    def _request(self, method: str, path: str, json_data: dict[str, Any] | None = None,
                 idempotency_key: str | None = None):
        if not self.config.enabled:
            raise ManagerError("Manager not configured", status_code=503)
        self._validate_base_url()
        url = f"{self.config.base_url}{path}"
        payload = json_data or {}
        headers = self._headers(payload, idempotency_key=idempotency_key)
        timeout = (self.config.connect_timeout, self.config.read_timeout)
        try:
            resp = requests.request(method=method, url=url, headers=headers, json=payload, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ManagerError("Manager request timeout", status_code=504)
        except requests.exceptions.ConnectionError:
            raise ManagerError("Manager connection error", status_code=503)
        except Exception:
            raise ManagerError("Manager request failed", status_code=503)

        if resp.status_code in (401, 403):
            raise ManagerError("Manager unauthorized", status_code=resp.status_code)
        if resp.status_code == 422:
            raise ManagerError("Manager request invalid", status_code=422)
        if resp.status_code == 503:
            raise ManagerError("Runtime manager not available", status_code=503)
        if resp.status_code < 200 or resp.status_code >= 300:
            raise ManagerError("Manager unexpected response", status_code=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise ManagerError("Manager invalid response", status_code=502)

    # Compatibility with old contract-only tests/callers.
    def catalog(self):
        return self._request("GET", "/v1/health", {})

    def health(self):
        return self._request("GET", "/v1/health", {})

    def create_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/instances/create", payload, idempotency_key=str(payload.get("instance_id", "")))

    def inspect_instance(self, instance_id: str, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id)}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("GET", f"/v1/instances/{instance_id}", body)

    def stop_instance(self, instance_id: str, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id)}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/stop", body)

    def remove_instance(self, instance_id: str, user_id: str | None = None, force: bool = True) -> dict[str, Any]:
        body = {"instance_id": str(instance_id), "force": bool(force)}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/remove", body)

    def expire_instance(self, instance_id: str, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id)}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/expire", body)

    def open_terminal(self, instance_id: str, user_id: str, shell: list[str], rows: int, cols: int, expires_at: str | None = None) -> dict[str, Any]:
        body = {
            "instance_id": str(instance_id),
            "user_id": str(user_id),
            "shell": shell,
            "rows": int(rows),
            "cols": int(cols),
        }
        if expires_at:
            body["expires_at"] = expires_at
        return self._request("POST", f"/v1/instances/{instance_id}/terminal/open", body)

    def write_terminal(self, instance_id: str, exec_id: str, data_b64: str, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id), "exec_id": exec_id, "data_b64": data_b64}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/terminal/write", body)

    def read_terminal(self, instance_id: str, exec_id: str, max_bytes: int = 4096, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id), "exec_id": exec_id, "max_bytes": int(max_bytes)}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/terminal/read", body)

    def resize_terminal(self, instance_id: str, exec_id: str, rows: int, cols: int, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id), "exec_id": exec_id, "rows": int(rows), "cols": int(cols)}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/terminal/resize", body)

    def close_terminal(self, instance_id: str, exec_id: str, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id), "exec_id": exec_id}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/terminal/close", body)

    def inspect_terminal(self, instance_id: str, exec_id: str, user_id: str | None = None) -> dict[str, Any]:
        body = {"instance_id": str(instance_id), "exec_id": exec_id}
        if user_id is not None:
            body["user_id"] = str(user_id)
        return self._request("POST", f"/v1/instances/{instance_id}/terminal/inspect", body)

    # Old contract-only methods - keep explicit failures.
    def provision(self, instance_id: int, challenge_id: int, catalog_id: str) -> dict[str, Any]:
        self._validate_base_url()
        raise ManagerError("Manager client not implemented (contract only)", status_code=503)

    def inspect(self, instance_id: int) -> dict[str, Any]:
        self._validate_base_url()
        raise ManagerError("Manager client not implemented (contract only)", status_code=503)

    def stop(self, instance_id: int) -> dict[str, Any]:
        self._validate_base_url()
        raise ManagerError("Manager client not implemented (contract only)", status_code=503)

    def cleanup(self, instance_id: int) -> dict[str, Any]:
        self._validate_base_url()
        raise ManagerError("Manager client not implemented (contract only)", status_code=503)
