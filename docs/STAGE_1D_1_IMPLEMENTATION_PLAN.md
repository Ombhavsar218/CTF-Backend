# Stage 1D.1 — Interactive Docker Terminal Implementation Plan

**Status:** PROPOSED — NOT STARTED

**Date:** 2026-11-18

This plan sequences the future implementation of the architecture assessed in
`STAGE_1D_1_TERMINAL_ARCHITECTURE_ASSESSMENT.md` and the controls in
`STAGE_1D_1_TERMINAL_SECURITY_BOUNDARY.md`. It is a plan only: no source, tests,
dependencies, migrations, database records or Docker state were changed.

---

## 1. Guiding constraints

1. Keep Stage 1C HTTP instances working unchanged.
2. Keep all Docker SDK access in `challenge_runtime/`.
3. Never accept a container ID, exec ID, command or host path from the browser.
4. Disconnecting a terminal must not stop the container.
5. Every layer re-checks ownership and active status.
6. Add mocked tests first; keep real Docker tests opt-in and separate.
7. Preserve all existing uncommitted work; never reset/clean/stage/commit.

---

## 2. Phase A — Dependencies and ASGI foundation

**Goal:** make the Django project capable of serving WebSockets without yet
adding terminal behaviour.

### Changes

- Add backend packages (pin versions during implementation after compatibility
  check): `channels`, `daphne`, `channels-redis` (production/multi-process).
- Add frontend packages: `@xterm/xterm`, `@xterm/addon-fit`, optional
  `@xterm/addon-web-links`.
- Set `ASGI_APPLICATION = 'config.asgi.application'`.
- Replace `config/asgi.py` with a `ProtocolTypeRouter`:
  - `http` -> existing Django application;
  - `websocket` -> `URLRouter` from `terminal.routing`.
- Add `channels` and a new `terminal` app to `INSTALLED_APPS`.
- Add a `CHANNEL_LAYERS` setting:
  - `InMemoryChannelLayer` for local single-process tests;
  - `RedisChannelLayer` via `CACHE_URL`/dedicated setting for production.
- Extend CSP `connect-src` with `ws://localhost:8000`,
  `ws://127.0.0.1:8000` and the production `wss://` origin.
- Ensure the reverse proxy forwards `Upgrade`/`Connection` headers and that
  ingress never proxies the Docker socket.

### Gate

`manage.py check`, existing HTTP tests, J19 tests and the frontend harness all
still pass with no route/API change.

---

## 3. Phase B — Runtime mode configuration and safe metadata

**Goal:** let the backend and UI distinguish terminal challenges from HTTP
challenges without exposing runtime internals.

### Backend changes

- Add admin-only `Challenge` fields in a new migration:
  - `runtime_access_mode`: `http` (default) or `terminal`;
  - `runtime_terminal_command`: bounded JSON/string, default `/bin/sh`;
  - `runtime_terminal_user`: bounded string, default empty (image default).
- Extend `ChallengeWriteSerializer` and admin form handling with validation.
- Fix the Stage 1C residual gap where `ChallengeAdminSerializer` does not
  return runtime fields, so admin edits round-trip correctly.
- Add a non-secret derived public field (name proposed: `instanceMode`) to
  `ChallengePublicSerializer`: `http` or `terminal`.
- Change `build_connection_meta()`:
  - `http` mode: keep the existing `type/host/port/target/url` shape exactly;
  - `terminal` mode: no port required, return `{"type": "terminal"}` only;
  - remove `container_id` from public `connection_meta` for all modes.
- Relax `InstanceService.start()`/`ChallengeRuntimeService.start()` port
  requirement only for terminal mode; HTTP mode keeps current validation.

### Frontend changes

- `normalizeInstance()` exposes `mode`/`terminal` from the backend payload but
  invents nothing.
- `ChallengeDetails.jsx` chooses the control based on `instanceMode`:
  - HTTP -> existing `Open`;
  - terminal -> new `Open Terminal`.

### Gate

All existing configured challenges remain `http` and their Stage 1C HTTP
smoke test still passes unchanged. No existing record is modified by this plan
document.

---

