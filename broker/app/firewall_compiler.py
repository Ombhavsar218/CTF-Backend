import hashlib
import json
from dataclasses import asdict
from typing import Any, Dict, List

from .firewall_policy import FirewallPolicy, FirewallPolicyError


class FirewallRuleCompiler:
    @staticmethod
    def canonical_serialize(rules: List[Dict[str, Any]]) -> str:
        # Stable ordering
        normalized = []
        for r in sorted(rules, key=lambda x: (
            x.get('policy_id',''), x.get('instance_id',''), x.get('source_component',''),
            x.get('direction',''), x.get('ip_version',''), x.get('protocol',''),
            x.get('network_id',''), x.get('dest_ip') or '', x.get('dest_subnet') or '',
            x.get('dest_port') or 0
        )):
            normalized.append({
                "policy_id": r["policy_id"],
                "instance_id": r["instance_id"],
                "source_component": r["source_component"],
                "direction": r["direction"],
                "ip_version": r["ip_version"],
                "protocol": r["protocol"],
                "network_id": r["network_id"],
                "dest_ip": r["dest_ip"],
                "dest_subnet": r["dest_subnet"],
                "dest_port": r["dest_port"],
                "action": r.get("action", "ACCEPT"),
                "default_action": r.get("default_action", "DROP"),
            })
        return json.dumps(normalized, sort_keys=True)

    def compile(self, policy: FirewallPolicy) -> Dict[str, Any]:
        if not isinstance(policy, FirewallPolicy):
            raise FirewallPolicyError("Invalid policy")
        # Require ownership verification
        if not getattr(policy, 'ownership_verified', False):
            raise FirewallPolicyError("Policy not ownership-verified")
        for t in policy.targets:
            if not getattr(t, 'verified', False):
                raise FirewallPolicyError("Target not ownership-verified")
        if policy.source_component == "proxy":
            raise FirewallPolicyError("Proxy not authorized for firewall administration")
        rules: List[Dict[str, Any]] = []
        seen = set()
        for t in policy.targets:
            rule = {
                "policy_id": policy.policy_id,
                "instance_id": policy.instance_id,
                "source_component": policy.source_component,
                "direction": policy.direction,
                "ip_version": policy.ip_version,
                "protocol": t.protocol,
                "network_id": t.network_id,
                "dest_ip": t.ip,
                "dest_subnet": t.subnet,
                "dest_port": t.port,
                "action": "ACCEPT",
                "default_action": "DROP",
            }
            if rule["dest_port"] is None and rule["direction"] == "egress":
                raise FirewallPolicyError("Unrestricted port rejected")
            if rule["dest_ip"] is None and rule["dest_subnet"] is None:
                raise FirewallPolicyError("Unrestricted destination rejected")
            key = (rule["source_component"], rule["direction"], rule["ip_version"], rule["protocol"],
                   rule["network_id"], rule["dest_ip"], rule["dest_subnet"], rule["dest_port"])
            if key in seen:
                raise FirewallPolicyError("Duplicate rule rejected")
            seen.add(key)
            rules.append(rule)
        if not rules:
            raise FirewallPolicyError("No rules generated")
        # ensure no unrestricted ACCEPT
        for r in rules:
            if r["dest_port"] is None or (r["dest_ip"] is None and r["dest_subnet"] is None):
                raise FirewallPolicyError("Unrestricted ACCEPT rule rejected")
        payload = self.canonical_serialize(rules)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return {"policy_id": policy.policy_id, "rules": rules, "compiled_rule_digest": digest, "rule_count": len(rules), "canonical": payload}


firewall_compiler = FirewallRuleCompiler()
