# Stage 1D.5 — Backend Session Recovery Security Companion

**Date:** 2026-11-19  
**Security gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**Open items:** T-11, T-13, T-27 — **OPEN — ACCEPTANCE REQUIRED**

Canonical cross-stack document: `E:\Flag-hunt\ctf-platform\docs\STAGE_1D_5_SESSION_RECOVERY_SECURITY.md`.

---

## 1. Backend controls retained on every reconnect

- SHA-256 ticket hashes with atomic single-use conditional consume.
- 30-second default ticket TTL.
- Ticket binding to user and instance; mismatched user consume is rejected.
- Exact Origin allowlist and exact `flaghunt-terminal-v1` + ticket subprotocols.
- Active/running/terminal-mode/ownership recheck on issue and WS admission.
- DB-backed per-user/per-instance active session limits.
- Channel-layer revocation and Celery stale-state cleanup.
- All Docker SDK access remains inside `challenge_runtime/`.

## 2. Recovery boundary

There is no tool-supported stream reattachment, so a new shell is the only supported recovery. The old exec ID and ticket are never reused; previous output is not replayed. The browser receives only generic status/error reasons, never IDs, endpoints, commands, users, tickets, or ownership records.

## 3. Security result

No firewall integration, privileged helper, host firewall change, production deployment, or Stage 1B closure occurred. Production still requires Redis channel layers and preferably PostgreSQL; SQLite/in-memory defaults remain development-oriented.
