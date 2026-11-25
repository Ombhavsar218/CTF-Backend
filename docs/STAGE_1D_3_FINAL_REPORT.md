# Stage 1D.3 — Final Report

**Date:** 2026-11-19  
**Stage:** Docker Interactive Exec and PTY Integration  
**Final status:** **BACKEND DOCKER EXEC/PTY INTEGRATION IMPLEMENTED — BROWSER INTERACTIVE TERMINAL NOT COMPLETE.**

---

## 1. Executive summary

Stage 1D.3 connected the Stage 1D.2 authenticated WebSocket gateway to a real
Docker exec/PTY adapter in `challenge_runtime/`.

Delivered:

- one dedicated interactive exec per authorized WebSocket connection;
- server-side container resolution and fresh ownership/lifecycle/running checks;
- TTY + stdin + fixed backend `/bin/sh`, never a browser-supplied command;
- separated create/start/read/write/resize/inspect/close operations;
- bounded JSON/base64 terminal I/O with rate and buffer limits;
- validated PTY resize with integer and dimension bounds;
- DB-backed exec coordination, cross-worker revocation, and stale-session reaping;
- disconnect cleanup that closes only the exec stream;
- Stage 1C lifecycle cleanup for stop/expiry/failure/reconciliation;
- mocked regression coverage plus a passed real-Docker integration test.

The browser-based interactive terminal is still **not complete**. Frontend
xterm.js integration, reconnect/resume behavior, and browser end-to-end testing
remain outstanding.

---

## 2. Mandatory safety status

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

T-11, T-13 and T-27 remain:

**OPEN — ACCEPTANCE REQUIRED**

No firewall-controller, UDS/SO_PEERCRED, privileged-helper, host firewall,
CAP_NET_ADMIN, cloud, or production work was performed. No Stage 1B gate was
closed. Previously identified findings remain deferred and open.

---

## 3. Mock-tested functionality

Deterministic mocked/isolated tests passed:

- exec creation with `/bin/sh`, `tty=True`, `stdin=True`, `privileged=False`;
- rejection of non-owners, stopped instances, non-terminal challenges, and
  stopped/missing containers;
- no PID 1 attach, no host command path;
- browser-supplied container/exec/user/command identifiers ignored;
- input and output forwarding over the authenticated WebSocket;
- resize validation, bounds, and rate limiting;
- disconnect cleanup without container stop/remove;
- instance-stop revocation and client notification;
- Docker error and container-disappearance handling;
- repeated cleanup/idempotency and stale connection reaping;
- Stage 1D.2 ticket/Origin/subprotocol/session-limit regressions;
- existing HTTP challenge regression behavior;
- blocking-read/input-write concurrency regression.

Command result: `Ran 78 tests ... OK (skipped=2)`.

---

## 4. Real-Docker-tested functionality

The opt-in real test passed against Docker Engine 29.6.1 with a disposable,
unprivileged `alpine:3.20` container:

- real terminal-mode Stage 1C instance start without a published port;
- real TTY exec shell starts inside the user's own container;
- written input reaches the shell and output is received;
- `exec_resize(40, 100)` succeeds and `stty size` reports `40 100`;
- closing the exec leaves the container running;
- Stage 1C stop removes the container and network;
- no managed test container/network remains after the test.

Command result: `Ran 1 test in 12.643s ... OK`.

This is a backend real-Docker verification only. It is not a browser terminal
test and does not imply frontend readiness.

---

## 5. Remaining limitations

1. No xterm.js or frontend terminal UI; no frontend file was changed.
2. No browser end-to-end test, reconnect, or resume behavior.
3. Stage 1C HTTP `connection_meta` still contains `container_id`; terminal-mode
   metadata does not. Removing the HTTP field would change existing HTTP
   behavior and was deliberately deferred.
4. Ticket consumption still occurs before all post-authentication checks, so a
   failed connect can burn an otherwise valid single-use ticket. Exec creation
   itself is rechecked.
5. Stage 1C `QuerySet.update()` status transitions do not fire `post_save`; the
   consumer watchdog and Beat cleanup cover them within their intervals.