## 4. Phase C — Docker exec/PTY adapter

**Goal:** add interactive exec capability inside the existing adapter boundary.

### Changes in `challenge_runtime/docker_adapter.py`

Add narrow methods that use the low-level API so the exec ID is retained:

```text
create_exec_session(container_id, command, user, tty=True) -> exec_id
start_exec_session(exec_id, tty=True) -> socket
resize_exec_session(exec_id, rows, cols)
inspect_exec_session(exec_id) -> {running, exit_code}
close_exec_session(socket, exec_id)
```

Implementation notes:

- `exec_create(..., stdin=True, stdout=True, stderr=True, tty=True,
  privileged=False)`;
- `exec_start(..., tty=True, socket=True)`;
- do not use `demux=True` with TTY;
- socket reads/writes happen off the ASGI event loop in a thread;
- set bounded socket timeouts/heartbeats appropriate for a long-lived stream;
- translate Docker SDK errors into existing `RuntimeErrorBase` subclasses.

### Changes in `challenge_runtime/service.py`

- Add `open_terminal_session(instance, challenge, rows, cols)` and
  `close_terminal_session(session)`.
- Re-resolve container ID from the DB; never take it from a caller.
- Verify Docker inspect says `running` before creating exec.
- Keep HTTP start/stop/reconcile paths unchanged.

### Gate

Mocked adapter tests assert exact low-level calls, TTY/stdin flags, resize and
cleanup. No real container is created in the default suite.

---

## 5. Phase D — Ticket, auth, consumer and session tracking

**Goal:** authenticate and stream terminal traffic safely.

### Backend changes

- `POST /api/v1/challenges/instances/terminal-ticket/`
  - `IsAuthenticated`;
  - DRF throttle `terminal_ticket` (proposed `10/minute`);
  - validates active running instance and limits;
  - returns `{ticket, url, expires_in}` only.
- `terminal/ticket.py`
  - random opaque ticket;
  - cache/DB record with `user_id`, `instance_id`, `expires_at`, `used`;
  - atomic single-use consume.
- `terminal/auth.py`
  - read `Sec-WebSocket-Protocol: flaghunt-terminal-v1, <ticket>`;
  - validate origin against `CORS_ALLOWED_ORIGINS` + same-origin;
  - reject missing/unknown origin and malformed ticket;
  - put authenticated user, instance and ticket into `scope`.
- `terminal/models.py`
  - `TerminalSession` with `user`, `instance`, `exec_id` (internal),
    `rows`, `cols`, `status`, timestamps; no public endpoint for exec IDs.
- `terminal/consumers.py`
  - accept only after ownership/status recheck;
  - `input` -> queued write to exec socket;
  - `resize` -> clamped `exec_resize`;
  - `output` -> bounded/capped socket reads;
  - `status`/`error` frames for lifecycle;
  - close exec/session on disconnect, not the container.
- `terminal/routing.py`
  - `ws/challenges/instances/terminal/`.

### Gate

Mocked Channels/WebSocket tests cover the ten security properties from the
security boundary document. Failed auth performs zero Docker calls.

---

## 6. Phase E — Expiry, stop and reconciliation integration

**Goal:** terminal sessions never outlive their instance.

### Changes

- Hook `TerminalSessionManager.close_all_for_instance(instance_id)` into:
  - `ChallengeRuntimeService.stop()`;
  - `ChallengeRuntimeService.expire()`;
  - `reconcile()` failure paths;
  - optional periodic sweep for sessions past expiry.
- Use a signal or explicit service call that avoids importing consumer modules
  from `instances/`.
- Send a channel-layer message so open consumers close promptly.
- Make cleanup idempotent and safe when Docker reports missing containers.

### Gate

Tests prove Stop/expiry closes exec sessions and sockets while no extra
container stop/remove call is introduced beyond the Stage 1C lifecycle.

---

## 7. Phase F — Frontend interactive terminal

**Goal:** render a real, interactive shell in the browser.

### Changes

