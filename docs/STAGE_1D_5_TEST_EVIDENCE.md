# Stage 1D.5 — Backend Test Evidence Companion

**Date:** 2026-11-19  
**Security gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**Open items:** T-11, T-13, T-27 — **OPEN — ACCEPTANCE REQUIRED**

Canonical cross-stack evidence: `E:\Flag-hunt\ctf-platform\docs\STAGE_1D_5_TEST_EVIDENCE.md`.

---

## Commands and results

From `E:\Flag-hunt\ctf-platform-be` using `venv\Scripts\python.exe`:

- `manage.py check` — no issues.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `manage.py test terminal.tests.test_reconnect_policy -v 1` — 9 tests, OK.
- `manage.py test terminal -v 1` — 57 tests, OK. A first run showed one intermittent pre-existing SQLite ticket-consumption race failure; the isolated test and repeated full suite passed.
- `manage.py test challenge_runtime terminal -v 1` — 87 tests, OK, skipped=2.
- `manage.py test instances config challenges -v 1` — 137 tests, OK.
- `manage.py test achievements announcements audit broker manager notifications platform_settings submissions users -v 1` — 490 tests, OK.
- `FLAGHUNT_REAL_DOCKER_TESTS=1 manage.py test challenge_runtime.tests.test_real_exec_integration -v 1` — 1 test, OK.

A whole-tree `manage.py test` is deliberately not claimed clean because the pre-existing untracked top-level `test_digest.py` fails with `TypeError: ValidatedRuntimeSpec.__init__() takes 14 positional arguments but 15 were given`.

Mocked ASGI/DB tests are not Docker E2E. The real Docker test exercises the adapter directly; browser-to-real-Docker E2E remains outstanding.
