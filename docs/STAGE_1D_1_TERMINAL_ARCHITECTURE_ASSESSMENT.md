# Stage 1D.1 — Interactive Docker Web Terminal Architecture Assessment

**Status:** INSPECTION AND ARCHITECTURE ASSESSMENT ONLY — NO TERMINAL FUNCTIONALITY IMPLEMENTED

**Date:** 2026-11-18  
**Workspace:** `E:\Flag-hunt`  
**Backend:** `ctf-platform-be`  
**Frontend:** `ctf-platform`

---

## 1. Purpose and scope

This document inspects the completed Stage 1C Docker-backed challenge instance
implementation and assesses what is required to add an interactive,
browser-based Linux terminal whose commands run inside the authenticated
student's assigned Docker container.

It is a read-only architecture inspection. No application source, tests,
dependencies, Docker state, database records or migrations were changed.

Out of scope for this assessment:

- implementing the terminal;
- installing packages;
- creating/starting/stopping/removing containers;
- modifying the firewall-controller/manager architecture;
- changing host firewall rules or adding privileged helpers;
- exposing the Docker socket anywhere outside the existing backend process.

---

## 2. Verified Stage 1C baseline

### 2.1 Backend instance lifecycle

| Area | Verified current behaviour |
| --- | --- |
| `instances/models.py` | `ChallengeInstance` stores `user`, `challenge`, `status`, `expires_at`, `stopped_at`, `failure_reason`, internal container/network identifiers, public `connection_meta`, and timestamps. DB constraint `unique_active_instance_per_user` allows at most one non-terminal instance per user. Terminal states are `stopped`, `expired`, `failed`. |
| `instances/services.py` | `InstanceService.start()` validates that the challenge is published, `runtime_enabled`, has `runtime_image` and `runtime_internal_port`; retires expired rows; reserves the instance in a transaction; and delegates Docker work to `ChallengeRuntimeService`. `active()` resolves only the caller's own non-terminal row and expires stale rows. `stop()` stops only the caller's row. |
| `instances/views.py` | `InstanceStartView` requires `IsAuthenticated`; `InstanceActiveView` requires `IsAuthenticated` for both `GET` and `DELETE`. No instance ID is accepted for active/stop — the user is always resolved from the request. |
| `instances/serializers.py` | Public serializer exposes `id`, challenge fields, `status`, `expires_at`, `remaining_seconds`, `created_at`, `stopped_at`, `connection_meta`, `failure_reason`. Internal name/container/network ID fields are not listed. |
| `instances/tasks.py` | `instances.cleanup_expired` calls `InstanceService().cleanup()`. |
| `config/settings.py` | Beat schedules `stage1c-instance-cleanup` every 60 seconds by default. |
| `instances/urls.py` | `POST /api/v1/challenges/<pk>/instances/start/`, `GET|DELETE /api/v1/challenges/instances/active/`. |
| `config/urls.py` | Includes `instances.urls` under `/api/v1/`. |

### 2.2 Docker runtime adapter

`challenge_runtime/` contains the only Docker SDK access:

- `config.py` — `RuntimeConfig` reads `FLAGHUNT_DOCKER_HOST`, timeout,
  publish host (`127.0.0.1` default), instance duration, stop/cleanup timeouts.
- `errors.py` — bounded runtime error types.
- `docker_adapter.py` — lazy `docker.from_env()` client; `ensure_image`,
  `create_network`, `create_container`, `inspect_container`,
  `find_container_by_name`, `stop_container`, `remove_container`,
  `remove_network`, `list_managed_containers`.
- `service.py` — lifecycle orchestration, labels, connection metadata builder,
  start/stop/expire/reconcile.

Verified container hardening in `create_container()`:

- bridge network per instance with inter-container communication disabled;
- loopback-published internal port only;
- `privileged=False`;
- `cap_drop=['ALL']`;
- `security_opt=['no-new-privileges:true']`;
- CPU quota, memory limit, PID limit;
- read-only root filesystem with a bounded `rw,noexec,nosuid` `/tmp` tmpfs;
- `restart_policy={'Name': 'no'}` and `auto_remove=False`;
- managed labels `flaghunt.managed=true`, instance/user/challenge IDs.

There are currently **no** `exec_create`, `exec_start`, `exec_resize`,
`exec_inspect`, `attach`, `attach_socket`, TTY or PTY methods in the adapter.

### 2.3 Authentication and HTTP API

- DRF authenticates with SimpleJWT first, then session auth.
- `SIMPLE_JWT` uses a 15-minute access lifetime by default, rotating refresh
  tokens and blacklisting after rotation.
- The SPA stores `cyberforge_access` and `cyberforge_refresh` in `localStorage`;
  `src/services/api.js` attaches `Authorization: Bearer <access>` and performs
  one refresh-and-retry on HTTP 401.
- CORS dev default is `http://localhost:5173`; production defaults to no
  cross-origin origins.
- CSP `connect-src` currently lists only `http://localhost:5173`,
  `http://127.0.0.1:5173`, `http://localhost:8000` and
  `http://127.0.0.1:8000`. It has no `ws:`/`wss:` entries.

### 2.4 ASGI / WebSocket status

- `config/asgi.py` is the Django-generated plain
  `get_asgi_application()` wrapper.
- No `ASGI_APPLICATION` setting exists.
- `INSTALLED_APPS` has no `channels` app.
- `requirements.txt` has `asgiref==3.12.1` (a Django dependency) but no
  `channels`, `daphne`, `channels-redis`, `websockets` or `wsproto`.
- No WebSocket consumer, routing, ASGI middleware or channel layer exists in
  the backend.
- Repository-root `docker-compose.yml` runs Redis, Celery worker and Beat;
  Django remains on the Windows host. There is no ASGI service.

### 2.5 Frontend status

- `package.json` has no xterm.js package and no WebSocket client library.
- `src/services/challengeService.js` calls the real instance endpoints and
  `normalizeInstance()` derives connection data only from backend
  `connection_meta`.
- `src/pages/ChallengeDetails.jsx` polls `getInstance()` while provisioning,
  shows a countdown, and renders Start/Stop/Open controls. The "Open" link is
  rendered only when `instance.connection.url` exists, so it only supports the
  HTTP flow.
- `src/components/ui/Terminal.jsx` is a decorative animation with hard-coded
  lines. It does not accept input or connect to any backend.
- `src/components/ui/PowerShellTerminal.jsx` is a local mock command emulator
  driven by `src/data/challenges.js` and `useApp()`. It does not connect to a
  container and must not be mistaken for terminal infrastructure.

Neither existing terminal component is reusable as a real shell.

### 2.6 Verified Docker SDK capabilities (installed `docker==7.1.0`)

Read-only inspection of the installed SDK source confirmed:

- `Container.exec_run(..., stdin=True, tty=True, socket=True)` creates an exec
  instance and returns a socket when `socket=True`.
- Low-level `APIClient.exec_create()` and `exec_start()` are available.
- `APIClient.exec_resize(exec_id, height, width)` exists and resizes the exec
  PTY.
- `APIClient.exec_inspect(exec_id)` exposes exec state/exit code.
- `Container.attach_socket()` and `APIClient.resize(container, height, width)`
  exist for container-level attach/resize.

Important nuance: `exec_run(socket=True)` returns an `ExecResult(None, socket)`
and **does not expose the generated exec ID**. A terminal gateway that needs
resize must call `exec_create()` and `exec_start()` directly so it can retain
the ID for `exec_resize()` and `exec_inspect()`.

### 2.7 Current public metadata concern

`challenge_runtime.service.build_connection_meta()` currently includes
`container_id` from Docker inspection, and `ChallengeInstancePublicSerializer`
serializes the whole `connection_meta` object. Although the model comment says
internal identifiers are never serialized, the full container ID therefore
reaches normal authenticated API clients today.

