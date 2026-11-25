"""Configuration for the minimal challenge runtime manager.

All secrets/config come from environment variables. No secrets are hardcoded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = _env(name, default)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class ManagerConfig:
    bind_host: str = "127.0.0.1"
    bind_port: int = 8091
    auth_token: str = field(default="", repr=False)
    # Optional HMAC signing key for request freshness/replay protection.
    signing_key: str = field(default="", repr=False)
    request_max_age_seconds: int = 30
    docker_host: str = ""
    docker_timeout: int = 60
    publish_host: str = "127.0.0.1"
    allowed_image_digests: tuple[str, ...] = ()
    allowed_image_repos: tuple[str, ...] = ()
    max_cpu: float = 0.25
    max_memory_mb: int = 128
    max_pids: int = 64
    max_duration_minutes: int = 60
    exec_read_timeout: float = 0.25
    audit_log_path: str = ""

    @classmethod
    def from_env(cls) -> "ManagerConfig":
        return cls(
            bind_host=_env("RUNTIME_MANAGER_BIND_HOST", "127.0.0.1") or "127.0.0.1",
            bind_port=_int("RUNTIME_MANAGER_BIND_PORT", 8091),
            auth_token=_env("RUNTIME_MANAGER_TOKEN"),
            signing_key=_env("RUNTIME_MANAGER_SIGNING_KEY"),
            request_max_age_seconds=max(5, _int("RUNTIME_MANAGER_REQUEST_MAX_AGE_SECONDS", 30)),
            docker_host=_env("FLAGHUNT_DOCKER_HOST"),
            docker_timeout=_int("FLAGHUNT_DOCKER_TIMEOUT", 60),
            publish_host=_env("FLAGHUNT_PUBLISH_HOST", "127.0.0.1") or "127.0.0.1",
            allowed_image_digests=_csv("RUNTIME_MANAGER_ALLOWED_IMAGE_DIGESTS"),
            allowed_image_repos=_csv("RUNTIME_MANAGER_ALLOWED_IMAGE_REPOS"),
            max_cpu=_float("RUNTIME_MANAGER_MAX_CPU", 0.25),
            max_memory_mb=_int("RUNTIME_MANAGER_MAX_MEMORY_MB", 128),
            max_pids=_int("RUNTIME_MANAGER_MAX_PIDS", 64),
            max_duration_minutes=_int("RUNTIME_MANAGER_MAX_DURATION_MINUTES", 60),
            exec_read_timeout=min(2.0, max(0.05, _float("RUNTIME_MANAGER_EXEC_READ_TIMEOUT", 0.25))),
            audit_log_path=_env("RUNTIME_MANAGER_AUDIT_LOG"),
        )
