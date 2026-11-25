# Stage 1D.5 — Backend Final Report Companion

**Final status:** BACKEND BOUNDED FRESH-SHELL RECOVERY COMPLETE — FULL BROWSER-TO-DOCKER E2E OUTSTANDING  
**Security gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11 / T-13 / T-27:** **OPEN — ACCEPTANCE REQUIRED**

Canonical cross-stack final report: `E:\Flag-hunt\ctf-platform\docs\STAGE_1D_5_FINAL_REPORT.md`.

---

## 1. Backend result

The backend already implemented the safe recovery boundary: WebSocket disconnect closes only the exec stream and DB session, never the container. Stage 1D.5 verified that Docker SDK cannot reattach a closed exec stream and enforced the fresh-shell policy primarily through the frontend recovery contract.

One backend source fix was required: `terminal/consumers.py` `_cleanup()` no longer cancels and joins `asyncio.current_task()`, preventing recursive self-cancellation when an exec exits from inside `_output_sender()`.

Nine deterministic tests were added in `terminal/tests/test_reconnect_policy.py`. All backend checks, focused suites, regression suites, and the opt-in real Docker exec test passed; see `STAGE_1D_5_TEST_EVIDENCE.md`.

---

## 2. Backend changed files

1. `terminal/consumers.py` — lifecycle cleanup fix.
2. `terminal/tests/test_reconnect_policy.py` — new deterministic reconnect tests.
3. `docs/STAGE_1D_5_RECONNECTION_ARCHITECTURE.md` — new.
4. `docs/STAGE_1D_5_SESSION_RECOVERY_SECURITY.md` — new.
5. `docs/STAGE_1D_5_TEST_EVIDENCE.md` — new.
6. `docs/STAGE_1D_5_FINAL_REPORT.md` — new.

No settings, migrations, Docker adapter code, Stage 1C lifecycle, REST/WS contract, firewall, deployment, or production configuration was changed.

---

## 3. Git state

- HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`, branch `main`.
- Pre-change: modified `28`, staged `0`, untracked `782` expanded.
- Post-change: modified `28`, staged `0`, untracked `787` expanded.
- No destructive Git operations, staging, or commits were performed.
