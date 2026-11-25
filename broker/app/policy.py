from dataclasses import dataclass
from typing import Any, Dict, Optional


class BrokerPolicyError(ValueError):
    pass


@dataclass
class BrokerValidatedSpec:
    challenge_image_id: str
    image_repository: str
    image_digest: str
    approved_container_port: int
    resource_profile: Dict[str, Any]
    max_lifetime_seconds: int
    storage_policy: str = "ephemeral"
    network_policy: str = "deny_all_egress"


class BrokerPolicyValidator:
    """
    Broker policy validation interface. In this phase uses mocked catalog data only.
    Must eventually resolve independently from broker allowlist.
    """

    # Mocked allowlist for testing only - no production images
    MOCK_CATALOG = {}

    @classmethod
    def register_mock(cls, challenge_image_id: str, spec_data: Dict[str, Any]):
        cls.MOCK_CATALOG[challenge_image_id] = spec_data

    @classmethod
    def validate_create_request(cls, challenge_image_id: str,
                                resource_profile: Optional[Dict[str, Any]] = None,
                                approved_container_port: Optional[int] = None) -> BrokerValidatedSpec:
        if challenge_image_id not in cls.MOCK_CATALOG:
            raise BrokerPolicyError("Unknown challenge image ID")
        entry = cls.MOCK_CATALOG[challenge_image_id]
        digest = entry.get("image_digest", "")
        if not digest or not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
            raise BrokerPolicyError("Invalid or missing image digest")
        port = approved_container_port if approved_container_port is not None else entry.get("approved_container_port")
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise BrokerPolicyError("Invalid port")
        rp = resource_profile if resource_profile is not None else entry.get("resource_profile", {})
        if not isinstance(rp, dict):
            raise BrokerPolicyError("Unsupported resource profile")
        lifetime = entry.get("max_lifetime_seconds", 3600)
        if not isinstance(lifetime, int) or lifetime < 60 or lifetime > 3600:
            raise BrokerPolicyError("Invalid lifetime")
        if entry.get("storage_policy") != "ephemeral":
            raise BrokerPolicyError("Invalid storage policy")
        if entry.get("network_policy") != "deny_all_egress":
            raise BrokerPolicyError("Invalid network policy")
        return BrokerValidatedSpec(
            challenge_image_id=challenge_image_id,
            image_repository=entry.get("image_repository", ""),
            image_digest=digest,
            approved_container_port=port,
            resource_profile=rp,
            max_lifetime_seconds=lifetime,
            storage_policy="ephemeral",
            network_policy="deny_all_egress",
        )


broker_policy = BrokerPolicyValidator()
