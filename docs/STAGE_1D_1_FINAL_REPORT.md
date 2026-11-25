# Stage 1D.1 — Interactive Docker Web Terminal Architecture Inspection: Final Report

**Status:** INSPECTION COMPLETE — TERMINAL FUNCTIONALITY NOT IMPLEMENTED

**Date:** 2026-11-18

---

## 1. Executive summary

Stage 1C provides a working, authenticated, Docker-backed **HTTP** challenge
instance lifecycle. It does not provide an interactive terminal.

The recommended Stage 1D architecture is:

- **xterm.js** in the React SPA for rendering and keystroke/resize capture;
- a **Django Channels / Daphne** ASGI WebSocket gateway in the existing Django
  backend;
- an authenticated, short-lived, single-use **terminal ticket** obtained via
  the existing REST/JWT flow and presented as a WebSocket subprotocol;
- strict server-side resolution of the student's own active instance;
- a dedicated **Docker exec + PTY + resize** adapter inside the existing
  `challenge_runtime/` package;
- session tracking and cleanup tied to the existing Stage 1C Stop/expiry/
  reconcile lifecycle;
- explicit HTTP vs terminal challenge mode with default `http`, preserving all
  existing challenge behaviour.

No terminal endpoint, consumer, adapter method, frontend component, dependency,
migration or test was added during this stage.

---

## 2. Deliverables created

| File | Contents |
| --- | --- |
| `docs/STAGE_1D_1_TERMINAL_ARCHITECTURE_ASSESSMENT.md` | Verified Stage 1C baseline, Docker SDK PTY/resize capability check, architecture decision, endpoints, modules and compatibility. |
| `docs/STAGE_1D_1_TERMINAL_SECURITY_BOUNDARY.md` | Trust boundaries and concrete controls for the ten required security properties, data classification and verification checklist. |
| `docs/STAGE_1D_1_IMPLEMENTATION_PLAN.md` | Phased implementation sequence, files to add/change, test strategy, acceptance criteria and rollback guardrails. |
| `docs/STAGE_1D_1_FINAL_REPORT.md` | This report. |

---

## 3. Verified existing capabilities

### Backend

- `instances/models.py` — seven instance statuses, one-active-instance DB
  constraint, expiry metadata, internal IDs, public `connection_meta`.
- `instances/services.py` — ownership-scoped start/active/stop, expiry
  retirement, conflict/failure handling, single-active invariant.
- `instances/views.py` — `IsAuthenticated` on all instance endpoints; no
  client-supplied instance ID for active/stop.
- `instances/serializers.py` — bounded public instance payload with
  `remaining_seconds` and `failure_reason`.
- `instances/tasks.py` and `config/settings.py` — cleanup task scheduled every
  60 seconds via Celery Beat.
- `instances/urls.py` / `config/urls.py` — real routes under `/api/v1/`.
- `challenge_runtime/` — sole Docker SDK boundary; image pull, isolated bridge
  network, loopback port publish, hardened container creation, inspect, stop,
  remove and reconcile.
- Installed `docker==7.1.0` exposes the low-level primitives needed later:
  `exec_create`, `exec_start(socket=True)`, `exec_resize`, `exec_inspect`,
  `attach_socket` and container `resize`. `exec_run(socket=True)` does not
  return the exec ID, so direct low-level calls are required for resize.

### Frontend

- `challengeService.js` uses the real instance endpoints and a
  `normalizeInstance()` adapter.
- `ChallengeDetails.jsx` shows Start/Stop/Open, status, countdown and errors,
  and polls while starting/stopping.
- `api.js` attaches the existing localStorage Bearer JWT and refreshes once on
  HTTP 401.
- Existing `Terminal.jsx` and `PowerShellTerminal.jsx` are simulated/local UI
  only; neither is connected to a container.

### Platform

- DRF uses SimpleJWT (15-minute access default) plus session auth.
- CORS dev default is `http://localhost:5173`; production defaults to no
  cross-origin origins.
- Redis, Celery worker and Beat run via Docker Compose; Django runs on the host.

---

## 4. Missing capabilities

| Capability | Current state |
| --- | --- |
| ASGI/WebSocket runtime | Plain Django ASGI wrapper only; no `ASGI_APPLICATION`, Channels, Daphne or channel layer. |
| Terminal auth | No JS WebSocket ticket flow; native WS cannot send the existing Bearer header directly. |
| Docker exec/PTY | Adapter has no exec, TTY, stdin, resize, inspect-exec or stream methods. |
| Container attach readiness | Stage 1C containers are not created with `stdin_open`/`tty`; attach to PID 1 is unsafe. |
| Session tracking | No terminal session model, limit, registry or cleanup hook. |
| Expiry integration | Container cleanup exists, but terminal sessions do not exist to clean up. |
| Browser terminal | No xterm.js dependency or interactive terminal component. |
| Challenge mode | No public `http` vs `terminal` distinction; port is required for all runtime challenges. |
| Safe metadata | `connection_meta` currently includes a Docker container ID that must not be public. |
| Admin round-trip | `ChallengeAdminSerializer` omits Stage 1C runtime fields even though the write serializer accepts them. |
| CSP for WS | `connect-src` has no `ws:`/`wss:` origins. |
| Origin/limits | No WS origin validation, frame/rate/size limits or ticket throttle. |

---

## 5. Architecture recommendation

