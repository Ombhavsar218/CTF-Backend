"""Fixed runtime policy and request validation."""
from __future__ import annotations

from .errors import ValidationError

ALLOWED_REQUEST_FIELDS = {
    "create": {
        "instance_id", "challenge_id", "user_id", "image", "image_digest",
        "runtime_access_mode", "runtime_internal_port", "runtime_connection_type",
        "runtime_command", "cpu_limit", "memory_mb", "pids_limit", "read_only",
        "expires_at", "request_id",
    },
    "inspect": {"instance_id", "user_id", "request_id"},
    "stop": {"instance_id", "user_id", "request_id"},
    "remove": {"instance_id", "user_id", "request_id", "force"},
    "expire": {"instance_id", "user_id", "request_id"},
    "terminal_open": {"instance_id", "user_id", "shell", "rows", "cols", "expires_at", "request_id"},
    "terminal_write": {"instance_id", "user_id", "exec_id", "data_b64", "request_id"},
    "terminal_read": {"instance_id", "user_id", "exec_id", "max_bytes", "request_id"},
    "terminal_resize": {"instance_id", "user_id", "exec_id", "rows", "cols", "request_id"},
    "terminal_close": {"instance_id", "user_id", "exec_id", "request_id"},
    "terminal_inspect": {"instance_id", "user_id", "exec_id", "request_id"},
    "health": {"request_id"},
}


def reject_unknown_fields(payload: dict, operation: str) -> None:
    allowed = ALLOWED_REQUEST_FIELDS.get(operation)
    if allowed is None:
        raise ValidationError("Unsupported operation")
    if not isinstance(payload, dict):
        raise ValidationError("Invalid request payload")
    unknown = set(payload.keys()) - allowed
    if unknown:
        raise ValidationError("Invalid request fields")


def require_str(payload: dict, key: str, max_len: int = 255) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Invalid {key}")
    value = value.strip()
    if len(value) > max_len:
        raise ValidationError(f"Invalid {key}")
    return value


def require_int(payload: dict, key: str, minimum: int | None = None, maximum: int | None = None) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Invalid {key}")
    if minimum is not None and value < minimum:
        raise ValidationError(f"Invalid {key}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"Invalid {key}")
    return value


def require_bool(payload: dict, key: str, default: bool | None = None) -> bool:
    if key not in payload:
        if default is None:
            raise ValidationError(f"Invalid {key}")
        return default
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValidationError(f"Invalid {key}")
    return value


def validate_image(image: str, digest: str, config) -> str:
    image = (image or "").strip()
    digest = (digest or "").strip()
    if not digest.startswith("sha256:") or len(digest) < 71:
        raise ValidationError("Approved image digest is required")
    if config.allowed_image_digests and digest not in config.allowed_image_digests:
        raise ValidationError("Image digest is not allowed")
    if config.allowed_image_repos:
        repo = image.split("@", 1)[0]
        if repo not in config.allowed_image_repos:
            raise ValidationError("Image repository is not allowed")
    # Prefer immutable digest reference.
    return f"{image.split('@', 1)[0]}@{digest}" if image else digest


def validate_runtime_limits(payload: dict, config) -> dict:
    cpu = payload.get("cpu_limit", config.max_cpu)
    mem = payload.get("memory_mb", config.max_memory_mb)
    pids = payload.get("pids_limit", config.max_pids)
    if isinstance(cpu, bool) or not isinstance(cpu, (int, float)):
        raise ValidationError("Invalid cpu_limit")
    if isinstance(mem, bool) or not isinstance(mem, int):
        raise ValidationError("Invalid memory_mb")
    if isinstance(pids, bool) or not isinstance(pids, int):
        raise ValidationError("Invalid pids_limit")
    cpu = float(cpu)
    if cpu <= 0 or cpu > float(config.max_cpu):
        raise ValidationError("Invalid cpu_limit")
    if mem <= 0 or mem > int(config.max_memory_mb):
        raise ValidationError("Invalid memory_mb")
    if pids <= 0 or pids > int(config.max_pids):
        raise ValidationError("Invalid pids_limit")
    read_only = require_bool(payload, "read_only", default=True)
    if read_only is not True:
        raise ValidationError("Read-only root filesystem is required")
    return {
        "cpu_limit": cpu,
        "memory_mb": mem,
        "pids_limit": pids,
        "read_only": True,
    }