Stage 1D must treat that value as internal-only: remove it from public
`connection_meta` (or strip it in the serializer) before exposing terminal
tickets. The terminal gateway must never accept a browser-supplied container ID
or exec ID.

---

## 3. Terminal architecture assessment

### 3.1 Browser terminal: xterm.js

**Recommendation:** use the modern scoped xterm.js packages:

- `@xterm/xterm`
- `@xterm/addon-fit`
- optionally `@xterm/addon-web-links`

Requirements verified against the intended design:

- render UTF-8/ANSI output from the container PTY;
- send raw keystrokes with `term.onData(...)`;
- send resize events with `term.onResize(...)`;
- theme with existing CSS variables rather than hard-coded colours;
- fit to a modal/drawer container and re-fit on window resize;
- cap scrollback (e.g. 5,000 lines) to bound browser memory.

xterm.js alone is only a renderer/input surface — it provides no transport,
authentication or container access.

### 3.2 WebSocket gateway: Django Channels

**Recommendation:** Django Channels with Daphne is the best fit for this
Django/DRF project.

Rationale:

- Channels integrates with Django auth, settings and ORM.
- `ProtocolTypeRouter` cleanly separates HTTP and WebSocket traffic.
- Custom middleware can validate an authenticated terminal ticket and origin
  before the consumer runs.
- A channel layer lets REST views and consumers exchange cleanup events across
  processes.
- `channels_redis` can reuse the existing Redis deployment for the layer.

Alternative considered and rejected: a separate FastAPI terminal gateway.
The repository already has a FastAPI runtime-manager package, but reusing it
would introduce a second auth model, a second deployment unit and a second
place that can touch Docker. That weakens the single-adapter boundary and is
unnecessary for the existing Django-centric stack.

Deployment implication: add an ASGI entry point (`ASGI_APPLICATION`) and an
ASGI server. For local development, Daphne via `runserver` is acceptable. For
production, run Daphne/Uvicorn behind the existing TLS reverse proxy with
`Upgrade` support. The standalone manager's Uvicorn is a separate component
and must not be repurposed.

### 3.3 Process execution inside the assigned container

**Recommendation:** create a dedicated interactive shell using Docker exec,
not Docker attach to PID 1.

Use low-level adapter calls:

1. `api.exec_create(container_id_from_db, cmd=[shell], stdin=True,
   stdout=True, stderr=True, tty=True, privileged=False, user=fixed_user)`
2. `api.exec_start(exec_id, tty=True, socket=True)` -> raw bidirectional socket
3. `api.exec_resize(exec_id, rows, cols)` on xterm resize
4. `api.exec_inspect(exec_id)` for state/exit checks
5. close the socket and mark the DB session closed on disconnect/cleanup

Why exec, not attach:

- Stage 1C containers were created without `stdin_open=True` and `tty=True`,
  so attach cannot provide a usable interactive stdout/stdin stream as-is.
- Attaching targets the container's PID 1 — the challenge service itself. A
  student could stop it with Ctrl-C or `exit`, breaking the challenge.
- Exec creates an isolated shell process. Closing that shell does not stop the
  container.
- Exec keeps the existing Stage 1C command and HTTP port workflow untouched;
  no container recreation is needed for terminal challenges.

### 3.4 PTY, resize and streaming requirements

A fully functional terminal requires all of the following:

| Requirement | Current Stage 1C | Required addition |
| --- | --- | --- |
| PTY allocation | Absent | `tty=True` on `exec_create` and `exec_start` |
| Bidirectional stdin | Absent, `stdout=False`/`stderr=False` on container create | `stdin=True` on exec; socket read/write bridge |
| Merged stdout/stderr | Absent | TTY mode; do not `demux` when `tty=True` |
| Terminal size | Absent | Send initial rows/cols; handle `onResize`; call `api.exec_resize` |
| Binary-safe streaming | Absent | Forward UTF-8/binary bytes without JSON re-encoding per keystroke where possible |
| Blocking I/O isolation | Not applicable | Docker SDK is synchronous; run socket reads/writes in a thread, not the ASGI event loop |
| Exit detection | Absent | `exec_inspect` / socket EOF; close WebSocket with a clear reason code |