- Add `src/services/terminalService.js`:
  - call `api.post('/challenges/instances/terminal-ticket/')`;
  - open WebSocket with subprotocols
    `['flaghunt-terminal-v1', ticket]`;
  - handle output/input/resize frames;
  - reconnect with capped exponential backoff and a fresh ticket.
- Add `src/components/ui/InteractiveTerminal.jsx`:
  - xterm.js + fit addon;
  - `onData` -> `input`, `onResize` -> `resize`;
  - font/colours from CSS variables;
  - bounded scrollback;
  - focus/keyboard accessibility and close button.
- Update `ChallengeDetails.jsx`:
  - show `Open Terminal` for terminal mode;
  - keep polling active instance while the terminal is open;
  - close on instance terminal status with a readable message;
  - leave the old `Open` link for HTTP mode.
- Keep `PowerShellTerminal.jsx` and decorative `Terminal.jsx` untouched as
  non-real UI components; do not reuse them as a shell.

### Gate

Frontend harness adds URL/auth/frame tests; `npm run build` succeeds.

---

## 8. Phase G — Testing and evidence

### Default mocked suite

- `challenge_runtime` adapter tests for exec create/start/resize/inspect/close.
- `terminal` tests for ticket issue/consume, origin rejection, auth rejection,
  ownership, status checks, limits, disconnect and cleanup.
- `instances` regression tests proving HTTP flow unchanged and no
  `container_id` in public `connection_meta`.
- Frontend harness tests for `terminalService` and mode-aware UI wiring.

### Opt-in real Docker suite

 Separate module, skipped unless `FLAGHUNT_REAL_DOCKER_TESTS=1`:

- create a terminal-mode challenge with a small Linux image;
- start via real Stage 1C lifecycle;
- issue ticket and connect through real Channels stack;
- send a command whose output proves a PTY (for example `stty size`);
- send input and verify output;
- send resize and verify changed dimensions;
- disconnect and verify container still running;
- stop via existing API and verify container/network removed;
- assert no `flaghunt.managed=true` containers/networks remain.

### Required test commands during implementation

```powershell
# backend (default, Docker mocked)
.\venv\Scripts\python.exe manage.py test instances challenge_runtime terminal -v 1

# opt-in real Docker integration
$env:FLAGHUNT_REAL_DOCKER_TESTS='1'
.\venv\Scripts\python.exe manage.py test terminal.tests.test_real_docker -v 1
Remove-Item Env:FLAGHUNT_REAL_DOCKER_TESTS

# existing regression suites
.\venv\Scripts\python.exe manage.py test instances challenge_runtime -v 1
# J19 broker suite from its documented entry point

cd ..\ctf-platform
node scripts\challenges-harness\run.mjs
npm run build
```

---

## 9. Acceptance criteria

Stage 1D may be called implemented only when all are true:

- [ ] HTTP Stage 1C challenges still start/open/stop exactly as before.
- [ ] Terminal challenges can start and show an interactive xterm shell.
- [ ] Keystrokes, PTY output and resize work in a real opt-in Docker test.
- [ ] Only the authenticated owner can open a terminal for an active instance.
- [ ] Stopped/expired/failed instances are rejected at ticket and WS connect.
- [ ] Browser never supplies container/exec IDs or commands.
- [ ] No Docker SDK import outside `challenge_runtime/`.
- [ ] Disconnect leaves the container running; Stop/expiry closes sessions.
- [ ] Public payloads contain no container/exec IDs.
- [ ] Origin, ticket, rate and size limits are tested.
- [ ] No privileged container, host mount, host shell or socket exposure.
- [ ] All suites and build pass; Git state preserved with no commit.

---

## 10. Rollback / guardrails

- Feature-gate the new WS route and ticket endpoint behind a setting
  (proposed `FLAGHUNT_TERMINAL_ENABLED`, default off during rollout).
- Keep `runtime_access_mode` defaulting to `http`, so existing records remain
  HTTP-only.
- Do not delete or repurpose Stage 1C container cleanup paths.
- If a release must be rolled back, disabling the route/ticket endpoint leaves
  the HTTP workflow intact; no migration rollback should be required for the
  default `http` value.
- Never clean, reset, revert, stage or commit existing working-tree changes as
  part of this work.
