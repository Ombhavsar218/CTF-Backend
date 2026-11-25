# Phase 2L.2I.4 — Consolidated Architecture Remediation

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2I.4  
**Date:** 2026-11-14  
**Status:** **DOCUMENTATION REMEDIATION COMPLETE — IMPLEMENTATION, HOST VALIDATION, AND LIVE AUTHORIZATION REMAIN OPEN**  
**Scope:** Documentation-only consolidated remediation of `N-01` through `N-04` from Phase 2L.2I.3, with cross-document consistency updates across `docs/PHASE_2L_2H_1` through `docs/PHASE_2L_2H_5`.

No source code, tests, runtime configuration, migrations, UDS sockets, `SO_PEERCRED` paths, helper binaries, Docker configuration, firewall rules, systemd units, host settings, cloud resources, or production data were modified or executed by this phase. No host, firewall, Docker, reboot, rollback, real-transport, or capability operation was executed. No files were staged, committed, reset, checked out, or cleaned.

> **Current versus future.** This report records design/documentation remediation only. A design correction is not implementation closure, host-validation evidence, or live authorization. The live gate remains **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.

---

## 1. Objective and constraints

Phase 2L.2I.4 remediates the new 2L.2I.3 findings `N-01`–`N-04`, restores cross-document consistency across the five Phase 2L.2H architecture documents, and prepares the independent 2L.2I.5 verification pass.

**Permitted file scope:** only `docs/PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md`, `docs/PHASE_2L_2H_2_THREAT_MODEL_AND_TRUST_BOUNDARIES.md`, `docs/PHASE_2L_2H_3_FIREWALL_BACKEND_AND_PRIVILEGE_DESIGN.md`, `docs/PHASE_2L_2H_4_PERSISTENCE_RECOVERY_AND_DEPLOYMENT_DESIGN.md`, `docs/PHASE_2L_2H_5_IMPLEMENTATION_AND_VALIDATION_ROADMAP.md`, `docs/PHASE_2L_2I_4_CONSOLIDATED_ARCHITECTURE_REMEDIATION.md`, and `docs/PHASE_2L_2I_5_INDEPENDENT_REMEDIATION_VERIFICATION.md`.

**Read-only inputs inspected:** `docs/PHASE_2L_2I_1_INDEPENDENT_ARCHITECTURE_SECURITY_REVIEW.md`, `docs/PHASE_2L_2I_2_TARGETED_ARCHITECTURE_BLOCKER_REMEDIATION.md`, `docs/PHASE_2L_2I_3_INDEPENDENT_FOLLOWUP_ARCHITECTURE_SECURITY_REVIEW.md`, all five 2H documents, and selected source files for N-04/current-behavior evidence (`broker/app/dependencies.py`, `broker/app/routes.py`, `broker/app/docker_adapter.py`, `manager/app/runtime/docker_adapter.py`, `manager/app/routes.py`, `manager/app/runtime/__init__.py`, `broker/app/auth.py`, `broker/app/uds.py`, `broker/firewall_controller_service/authorization_strict.py`, `broker/firewall_controller_service/helper_contract.py`).

**Preservation rules:** `F-01`–`F-14`, `H-01`–`H-05`, `M-01`–`M-09`, `T-11`, `T-13`, `T-27`, `RR-01`–`RR-07`, and `I-07`–`I-09` remain tracked. `M-04` and `M-05` remain documentation/traceability closures only. `T-11` and `T-13` remain `OPEN — ACCEPTANCE REQUIRED`. `M-09` remains an open host-validation gate.

---

## 2. Baseline

### 2.1 Git baseline (pre-existing, not created by this phase)

- **Modified tracked files:** 26
- **Untracked entries:** 43
- `docs/` was a pre-existing untracked directory containing the full 2H/2I.1–2I.3 set and earlier phase documents; Git therefore cannot isolate newly created report files by path status alone. Scope compliance is evidenced by the permitted-file list and by not editing 2I.1–2I.3.

