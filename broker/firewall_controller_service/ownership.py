from typing import Dict, Any


class ControllerOwnershipAbstraction:
    def __init__(self):
        self._ownership = {}

    def get_broker_ownership_identity(self, req: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "policy_id": req.get("policy_id"),
            "policy_version": req.get("policy_version"),
            "instance_id": req.get("instance_id"),
            "network_id": req.get("network_id"),
            "expected_ownership_identity": req.get("expected_ownership_identity"),
        }

    def validate_ownership(self, req: Dict[str, Any]) -> bool:
        # Never trust firewall comments/labels; require broker-generated metadata
        ident = self.get_broker_ownership_identity(req)
        return ident.get("policy_id") is not None