Plain non-TTY `exec_run` does not allocate a PTY, so programs see no terminal,
job control and line editing behave differently, and `stty size` returns no
usable dimensions. Plain attach without `stdin_open`/`tty` is likewise not an
interactive shell. This must not be assumed to "just work".

### 3.5 Session, disconnect and reconnect behaviour

Recommended behaviour:

- One active terminal session per active instance (configurable cap, default
  1). Additional connections are rejected with a policy error.
- Browser disconnects close only the exec socket/session. They **never** call
  `InstanceService.stop()`, `expire()` or Docker stop/remove.
- On reconnect, issue a new ticket and start a new exec shell. Shell-local state
  is intentionally not preserved; container filesystem/process state is.
- If persistent shell history is required later, run `tmux`/`screen` inside the
  challenge image and attach to it from the gateway. That is a later enhancement
  and not required for Stage 1D.
- While a terminal is open, the frontend continues polling the active instance
  so it can close the UI when the instance becomes stopped/expired/failed.

### 3.6 Expiry and cleanup integration

Reuse the Stage 1C lifecycle rather than creating a parallel timer:

- `InstanceService.stop()` and `ChallengeRuntimeService.expire()` already
  mark the instance terminal and remove the container/network.
- Add a terminal-session cleanup hook invoked from that same path (e.g. a
  signal on status transition or an explicit session-manager call) to close
  exec sockets, mark session rows closed and notify the browser.
- `reconcile()` already detects missing/non-running containers; mark any
  terminal sessions for those instances closed too.
- A periodic sweeper can close sessions whose `expires_at` has passed as a
  defence in depth; the container cleanup remains authoritative.

---

## 4. Recommended concrete architecture

### 4.1 Component boundaries

```
Browser (React)
  xterm.js <-> terminalService <-> WebSocket
                    |
                    | single-use ticket (subprotocol), no Docker IDs
                    v
Django ASGI / Channels
  Origin + ticket auth middleware
        |
        v
  TerminalConsumer  --- ORM: ChallengeInstance (user + active status)
        |
        v
  TerminalSessionManager --- DB session row + limits + expiry
        |
        v
  challenge_runtime.exec adapter (only place importing docker)
        |
        v
  Student's own Docker container (exec shell with PTY)
```

Strict boundary rule: `views.py`, `serializers.py`, consumers and React code
must never import or call the Docker SDK. All Docker operations stay inside
`challenge_runtime/`, matching the Stage 1C decision.

### 4.2 Request lifecycle

1. Student clicks **Start Instance**. Existing Stage 1C endpoints create the
   container as today.
2. Once `instance.status == 'running'`, the UI decides whether to show
   **Open Terminal** or **Open** based on a new public, non-secret instance
   mode (see §6).
3. Student clicks **Open Terminal**. React calls
   `POST /api/v1/challenges/instances/terminal-ticket/` with the existing
   Bearer token.
4. Django resolves the caller's own active instance, rejects terminal
   statuses/expiry, enforces per-user/session limits, creates a single-use
   short-TTL ticket bound to `(user_id, instance_id)` in the cache, and returns
   the ticket plus the WS path.
5. React opens `new WebSocket(wsUrl, ['flaghunt-terminal-v1', ticket])`.
   The ticket is carried as a WebSocket subprotocol instead of a URL query
   parameter, so it is not written into proxy/referrer logs.
6. Channels middleware validates origin and consumes the ticket atomically.
   It loads the instance via `user=request.user` and rejects non-running,
   expired or foreign instances.
