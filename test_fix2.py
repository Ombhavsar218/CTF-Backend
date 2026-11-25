from unittest.mock import MagicMock
from manager.app.runtime import DockerRuntimeAdapter, RuntimeError
from manager.app.policy import ValidatedRuntimeSpec

spec = ValidatedRuntimeSpec(
    challenge_image_id="test-chal",
    image_repository="registry.example.com/test/chal",
    image_digest="sha256:" + "a" * 64,
    image_ref="registry.example.com/test/chal:latest",
    display_name="Test",
    approved_container_port=8080,
    resource_profile={"cpu_limit_cores": 0.5, "memory_limit_mb": 256, "pid_limit": 128},
    max_lifetime_seconds=3600,
    storage_policy="ephemeral",
    network_policy="deny_all_egress",
    health_check={},
    ephemeral_storage=True,
    egress_denied=True,
)
client = MagicMock()
adapter = DockerRuntimeAdapter(docker_client=client)
try:
    adapter.create_container(spec, instance_id="1")
    print("BAD")
except RuntimeError:
    print("OK")
