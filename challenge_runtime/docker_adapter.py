"""Thin Docker SDK adapter used only by the challenge-instance runtime.

Views, serializers and the firewall-controller architecture never import this
module. All daemon access is lazy so Django checks and tests work without a
running Docker Engine.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Optional

from .config import RuntimeConfig
from .errors import (
    ContainerCleanupFailed,
    ContainerInspectionFailed,
    ContainerLaunchFailed,
    DockerUnavailable,
    ExecSessionError,
    ImageUnavailable,
)
from .exec_session import ExecSession


class DockerAdapter:
    """Small, explicit wrapper around the Docker SDK operations we need."""

    LABEL_MANAGED = 'flaghunt.managed=true'

    def __init__(self, client=None, config: Optional[RuntimeConfig] = None):
        self._client = client
        self._config = config or RuntimeConfig.from_env()

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def client(self):
        if self._client is None:
            try:
                import docker  # local import: no daemon access at module import
            except Exception as exc:
                raise DockerUnavailable('Docker SDK is not installed') from exc
            try:
                kwargs: Dict[str, Any] = {'timeout': self._config.timeout}
                if self._config.endpoint:
                    # Setting DOCKER_HOST lets the SDK honour the configured
                    # named-pipe/TCP endpoint without changing global settings.
                    os.environ.setdefault('DOCKER_HOST', self._config.endpoint)
                    kwargs['base_url'] = self._config.endpoint
                self._client = docker.from_env(**kwargs)
                self._client.ping()
            except Exception as exc:
                raise DockerUnavailable('Docker daemon is unavailable') from exc
        return self._client

    def _sdk_errors(self):
        try:
            from docker import errors as sdk_errors
        except Exception as exc:  # pragma: no cover - SDK is installed in venv
            raise DockerUnavailable('Docker SDK is not installed') from exc
        return sdk_errors

    def ensure_image(self, image: str) -> None:
        """Resolve the configured image locally, pulling it when necessary."""
        errors = self._sdk_errors()
        try:
            self.client.images.get(image)
            return
        except errors.ImageNotFound:
            pass
        except Exception as exc:
            raise ImageUnavailable('Could not query Docker images') from exc
        try:
            self.client.images.pull(image)
            self.client.images.get(image)
        except Exception as exc:
            raise ImageUnavailable(f'Docker image is unavailable: {image}') from exc

    def create_network(self, name: str, labels: Optional[Dict[str, str]] = None):
        errors = self._sdk_errors()
        try:
            return self.client.networks.create(
                name=name,
                driver='bridge',
                # Disable inter-container communication on this per-instance
                # bridge while retaining loopback port publication.
                options={'com.docker.network.bridge.enable_icc': 'false'},
                labels=labels or {},
                check_duplicate=True,
            )
        except Exception as exc:
            # A duplicate is safe only if it is our own labelled network.
            try:
                existing = self.client.networks.get(name)
            except Exception:
                existing = None
            if existing is not None and self._is_managed_labels(getattr(existing, 'attrs', {}).get('Labels') or {}):
                return existing
            raise ContainerLaunchFailed('Could not create isolated challenge network') from exc

    @staticmethod
    def _is_managed_labels(labels: Dict[str, str]) -> bool:
        return str(labels.get('flaghunt.managed', '')).lower() == 'true'

    def create_container(self, *, image: str, name: str, network_name: str,
                         command, internal_port: Optional[int], labels: Dict[str, str],
                         environment: Optional[Dict[str, str]] = None,
                         cpu_limit: float = 0.5, memory_mb: int = 256,
                         pids_limit: int = 64, read_only: bool = True):
        errors = self._sdk_errors()
        ports = {}
        if internal_port:
            ports[f'{int(internal_port)}/tcp'] = (self._config.publish_host, None)
        cpu = max(float(cpu_limit or 0.5), 0.05)
        try:
            return self.client.containers.run(
                image=image,
                name=name,
                command=command or None,
                detach=True,
                network=network_name,
                ports=ports,
                environment=environment or {},
                labels=labels,
                privileged=False,
                cap_drop=['ALL'],
                security_opt=['no-new-privileges:true'],
                pids_limit=max(int(pids_limit or 64), 16),
                mem_limit=f'{max(int(memory_mb or 256), 64)}m',
                cpu_period=100000,
                cpu_quota=max(int(cpu * 100000), 1000),
                read_only=bool(read_only),
                tmpfs={'/tmp': 'rw,noexec,nosuid,size=64m,mode=1777'},
                restart_policy={'Name': 'no'},
                auto_remove=False,
                stop_signal='SIGTERM',
                stdout=False,
                stderr=False,
            )
        except errors.ImageNotFound as exc:
            raise ImageUnavailable(f'Docker image is unavailable: {image}') from exc
        except Exception as exc:
            raise ContainerLaunchFailed('Could not create challenge container') from exc

    def inspect_container(self, container_id: str) -> Dict[str, Any]:
        errors = self._sdk_errors()
        try:
            container = self.client.containers.get(container_id)
            container.reload()
            attrs = container.attrs or {}
            network_settings = (attrs.get('NetworkSettings') or {}).get('Networks') or {}
            return {
                'id': container.id,
                'name': container.name,
                'status': container.status,
                'ports': getattr(container, 'ports', None) or (attrs.get('NetworkSettings') or {}).get('Ports') or {},
                'labels': (attrs.get('Config') or {}).get('Labels') or {},
                'networks': sorted(network_settings.keys()),
            }
        except errors.NotFound as exc:
            raise ContainerInspectionFailed('Challenge container is missing') from exc
        except Exception as exc:
            raise ContainerInspectionFailed('Could not inspect challenge container') from exc

    def find_container_by_name(self, name: str):
        errors = self._sdk_errors()
        try:
            matches = self.client.containers.list(all=True, filters={'name': name})
        except Exception as exc:
            raise ContainerInspectionFailed('Could not query challenge containers') from exc
        for candidate in matches:
            if getattr(candidate, 'name', '') == name:
                return candidate
        return None

    def stop_container(self, container_id: str) -> None:
        errors = self._sdk_errors()
        try:
            container = self.client.containers.get(container_id)
            container.reload()
            if container.status == 'running':
                try:
                    container.stop(timeout=self._config.stop_timeout)
                except errors.NotFound:
                    return
                except Exception:
                    container.kill()
        except errors.NotFound:
            return
        except Exception as exc:
            raise ContainerCleanupFailed('Could not stop challenge container') from exc

    def remove_container(self, container_id: str) -> None:
        errors = self._sdk_errors()
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=True)
        except errors.NotFound:
            return
        except Exception as exc:
            raise ContainerCleanupFailed('Could not remove challenge container') from exc

    def remove_network(self, network_id: str) -> None:
        errors = self._sdk_errors()
        try:
            network = self.client.networks.get(network_id)
            network.remove()
        except errors.NotFound:
            return
        except Exception as exc:
            # Active-endpoint conflicts are transient during concurrent stop;
            # the task can retry, so do not turn them into host-level errors.
            if 'active endpoints' not in str(exc).lower():
                raise ContainerCleanupFailed('Could not remove challenge network') from exc

    def list_managed_containers(self):
        try:
            return self.client.containers.list(all=True, filters={'label': [self.LABEL_MANAGED]})
        except Exception as exc:
            raise ContainerInspectionFailed('Could not list challenge containers') from exc

    def create_exec_session(self, container_id: str, command, user: str = '',
                            tty: bool = True) -> str:
        """Create a dedicated exec instance and return only its internal ID.

        This never uses ``container.attach()``/PID 1 and never accepts a Docker
        endpoint from a caller. The command is validated by the runtime service
        before it reaches this method.
        """
        errors = self._sdk_errors()
        try:
            result = self.client.api.exec_create(
                container_id,
                command,
                stdout=True,
                stderr=True,
                stdin=True,
                tty=bool(tty),
                privileged=False,
                user=user or '',
            )
        except errors.NotFound as exc:
            raise ContainerInspectionFailed('Challenge container is missing') from exc
        except Exception as exc:
            raise ExecSessionError('Could not create terminal session') from exc
        exec_id = result.get('Id') if isinstance(result, dict) else getattr(result, 'Id', '')
        if not exec_id:
            raise ExecSessionError('Docker did not return a terminal session')
        return str(exec_id)

    def start_exec_session(self, exec_id: str, tty: bool = True) -> ExecSession:
        """Start an exec stream and wrap its transport-specific socket."""
        errors = self._sdk_errors()
        try:
            sock = self.client.api.exec_start(exec_id, tty=bool(tty), socket=True)
        except errors.NotFound as exc:
            raise ExecSessionError('Terminal session is unavailable') from exc
        except Exception as exc:
            raise ExecSessionError('Could not start terminal session') from exc
        if sock is None:
            raise ExecSessionError('Docker did not open a terminal stream')
        return ExecSession(exec_id, sock, self.client.api)

    def resize_exec_session(self, exec_id: str, rows: int, cols: int) -> None:
        """Resize an exec PTY. Dimensions are bounded by the caller."""
        errors = self._sdk_errors()
        try:
            self.client.api.exec_resize(str(exec_id), height=int(rows), width=int(cols))
        except errors.NotFound as exc:
            raise ExecSessionError('Terminal session is unavailable') from exc
        except Exception as exc:
            raise ExecSessionError('Could not resize terminal') from exc

    def inspect_exec_session(self, exec_id: str) -> Dict[str, Any]:
        """Return a bounded exec-state summary."""
        errors = self._sdk_errors()
        try:
            result = self.client.api.exec_inspect(str(exec_id)) or {}
        except errors.NotFound as exc:
            raise ExecSessionError('Terminal session is unavailable') from exc
        except Exception as exc:
            raise ExecSessionError('Could not inspect terminal session') from exc
        return {
            'running': bool(result.get('Running')),
            'exit_code': result.get('ExitCode'),
        }

    def close_exec_session(self, session: ExecSession) -> None:
        """Close an exec stream without touching the challenge container."""
        if session is None:
            return
        try:
            session.close()
        except Exception as exc:
            raise ExecSessionError('Could not close terminal session') from exc

    @staticmethod
    def new_suffix() -> str:
        return uuid.uuid4().hex[:12]