Use a dedicated Channels consumer behind a ticket-authenticated WebSocket,
delegating all container interaction to the existing Docker adapter.

### Lifecycle

1. Existing Stage 1C Start creates the student's container.
2. UI reads a new non-secret `instanceMode` and shows `Open Terminal` or the
   unchanged HTTP `Open` link.
3. `POST /api/v1/challenges/instances/terminal-ticket/` authenticates the
   existing JWT, resolves the caller's active running instance, and returns a
   one-time ticket.
4. `new WebSocket(..., ['flaghunt-terminal-v1', ticket])` connects to
   `/ws/challenges/instances/terminal/`.
5. Middleware validates origin and consumes the ticket; the consumer rechecks
   ownership/status and opens a TTY exec session using the DB-resolved
   container ID.
6. xterm `onData`/`onResize` map to exec socket writes and `exec_resize`; exec
   socket bytes stream back to xterm.
7. Disconnect closes only the exec session. Stop/expiry/reconcile closes all
   sessions and leaves container cleanup to Stage 1C.

### Endpoints

Existing unchanged:

- `POST /api/v1/challenges/<pk>/instances/start/`
- `GET|DELETE /api/v1/challenges/instances/active/`

New:

- `POST /api/v1/challenges/instances/terminal-ticket/`
- `WS /ws/challenges/instances/terminal/`

### Dependencies

Backend: `channels`, `daphne`, `channels-redis` (multi-process/production).  
Frontend: `@xterm/xterm`, `@xterm/addon-fit`, optional
`@xterm/addon-web-links`.

---

## 6. Security boundaries

The full control set is in `STAGE_1D_1_TERMINAL_SECURITY_BOUNDARY.md`. Summary:

1. Instance lookup is always scoped to the authenticated user.
2. Container/exec IDs are resolved server-side; browser input never names
   them; current public `connection_meta.container_id` must be removed.
3. Browser has no Docker socket path; only the backend adapter imports `docker`.
4. Gateway exec targets the assigned container only; commands/users are
   fixed/admin-configured, never browser-supplied; no host shell.
5. Ticket and session rows bind user + instance; one active session by default.
6. Stopped/expired/failed instances are rejected at ticket, connect and during
   the stream.
7. WebSocket subprotocol ticket + explicit Origin allowlist + TLS in prod.
8. Defined frame, rate, buffer, resize, session and global connection limits.
9. Disconnect closes the exec session, never the container.
10. Stop/expiry/reconcile close sessions idempotently.

Explicit prohibitions remain: no privileged containers/exec, host mounts,
Docker socket exposure, unrestricted host commands, CAP_NET_ADMIN, host firewall
changes or privileged helpers.

---

## 7. Compatibility with HTTP challenges

The HTTP workflow is preserved by making terminal access an explicit opt-in:

- new `runtime_access_mode` defaults to `http`;
- HTTP challenges keep port publishing and the current `connection_meta` shape;
- terminal challenges need no published port;
- `runtime_terminal_command`/`runtime_terminal_user` are admin-only and not
  browser-controlled;
- `instanceMode` is public and non-secret, so the UI can choose the right
  control without leaking image, command, port or IDs;
- no existing challenge record was changed during this inspection.

---

## 8. Proposed implementation sequence

1. **Phase A** — dependencies, ASGI router, channel layer, CSP WS origins.
2. **Phase B** — runtime mode fields, safe metadata, remove public container ID,
   fix admin serializer round-trip.
3. **Phase C** — `exec_create/start/resize/inspect/close` adapter methods and a
   narrow runtime service API.
4. **Phase D** — ticket endpoint, origin/ticket middleware, session model,
   consumer and limits.
5. **Phase E** — session cleanup on Stop/expiry/reconcile.
6. **Phase F** — xterm.js service/component and mode-aware `ChallengeDetails`.
7. **Phase G** — mocked tests, opt-in real Docker PTY/resize test, full harness,
   build and evidence update.

Acceptance is defined in `STAGE_1D_1_IMPLEMENTATION_PLAN.md`. Terminal
functionality must not be claimed until those checks pass.

---

## 9. Git state before and after

| Repository | HEAD | Branch | State | Modified tracked | Staged | Untracked collapsed | Untracked expanded |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| BE before | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | `main` | before inspection | 27 | 0 | 284 | 740 |
| BE after | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | `main` | four new untracked docs | 27 | 0 | 284 | 744 |
| FE before | `453cbe2b0a017dbd643ff6f77746f85f9965b8d7` | `main` | before inspection | 36 | 0 | 43 | 11 |
| FE after | `453cbe2b0a017dbd643ff6f77746f85f9965b8d7` | `main` | unchanged | 36 | 0 | 43 | 11 |

New untracked BE files:

```text
docs/STAGE_1D_1_TERMINAL_ARCHITECTURE_ASSESSMENT.md
docs/STAGE_1D_1_TERMINAL_SECURITY_BOUNDARY.md
docs/STAGE_1D_1_IMPLEMENTATION_PLAN.md
docs/STAGE_1D_1_FINAL_REPORT.md
```

No reset, clean, revert, stage or commit was performed. No application source,
test, dependency file, migration, Docker state or database record was changed.

---

## 10. Final statement

The architecture is ready to implement, but **interactive terminal access does
not exist yet**. It requires the ASGI/Channels, ticket/auth, exec/PTY, session
cleanup and xterm.js work described in the implementation plan, followed by
mocked and opt-in real Docker verification.
