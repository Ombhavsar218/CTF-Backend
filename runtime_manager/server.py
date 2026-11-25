"""Minimal authenticated HTTP runtime manager.

This is a narrow control plane for Django. It does not expose arbitrary Docker
operations. All requests are authenticated, validated, and ownership-checked.
"""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .audit import audit, configure_audit
from .auth import authenticate
from .config import ManagerConfig
from .docker_ops import RuntimeDockerOps
from .errors import AuthError, ManagerError, ValidationError
from .policy import (
    reject_unknown_fields,
    require_bool,
    require_int,
    require_str,
    validate_image,
    validate_runtime_limits,
)


class RuntimeManagerApp:
    def __init__(self, config: ManagerConfig | None = None, ops: RuntimeDockerOps | None = None):
        self.config = config or ManagerConfig.from_env()
        self.ops = ops or RuntimeDockerOps(self.config)
        configure_audit(self.config.audit_log_path)

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict]:
        request_id = headers.get("x-request-id", "")
        try:
            authenticate(headers, self.config)
        except ManagerError as exc:
            audit("auth.failed", request_id=request_id, path=path, code=exc.code)
            return exc.status, {"error": exc.code, "message": "Authentication failed"}

        try:
            payload = self._parse_body(body)
            if request_id and "request_id" not in payload:
                payload["request_id"] = request_id
            status, data = self._route(method, path, payload)
            audit("request.ok", request_id=payload.get("request_id", request_id), path=path, method=method)
            return status, data
        except ManagerError as exc:
            audit("request.error", request_id=request_id, path=path, method=method, code=exc.code)
            return exc.status, {"error": exc.code, "message": exc.message}
        except Exception:
            audit("request.error", request_id=request_id, path=path, method=method, code="INTERNAL_ERROR")
            return 500, {"error": "MANAGER_ERROR", "message": "Internal error"}

    def _parse_body(self, body: bytes) -> dict:
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ValidationError("Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValidationError("Invalid request payload")
        return payload

    def _route(self, method: str, path: str, payload: dict) -> tuple[int, dict]:
        parts = [p for p in urlparse(path).path.split("/") if p]
        if method == "GET" and parts == ["v1", "health"]:
            reject_unknown_fields(payload, "health")
            return 200, {"status": "ok"}
        if parts[:2] != ["v1", "instances"]:
            raise ValidationError("Unsupported endpoint")

        if method == "POST" and parts == ["v1", "instances", "create"]:
            return 200, self._create(payload)
        if len(parts) < 3:
            raise ValidationError("Unsupported endpoint")
        instance_id = parts[2]
        if "instance_id" in payload and str(payload["instance_id"]) != str(instance_id):
            raise ValidationError("Instance ID mismatch")
        payload.setdefault("instance_id", instance_id)

        if method == "GET" and len(parts) == 3:
            reject_unknown_fields(payload, "inspect")
            info = self.ops.inspect(str(instance_id), user_id=payload.get("user_id"))
            return 200, {"instance_id": str(instance_id), "info": info}
        if method == "POST" and len(parts) == 4 and parts[3] in {"stop", "remove", "expire"}:
            op = parts[3]
            reject_unknown_fields(payload, op)
            if op == "stop":
                result = self.ops.stop(str(instance_id), user_id=payload.get("user_id"))
            elif op == "remove":
                force = require_bool(payload, "force", default=True)
                result = self.ops.remove(str(instance_id), user_id=payload.get("user_id"), force=force)
            else:
                # Expire = stop + remove; idempotent.
                try:
                    self.ops.stop(str(instance_id), user_id=payload.get("user_id"))
                except Exception:
                    pass
                result = self.ops.remove(str(instance_id), user_id=payload.get("user_id"), force=True)
            return 200, {"instance_id": str(instance_id), **result}
        if method == "POST" and len(parts) == 5 and parts[3] == "terminal":
            return 200, self._terminal(parts[4], payload)
        raise ValidationError("Unsupported endpoint")

    def _create(self, payload: dict) -> dict:
        reject_unknown_fields(payload, "create")
        instance_id = require_str(payload, "instance_id", 64)
        challenge_id = require_str(payload, "challenge_id", 64)
        user_id = require_str(payload, "user_id", 64)
        image = require_str(payload, "image", 512)
        digest = require_str(payload, "image_digest", 128)
        image_ref = validate_image(image, digest, self.config)
        limits = validate_runtime_limits(payload, self.config)
        mode = payload.get("runtime_access_mode", "http")
        if mode not in {"http", "terminal"}:
            raise ValidationError("Invalid runtime_access_mode")
        internal_port = payload.get("runtime_internal_port")
        if mode == "http":
            internal_port = require_int(payload, "runtime_internal_port", 1, 65535)
        elif internal_port is not None:
            internal_port = require_int(payload, "runtime_internal_port", 1, 65535)
        command = payload.get("runtime_command")
        if command is not None and not isinstance(command, (str, list)):
            raise ValidationError("Invalid runtime_command")
        if isinstance(command, list) and not all(isinstance(x, str) and x for x in command):
            raise ValidationError("Invalid runtime_command")
        req = {
            "instance_id": instance_id,
            "challenge_id": challenge_id,
            "user_id": user_id,
            "image_ref": image_ref,
            "runtime_access_mode": mode,
            "runtime_internal_port": internal_port,
            "runtime_command": command,
            "expires_at": payload.get("expires_at"),
            "container_user": "1000:1000",
            **limits,
        }
        result = self.ops.create(req)
        return {"instance_id": instance_id, **result}

    def _terminal(self, action: str, payload: dict) -> dict:
        instance_id = str(payload.get("instance_id"))
        user_id = payload.get("user_id")
        if action == "open":
            reject_unknown_fields(payload, "terminal_open")
            require_str(payload, "user_id", 64)
            shell = payload.get("shell")
            if not isinstance(shell, list) or not shell or not all(isinstance(s, str) and s for s in shell):
                raise ValidationError("Invalid shell")
            rows = require_int(payload, "rows", 1, 500)
            cols = require_int(payload, "cols", 1, 500)
            return self.ops.open_terminal(instance_id, str(user_id), shell, rows, cols, payload.get("expires_at"))
        if action == "write":
            reject_unknown_fields(payload, "terminal_write")
            exec_id = require_str(payload, "exec_id", 128)
            data_b64 = require_str(payload, "data_b64", 200000)
            return self.ops.write_terminal(instance_id, exec_id, data_b64, user_id=user_id)
        if action == "read":
            reject_unknown_fields(payload, "terminal_read")
            exec_id = require_str(payload, "exec_id", 128)
            max_bytes = require_int(payload, "max_bytes", 1, 16384) if "max_bytes" in payload else 4096
            return self.ops.read_terminal(instance_id, exec_id, max_bytes=max_bytes, user_id=user_id)
        if action == "resize":
            reject_unknown_fields(payload, "terminal_resize")
            exec_id = require_str(payload, "exec_id", 128)
            rows = require_int(payload, "rows", 1, 500)
            cols = require_int(payload, "cols", 1, 500)
            return self.ops.resize_terminal(instance_id, exec_id, rows, cols, user_id=user_id)
        if action == "close":
            reject_unknown_fields(payload, "terminal_close")
            exec_id = require_str(payload, "exec_id", 128)
            return self.ops.close_terminal(instance_id, exec_id, user_id=user_id)
        if action == "inspect":
            reject_unknown_fields(payload, "terminal_inspect")
            exec_id = require_str(payload, "exec_id", 128)
            return self.ops.inspect_terminal(instance_id, exec_id, user_id=user_id)
        raise ValidationError("Unsupported terminal operation")


def make_handler(app: RuntimeManagerApp):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, data: dict):
            raw = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self):
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, data = app.handle(self.command, self.path, headers, body)
            self._send(status, data)

        def do_GET(self):  # noqa: N802
            self._handle()

        def do_POST(self):  # noqa: N802
            self._handle()

        def log_message(self, fmt, *args):  # quiet default logging
            return

    return Handler


def serve(config: ManagerConfig | None = None) -> None:
    config = config or ManagerConfig.from_env()
    app = RuntimeManagerApp(config=config)
    server = ThreadingHTTPServer((config.bind_host, config.bind_port), make_handler(app))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
