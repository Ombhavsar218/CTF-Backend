from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import catalog


@dataclass(frozen=False)
class ValidatedRuntimeSpec:
    challenge_image_id: str
    image_repository: str
    image_digest: str
    image_ref: str
    display_name: str
    approved_container_port: int
    resource_profile: Dict[str, Any]
    max_lifetime_seconds: int
    storage_policy: str
    network_policy: str
    health_check: Dict[str, Any]
    ephemeral_storage: bool
    egress_denied: bool


class PolicyValidationError(ValueError):
    pass


class PolicyValidator:
    ALLOWED_STORAGE_POLICIES = {"ephemeral"}
    ALLOWED_NETWORK_POLICIES = {"deny_all_egress"}
    SUPPORTED_RESOURCE_PROFILES = {"small", "medium", "large", "default"}

    @staticmethod
    def _validate_digest(digest: str) -> None:
        if not digest:
            raise PolicyValidationError("Missing image digest")
        if not isinstance(digest, str):
            raise PolicyValidationError("Invalid image digest")
        if not (digest.startswith("sha256:") and len(digest) == 71):
            raise PolicyValidationError("Invalid image digest")
        hex_part = digest.split(":", 1)[1]
        if not all(c in "0123456789abcdef" for c in hex_part):
            raise PolicyValidationError("Invalid image digest")

    @staticmethod
    def validate_catalog_entry_config(entry_data: Dict[str, Any]) -> None:
        required_fields = [
            "challenge_image_id",
            "display_name",
            "image_repository",
            "image_digest",
            "approved_container_port",
            "resource_profile",
            "max_lifetime",
            "storage_policy",
            "network_policy",
            "health_check_settings",
        ]
        for field in required_fields:
            if field not in entry_data:
                raise PolicyValidationError(f"Missing required field: {field}")

        PolicyValidator._validate_digest(entry_data["image_digest"])

        port = entry_data["approved_container_port"]
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise PolicyValidationError("Invalid port")

        duration = entry_data["max_lifetime"]
        if not isinstance(duration, int) or duration < 60 or duration > catalog.MAX_LIFETIME_SECONDS:
            raise PolicyValidationError("Invalid duration")

        resource_profile = entry_data["resource_profile"]
        if isinstance(resource_profile, str):
            if resource_profile not in PolicyValidator.SUPPORTED_RESOURCE_PROFILES:
                raise PolicyValidationError("Unsupported resource profile")
        elif isinstance(resource_profile, dict):
            PolicyValidator.validate_resource_profile(resource_profile)
        else:
            raise PolicyValidationError("Unsupported resource profile")

        storage_policy = entry_data["storage_policy"]
        if storage_policy != "ephemeral":
            raise PolicyValidationError("Invalid storage policy")

        network_policy = entry_data["network_policy"]
        if network_policy != "deny_all_egress":
            raise PolicyValidationError("Invalid network policy")

        if not isinstance(entry_data["health_check_settings"], dict):
            raise PolicyValidationError("Invalid health-check settings")

    @staticmethod
    def validate_resource_profile(resource_profile: Dict[str, Any]) -> None:
        required = ["cpu_limit_cores", "memory_limit_mb", "pid_limit"]
        for r in required:
            if r not in resource_profile:
                raise PolicyValidationError("Unsupported resource profile")
        try:
            cpu = float(resource_profile["cpu_limit_cores"])
            mem = int(resource_profile["memory_limit_mb"])
            pid = int(resource_profile["pid_limit"])
        except Exception:
            raise PolicyValidationError("Unsupported resource profile")

        try:
            catalog.validate_policy_limits(cpu, mem, pid, resource_profile.get("max_lifetime_seconds", catalog.MAX_LIFETIME_SECONDS))
        except ValueError as e:
            if "below minimum" in str(e).lower() or "exceeds" in str(e).lower():
                raise PolicyValidationError(str(e))
            raise PolicyValidationError("Unsupported resource profile")

    @staticmethod
    def resolve_challenge_image_id(challenge_image_id: str):
        entry = catalog.get_entry_by_challenge_id(challenge_image_id)
        if not entry:
            raise PolicyValidationError("Unknown challenge image ID")
        return entry

    @staticmethod
    def validate_provision_request(challenge_image_id: str, duration_seconds: Optional[int] = None,
                                   resource_profile: Optional[Any] = None,
                                   container_port: Optional[int] = None) -> ValidatedRuntimeSpec:
        entry = PolicyValidator.resolve_challenge_image_id(challenge_image_id)

        if not entry.image_digest or not entry.digest_pinned:
            raise PolicyValidationError("Invalid or missing image digest")
        PolicyValidator._validate_digest(entry.image_digest)

        if duration_seconds is not None:
            if not isinstance(duration_seconds, int) or duration_seconds < 60 or duration_seconds > entry.max_lifetime_seconds or duration_seconds > catalog.MAX_LIFETIME_SECONDS:
                raise PolicyValidationError("Invalid duration")
        else:
            duration_seconds = entry.max_lifetime_seconds

        if resource_profile is not None:
            if isinstance(resource_profile, str):
                if resource_profile not in PolicyValidator.SUPPORTED_RESOURCE_PROFILES:
                    raise PolicyValidationError("Unsupported resource profile")
            elif isinstance(resource_profile, dict):
                PolicyValidator.validate_resource_profile(resource_profile)
            else:
                raise PolicyValidationError("Unsupported resource profile")
        else:
            resource_profile = entry.resource_profile_name if hasattr(entry, 'resource_profile_name') else "default"

        if container_port is not None:
            if container_port != entry.approved_container_port:
                raise PolicyValidationError("Invalid port")
        else:
            container_port = entry.approved_container_port
        if not isinstance(container_port, int) or container_port < 1 or container_port > 65535:
            raise PolicyValidationError("Invalid port")

        if entry.storage_policy != "ephemeral":
            raise PolicyValidationError("Invalid storage policy")
        if entry.network_policy != "deny_all_egress" and entry.network_policy != "default-deny":
            raise PolicyValidationError("Invalid network policy")
        if not getattr(entry, 'egress_denied', True):
            raise PolicyValidationError("Default-deny egress required")

        spec = ValidatedRuntimeSpec(
            challenge_image_id=entry.challenge_image_id,
            image_repository=entry.image_repository,
            image_digest=entry.image_digest,
            image_ref=entry.image_ref,
            display_name=entry.display_name,
            approved_container_port=container_port,
            resource_profile=resource_profile if isinstance(resource_profile, dict) else {"profile": resource_profile},
            max_lifetime_seconds=duration_seconds,
            storage_policy=entry.storage_policy,
            network_policy=entry.network_policy,
            health_check=entry.health_check_settings if hasattr(entry, 'health_check_settings') else {},
            ephemeral_storage=True,
            egress_denied=True,
        )
        return spec


validator = PolicyValidator()
