from unittest.mock import MagicMock

import pytest

from manager.app.runtime.base import RuntimeError, RuntimeNotFoundError, RuntimeNotOwnedError
from manager.app.runtime.docker_adapter import DockerRuntimeAdapter


def test_manager_runtime_adapter_rejects_injected_docker_client():
    fake_client = MagicMock()
    with pytest.raises(RuntimeError):
        DockerRuntimeAdapter(docker_client=fake_client)
    assert not fake_client.mock_calls
    if hasattr(fake_client, 'containers'):
        assert not fake_client.containers.mock_calls
    if hasattr(fake_client, 'api'):
        assert not fake_client.api.mock_calls


def test_manager_runtime_adapter_operations_fail_closed():
    adapter = DockerRuntimeAdapter()
    with pytest.raises(RuntimeError):
        adapter.create_container(MagicMock(), instance_id='1')
    with pytest.raises(RuntimeError):
        adapter.start_container('c1')
    with pytest.raises(RuntimeError):
        adapter.inspect_container('c1')
    with pytest.raises(RuntimeError):
        adapter.stop_container('c1')
    with pytest.raises(RuntimeError):
        adapter.remove_container('c1')
    with pytest.raises(RuntimeError):
        adapter.health_check_container('c1')


def test_fake_docker_client_cannot_activate_forbidden_operations():
    fake_client = MagicMock()
    try:
        DockerRuntimeAdapter(docker_client=fake_client)
        assert False, "client injection must fail closed"
    except RuntimeError:
        pass
    adapter = DockerRuntimeAdapter()
    for method, args in [
        ('create_container', (MagicMock(), '1')),
        ('start_container', ('c1',)),
        ('inspect_container', ('c1',)),
        ('stop_container', ('c1',)),
        ('remove_container', ('c1',)),
        ('health_check_container', ('c1',)),
    ]:
        with pytest.raises(RuntimeError):
            getattr(adapter, method)(*args)
    assert not fake_client.mock_calls


def test_runtime_error_types_remain_available():
    assert issubclass(RuntimeNotFoundError, RuntimeError)
    assert issubclass(RuntimeNotOwnedError, RuntimeError)
