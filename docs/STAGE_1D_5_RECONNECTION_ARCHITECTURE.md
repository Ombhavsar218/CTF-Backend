# Stage 1D.5 — Backend Reconnection Architecture Companion

**Date:** 2026-11-19  
**Security gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**Open items:** T-11, T-13, T-27 — **OPEN — ACCEPTANCE REQUIRED**

Canonical cross-stack document: `E:\Flag-hunt\ctf-platform\docs\STAGE_1D_5_RECONNECTION_ARCHITECTURE.md`.

---

## 1. Verified backend behavior

- Docker SDK `7.1.0` `exec_start(socket=True)` returns a transport-specific socket; there is no exec-stream reattach API.
- WebSocket disconnect closes only that exec stream and releases the `TerminalSession`.
- The container/instance is untouched: no `InstanceService.stop()`, `expire()`, `DockerAdapter.stop_container()`, or `remove_container()`.
- Ticket consumption is atomic and single-use; ownership/running/mode checks are re-run on ticket issue and WS admission.
- DB constraints and channel-layer revocation groups remain the shared multi-worker coordination mechanism.

## 2. Enforced policy

Controlled fresh shell. After an abnormal WebSocket close, the frontend may make at most four bounded reconnects. Each attempt obtains a fresh ticket and opens a new WebSocket; the backend creates a new fixed `/bin/sh` exec/PTY. No output replay, no exec reattachment, no server-side reconnect grace beyond ticket TTL and stale-session cleanup, and no false connected state.

## 3. Backend changes in this stage

- `terminal/consumers.py`: `_cleanup()` now skips `asyncio.current_task()` when cancelling/joining tasks. This fixes a recursive self-cancellation when an exec exits inside `_output_sender()` and `_close_with()` calls cleanup.
- `terminal/tests/test_reconnect_policy.py`: nine deterministic mocked tests for fresh-shell recovery, replay/expiry/non-owner/stopped-instance rejection, duplicate sessions, abandoned-session cleanup, exec exit, and no container lifecycle mutation.

No settings, migration, Docker adapter, Stage 1C lifecycle, or REST/WS contract changes were made.
