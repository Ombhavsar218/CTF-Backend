# Post-J.20 Stage 1B.17 — Residual Risk Assessment (Mock-Only)

**Mandatory status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED

T-11, T-13, T-27 remain: OPEN — ACCEPTANCE REQUIRED

## Disposition of Stage 1B.16 findings addressed this milestone

| ID | Stage 1B.17 disposition | Residual note |
|---|---|---|
| R16-01 | Remediated in mock/test boundary (`broker/app/auth.py`) | Trusted transport identity wins; conflicting headers ignored+audited by field name. No real UDS/kernel identity implemented. |
| R16-05 | Remediated in strict + mock authorization providers | Caller-controlled `controller_verified` no longer suppresses trusted-flag rejection. |
| R16-08 | **Explicitly unresolved by design** | No production controller/authorizer/UDS wiring added (out of authorized scope). Mandatory status unchanged. |
| R16-02 | Remediated for reconciled promotions | Promotion paths now persist guarded reconciliation status; failures/conflicts are fail-closed/uncertain. |
| R16-03 | Partially remediated via explicit contract/rejection | Unsupported heuristic claims rejected; explicit `owned_network_cidrs` enforced when supplied. No authoritative CIDR source exists in current ownership persistence; absence of scope claim remains unsupported (no enforcement) for backward compatibility. |
| R16-06 | Remediated | Exact `policy_id:version` identity matching; overlapping `p1`/`p10` regressions pass. |
| R16-04 | Remediated at canonical validation boundary | Rules-only digest no longer accepted as canonical digest; full digest required. Internal legacy ownership alias for canonical-policy-body persistence remains an identified compatibility limitation (not a caller-accepted canonical digest at ingress). |
| R16-09 | Remediated | Representation-independent compiled mirror validation with bounded marker scan. |
| R16-07 | Remediated | Outward helper errors bounded/non-disclosing; exception type retained internally only. |
| R16-10 | Evidence completeness improved for Stage 1B.17 | Raw stdout/stderr/exit/duration retained for all runs. Historical 1B.13–1B.15 gaps (no stderr for some runs, reported-only counts, truncated artifacts) remain as previously recorded and are not retroactively repaired. |

## Remaining structural / authority risks (unchanged)

- T-11/T-13/T-27 remain OPEN — ACCEPTANCE REQUIRED; no named authority approval, signature or acceptance date was created or changed.
- No real UDS/SO_PEERCRED, kernel identity, privileged helper, Linux capabilities, nftables/iptables/DOCKER-USER, host firewall, Docker runtime/socket, cloud deployment, live backend or Stage 1C work performed.
- Production wiring of controller/auth/UDS is still absent (R16-08); mock/test seams remain distinguishable from production trust.
- Historical evidence governance gaps from Stage 1B.16 (missing stderr on older stages, reported-only counts 218/J.18 16/J.19 28, no authored final hash snapshot, truncated 1A1/1A2/j17 stdout, unresolved FK-pragma expectation conflict) remain documented and unresolved.
- No gate was closed, no acceptance state changed, no risk accepted by this milestone.

## Completion criteria

All safely addressable findings within the authorized mock-only boundary (R16-01 through R16-07, R16-09) were corrected with deterministic regression tests and full raw evidence. R16-08 was left explicitly unresolved because it requires unauthorized production wiring. R16-10 was satisfied for this milestone by preserving raw evidence for every run.

Status remains: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.
