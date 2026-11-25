import ipaddress
import json
from typing import Any, Dict, List, Optional

from .network_ownership import PersistentNetworkOwnershipStore
from .ownership_store_persistent import PersistentOwnershipStore


class FirewallMembershipError(Exception):
    pass


class FirewallMembershipVerifier:
    @staticmethod
    def verify_target_membership(network_store: PersistentNetworkOwnershipStore,
                                 container_store: PersistentOwnershipStore,
                                 instance_id: str,
                                 network_id: str,
                                 ip: Optional[str] = None,
                                 subnet: Optional[str] = None) -> bool:
        if not network_store or not container_store:
            raise FirewallMembershipError("Stores required")
        try:
            net_rec = network_store.verify(network_id)
        except Exception:
            raise FirewallMembershipError("Unknown or unowned network")
        if getattr(net_rec, 'lifecycle_state', 'active') != 'active':
            raise FirewallMembershipError("Stale network ownership")
        if str(net_rec.instance_id) != str(instance_id):
            raise FirewallMembershipError("Network-instance mismatch")
        try:
            cont_rec = container_store.verify(str(instance_id))
        except Exception:
            raise FirewallMembershipError("Unknown or unowned instance")
        # Need subnet metadata - if not present, reject (fail closed)
        net_subnet = {}
        try:
            rows = network_store.db.query('SELECT subnet_info FROM network_ownership WHERE network_id = ?', (network_id,))
            if rows and rows[0]['subnet_info']:
                val = rows[0]['subnet_info']
                if isinstance(val, str):
                    try:
                        net_subnet = json.loads(val)
                    except Exception:
                        net_subnet = {}
                elif isinstance(val, dict):
                    net_subnet = val
        except Exception:
            net_subnet = {}
        owned_subnet = net_subnet.get('subnet') or net_subnet.get('network') or net_subnet.get('cidr')
        if not owned_subnet:
            raise FirewallMembershipError("Missing subnet metadata")
        try:
            owned_net = ipaddress.ip_network(str(owned_subnet), strict=False)
        except Exception:
            raise FirewallMembershipError("Missing or inconsistent subnet metadata")
        if subnet is not None:
            try:
                s_net = ipaddress.ip_network(str(subnet), strict=False)
            except Exception:
                raise FirewallMembershipError("Invalid subnet")
            if s_net.prefixlen < owned_net.prefixlen:
                raise FirewallMembershipError("Target outside owned network subnet")
            if s_net.version != owned_net.version:
                raise FirewallMembershipError("IP version mismatch")
            # Check membership
            if not (owned_net.supernet_of(s_net) or str(s_net) == str(owned_net) or s_net.network_address in owned_net):
                # More precise: target subnet must be contained in owned network
                try:
                    # Check if any address of target is outside - rough check
                    if s_net.prefixlen >= owned_net.prefixlen:
                        # target is same or smaller; check containment
                        if s_net.network_address not in owned_net:
                            raise FirewallMembershipError("Target outside owned network subnet")
                except FirewallMembershipError:
                    raise
                except Exception:
                    raise FirewallMembershipError("Target outside owned network subnet")
        if ip is not None:
            try:
                ip_obj = ipaddress.ip_address(str(ip))
            except Exception:
                raise FirewallMembershipError("Invalid IP")
            if ip_obj.version != owned_net.version:
                raise FirewallMembershipError("IP version mismatch")
            try:
                if ip_obj not in owned_net:
                    raise FirewallMembershipError("IP outside owned subnet")
            except Exception:
                raise FirewallMembershipError("IP outside owned subnet")
        return True


firewall_membership_verifier = FirewallMembershipVerifier()
