"""Local Docker runtime configuration for challenge instances.

All variables are optional and safe defaults are used for local development.
The SDK detects the active Docker context when no explicit endpoint is set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class RuntimeConfig:
    endpoint: str = ''
    timeout: int = 60
    publish_host: str = '127.0.0.1'
    duration_minutes: int = 60
    stop_timeout: int = 10
    cleanup_timeout: int = 5

    @classmethod
    def from_env(cls) -> 'RuntimeConfig':
        return cls(
            endpoint=os.environ.get('FLAGHUNT_DOCKER_HOST', '').strip(),
            timeout=_int('FLAGHUNT_DOCKER_TIMEOUT', 60),
            publish_host=os.environ.get('FLAGHUNT_PUBLISH_HOST', '127.0.0.1').strip() or '127.0.0.1',
            duration_minutes=_int('FLAGHUNT_INSTANCE_DURATION_MINUTES', 60),
            stop_timeout=_int('FLAGHUNT_CONTAINER_STOP_TIMEOUT', 10),
            cleanup_timeout=_int('FLAGHUNT_CONTAINER_CLEANUP_TIMEOUT', 5),
        )
