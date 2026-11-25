"""Challenge runtime orchestration.

Production mode delegates Docker operations to the restricted runtime manager.
Direct Docker SDK access is allowed only for explicit development/testing.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from instances.manager_client import ManagerClient, ManagerError

from .config import RuntimeConfig
from .docker_adapter import DockerAdapter
from .errors import DockerUnavailable, RuntimeErrorBase
from .manager_exec import ManagerExecSession

TERMINAL = {'stopped', 'expired', 'failed'}


def _command(challenge) -> Any:
    raw = (getattr(challenge, 'runtime_command', '') or '').strip()
    if not raw:
        return None
    if raw.startswith('['):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return parsed
        except (TypeError, ValueError):
            pass
    return raw


def _message(exc: BaseException) -> str:
    text = getattr(exc, 'message', None) or str(exc) or exc.__class__.__name__
    return text[:255]


def _labels(instance, challenge) -> Dict[str, str]:
    return {
        'flaghunt.managed': 'true',
        'flaghunt.instance-id': str(instance.pk),
        'flaghunt.user-id': str(instance.user_id),
        'flaghunt.challenge-id': str(challenge.pk),
    }


def _host_port(info: Dict[str, Any], internal_port: Optional[int]) -> Optional[int]:
    if not internal_port:
        return None
    bindings = (info.get('ports') or {}).get(f'{int(internal_port)}/tcp') or []
    if isinstance(bindings, dict):
        bindings = [bindings]
    for binding in bindings:
        port = binding.get('HostPort') if isinstance(binding, dict) else None
        if port:
            try:
                return int(port)
            except (TypeError, ValueError):
                continue
    return None


def build_connection_meta(challenge, info: Dict[str, Any], config: RuntimeConfig) -> Optional[Dict[str, Any]]:
    """Build connection details only from confirmed Docker inspection data."""
    if getattr(challenge, 'runtime_access_mode', 'http') == 'terminal':
        # Terminal mode needs no published port and must never carry internal
        # container identifiers. HTTP mode keeps its Stage 1C shape below.
        return {'type': 'terminal'}
    port = _host_port(info, challenge.runtime_internal_port)
    if not port:
        return None
    kind = (challenge.runtime_connection_type or 'tcp').lower()
    host = config.publish_host
    meta: Dict[str, Any] = {
        'type': kind,
        'host': host,
        'port': port,
        'target': f'{host}:{port}',
        'container_id': info.get('id', ''),
    }
    if kind in ('http', 'https'):
        meta['url'] = f'{kind}://{host}:{port}'
    return meta


def duration_for(challenge, config: RuntimeConfig) -> int:
    configured = getattr(challenge, 'runtime_duration_minutes', 0) or 0
    return max(int(configured), 1) if configured else max(int(config.duration_minutes), 1)


def _runtime_backend() -> str:
    return (getattr(settings, "RUNTIME_BACKEND", "manager") or "manager").strip().lower()


def _direct_docker_allowed() -> bool:
    return bool(getattr(settings, "ALLOW_DIRECT_DOCKER", False))


class ChallengeRuntimeService:
    def __init__(self, adapter: Optional[DockerAdapter] = None,
                 config: Optional[RuntimeConfig] = None,
                 manager_client: Optional[ManagerClient] = None):
        self.config = config or RuntimeConfig.from_env()
        self.manager_client = manager_client
        self.adapter = adapter
        self.backend = "direct" if adapter is not None else _runtime_backend()
        if self.backend not in {"direct", "manager"}:
            self.backend = "manager"
        if self.backend == "manager":
            self.manager_client = self.manager_client or ManagerClient()
        elif self.backend == "direct" and self.adapter is None:
            if not _direct_docker_allowed():
                raise RuntimeErrorBase(
                    "Direct Docker runtime is disabled. Configure the runtime manager "
                    "or explicitly set RUNTIME_BACKEND=direct and ALLOW_DIRECT_DOCKER=True for development."
                )
            self.adapter = DockerAdapter(config=self.config)

    def start(self, instance, challenge):
        """Create and start a real container for an already-reserved instance."""
        from instances.models import ChallengeInstance

        with transaction.atomic():
            instance = ChallengeInstance.objects.select_for_update().get(pk=instance.pk)
            instance.status = ChallengeInstance.STATUS_STARTING
            instance.failure_reason = ''
            if not instance.internal_name:
                instance.internal_name = f'flaghunt-{instance.pk}-{DockerAdapter.new_suffix()}'
            instance.save(update_fields=[
                'status', 'failure_reason', 'internal_name', 'updated_at',
            ])

        name = instance.internal_name
        try:
            if self.backend == "manager":
                result = self._start_via_manager(instance, challenge)
                info = result.get("info") or {}
                container_id = result.get("container_id") or info.get("id", "")
                network_id = result.get("network_id", "")
                meta = build_connection_meta(challenge, info, self.config)
                if getattr(challenge, "runtime_access_mode", "http") != "terminal" and challenge.runtime_internal_port and meta is None:
                    raise RuntimeErrorBase("Challenge container did not publish a host port")
                with transaction.atomic():
                    instance = ChallengeInstance.objects.select_for_update().get(pk=instance.pk)
                    instance.status = ChallengeInstance.STATUS_RUNNING
                    instance.internal_container_id = container_id
                    instance.internal_network_id = network_id
                    instance.connection_meta = meta
                    instance.failure_reason = ""
                    instance.save(update_fields=[
                        "status", "internal_container_id", "internal_network_id",
                        "connection_meta", "failure_reason", "updated_at",
                    ])
                return instance

            network_name = f"{name}-net"
            network = None
            container_id = ""
            self.adapter.ensure_image(challenge.runtime_image)
            network = self.adapter.create_network(network_name, _labels(instance, challenge))
            container = self.adapter.create_container(
                image=challenge.runtime_image,
                name=name,
                network_name=getattr(network, "name", network_name),
                command=_command(challenge),
                internal_port=challenge.runtime_internal_port,
                labels=_labels(instance, challenge),
                cpu_limit=challenge.runtime_cpu_limit,
                memory_mb=challenge.runtime_memory_mb,
                pids_limit=challenge.runtime_pids_limit,
                read_only=challenge.runtime_read_only,
            )
            container_id = getattr(container, "id", "") or ""
            info = self.adapter.inspect_container(container_id)
            for _ in range(20):
                if info.get("status") == "running":
                    break
                if info.get("status") in ("exited", "dead"):
                    break
                time.sleep(0.25)
                info = self.adapter.inspect_container(container_id)
            if info.get("status") != "running":
                raise RuntimeErrorBase("Challenge container did not reach running state")
            meta = build_connection_meta(challenge, info, self.config)
            if challenge.runtime_internal_port and meta is None:
                raise RuntimeErrorBase("Challenge container did not publish a host port")

            with transaction.atomic():
                instance = ChallengeInstance.objects.select_for_update().get(pk=instance.pk)
                instance.status = ChallengeInstance.STATUS_RUNNING
                instance.internal_container_id = info.get("id", container_id)
                instance.internal_network_id = getattr(network, "id", "") or ""
                instance.connection_meta = meta
                instance.failure_reason = ""
                instance.save(update_fields=[
                    "status", "internal_container_id", "internal_network_id",
                    "connection_meta", "failure_reason", "updated_at",
                ])
            return instance
        except Exception as exc:
            if self.backend == "direct":
                self._best_effort_cleanup(locals().get("container_id", ""), locals().get("network", None) and getattr(locals().get("network"), "id", "") or "")
            with transaction.atomic():
                instance = ChallengeInstance.objects.select_for_update().get(pk=instance.pk)
                instance.status = ChallengeInstance.STATUS_FAILED
                instance.stopped_at = timezone.now()
                instance.failure_reason = _message(exc)
                instance.connection_meta = None
                instance.save(update_fields=[
                    "status", "stopped_at", "failure_reason", "connection_meta", "updated_at",
                ])
            if isinstance(exc, RuntimeErrorBase):
                raise
            raise RuntimeErrorBase(_message(exc)) from exc

    def _image_ref_and_digest(self, challenge) -> tuple[str, str]:
        image = (getattr(challenge, "runtime_image", "") or "").strip()
        if "@sha256:" in image:
            repo, digest = image.rsplit("@", 1)
            return repo, digest
        digest_map = getattr(settings, "RUNTIME_APPROVED_IMAGE_DIGESTS", {}) or {}
        digest = digest_map.get(image, "")
        if not digest:
            raise RuntimeErrorBase("Challenge image digest is required for manager runtime")
        return image, digest

    def _start_via_manager(self, instance, challenge) -> Dict[str, Any]:
        image, digest = self._image_ref_and_digest(challenge)
        payload = {
            "instance_id": str(instance.pk),
            "challenge_id": str(challenge.pk),
            "user_id": str(instance.user_id),
            "image": image,
            "image_digest": digest,
            "runtime_access_mode": getattr(challenge, "runtime_access_mode", "http"),
            "runtime_internal_port": challenge.runtime_internal_port,
            "runtime_command": _command(challenge),
            "cpu_limit": challenge.runtime_cpu_limit,
            "memory_mb": challenge.runtime_memory_mb,
            "pids_limit": challenge.runtime_pids_limit,
            "read_only": True,
            "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
        }
        try:
            return self.manager_client.create_instance(payload)
        except ManagerError as exc:
            raise RuntimeErrorBase(exc.message or "Runtime manager request failed") from exc

    def stop(self, instance):
        """Stop and remove the container and its private network."""
        from instances.models import ChallengeInstance

        with transaction.atomic():
            instance = ChallengeInstance.objects.select_for_update().get(pk=instance.pk)
            instance.status = ChallengeInstance.STATUS_STOPPING
            instance.save(update_fields=['status', 'updated_at'])

        warning = ''
        try:
            if self.backend == "manager":
                try:
                    self.manager_client.stop_instance(str(instance.pk), user_id=str(instance.user_id))
                except Exception as exc:
                    warning = f'Cleanup warning: {_message(exc)}'
                self.manager_client.remove_instance(str(instance.pk), user_id=str(instance.user_id), force=True)
            else:
                container_id = instance.internal_container_id
                network_id = instance.internal_network_id
                if not container_id and instance.internal_name:
                    found = self.adapter.find_container_by_name(instance.internal_name)
                    container_id = getattr(found, 'id', '') if found is not None else ''
                if container_id:
                    try:
                        self.adapter.stop_container(container_id)
                    except Exception as exc:
                        warning = f'Cleanup warning: {_message(exc)}'
                    self.adapter.remove_container(container_id)
                if network_id:
                    self.adapter.remove_network(network_id)
        except Exception as exc:
            warning = warning or f'Cleanup warning: {_message(exc)}'

        with transaction.atomic():
            instance = ChallengeInstance.objects.select_for_update().get(pk=instance.pk)
            instance.status = ChallengeInstance.STATUS_STOPPED
            instance.stopped_at = timezone.now()
            instance.connection_meta = None
            instance.failure_reason = warning[:255]
            instance.save(update_fields=[
                'status', 'stopped_at', 'connection_meta', 'failure_reason', 'updated_at',
            ])
        return instance

    def expire(self, instance):
        if self.backend == "manager":
            try:
                self.manager_client.expire_instance(str(instance.pk), user_id=str(instance.user_id))
            except Exception:
                pass
        stopped = self.stop(instance)
        from instances.models import ChallengeInstance
        with transaction.atomic():
            stopped = ChallengeInstance.objects.select_for_update().get(pk=stopped.pk)
            stopped.status = ChallengeInstance.STATUS_EXPIRED
            stopped.failure_reason = ''
            stopped.save(update_fields=['status', 'failure_reason', 'updated_at'])
        return stopped

    def reconcile(self):
        """Reconcile non-terminal instances after restarts/cleanup-task runs."""
        from instances.models import ChallengeInstance

        now = timezone.now()
        expired = list(ChallengeInstance.objects.filter(
            status__in=[ChallengeInstance.STATUS_REQUESTED, ChallengeInstance.STATUS_STARTING,
                        ChallengeInstance.STATUS_RUNNING, ChallengeInstance.STATUS_STOPPING],
            expires_at__lte=now,
        ))
        for instance in expired:
            try:
                self.expire(instance)
            except Exception:
                continue

        active = ChallengeInstance.objects.filter(
            status__in=[ChallengeInstance.STATUS_STARTING, ChallengeInstance.STATUS_RUNNING],
        ).select_related('challenge')
        for instance in active:
            try:
                info = self.inspect_container_for_instance(instance)
            except Exception as exc:
                with transaction.atomic():
                    instance.status = ChallengeInstance.STATUS_FAILED
                    instance.stopped_at = timezone.now()
                    instance.connection_meta = None
                    instance.failure_reason = _message(exc)
                    instance.save(update_fields=[
                        'status', 'stopped_at', 'connection_meta', 'failure_reason', 'updated_at',
                    ])
                continue
            if info.get('status') != 'running':
                with transaction.atomic():
                    instance.status = ChallengeInstance.STATUS_FAILED
                    instance.stopped_at = timezone.now()
                    instance.connection_meta = None
                    instance.failure_reason = 'Challenge container is no longer running'
                    instance.save(update_fields=[
                        'status', 'stopped_at', 'connection_meta', 'failure_reason', 'updated_at',
                    ])
                continue
            meta = build_connection_meta(instance.challenge, info, self.config)
            if instance.connection_meta != meta:
                with transaction.atomic():
                    instance.connection_meta = meta
                    instance.save(update_fields=['connection_meta', 'updated_at'])

    def inspect_container_for_instance(self, instance) -> Dict[str, Any]:
        if self.backend == "manager":
            try:
                res = self.manager_client.inspect_instance(str(instance.pk), user_id=str(instance.user_id))
            except ManagerError as exc:
                raise RuntimeErrorBase(exc.message or 'Challenge container is not available') from exc
            info = res.get('info') or {}
            labels = info.get('labels') or {}
            if (labels.get('flaghunt.managed') != 'true'
                    or str(labels.get('flaghunt.instance-id')) != str(instance.pk)
                    or str(labels.get('flaghunt.user-id')) != str(instance.user_id)):
                raise RuntimeErrorBase('Challenge container ownership could not be confirmed')
            return info
        container_id = instance.internal_container_id
        if not container_id and instance.internal_name:
            found = self.adapter.find_container_by_name(instance.internal_name)
            container_id = getattr(found, 'id', '') if found is not None else ''
        if not container_id:
            raise RuntimeErrorBase('Challenge container is not available')
        return self.adapter.inspect_container(container_id)

    def confirm_running(self, instance) -> Dict[str, Any]:
        """Read-only runtime check used before issuing a terminal ticket."""
        info = self.inspect_container_for_instance(instance)
        if info.get('status') != 'running':
            raise RuntimeErrorBase('Challenge container is not running')
        labels = info.get('labels') or {}
        expected_user = getattr(instance, 'user_id', '')
        if (labels.get('flaghunt.managed') != 'true'
                or labels.get('flaghunt.instance-id') != str(instance.pk)
                or (expected_user and labels.get('flaghunt.user-id') != str(expected_user))):
            raise RuntimeErrorBase('Challenge container ownership could not be confirmed')
        return info

    def open_terminal_session(self, instance, user, command, rows: int, cols: int):
        """Create and start one interactive exec session.

        All identifiers come from the authenticated, server-side instance. The
        caller cannot name a container, exec, endpoint, user or host path.
        """
        from instances.models import ChallengeInstance

        if getattr(instance, 'user_id', None) != getattr(user, 'pk', None):
            raise RuntimeErrorBase('Challenge instance ownership could not be confirmed')
        if (instance.status != ChallengeInstance.STATUS_RUNNING or instance.is_expired):
            raise RuntimeErrorBase('Challenge instance is not available')
        if getattr(instance.challenge, 'runtime_access_mode', 'http') != 'terminal':
            raise RuntimeErrorBase('This challenge is not configured for terminal access')

        info = self.confirm_running(instance)
        container_id = info.get('id') or instance.internal_container_id
        if self.backend == "manager":
            try:
                res = self.manager_client.open_terminal(
                    str(instance.pk), str(user.pk), command, int(rows), int(cols),
                    expires_at=instance.expires_at.isoformat() if instance.expires_at else None,
                )
            except ManagerError as exc:
                raise RuntimeErrorBase(exc.message or 'Terminal session could not be started') from exc
            exec_id = res.get('exec_id', '')
            session = ManagerExecSession(self.manager_client, str(instance.pk), exec_id, user_id=str(user.pk))
            return session, exec_id, container_id

        exec_id = self.adapter.create_exec_session(
            container_id, command, user='', tty=True
        )
        try:
            session = self.adapter.start_exec_session(exec_id, tty=True)
            try:
                self.adapter.resize_exec_session(exec_id, rows, cols)
            except Exception:
                session.close()
                raise
        except Exception:
            raise
        return session, exec_id, container_id

    def close_terminal_session(self, session) -> None:
        """Close only the exec stream; never stop or remove the container."""
        if hasattr(session, 'close'):
            session.close()
            return
        if self.backend == 'direct' and self.adapter is not None:
            self.adapter.close_exec_session(session)

    def inspect_terminal_session(self, exec_id: str) -> Dict[str, Any]:
        if self.backend == "manager":
            # Manager inspect requires instance context; not used by current callers.
            raise RuntimeErrorBase('Terminal session inspection requires instance context')
        return self.adapter.inspect_exec_session(exec_id)

    def _best_effort_cleanup(self, container_id: str, network_id: str) -> None:
        if self.backend != 'direct' or self.adapter is None:
            return
        try:
            if container_id:
                self.adapter.remove_container(container_id)
        except Exception:
            pass
        try:
            if network_id:
                self.adapter.remove_network(network_id)
        except Exception:
            pass
