# Stage 1D.3 — Test Evidence

**Date:** 2026-11-19  
**Method:** Django test runner, Windows PowerShell, `ctf-platform-be/venv`.  
**Marker:** Mocked tests are deterministic and isolated. Real Docker results are
reported separately and required an explicit opt-in environment variable.

---

## 1. Static checks

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

Migration applied during implementation:

```text
Applying terminal.0002_terminalsession_close_reason_and_more... OK
```

Python compilation check for all changed runtime/gateway modules completed
without errors.

---

## 2. Docker SDK and engine inspection

Verified with `inspect.signature` in the project virtual environment:

```text
docker==7.1.0
exec_create(self, container, cmd, stdout=True, stderr=True, stdin=False,
            tty=False, privileged=False, user='', environment=None,
            workdir=None, detach_keys=None)
exec_start(self, exec_id, detach=False, tty=False, stream=False,
           socket=False, demux=False)
exec_resize(self, exec_id, height=None, width=None)
exec_inspect(self, exec_id)
```

Engine details:

```text
PING True
VERSION 29.6.1
BASE_URL http+docker://localnpipe
```

`exec_start(socket=True)` was confirmed to return `docker.transport.npipesocket.NpipeSocket`
with `recv`/`sendall`, not a conventional Python socket. This drove the
transport-aware read/write wrapper and the separation of read and write locks.

A source scan confirmed direct Docker imports remain confined to
`challenge_runtime/` source; other matches are test assertions in unrelated
manager/broker tests. No source call to `container.attach()` or `exec_run()`
exists; the only textual match is a docstring stating that attach is not used.

---

## 3. Mocked Stage 1D.3 and regression tests

```powershell
.\venv\Scripts\python.exe manage.py test challenge_runtime terminal -v 1
```

Final result:

```text
Ran 78 tests in 54.912s
OK (skipped=2)
```

The two skips are the opt-in real Docker tests. Coverage includes:

- exec creation with TTY, stdin, no privileges, fixed `/bin/sh`;
- read/write/resize/inspect/close as separate bounded operations;
- blocking output read does not block input/write/close;
- ownership, status, mode, and running-container rejection;
- browser-supplied container/exec/user/command identifiers ignored;
- WebSocket input and output forwarding;
- resize bounds and malformed dimension rejection;
- disconnect cleanup and no container stop/remove;
- instance stop revocation and notification;
- Docker error and container disappearance handling;
- ticket/Origin/subprotocol/session-limit Stage 1D.2 regressions;
- stale-session reaping and repeated cleanup idempotency;
- HTTP-mode port validation and terminal-mode start compatibility.

---

## 4. Wider backend regressions

```powershell
.\venv\Scripts\python.exe manage.py test instances challenge_runtime config challenges -v 1
```

Result:

```text
Ran 167 tests in 125.685s
OK (skipped=2)
```

```powershell
.\venv\Scripts\python.exe manage.py test achievements announcements audit notifications ops platform_settings submissions users -v 1
```

Result:

```text
Ran 519 tests in 561.140s
OK
```

The logged `ERROR` lines in those runs are intentional negative-path tests
(exception handling, audit unavailability, request-ID redaction checks, and
concurrent SQLite lock scenarios). They are not test failures.

---

## 5. Real Docker integration result — PASSED

The test is skipped by default and was run explicitly:

```powershell
$env:FLAGHUNT_REAL_DOCKER_TESTS='1'
.\venv\Scripts\python.exe manage.py test challenge_runtime.tests.test_real_exec_integration -v 1
Remove-Item Env:FLAGHUNT_REAL_DOCKER_TESTS
```

Final result:

```text
Ran 1 test in 12.643s
OK
```

What this real test verified on Docker Engine 29.6.1 using a disposable
unprivileged `alpine:3.20` container:

1. Stage 1C started a terminal-mode challenge without a published port.
2. `ChallengeRuntimeService.open_terminal_session()` created a real TTY exec.
3. A real `/bin/sh` shell started inside the user's own container.
4. Written input `echo STAGE1D3_PTY_OK\n` produced matching output.
5. `exec_resize(40, 100)` succeeded; `stty size` returned `40 100`.
6. Closing the exec left the challenge container `running`.
7. `InstanceService.stop()` removed the container and network.
8. No managed container or network with the test instance label remained.

### Defect found and fixed during real-Docker verification

The first real run hung at input writing. Root cause: `ExecSession.read()`
held a single RLock while performing a blocking named-pipe read, so the main
thread could not acquire the lock to write input. The wrapper was changed to
use separate read and write/control locks. A mocked regression test
(`test_blocking_output_read_does_not_block_input_write`) now prevents this bug
from returning. The final real-Docker run passed after this fix.

---

## 6. Not claimed

- A full `manage.py test` run is **not** claimed as clean. The previously
  identified untracked `test_digest.py` failure remains unrelated to this stage
  (`ValidatedRuntimeSpec.__init__()` arity mismatch), and earlier full-suite runs
  exceeded the time budget.
- No frontend test or build was run; no frontend file was changed.
- No browser-based end-to-end terminal test exists yet.
- No live firewall-controller, UDS/SO_PEERCRED, privileged-helper, host firewall,
  cloud, or production deployment verification was performed.