7. Consumer asks `challenge_runtime` to create a TTY exec session using the
   server-side container ID, retaining `exec_id`.
8. Consumer starts a background thread that reads exec socket bytes and sends
   them to the browser. Browser `onData` bytes are written back via a
   thread-safe queue. `onResize` calls `exec_resize`.
9. Disconnect closes the exec socket/session and marks the DB row closed. The
   container keeps running until explicit Stop, expiry or reconciliation.
10. Stop/expiry closes all related terminal sessions and notifies open sockets.

### 4.3 WebSocket authentication flow

- Native browser WebSockets cannot set arbitrary `Authorization` headers.
- Existing SPA JWTs remain in `localStorage`; the REST ticket endpoint uses
  the existing `api.post()` wrapper and therefore the existing Bearer refresh
  flow.
- The ticket is opaque, random, single-use, bound to user + instance, and
  expires in approximately 30 seconds.
- Channels checks:
  - exact advertised subprotocol;
  - ticket presence and single-use consumption;
  - `Origin` against an explicit allowlist derived from
    `CORS_ALLOWED_ORIGINS` plus same-origin;
  - authenticated user from ticket (not from a client-supplied ID);
  - active, running, non-expired instance owned by that user.
- A ticket must not grant a second connection after it has been consumed.
- Reconnection requests a new ticket.

### 4.4 Expected endpoints

**Existing, unchanged**

- `POST /api/v1/challenges/<pk>/instances/start/`
- `GET /api/v1/challenges/instances/active/`
- `DELETE /api/v1/challenges/instances/active/`

**New**

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/challenges/instances/terminal-ticket/` | Authenticated; issue a one-time terminal ticket for the caller's active running instance. Returns `{ ticket, url, expires_in }` and no container/exec IDs. |
| `WS` | `/ws/challenges/instances/terminal/` | Authenticated by subprotocol ticket; bidirectional terminal stream. Client sends `input` and `resize` frames; server sends `output`, `status` and `error` frames. |
| `GET` | `/api/v1/challenges/instances/<id>/terminal-sessions/` (admin/debug only) | Optional operational view of session counts/status; never exposes exec IDs publicly. |

Protocol frames (proposed):

```jsonc
// client -> server
{"type": "input",  "data": "<base64 or text chunk>"}
{"type": "resize", "rows": 24, "cols": 80}

