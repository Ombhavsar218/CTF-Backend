import ipaddress
import json
import re
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from .network_ownership import PersistentNetworkOwnershipStore
from .ownership_store_persistent import PersistentOwnershipStore
from .firewall_membership import firewall_membership_verifier, FirewallMembershipError


class FirewallPolicyError(ValueError):
    pass


@dataclass
class FirewallPolicyTarget:
    network_id: str
    instance_id: str
    ip: Optional[str] = None
    subnet: Optional[str] = None
    port: Optional[int] = None
    protocol: str = "tcp"
    verified: bool = False


@dataclass
class FirewallPolicy:
    policy_id: str
    instance_id: str
    source_component: str
    direction: str  # egress/ingress
    ip_version: str  # ipv4/ipv6/both
    targets: List[FirewallPolicyTarget]
    challenge_id: str = ""
    network_ownership_id: str = ""
    policy_version: int = 1
    state: str = "enforce"
    purpose: str = "challenge_isolation"
    ownership_verified: bool = False


class FirewallPolicyModel:
    ALLOWED_PROTOCOLS = {"tcp", "udp"}
    ALLOWED_DIRECTIONS = {"egress", "ingress"}
    ALLOWED_IP_VERSIONS = {"ipv4", "ipv6"}
    ALLOWED_SOURCES = {"broker", "challenge", "gateway"}  # proxy removed - no firewall admin privileges

    @classmethod
    def _normalize_ip(cls, ip_str: str):
        try:
            ip = ipaddress.ip_address(ip_str.strip())
            # Reject IPv4-mapped IPv6
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                raise FirewallPolicyError("IPv4-mapped IPv6 addresses are not allowed")
            return str(ip)
        except FirewallPolicyError:
            raise
        except Exception:
            raise FirewallPolicyError("Invalid IP")

    @classmethod
    def _normalize_subnet(cls, subnet_str: str):
        try:
            net = ipaddress.ip_network(subnet_str.strip(), strict=False)
            # Reject unrestricted
            if net.prefixlen == 0:
                raise FirewallPolicyError("Unrestricted CIDR rejected")
            return str(net)
        except FirewallPolicyError:
            raise
        except Exception:
            raise FirewallPolicyError("Invalid subnet")

    @classmethod
    def create_policy(cls, instance_id: str, source_component: str, direction: str,
                      ip_version: str, targets: List[Dict[str, Any]], challenge_id: str = "",
                      network_ownership_id: str = "", policy_version: int = 1,
                      state: str = "enforce", purpose: str = "challenge_isolation",
                      network_store: Optional[PersistentNetworkOwnershipStore] = None,
                      container_store: Optional[PersistentOwnershipStore] = None) -> FirewallPolicy:
        if not instance_id:
            raise FirewallPolicyError("Missing instance_id")
        if source_component not in cls.ALLOWED_SOURCES:
            raise FirewallPolicyError("Invalid source component")
        if direction not in cls.ALLOWED_DIRECTIONS:
            raise FirewallPolicyError("Invalid direction")
        if ip_version not in cls.ALLOWED_IP_VERSIONS:
            raise FirewallPolicyError("Invalid IP version")
        if not isinstance(targets, list) or not targets:
            raise FirewallPolicyError("Targets required")
        # Resolve ownership
        if network_store is None or container_store is None:
            raise FirewallPolicyError("Network and container ownership stores required")
        resolved_targets: List[FirewallPolicyTarget] = []
        for t in targets:
            if not isinstance(t, dict):
                raise FirewallPolicyError("Invalid target")
            # Never trust caller-provided network/instance - resolve from trusted records
            network_id = network_ownership_id or t.get("network_ownership_id") or t.get("network_id")
            inst = instance_id  # must come from verified instance
            if not network_id:
                raise FirewallPolicyError("Unknown network")
            ip = t.get("ip")
            subnet = t.get("subnet")
            port = t.get("port")
            protocol = t.get("protocol", "tcp")
            if protocol not in cls.ALLOWED_PROTOCOLS:
                raise FirewallPolicyError("Invalid protocol")
            if port is not None:
                if not isinstance(port, int) or port < 1 or port > 65535:
                    raise FirewallPolicyError("Invalid port")
            norm_ip = None
            norm_subnet = None
            if ip is not None:
                norm_ip = cls._normalize_ip(ip)
                ip_obj = ipaddress.ip_address(norm_ip)
                if ip_version == "ipv4" and ip_obj.version != 4:
                    raise FirewallPolicyError("IP version mismatch")
                if ip_version == "ipv6" and ip_obj.version != 6:
                    raise FirewallPolicyError("IP version mismatch")
                if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved:
                    raise FirewallPolicyError("Unauthorized destination")
            if subnet is not None:
                norm_subnet = cls._normalize_subnet(subnet)
                net_obj = ipaddress.ip_network(norm_subnet, strict=False)
                if ip_version == "ipv4" and net_obj.version != 4:
                    raise FirewallPolicyError("IP version mismatch")
                if ip_version == "ipv6" and net_obj.version != 6:
                    raise FirewallPolicyError("IP version mismatch")
                if net_obj.prefixlen == 0:
                    raise FirewallPolicyError("Unrestricted CIDR rejected")
                if net_obj.is_loopback or net_obj.is_link_local or net_obj.is_multicast or net_obj.is_reserved:
                    raise FirewallPolicyError("Unauthorized destination")
            if norm_ip is None and norm_subnet is None:
                raise FirewallPolicyError("Unrestricted destination rejected")
            if port is None and direction == "egress":
                raise FirewallPolicyError("Unrestricted port rejected")
            # Verify membership against trusted metadata
            try:
                firewall_membership_verifier.verify_target_membership(network_store, container_store, inst, network_id, norm_ip, norm_subnet)
            except FirewallMembershipError as e:
                raise FirewallPolicyError(str(e))
            resolved_targets.append(FirewallPolicyTarget(network_id=str(network_id), instance_id=str(inst),
                                                        ip=norm_ip, subnet=norm_subnet, port=port, protocol=protocol,
                                                        verified=True))
        policy_id = str(uuid.uuid4())
        return FirewallPolicy(policy_id=policy_id, instance_id=str(inst),
                              source_component=source_component, direction=direction,
                              ip_version=ip_version, targets=resolved_targets,
                              challenge_id=challenge_id or "", network_ownership_id=str(network_id),
                              policy_version=policy_version, state=state, purpose=purpose,
                              ownership_verified=True)


firewall_policy_model = FirewallPolicyModel()
