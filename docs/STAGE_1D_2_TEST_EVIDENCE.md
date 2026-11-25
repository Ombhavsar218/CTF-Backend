# Stage 1D.2 — Test Evidence

**Date:** 2026-11-19  
**Method:** Django test runner, Windows PowerShell, `ctf-platform-be/venv`.  
**Marker:** All new Stage 1D.2 tests are mocked/isolated. No real Docker daemon
operation, no real terminal exec, and no frontend test was added.

## 1. Static and configuration checks

```powershell
.\venv\Scripts\python.exe manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

```powershell
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Result:

```text
No changes detected
```

```powershell
.\venv\Scripts\python.exe manage.py migrate
```

Result:

```text
Applying challenges.0003_stage_1d_terminal_access_mode... OK
Applying terminal.0001_initial... OK
```

Dependency verification:

```text
channels      4.3.2
daphne        4.2.3
channels-redis 4.3.0
asgiref       3.12.1
```

Docker SDK import scan confirmed direct `docker` imports remain confined to
`challenge_runtime/` (adapter and its mocked tests). No terminal/gateway module
imports the Docker SDK or daemon.

## 2. New Stage 1D.2 mocked suite

```powershell
.\venv\Scripts\python.exe manage.py test terminal -v 1
```

Result:

```text
Found 36 test(s).
Ran 36 tests in 35.817s
OK
```

Coverage by module:

| Module | Tests | What it proves |
| --- | ---: | --- |
| `test_ticket_api.py` | 8 | route contract, unauthenticated rejection, opaque 201 response, no internal IDs, cross-user access ignored, inactive/non-terminal/runtime-unavailable rejection, per-user throttle |
| `test_websocket_gateway.py` | 12 | accepted handshake with label-only subprotocol, single-use replay, expired ticket, wrong Origin, null Origin, invalid subprotocol, malformed ticket, session cap, oversized frame, disconnect cleanup/no container stop, stop revocation broadcast, no exec path |
| `test_session_registry.py` | 13 | hash-only storage, replay/expiry/revocation/malformed/binding checks, two-thread concurrent consume, session caps, release, instance revocation, cleanup task, issuer failure redaction, terminal-mode gate |
| `test_runtime_confirm.py` | 3 | read-only Docker inspect with managed ownership, foreign container rejection, non-running rejection |

The `ERROR django.request ... Service Unavailable` line in this run is expected
output from the deliberate runtime-failure test.

## 3. Stage 1C/API/config regression suite

```powershell
.\venv\Scripts\python.exe manage.py test instances challenge_runtime config challenges -v 1
```

Result:

```text
Found 151 test(s).
Ran 151 tests in 131.055s
OK (skipped=1)
```

This includes the existing HTTP instance workflow tests (start → active → stop),
Stage 1C Docker adapter/service mocked tests, config/deployment tests, and
challenge API/serializer tests after adding `runtime_access_mode`.

## 4. Remaining app suites

```powershell
.\venv\Scripts\python.exe manage.py test achievements announcements audit notifications ops platform_settings submissions users -v 1
```

Result:

```text
Found 519 test(s).
Ran 519 tests in 492.539s
OK
```

`ops/tests.py` was an existing untracked file whose Beat assertion expected only
`phase14-heartbeat`. It was updated to expect the already-present
`stage1c-instance-cleanup` and the new `stage1d2-terminal-cleanup`; this was a
test expectation fix, not a production behavior change.

The tracebacks in this run are expected negatives from tests that deliberately
simulate unavailable audit services, unhealthy Celery, and concurrent hint/
submission conflicts. The suite returned OK.

## 5. Combined app-scoped total

| Group | Tests | Result |
| --- | ---: | --- |
| New terminal gateway | 36 | OK |
| Stage 1C/API/config/challenges | 151 | OK, 1 skipped |
| Remaining apps | 519 | OK |
| **Total app-scoped** | **706** | **OK, 1 skipped** |

## 6. Full-discovery limitation (not claimed as passing)

```powershell
.\venv\Scripts\python.exe manage.py test -v 1
```

The full-discovery attempt found 709 tests and exceeded the 600-second command
budget. It also discovers pre-existing untracked root-level test modules that
are outside the application suites. `--failfast` reproduced the first import
failure:

```text
ImportError: Failed to import test module: test_digest
File "E:\Flag-hunt\ctf-platform-be\test_digest.py", line 4, in <module>
TypeError: ValidatedRuntimeSpec.__init__() takes 14 positional arguments but 15 were given
```

This untracked file predates Stage 1D.2 and was left untouched. Therefore this
report does **not** claim a clean full-discovery run; it claims the 706
app-scoped tests above passed.

## 7. What was explicitly not tested

- No real-Docker test was run for Stage 1D.2.
- No interactive terminal execution was tested because it does not exist.
- No xterm.js/browser test was run; no frontend files changed.
- No production WSS/Redis deployment test was run.
- No firewall-controller or runtime-manager test was modified.

## 8. Test classification

| Classification | Stage 1D.2 evidence |
| --- | --- |
| Deterministic mocked tests | All 36 new terminal tests |
| Isolated infrastructure | In-memory channel layer, mocked `InstanceService`/runtime, mocked Docker adapter |
| Real integration | None in this stage |
| Frontend | Unchanged |
| Real Docker | Deferred to Stage 1D.3 opt-in integration suite |
