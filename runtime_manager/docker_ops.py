"""Docker operations for the runtime manager.

This module is the only place in the manager that talks to Docker. It enforces
ownership labels, fixed hardening policy, approved images, and bounded exec.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .errors import ConflictError, ForbiddenError, NotFoundError, UnavailableError, ValidationError

MANAGED_LABEL = "flaghunt.managed"
INSTANCE_LABEL = "flaghunt.instance-id"
CHALLENGE_LABEL = "flaghunt.challenge-id"
USER_LABEL = "flaghunt.user-id"
CREATED_LABEL = "flaghunt.created-at"
MANAGER_LABEL = "flaghunt.runtime-manager"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@dataclass
class ExecHandle:
    exec_id: str
    instance_id: str
    container_id: str
    stream: Any
    expires_at: datetime | None
    created_at: float


class RuntimeDockerOps:
    def __init__(self, config, docker_client=None):
        self.config = config
        self._docker = docker_client
        self._exec_sessions: dict[str, ExecHandle] = {}
        self._exec_lock = threading.Lock()

    @property
    def docker(self):
        if self._docker is None:
            try:
                import docker  # type: ignore
            except Exception as exc:
                raise UnavailableError("Docker SDK unavailable") from exc
            try:
                kwargs: dict[str, Any] = {"timeout": self.config.docker_timeout}
                if self.config.docker_host:
                    kwargs["base_url"] = self.config.docker_host
                self._docker = docker.from_env(**kwargs)
                self._docker.ping()
            except Exception as exc:
                raise UnavailableError("Docker daemon unavailable") from exc
        return self._docker

    def _sdk_errors(self):
        try:
            from docker import errors as sdk_errors  # type: ignore
            return sdk_errors
        except Exception as exc:
            raise UnavailableError("Docker SDK unavailable") from exc

    # ------------------------------------------------------------------
    # Labels and ownership
    # ------------------------------------------------------------------
    def labels_for(self, instance_id: str, challenge_id: str, user_id: str) -> dict[str, str]:
        return {
            MANAGED_LABEL: "true",
            INSTANCE_LABEL: str(instance_id),
            CHALLENGE_LABEL: str(challenge_id),
            USER_LABEL: str(user_id),
            CREATED_LABEL: _now_iso(),
            MANAGER_LABEL: "phase1-minimal",
        }

    def _verify_labels(self, labels: dict[str, Any] | None, instance_id: str, user_id: str | None = None) -> None:
        labels = labels or {}
        if str(labels.get(MANAGED_LABEL, "")).lower() != "true":
            raise ForbiddenError("Ownership verification failed")
        if str(labels.get(INSTANCE_LABEL, "")) != str(instance_id):
            raise ForbiddenError("Ownership verification failed")
        if user_id is not None and str(labels.get(USER_LABEL, "")) != str(user_id):
            raise ForbiddenError("Ownership verification failed")

    def _container_info(self, container) -> dict[str, Any]:
        container.reload()
        attrs = container.attrs or {}
        state = attrs.get("State") or {}
        labels = (attrs.get("Config") or {}).get("Labels") or {}
        ports = (attrs.get("NetworkSettings") or {}).get("Ports") or {}
        networks = sorted(((attrs.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        return {
            "id": container.id,
            "status": container.status,
            "running": bool(state.get("Running")),
            "labels": labels,
            "ports": ports,
            "networks": networks,
        }

    def _find_container_for_instance(self, instance_id: str):
        errors = self._sdk_errors()
        try:
            containers = self.docker.containers.list(
                all=True,
                filters={"label": [f"{MANAGED_LABEL}=true", f"{INSTANCE_LABEL}={instance_id}"]},
            )
        except Exception as exc:
            raise UnavailableError("Docker query failed") from exc
        for c in containers:
            labels = ((c.attrs or {}).get("Config") or {}).get("Labels") or {}
            if str(labels.get(INSTANCE_LABEL)) == str(instance_id):
                return c
        return None

    def _require_container(self, instance_id: str, user_id: str | None = None):
        c = self._find_container_for_instance(instance_id)
        if c is None:
            raise NotFoundError("Instance container not found")
        info = self._container_info(c)
        self._verify_labels(info.get("labels"), instance_id, user_id=user_id)
        return c, info

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        instance_id = str(payload["instance_id"])
        challenge_id = str(payload["challenge_id"])
        user_id = str(payload["user_id"])
        image_ref = payload["image_ref"]
        expires_at = payload.get("expires_at")
        expires_dt = _parse_iso(expires_at) if expires_at else None
        if expires_dt and expires_dt <= datetime.now(timezone.utc):
            raise ValidationError("Instance already expired")

        existing = self._find_container_for_instance(instance_id)
        if existing is not None:
            info = self._container_info(existing)
            self._verify_labels(info.get("labels"), instance_id, user_id=user_id)
            return {"status": info["status"], "container_id": info["id"], "created": False, "info": info}

        labels = self.labels_for(instance_id, challenge_id, user_id)
        name = f"flaghunt-{instance_id}-{uuid.uuid4().hex[:12]}"
        network_name = f"{name}-net"
        network = None
        container = None
        errors = self._sdk_errors()
        try:
            self._ensure_image(image_ref)
            network = self.docker.networks.create(
                name=network_name,
                driver="bridge",
                options={"com.docker.network.bridge.enable_icc": "false"},
                labels=labels,
                check_duplicate=True,
            )
            command = payload.get("runtime_command")
            ports = {}
            internal_port = payload.get("runtime_internal_port")
            if payload.get("runtime_access_mode", "http") != "terminal" and internal_port:
                ports[f"{int(internal_port)}/tcp"] = (self.config.publish_host, None)
            create_kwargs = dict(
                image=image_ref,
                name=name,
                command=command or None,
                detach=True,
                network=getattr(network, "name", network_name),
                ports=ports,
                environment={},
                labels=labels,
                privileged=False,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=max(16, int(payload["pids_limit"])),
                mem_limit=f"{max(64, int(payload['memory_mb']))}m",
                cpu_period=100000,
                cpu_quota=max(1000, int(float(payload["cpu_limit"]) * 100000)),
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m,mode=1777"},
                restart_policy={"Name": "no"},
                auto_remove=False,
                stdin_open=False,
                tty=False,
                user=payload.get("container_user", "1000:1000"),
            )
            # Best-effort explicit seccomp profile if available on host.
            seccomp = payload.get("seccomp_profile")
            if seccomp:
                create_kwargs["security_opt"] = ["no-new-privileges:true", f"seccomp={seccomp}"]
            container = self.docker.containers.run(**create_kwargs)
            info = self._container_info(container)
            return {
                "status": info["status"],
                "container_id": info["id"],
                "network_id": getattr(network, "id", ""),
                "created": True,
                "info": info,
            }
        except Exception as exc:
            try:
                if container is not None:
                    container.remove(force=True)
            except Exception:
                pass
            try:
                if network is not None:
                    network.remove()
            except Exception:
                pass
            if isinstance(exc, (ValidationError, ForbiddenError, NotFoundError, ConflictError, UnavailableError)):
                raise
            raise UnavailableError("Container creation failed") from exc

    def _ensure_image(self, image_ref: str) -> None:
        errors = self._sdk_errors()
        try:
            self.docker.images.get(image_ref)
            return
        except errors.ImageNotFound as exc:
            raise ValidationError("Approved image is not available locally") from exc
        except Exception as exc:
            raise UnavailableError("Image inspection failed") from exc

    def inspect(self, instance_id: str, user_id: str | None = None) -> dict[str, Any]:
        _, info = self._require_container(instance_id, user_id=user_id)
        return info

    def start(self, instance_id: str, user_id: str | None = None) -> dict[str, Any]:
        c, info = self._require_container(instance_id, user_id=user_id)
        if not info.get("running"):
            try:
                c.start()
                c.reload()
                info = self._container_info(c)
            except Exception as exc:
                raise UnavailableError("Container start failed") from exc
        return info

    def stop(self, instance_id: str, user_id: str | None = None, timeout: int = 10) -> dict[str, Any]:
        c, _ = self._require_container(instance_id, user_id=user_id)
        try:
            c.reload()
            if c.status == "running":
                c.stop(timeout=max(1, int(timeout)))
        except Exception:
            try:
                c.kill()
            except Exception:
                pass
        try:
            c.reload()
        except Exception:
            pass
        return {"status": getattr(c, "status", "unknown")}

    def remove(self, instance_id: str, user_id: str | None = None, force: bool = True) -> dict[str, Any]:
        c, info = self._require_container(instance_id, user_id=user_id)
        network_ids = []
        try:
            attrs = c.attrs or {}
            networks = ((attrs.get("NetworkSettings") or {}).get("Networks") or {})
            for n in networks.values():
                nid = n.get("NetworkID")
                if nid:
                    network_ids.append(nid)
        except Exception:
            pass
        try:
            c.remove(force=bool(force))
        except self._sdk_errors().NotFound:
            pass
        except Exception as exc:
            raise UnavailableError("Container removal failed") from exc
        for nid in network_ids:
            try:
                net = self.docker.networks.get(nid)
                net.remove()
            except Exception:
                pass
        return {"removed": True, "container_id": info.get("id")}

    # ------------------------------------------------------------------
    # Terminal exec
    # ------------------------------------------------------------------
    def open_terminal(self, instance_id: str, user_id: str, shell: list[str], rows: int, cols: int,
                      expires_at: str | None) -> dict[str, Any]:
        expires_dt = _parse_iso(expires_at) if expires_at else None
        if expires_dt and expires_dt <= datetime.now(timezone.utc):
            raise ForbiddenError("Instance expired")
        c, info = self._require_container(instance_id, user_id=user_id)
        if not info.get("running"):
            raise ConflictError("Container is not running")
        try:
            api = self.docker.api
            exec_id = api.exec_create(
                c.id,
                cmd=shell,
                tty=True,
                stdin=True,
                stdout=True,
                stderr=True,
                user="1000:1000",
            )["Id"]
            sock = api.exec_start(exec_id, tty=True, stream=True, socket=True, demux=False)
            # docker-py returns a SocketIO/socket wrapper; normalize to raw socket.
            raw = getattr(sock, "_sock", sock)
            raw.settimeout(self.config.exec_read_timeout)
            try:
                api.exec_resize(exec_id, height=int(rows), width=int(cols))
            except Exception:
                pass
        except Exception as exc:
            raise UnavailableError("Terminal exec could not be started") from exc
        with self._exec_lock:
            self._exec_sessions[exec_id] = ExecHandle(
                exec_id=exec_id, instance_id=str(instance_id), container_id=c.id,
                stream=raw, expires_at=expires_dt, created_at=time.time(),
            )
        return {"exec_id": exec_id, "container_id": c.id}

    def _get_exec(self, instance_id: str, exec_id: str, user_id: str | None = None) -> ExecHandle:
        self._require_container(instance_id, user_id=user_id)
        with self._exec_lock:
            handle = self._exec_sessions.get(exec_id)
        if handle is None or str(handle.instance_id) != str(instance_id):
            raise NotFoundError("Terminal session not found")
        if handle.expires_at and handle.expires_at <= datetime.now(timezone.utc):
            self.close_terminal(instance_id, exec_id, user_id=user_id)
            raise ForbiddenError("Instance expired")
        return handle

    def write_terminal(self, instance_id: str, exec_id: str, data_b64: str, user_id: str | None = None) -> dict[str, Any]:
        handle = self._get_exec(instance_id, exec_id, user_id=user_id)
        try:
            data = base64.b64decode(data_b64.encode("ascii"), validate=True)
        except Exception:
            raise ValidationError("Invalid terminal input")
        if not data:
            return {"written": 0}
        try:
            handle.stream.sendall(data)
        except Exception as exc:
            raise UnavailableError("Terminal write failed") from exc
        return {"written": len(data)}

    def read_terminal(self, instance_id: str, exec_id: str, max_bytes: int = 4096, user_id: str | None = None) -> dict[str, Any]:
        handle = self._get_exec(instance_id, exec_id, user_id=user_id)
        max_bytes = max(1, min(int(max_bytes), 16384))
        try:
            chunk = handle.stream.recv(max_bytes)
        except TimeoutError:
            return {"data_b64": "", "eof": False}
        except Exception as exc:
            msg = str(exc).lower()
            if "timed out" in msg or "timeout" in msg:
                return {"data_b64": "", "eof": False}
            raise UnavailableError("Terminal read failed") from exc
        if not chunk:
            return {"data_b64": "", "eof": True}
        return {"data_b64": base64.b64encode(chunk).decode("ascii"), "eof": False}

    def resize_terminal(self, instance_id: str, exec_id: str, rows: int, cols: int, user_id: str | None = None) -> dict[str, Any]:
        self._get_exec(instance_id, exec_id, user_id=user_id)
        try:
            self.docker.api.exec_resize(exec_id, height=int(rows), width=int(cols))
        except Exception as exc:
            raise UnavailableError("Terminal resize failed") from exc
        return {"resized": True}

    def close_terminal(self, instance_id: str, exec_id: str, user_id: str | None = None) -> dict[str, Any]:
        with self._exec_lock:
            handle = self._exec_sessions.pop(exec_id, None)
        if handle is None:
            return {"closed": True}
        try:
            handle.stream.close()
        except Exception:
            pass
        return {"closed": True}

    def inspect_terminal(self, instance_id: str, exec_id: str, user_id: str | None = None) -> dict[str, Any]:
        self._get_exec(instance_id, exec_id, user_id=user_id)
        try:
            info = self.docker.api.exec_inspect(exec_id)
        except Exception as exc:
            raise UnavailableError("Terminal inspect failed") from exc
        return {"running": bool(info.get("Running")), "exit_code": info.get("ExitCode")}
