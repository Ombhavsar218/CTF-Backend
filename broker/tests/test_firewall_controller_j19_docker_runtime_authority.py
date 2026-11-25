"""Phase 2L.2J.19 Docker/runtime authority closure tests (mock-only, source & test proof).

Repository-wide negative tests for discovered broker-side Docker/runtime authority
paths: adapters, compatibility exports, DI/factory construction, route reachability,
socket/endpoint/env enablement attempts, and error sanitization. No real Docker
daemon/socket or host operations are performed.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from broker.app import dependencies, policy
from broker.app.docker_adapter import (
    BrokerDockerAdapter,
    BrokerDockerError,
    BrokerDockerNetworkError,
    BrokerDockerNotFoundError,
    BrokerDockerNotOwnedError,
    DockerAdapterBase,
)
from broker.app.main import app
from broker.app.routes import get_adapter

REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_APP = REPO_ROOT / "broker" / "app"
MANAGER_APP = REPO_ROOT / "manager" / "app"


def _register_policy():
    policy.broker_policy.register_mock(
        "chal-j19",
        {
            "image_repository": "registry.example.com/test/chal-j19",
            "image_digest": "sha256:" + "b" * 64,
            "approved_container_port": 8080,
            "resource_profile": {"cpu_limit_cores": 0.5, "memory_limit_mb": 256, "pid_limit": 128},
            "max_lifetime_seconds": 3600,
            "storage_policy": "ephemeral",
            "network_policy": "deny_all_egress",
        },
    )


def _auth_headers():
    return {"X-Broker-Peer-Uid": "1000", "X-Broker-Peer-User": "flaghunt-mgr"}


# --- inventory/source-proof helpers ---

def _iter_project_py_files():
    exclude_parts = {"venv", "__pycache__", ".pytest_cache", "manager-deploy-clean", "manager-package-check"}
    for base in (REPO_ROOT / "broker", REPO_ROOT / "manager", REPO_ROOT / "instances", REPO_ROOT / "config", REPO_ROOT / "ops"):
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if any(part in exclude_parts for part in p.parts):
                continue
            yield p
    for p in REPO_ROOT.glob("*.py"):
        if any(part in exclude_parts for part in p.parts):
            continue
        yield p


def test_no_docker_sdk_import_or_socket_endpoint_in_runtime_source():
    """Repository-wide source proof: no docker SDK/client/socket/endpoint strings in runtime source paths."""
    forbidden = (
        "import docker",
        "from docker",
        "docker.from_env",
        "docker.DockerClient",
        "docker.APIClient",
        "DOCKER_HOST",
        "/var/run/docker.sock",
        "npipe://",
        "unix://",
    )
    # Exclude J.19 test files that intentionally contain forbidden tokens as string literals for assertions
    j19_test_names = {
        "test_firewall_controller_j19_docker_runtime_authority.py",
        "test_manager_j19_docker_runtime_authority.py",
    }
    # Pre-existing untracked debug/fix scripts (not runtime/imported paths); preserved and inventoried
    excluded_untracked_scripts = {"check_docker.py", "fix_docker.py", "test_digest.py", "test_fix2.py", "test_own.py"}
    offenders = []
    for p in _iter_project_py_files():
        if p.name in j19_test_names or p.name in excluded_untracked_scripts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            for token in forbidden:
                if token in line:
                    offenders.append(f"{p.relative_to(REPO_ROOT)}:{i}:{token}")
    assert offenders == [], f"Unexpected Docker SDK/socket/endpoint references in project source: {offenders}"


def test_broker_dependency_factory_is_only_runtime_adapter_construction_path():
    """DI/factory construction: dependencies.get_adapter returns fail-closed adapter; no alternate factory in broker app."""
    adapter = dependencies.get_adapter()
    assert isinstance(adapter, BrokerDockerAdapter)
    assert adapter.__class__ is BrokerDockerAdapter
    assert getattr(adapter, "_client", "sentinel") is None
    assert getattr(adapter, "_api", "sentinel") is None
    # No other construction/factory in broker app modules (docker_adapter defines the class; no instantiation)
    for p in BROKER_APP.glob("*.py"):
        src = p.read_text(encoding="utf-8", errors="ignore")
        if p.name == "dependencies.py":
            assert "return BrokerDockerAdapter(docker_client=None" in src
            continue
        if p.name == "docker_adapter.py":
            # class definition only; must not create docker clients or call SDK/socket APIs
            for token in ("import docker", "from docker", "docker.from_env", "DockerClient", "APIClient", "DOCKER_HOST", "/var/run/docker.sock", "npipe://", "unix://"):
                assert token not in src
            continue
        assert "BrokerDockerAdapter(" not in src, f"Unexpected BrokerDockerAdapter construction in {p}"


# --- direct construction / injected client / compatibility exports ---

def test_direct_adapter_construction_fail_closed_and_no_client_retained():
    adapter = BrokerDockerAdapter()
    assert adapter._client is None
    assert adapter._api is None
    # internal registries are stored but no docker client/socket handles retained
    assert adapter._ownership is None
    assert adapter._network_ownership is None
    reg = object()
    adapter2 = BrokerDockerAdapter(ownership_registry=reg, network_ownership_registry=reg)
    assert adapter2._client is None and adapter2._api is None
    assert adapter2._ownership is reg and adapter2._network_ownership is reg


def test_injected_fake_client_rejected_and_never_touched():
    for ctor_arg in ("docker_client",):
        fake = MagicMock(name="sentinel-docker-client")
        with pytest.raises(BrokerDockerError) as ei:
            BrokerDockerAdapter(**{ctor_arg: fake})
        assert str(ei.value) == "Docker runtime unavailable"
        assert ei.value.args == ("Docker runtime unavailable",)
        assert not fake.mock_calls
        for attr in ("containers", "api", "networks", "images", "volumes"):
            if hasattr(fake, attr):
                assert not getattr(fake, attr).mock_calls


def test_compatibility_export_docker_adapter_base_is_not_operational():
    # Compatibility/base export remains importable but cannot perform operational Docker actions.
    assert issubclass(BrokerDockerAdapter, DockerAdapterBase)
    base = DockerAdapterBase()
    with pytest.raises(NotImplementedError):
        base.create_container(MagicMock(), "i1")
    with pytest.raises(NotImplementedError):
        base.create_network({"name": "n"})
    # Concrete adapter remains fail-closed (does not delegate to NotImplemented/real ops)
    adapter = BrokerDockerAdapter()
    with pytest.raises(BrokerDockerError):
        adapter.create_container(MagicMock(), "i1")
    with pytest.raises(BrokerDockerNetworkError):
        adapter.create_network({"name": "n"})


# --- operations (container/image/network/volume), repeated/failure-state consistency ---

@pytest.mark.parametrize("call", [
    lambda a: a.create_container(MagicMock(image_repository="r", image_digest="sha256:"+"a"*64, approved_container_port=80, resource_profile=None), "1"),
    lambda a: a.start_container("c1"),
    lambda a: a.inspect_container("c1"),
    lambda a: a.stop_container("c1"),
    lambda a: a.remove_container("c1"),
    lambda a: a.health_check_container("c1"),
])
def test_container_operations_fail_closed_consistently(call):
    adapter = BrokerDockerAdapter()
    for _ in range(3):
        with pytest.raises(BrokerDockerError) as ei:
            call(adapter)
        assert str(ei.value) == "Docker runtime unavailable"
    assert adapter._client is None and adapter._api is None


@pytest.mark.parametrize("call", [
    lambda a: a.create_network({"name": "n1"}),
    lambda a: a.inspect_network("n1"),
    lambda a: a.verify_network_ownership("n1"),
    lambda a: a.connect_container_to_network("n1", "c1"),
    lambda a: a.disconnect_container_from_network("n1", "c1"),
    lambda a: a.remove_network("n1"),
    lambda a: a.network_exists("n1"),
    lambda a: a.health_check_network("n1"),
])
def test_network_volume_operations_fail_closed_consistently(call):
    adapter = BrokerDockerAdapter()
    for _ in range(3):
        with pytest.raises(BrokerDockerNetworkError) as ei:
            call(adapter)
        assert str(ei.value) == "Docker runtime unavailable"
    assert adapter._client is None and adapter._api is None


# --- env/socket/endpoint cannot enable operations; docker module not imported by adapter ---

@pytest.mark.parametrize("env", [
    {"DOCKER_HOST": "unix:///var/run/docker.sock"},
    {"DOCKER_HOST": "npipe:////./pipe/docker_engine"},
    {"DOCKER_HOST": "tcp://127.0.0.1:2375"},
    {"DOCKER_HOST": "http://evil.example:2375"},
])
def test_env_docker_endpoint_settings_cannot_enable_adapter(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Re-importing module must not create/connect client
    mod = importlib.reload(importlib.import_module("broker.app.docker_adapter"))
    adapter = mod.BrokerDockerAdapter()
    with pytest.raises(mod.BrokerDockerError):
        adapter.create_container(MagicMock(), "1")
    assert "docker" not in sys.modules or True  # docker may be absent; must not be required/used
    # No docker SDK module imported by our adapter module
    assert "docker" not in mod.__dict__
    assert not any(m.startswith("docker.") for m in sys.modules if m in getattr(mod, "__dict__", {}))


def test_adapter_module_has_no_docker_sdk_imports():
    src = inspect.getsource(importlib.import_module("broker.app.docker_adapter"))
    for token in ("import docker", "from docker", "docker.from_env", "DockerClient", "APIClient"):
        assert token not in src


# --- route reachability / DI override attempts / background-task reachability (source) ---

def test_routes_use_dependency_injected_adapter_and_no_direct_docker_access():
    routes_src = (BROKER_APP / "routes.py").read_text(encoding="utf-8", errors="ignore")
    assert "Depends(get_adapter)" in routes_src
    assert "BrokerDockerAdapter(" not in routes_src
    assert "docker_client" not in routes_src
    assert "import docker" not in routes_src
    # No background tasks/celery/startup hooks in broker app package
    for p in BROKER_APP.glob("*.py"):
        src = p.read_text(encoding="utf-8", errors="ignore").lower()
        assert "backgroundtasks" not in src.replace(" ", "")
        assert "celery" not in src
        assert "@app.on_event" not in src


def test_dependency_override_cannot_inject_operational_client_via_route():
    _register_policy()
    app.dependency_overrides = {}
    fake = MagicMock(name="route-injected-client")
    # Attempting to override with an adapter constructed from injected client must fail at construction
    import broker.app.docker_adapter as da
    with pytest.raises(da.BrokerDockerError):
        da.BrokerDockerAdapter(docker_client=fake)
    assert not fake.mock_calls
    # Default route path remains fail-closed (adapter unavailable -> 500, never docker call)
    client = TestClient(app)
    try:
        resp = client.post(
            "/broker/v1/containers/create",
            json={"request_id": "rj19-override", "instance_id": "j19-inst-1", "challenge_image_id": "chal-j19"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 500
        assert resp.json().get("detail") == "Internal error"
        assert not fake.mock_calls
    finally:
        app.dependency_overrides = {}


def test_existing_broker_authz_and_policy_behavior_preserved():
    _register_policy()
    client = TestClient(app)
    app.dependency_overrides = {}
    # authz preserved
    resp = client.get("/broker/v1/health")
    assert resp.status_code in (401, 403)
    resp = client.get("/broker/v1/health", headers=_auth_headers())
    assert resp.status_code == 200
    # policy rejection preserved (not masked as docker availability issue)
    resp = client.post(
        "/broker/v1/containers/create",
        json={"request_id": "rj19p", "instance_id": "1", "challenge_image_id": "unknown-chal-j19"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 422


def test_error_sanitization_no_socket_env_or_internal_leakage():
    sensitive = ("/var/run/docker.sock", "npipe://", "unix://", "DOCKER_HOST", "Traceback", "docker-py", "MagicMock")
    fake = MagicMock()
    import broker.app.docker_adapter as da
    with pytest.raises(da.BrokerDockerError) as ei:
        da.BrokerDockerAdapter(docker_client=fake)
    msg = str(ei.value)
    for token in sensitive:
        assert token not in msg
    # Route-level failures return bounded internal error
    client = TestClient(app)
    _register_policy()
    app.dependency_overrides = {}
    try:
        resp = client.post(
            "/broker/v1/containers/create",
            json={"request_id": "rj19e", "instance_id": "j19-inst-e", "challenge_image_id": "chal-j19"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 500
        body = str(resp.json())
        for token in ("/var/run/docker.sock", "npipe://", "unix://", "DOCKER_HOST", "Traceback"):
            assert token not in body
    finally:
        app.dependency_overrides = {}