**Modified tracked files (26):** `.env.example`, `.gitignore`, `README.md`, `achievements/views.py`, `announcements/views.py`, `challenges/admin_urls.py`, `challenges/models.py`, `challenges/serializers.py`, `challenges/tests.py`, `challenges/urls.py`, `challenges/views.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `requirements.txt`, `submissions/serializers.py`, `submissions/stats.py`, `submissions/tests.py`, `submissions/urls.py`, `submissions/views.py`, `users/admin_views.py`, `users/management/commands/setup_groups.py`, `users/tests.py`, `users/throttling.py`, `users/urls.py`, `users/views.py`.

**Untracked entries (43):** `.dockerignore`, `DEPLOYMENT.md`, `Dockerfile`, `audit/`, `broker/`, `check_docker.py`, `check_err.py`, `check_lines.py`, `config/celery.py`, `config/deploy.py`, `config/exceptions.py`, `config/middleware.py`, `config/observability.py`, `config/test_runner.py`, `config/test_urls.py`, `config/tests.py`, `debug_audit.py`, `debug_audit2.py`, `debug_conc.py`, `debug_forge.py`, `debug_line145.py`, `debug_sim.py`, `debug_transport.py`, `debug_transport2.py`, `docs/`, `err.txt`, `fix_docker.py`, `fix_skel.py`, `flaghunt-manager-26C3G1.zip`, `instances/`, `manager-deploy-clean/`, `manager-package-check/`, `manager/`, `ops/`, `out.txt`, `out2.txt`, `platform_settings/`, `requirements-production.txt`, `search_peer.py`, `test_digest.py`, `test_fix2.py`, `test_own.py`, `try_compile.py`.

### 2.2 Prior review state carried forward

From `PHASE_2L_2I_3_INDEPENDENT_FOLLOWUP_ARCHITECTURE_SECURITY_REVIEW.md`:
- High: 0 closed, 2 open (`H-01`, `H-05`), 3 partially resolved (`H-02`, `H-03`, `H-04`).
- Medium: 2 documentation-only closed (`M-04`, `M-05`), 1 open (`M-09`), 6 partially resolved (`M-01`, `M-02`, `M-03`, `M-06`, `M-07`, `M-08`).
- New findings: `N-01` Medium, `N-02` High, `N-03` Medium, `N-04` Medium.
- 2I.3 conclusion: **CONDITIONAL** for architecture documentation; **CONDITIONALLY READY** for controlled host-validation planning only after prerequisites; **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED** for live integration.

---

## 3. N-01 — socket directory, group assignment, and ownership

**Finding (2I.3):** UDS directory/socket ownership values were specified but the group-assignment mechanism was missing. A server in its own primary group could not safely create a client-group socket without `chown`, `CAP_CHOWN`, supplementary-group changes, or unsafe mode widening.

**Selected mechanism:** `2750` server-owned setgid directory, client primary group, kernel group inheritance. Socket `0660`, server owner, client group. No `chown`/`chgrp`, no `CAP_CHOWN`, no server membership in the client group, no supplementary-group socket access, no world-writable socket, no shared `flaghunt` group.

### 3.1 Design rules applied

| Control | Rule |
|---|---|
| `/run/flaghunt` | `root:root 0755`, non-world-writable |
| Edge directories | Exact server UID owner, exact client primary GID group, mode `2750` with `S_ISGID` |
| Sockets | Exact server owner, client group, mode `0660` |
| Creation | `systemd-tmpfiles` or equivalent root-only deployment creates directories before service start |
| Bind | Server binds with restrictive umask; kernel setgid-directory inheritance assigns the client group |
| Post-bind | Server sets/verifies `0660`; does not call `chown`/`chgrp`; does not require `CAP_CHOWN` |
| Fail-closed | Missing setgid bit, wrong owner/group/mode, no group inheritance, bad parent path, symlink, or unsafe replacement causes startup failure |
| Stale/live socket | Live socket never unlinked; stale socket removed only after owner/group/mode/type checks and failed live probe |
| Upgrades/restarts | Numeric IDs and tmpfiles records preserved; tmpfs cleared on reboot and tmpfiles reasserts `2750`; ID drift fails closed |
| Unauthorized local users | No directory traverse (`other ---`) and no socket access; root remains out of scope as host compromise |

### 3.2 2H document updates

- **2H.1 §5.1:** replaced `0750` directory model with `2750` setgid model, added explicit `S_ISGID` requirement, added normative group-assignment mechanism (N-01), updated socket table, preserved `SO_PEERCRED`/exact-allowlist requirements.
- **2H.1 §5.2:** directory verification now requires exact `2750` + setgid; bind flow relies on kernel inheritance and verifies owner/group without `chown`.
- **2H.1 §5.6/§7:** socket-path config and resolved decisions now require `2750` setgid directories and record that supplementary groups are not used for socket access.
- **2H.2:** T-01/T-03 and socket lifecycle decisions updated to `2750`; test mapping includes `SOCK-05`/`PATH-05` for setgid inheritance, drift, and cross-UID deny; N-01 recorded as **PARTIALLY RESOLVED — DESIGN COMPLETE; HOST EVIDENCE OPEN**.
- **2H.3 §5.4:** helper/controller/broker/runtime directories set to `2750` setgid; boot verification rejects `0750`; references 2H.1 §5.1.
- **2H.4 §6.2–6.3:** group text states server is not in client group; socket table and decision updated to `2750`; boot/deployment requires proving setgid inheritance on pinned `/run`.
- **2H.5:** transport, deployment, live gate, resolved decisions, and checklist updated for `2750` setgid, kernel inheritance, and cross-UID deny.

**N-01 disposition:** **PARTIALLY RESOLVED — DOCUMENTATION/DESIGN COMPLETE; HOST EVIDENCE OPEN.** Implementation and pinned-host validation are still required.

---

## 4. N-02 — canonical firewall rule schema

**Finding (2I.3, High):** 2H.1 froze a 7-field TCP/UDP schema with no direction and rejected ICMP, while 2H.3 required direction/state/DNS and allowed optional ICMP. No single source of truth existed.

**Resolution:** `docs/PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md` §4.4.1 is the sole normative canonical schema (`rule-schema-v1`, protocol schema `2L.2I.2`). 2H.3 maps it to the backend, 2H.4 persists it, and 2H.5 tests it. No document defines a competing schema.

### 4.1 Canonical schema (normative summary)

| Field | Type | Required | Validation / normalization |
|---|---|---|---|
| `family` | string | yes | `ipv4` or `ipv6`; explicit; must be present in sorted unique `required_families` |
| `direction` | string | yes | `ingress` or `egress`; no bidirectional/implicit default; two rules required for both directions |
| `protocol` | string | yes | `tcp` or `udp` only in v1; `icmp`, `icmpv6`, `any`, SCTP, and others are `UNSUPPORTED_RULE` |
| `source_cidr` | string | yes | Canonical network CIDR wholly inside the ownership record's owned challenge network |
| `destination_cidr` | string | yes | Canonical network CIDR wholly inside the same owned challenge network |
| `port_start` | integer | yes | 1..65535, decimal integer |
| `port_end` | integer | yes | 1..65535 and `>= port_start` |
| `action` | string | yes | `accept` or `drop` |

**Structural rules:** `INSTALL_POLICY` requires 1..256 rules; each rule has exactly these eight fields; unknown/duplicate/missing fields rejected. Rule array order preserved. `required_families` is sorted, unique, and matches rule families. `compiled`, if present, is data-only and must be an exact canonical mirror (`schema_version` + `rules`) of top-level `rules`; it is never executed and never authorizes policy.

**CIDR/protocol semantics:** IPv4 dotted decimal, no leading zeroes/host bits; IPv6 RFC 5952 lowercase compressed, no brackets/zone/mapped forms. Reject `/0`, unspecified, loopback, link-local, multicast, reserved, benchmark, documentation, metadata, IPv4-mapped, and any CIDR not wholly within the owned challenge network. Full-range `1..65535` `accept` is rejected. DNS is not a separate field/protocol: explicit `tcp`/`udp` rule to an in-scope approved resolver on port 53 only. Connection state is not a field: backend conntrack may be used only for return traffic of an already-accepted canonical flow, never a global established/related bypass.

**ICMP/ICMPv6:** explicitly out of `rule-schema-v1` and deferred. The earlier 2H.3 "optional ICMP" allowance is superseded; v1 rejects ICMP/ICMPv6 as `UNSUPPORTED_RULE`. A future schema version must define type/code, ownership, and approval fields.

**Normalization/ambiguity:** canonical JSON has sorted object keys, no insignificant whitespace, UTF-8, lowercase hex, decimal integers, no floats/bools/null/NaN/Infinity/duplicate keys. CIDR representation is normalized only at representation level; host bits/prefixes/ports are never widened. Identical duplicates rejected; overlapping matches with different actions are `AMBIGUOUS_RULE`.

**Digests/versioning:** `compiled_rule_digest` is SHA-256 of canonical `rules` array (order preserved). `canonical_policy_digest` is SHA-256 of the canonical policy object containing policy/ownership identifiers plus `required_families` and `rules`. Rule schema is `rule-schema-v1`; protocol schema remains `2L.2I.2`. Future fields/protocols/ICMP require a new reviewed schema version and new digest domain; no silent dual acceptance and no legacy flat/`2L.2G.3` rule shape.

**Error mapping:** `INVALID_RULE`, `UNSUPPORTED_RULE`, and `AMBIGUOUS_RULE` added to the closed registry; `UNSUPPORTED_PROTOCOL` remains for envelope protocol class.

### 4.2 Layer mapping matrix

| Layer | Representation | Prohibited behavior |
|---|---|---|
| Transport (2H.1) | JSON rule objects with exactly the 8 canonical fields | Inferring identity/direction/family/protocol/ports; accepting ICMP/`any`/unknown fields |
| Broker (2H.1/2H.4) | Forwards same canonical fields after envelope/ownership authorization | Rewriting rules for convenience; accepting legacy shapes |
| Controller (2H.1/2H.4) | Validates, persists canonical JSON + digests, passes same rules to helper | Second rule language; trusting `compiled` without comparison |
| Helper (2H.1/2H.3) | Revalidates same fields and ownership/marker binding before backend access | Backend defaults, global state accepts, silent drops, `2L.2G.3` payload |
| Backend (2H.3) | Direct mapping of family/direction/protocol/CIDRs/ports/action to fixed nftables/iptables | Supporting undefined fields, host/LAN/metadata destinations, or approximate rules |
| Persistence/read-back (2H.4) | Stores/compares canonical JSON and digest; serializes observed rules back to 8 fields | Lossy summary, handle-only identity, CIDR/port normalization/widening |

### 4.3 2H document updates

- **2H.1:** added §4.4.1; replaced prior 7-field paragraph; added `direction` to the rule schema; explicitly rejected ICMP/ICMPv6; added `INVALID_RULE`/`UNSUPPORTED_RULE`/`AMBIGUOUS_RULE`; updated consistency rules.
- **2H.3 §3.3:** converted from independent field-definition table to backend mapping of `rule-schema-v1`; removed "optional ICMP only by explicit approved policy" as allowed v1 behavior and stated supersession; mapped direction/state/DNS as canonical semantics/constraints rather than separate schema definitions.
- **2H.4 §2.2:** added `canonical_policy_json`, `rule_schema_version`, and canonical policy persistence rules; prohibits lossy projection or silent normalization during persistence/recovery.
- **2H.5:** added `SCHEMA-01`–`SCHEMA-05` test requirements, canonical read-back tests, no legacy flat/`2L.2G.3` acceptance, and live-gate checklist item for canonical schema.

**N-02 disposition:** **PARTIALLY RESOLVED — DOCUMENTATION/DESIGN COMPLETE; IMPLEMENTATION/TEST EVIDENCE OPEN.** The schema contradiction is removed from the 2H target design; current helper/controller/broker code still uses older contracts and must be migrated with evidence.

---

## 5. N-03 — I-07/I-08/I-09 propagation and 2I.2 erratum

**Finding (2I.3):** I-07/I-08/I-09 were present in 2H.2 and 2H.5 but absent from 2H.1 §2.4, 2H.3 §1.1, and 2H.4 §1.3/final checklist; 2I.2 overstated consistency.

**Propagation applied (exact meaning preserved):**

| Residual | 2H.1 §2.4 | 2H.3 §1.1 | 2H.4 §1.3 | 2H.4 checklist | 2H.5 residuals/checklist |
|---|---|---|---|---|---|
| **I-07 — Broader identifier/field scope** | Yes | Yes | Yes | Yes (`RR-01..RR-07 and I-07..I-09`) | Yes |
| **I-08 — Raw `BrokerDBError` on non-failure paths** | Yes | Yes | Yes | Yes | Yes |
| **I-09 — `strict_auth=False` legacy footgun** | Yes | Yes | Yes | Yes | Yes |

Each propagated entry states the residual title, affected components, security impact, required mitigation, owner/workstream, and `OPEN` status with closure evidence.

**2I.2 erratum (Phase I cannot edit 2I.2):** `PHASE_2L_2I_2_TARGETED_ARCHITECTURE_BLOCKER_REMEDIATION.md` Section 13.1/consistency claims that I-07/I-08/I-09 are consistently tracked across all five 2H documents and that the addressed design decisions are internally consistent are **superseded/inaccurate in that specific respect**. I-07–I-09 were not fully propagated to 2H.1 §2.4, 2H.3 §1.1, and 2H.4 §1.3 at the time of 2I.3 review. This 2I.4 remediation adds the missing propagation and records the correction; 2I.2 remains the historical record and is not modified.

**N-03 disposition:** **DOCUMENTATION CORRECTED; TRACKING/ACCEPTANCE OPEN.** I-07, I-08, and I-09 remain open residuals and are not closed by propagation.

---

## 6. N-04 — broker/manager Docker authority and T-27 current-code note

**Finding (2I.3):** Source still contained Docker adapters; the "runtime adapter only" boundary was not mechanically enforced. T-27 needed a current-code note.

### 6.1 Current inspected code state (evidence)

| Component | Inspected evidence | Current state |
|---|---|---|
| Broker adapter wiring | `broker/app/dependencies.py:48` returns `BrokerDockerAdapter(docker_client=None, ownership_registry=..., network_ownership_registry=...)`; `broker/app/routes.py` injects `get_adapter()` into create/start/inspect/stop/remove/health routes | Wired to routes but clientless by default; adapter can accept a Docker client and implements container/network operations |
| Broker adapter behavior | `broker/app/docker_adapter.py` `_ensure_client()` raises `BrokerDockerError("Docker daemon unavailable")` when no client/API is present | Fails closed without client; no proven Docker reachability in inspected default wiring |
| Manager adapter | `manager/app/runtime/docker_adapter.py` exports `DockerRuntimeAdapter`; `manager/app/runtime/__init__.py` exports it; tests inject mock clients | Present/exported and mock-tested, but no manager route is wired to it in inspected code |
| Manager routes | `manager/app/routes.py` returns `503 Runtime manager not available` for runtime operations | No live runtime-adapter/Docker operation path observed in inspected routes |
| Runtime service | Source inspection | No separate `flaghunt-runtime` service or fixed-operation runtime UDS endpoint exists |
| Target residual | 2H.2 T-27, 2H.3 §5.7 | Rootful Docker access remains host-root-equivalent at the runtime adapter; proxying does not remove it |

### 6.2 Documentation updates and future restrictions

- **2H.1 §3.4/§6/§7/§8:** records current broker/manager adapter state as N-04/T-27 open and states the target has no broker/manager Docker authority.
- **2H.2:** T-27 current limitation updated to include broker wired/clientless adapter and manager exported/mock-tested adapter; residual states N-04 remains open; N-04 added to §6.2; RTA/validation mapping notes broker/manager denial.
- **2H.3 §5.7:** added current-code audit and required future restrictions table (allowed/rejected operations, authority ownership, fixed API boundary, resource restrictions, authentication/authorization, audit, failure behavior, testing/acceptance).
- **2H.5:** current/target rows, phase 2.7, gate checklist, resolved decisions, and 2.8 consistency rules updated to require broker and manager to have no Docker socket/group/API/import/route and to treat N-04 as open.

**Required future restrictions (design acceptance criteria):** only fixed `RUNTIME_*` catalog-bound operations; no arbitrary image/command/mount/namespace/capability/device/exec/pull/daemon API; only `flaghunt-runtime` may hold Docker socket/group; fixed UDS contract with `SO_PEERCRED`, ownership labels, catalog/spec digest, bounded resources, independent audit, fail-closed uncertain behavior, and explicit T-27 acceptance evidence.

**N-04 disposition:** **OPEN — SOURCE AUTHORITY REMAINS.** Documentation now records the current state and target restrictions, but no source change was made.

---

## 7. High/Medium finding status update

### 7.1 High findings (H-01–H-05)

| ID | Prior 2I.3 | 2I.4 disposition | Rationale |
|---|---|---|---|
| H-01 | OPEN | **PARTIALLY RESOLVED — DESIGN COMPLETE; HOST EVIDENCE OPEN** | N-01 selects and documents `2750` setgid + kernel inheritance + fail-closed verification across 2H.1/2H.3/2H.4/2H.5. No UDS/host proof exists. |
| H-02 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — DESIGN COMPLETE; CODE/TEST EVIDENCE OPEN** | Target broker/runtime boundary remains documented and strengthened; N-04 explicitly records remaining broker/manager adapters and required removal/negative tests. |
| H-03 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; IMPLEMENTATION OPEN** | No 2I.4 design conflict found; current request/header identity and digest behavior remain in code (`broker/app/auth.py`, `authorization_strict.py`, controller request identity fields) and require implementation/migration. |
| H-04 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; IMPLEMENTATION OPEN** | Direct-bind manager-broker UDS target remains documented; current broker is still HTTP/FastAPI with unsafe header merge and optional token behavior in inspected code. |
| H-05 | OPEN | **PARTIALLY RESOLVED — DESIGN COMPLETE; IMPLEMENTATION/TEST EVIDENCE OPEN** | N-02 establishes a single canonical rule schema in 2H.1 §4.4.1 and aligns 2H.3/2H.4/2H.5, but current helper/controller contracts and tests are not migrated. |

### 7.2 Medium findings (M-01–M-09)

| ID | Prior 2I.3 | 2I.4 disposition | Rationale |
|---|---|---|---|
| M-01 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; IMPLEMENTATION/TESTS OPEN** | Global-per-receiver idempotency remains the documented target; no schema/migration/test closure. |
| M-02 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; IMPLEMENTATION/TESTS OPEN** | Direct-bind socket lifecycle is now specified with setgid mechanism, but `broker/app/uds.py` and real UDS implementation/tests remain unvalidated. |
| M-03 | PARTIALLY RESOLVED | **DOCUMENTATION CORRECTED; TRACKING/ACCEPTANCE OPEN** | I-07/I-08/I-09 propagated to 2H.1/2H.3/2H.4/checklists and 2I.2 erratum recorded. Residuals themselves remain open. |
| M-04 | CLOSED — mapping only | **CLOSED — DOCUMENTATION/TRACEABILITY ONLY (UNCHANGED)** | Per-threat test mapping remains present; underlying tests/controls are not closed. |
| M-05 | CLOSED — register only | **CLOSED — DOCUMENTATION/TRACEABILITY ONLY (UNCHANGED)** | Threat-register additions remain present; underlying controls/tests are not closed. |
| M-06 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; IMPLEMENTATION/TESTS OPEN** | Append-only evidence/FKs/per-family derived states and canonical persistence rules are documented; schema/migration/tests remain open. |
| M-07 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; DEPLOYMENT ASSERTIONS OPEN** | Numeric IDs/paths/modes are documented, including setgid verification; no deployment/runtime proof. |
| M-08 | PARTIALLY RESOLVED | **PARTIALLY RESOLVED — TARGET DESIGN DOCUMENTED; IMPLEMENTATION/TESTS OPEN** | Canonical rule schema and migration direction are documented; current helper contract remains `2L.2G.3`-era and un-migrated. |
| M-09 | OPEN | **OPEN — HOST VALIDATION GATE** | No nftables/iptables/Docker/privilege/reboot/rollback/setgid-inheritance host tests executed. |

---

## 8. Cross-document consistency corrections

| Area | Correction |
|---|---|
| Socket modes/mechanism | All 2H socket-directory references aligned to `2750` setgid, owner-server/client-group, `0660` sockets, kernel inheritance, fail-closed verification. DB directory modes in 2H.4 remain `0750` where appropriate and are not socket directories. |
| Canonical schema source | 2H.1 §4.4.1 is the only rule-schema definition; 2H.3/2H.4/2H.5 map/persist/test it. ICMP/ICMPv6 rejected/deferred in v1; direction explicit; state/DNS not separate rule fields. |
| I-07/I-08/I-09 | Propagated to 2H.1 §2.4, 2H.3 §1.1, 2H.4 §1.3 and checklist; 2H.5 residual/checklist retained. |
| 2I.2 matrix | Not edited. Erratum recorded: 2I.2 overstated I-07–I-09 propagation/consistency for the affected residual lists. |
| N-04/T-27 | Current-code notes and future restrictions added; broker/manager no-target-Docker claim is design-only and open. |
| 2H.5/2H.2 tests | Added/recorded SOCK/PATH setgid checks and SCHEMA-01–SCHEMA-05 requirements; gate text now includes canonical schema and N-04 removal. |

---

## 9. Preserved findings and risk acceptances

Preserved and not closed by this phase: `F-01`–`F-14`, `H-01`–`H-05`, `M-01`–`M-09`, `T-11`, `T-13`, `T-27`, `RR-01`–`RR-07`, `I-07`–`I-09`, and `N-04`. `M-04`/`M-05` remain documentation-only closures. `T-11` and `T-13` remain `OPEN — ACCEPTANCE REQUIRED`. No residual is closed by design text alone.

---

## 10. Limitations

- Documentation-only. No implementation, migration, runtime, host, Docker, firewall, capability, reboot, rollback, or production validation was executed.
- The 2H documents in this workspace were pre-existing untracked files; edits were constrained to the permitted 2H set and the two new 2I reports.
- N-01 depends on pinned-host proof that `/run` honors setgid-directory group inheritance and that the exact UID/GID/mode model is deployable.
- N-02 depends on implementation and tests across broker/controller/helper/backend/persistence and migration away from current contracts.
- N-04 remains open in source; current broker adapter is wired but clientless and manager adapter is present but not route-wired in inspected code.
- 2I.2 historical text is unmodified by Phase I scope; the erratum in this report and 2I.5 supersedes its affected consistency claim.

---

## 11. Readiness decisions (2I.4 disposition)

| Area | Decision | Rationale |
|---|---|---|
| Architecture documentation | **CONDITIONAL — improved but not fully verified** | N-01/N-02/N-03/N-04 are addressed in design/documentation, but independent 2I.5 verification, host evidence, and implementation closure remain required. |
| Controlled host-validation planning | **CONDITIONALLY READY** | Planning may proceed only for the documented target: `2750` setgid UDS edges, canonical `rule-schema-v1`, no Docker authority for broker/manager, and explicit T-11/T-13/T-27/N-04 acceptance/evidence gates. |
| Live firewall integration | **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED** | No implementation, host validation, residual closure, or explicit authorization exists. |

**Gate statement:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