6. `revoke_for_user()` remains unwired to user-disable events.
7. Byte/rate limits are per ASGI worker. Production needs the Redis channel
   layer; PostgreSQL is recommended over SQLite for row-lock semantics even
   though conditional unique constraints protect session caps.
8. No live firewall integration, privileged helper, UDS/SO_PEERCRED, CAP_NET_ADMIN,
   host firewall change, cloud deployment, or production deployment.
9. T-11, T-13 and T-27 remain open and require acceptance.

---

## 6. Unresolved security concerns

- The public Stage 1C HTTP API still exposes `container_id` in HTTP-mode
  `connection_meta`.
- Production origin allowlist, WSS configuration, Redis channel layer, and
  workspace/container isolation still require security review before any
  public rollout.
- Interactive shell access is inherently powerful inside the challenge
  container; existing Stage 1C restrictions must remain intact and should be
  re-audited before public exposure.
- Terminal I/O is logged nowhere by design, which also means there is no
  session recording or audit trail of shell commands yet.

Nothing in this stage marks any previously identified finding fixed or accepted.

---

## 7. Git state and preservation evidence

### Before implementation

```text
BE HEAD   b3655841ffc0a0cea2cfd33ad56d7ed355a4d068
BE BRANCH main
BE STATUS modified 28 / staged 0 / untracked 287 collapsed / 770 expanded

FE HEAD   453cbe2b0a017dbd643ff6f77746f85f9965b8d7
FE BRANCH main
FE STATUS modified 36 / staged 0 / untracked 43 collapsed / 11 expanded
```

### After implementation

```text
BE HEAD   b3655841ffc0a0cea2cfd33ad56d7ed355a4d068
BE BRANCH main
BE STATUS modified 28 / staged 0 / untracked 287 collapsed / 782 expanded

FE HEAD   453cbe2b0a017dbd643ff6f77746f85f9965b8d7
FE BRANCH main
FE STATUS modified 36 / staged 0 / untracked 43 collapsed / 11 expanded
```

No `git reset`, `git clean`, `git checkout`, destructive restore, `git add`, or
`git commit` was run. No unrelated modified or untracked file was removed or
overwritten. No frontend file was changed.

---

## 8. Every file changed by this stage

Modified or newly added backend files:

1. `.env.example`
2. `challenge_runtime/errors.py`
3. `challenge_runtime/exec_session.py` *(new)*
4. `challenge_runtime/docker_adapter.py`
5. `challenge_runtime/service.py`
6. `challenge_runtime/tests/test_exec_adapter_mocked.py` *(new)*
7. `challenge_runtime/tests/test_real_exec_integration.py` *(new)*
8. `challenge_runtime/tests/test_terminal_mode_lifecycle.py` *(new)*
9. `config/settings.py`
10. `instances/services.py`
11. `terminal/consumers.py`
12. `terminal/models.py`
13. `terminal/migrations/0002_terminalsession_close_reason_and_more.py` *(new)*
14. `terminal/ratelimits.py` *(new)*
15. `terminal/services.py`
16. `terminal/tests/helpers.py`
17. `terminal/tests/test_exec_stream.py` *(new)*
18. `terminal/tests/test_ratelimits.py` *(new)*
19. `terminal/tests/test_session_registry.py`
20. `terminal/tests/test_websocket_gateway.py`
21. `docs/STAGE_1D_3_DOCKER_EXEC_PTY_IMPLEMENTATION.md` *(new)*
22. `docs/STAGE_1D_3_TERMINAL_STREAM_SECURITY.md` *(new)*
23. `docs/STAGE_1D_3_TEST_EVIDENCE.md` *(new)*
24. `docs/STAGE_1D_3_FINAL_REPORT.md` *(new)*

---

## 9. Completion determination

Stage 1D.3 meets its backend completion criteria: a dedicated Docker exec/PTY
session can be created and bridged to the authenticated WebSocket, resize is
bounded, lifecycle cleanup is implemented, focused mocked tests pass, existing
HTTP and Stage 1D.2 regression tests pass, a real-Docker backend test passed,
and documentation/Git evidence is complete.

The browser-based interactive terminal remains incomplete pending frontend
xterm.js integration and end-to-end verification in later stages.