// server -> client
{"type": "output", "data": "<base64 or text chunk>"}
{"type": "status", "state": "connected|disconnected|expired|closed"}
{"type": "error",  "message": "Human-readable, bounded message"}
```

Binary-safe transport should be used for `input`/`output`. Base64 is an
acceptable JSON-compatible fallback but adds overhead.

### 4.5 Required backend modules (future work)

| Module | Responsibility |
| --- | --- |
| `config/asgi.py` | `ProtocolTypeRouter` with HTTP + WebSocket application. |
| `config/settings.py` | `channels`, `terminal` apps; `ASGI_APPLICATION`; `CHANNEL_LAYERS`; terminal origin/limit settings; CSP `ws/wss` entries. |
| `terminal/auth.py` | Ticket issue/consume middleware and origin validation. |
| `terminal/consumers.py` | WebSocket protocol, framing, limits, send/receive bridge. |
| `terminal/session.py` | Session manager, per-instance caps, cleanup hooks. |
| `terminal/ticket.py` | Cache-backed one-time ticket service. |
| `terminal/models.py` | Internal `TerminalSession` rows (no public exec IDs). |
| `terminal/routing.py` | WebSocket URL routing. |
| `terminal/urls.py` | Ticket endpoint. |
| `challenge_runtime/docker_adapter.py` | Add exec create/start/resize/inspect/close methods using retained `exec_id`. |
| `challenge_runtime/service.py` | Expose a narrow `open_terminal_session(instance)` API to the consumer. |
| `instances/services.py` / `challenge_runtime/service.py` | Invoke terminal cleanup on stop/expire/reconcile without importing consumer code. |

### 4.6 Required frontend modules (future work)

| File | Responsibility |
| --- | --- |
| `src/services/terminalService.js` | Request ticket, build WS URL/subprotocol, reconnect backoff, close codes. |
| `src/components/ui/InteractiveTerminal.jsx` | xterm.js instance, fit addon, input/resize wiring, bounded scrollback. |
| `src/pages/ChallengeDetails.jsx` | Show **Open Terminal** for terminal mode; manage modal/drawer lifecycle; keep polling instance state while open. |
| `src/services/challengeService.js` / `normalizeInstance()` | Propagate a public `mode`/`terminal` flag without fabricating connection data. |
| `package.json` | Add xterm.js packages when implementation begins. |

### 4.7 Required dependencies (install only during implementation)

Backend:

- `channels`
- `daphne` (ASGI server for development/production)
- `channels-redis` if multi-process or production channel layer is required
- existing `docker==7.1.0`, Django 5.2, DRF, SimpleJWT, Redis/Celery remain

Frontend:

- `@xterm/xterm`
- `@xterm/addon-fit`
- optional `@xterm/addon-web-links`

No new dependency may touch the Docker socket from the browser or execute host
commands.

---

## 5. Compatibility with existing HTTP challenges

The Stage 1C HTTP workflow must remain byte-for-byte compatible for existing
challenges:

- same Start/Active/Stop endpoints;
- same Docker container creation, loopback port publishing and inspection;
- same `connection_meta` shape for HTTP/HTTPS (`type`, `host`, `port`,
  `target`, `url`);
- same frontend Start/Stop/Open flow when the challenge is HTTP mode;
- same one-active-instance-per-user constraint and expiry cleanup.

### Proposed mode configuration

Add an explicit admin-only field rather than inferring mode from category or
`runtime_connection_type`:

```text
runtime_access_mode: "http" | "terminal"   (default "http")
```

Optionally add:

```text
runtime_terminal_command: JSON array or string  (default ["/bin/sh"])
runtime_terminal_user: string                   (default image user / fixed ctf user)
```

Rules:

- `http` keeps the current Stage 1C requirement for
  `runtime_internal_port` and published-port metadata.
- `terminal` does not require a published port; `connection_meta` contains a
  non-secret marker such as `{"type": "terminal"}`.
- Terminal command/user are administrator-configured, never browser-supplied.
- A public, derived `instanceMode`/`accessType` may be added to
  `ChallengePublicSerializer` so the UI can choose **Open Terminal** vs
  **Open** without exposing image, command, port or internal IDs.
- Existing challenge records must **not** be modified during this inspection;
  the default `http` preserves their current behaviour.

Note: `ChallengeAdminSerializer` currently omits the Stage 1C runtime fields
even though `ChallengeWriteSerializer` accepts them, so admin edit round-trips
do not currently preserve runtime configuration. This should be remediated in
the implementation phase, but is not changed here.

---

## 6. Conclusion

Stage 1C provides a solid, well-isolated **HTTP instance** foundation:
authenticated REST endpoints, one active instance per user, real Docker
lifecycle, expiry cleanup and a loopback-published connection URL.

It does **not** provide an interactive terminal. The missing capabilities are:
a public access-mode distinction, terminal-aware connection metadata, ASGI and
Channels, a JWT-to-ticket authentication flow, an exec/PTY/resize adapter,
session tracking and cleanup, an xterm.js frontend, and limit/origin enforcement.

The recommended design is a Django Channels WebSocket gateway that consumes a
single-use REST-issued ticket, resolves the instance strictly from the
authenticated user, and delegates all Docker work to a new exec/PTY section of
the existing `challenge_runtime` adapter. Disconnects close only the exec
session; container lifecycle remains owned by Stage 1C Stop/expiry/reconcile.

No terminal functionality exists yet. Implementation and testing are required
before making any functional claim.
