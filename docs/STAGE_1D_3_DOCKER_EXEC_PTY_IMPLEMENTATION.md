# Stage 1D.3 — Docker Exec/PTY Implementation

**Date:** 2026-11-19  
**Scope:** Backend-only Docker interactive exec adapter and WebSocket bridge.  
**Status:** Backend exec/PTY foundation implemented. Frontend integration is not implemented.

---

## 1. Outcome

Stage 1D.3 connects the Stage 1D.2 authenticated WebSocket gateway to one
dedicated interactive Docker exec session per authorized connection.

Implemented capabilities:

- server-side resolution of the authenticated instance's container;
- ownership, lifecycle, mode, and running-container rechecks immediately before
  exec creation;
- TTY-enabled, stdin-enabled, non-privileged exec using the fixed backend shell
  `/bin/sh`;
- separated adapter operations for create/start/read/write/resize/inspect/close;
- bounded JSON/base64 WebSocket input/output with rate and buffer limits;
- validated and bounded PTY resize;
- DB-backed exec coordination fields and cross-worker revocation;
- disconnect cleanup that closes only the exec stream, never the container;
- Stage 1C lifecycle stop/expiry/reconciliation closes terminal sessions.

No `container.attach()` call is used. PID 1 is never modified. No Docker socket,
container ID, exec ID, host path, command, or user is accepted from a browser
frame.

---

## 2. Architecture

```
Browser (future xterm.js)
   |  JSON text frames: input(base64) / resize(rows,cols) / ping
   v
Stage 1D.2 TicketAuthMiddleware -> TerminalGatewayConsumer
   |  server-side user/instance/ticket context only
   v
ChallengeRuntimeService.open_terminal_session()
   |  ownership + active + terminal-mode + confirm_running()
   v
DockerAdapter -> Docker API exec_create / exec_start / exec_resize / exec_inspect
   |
   v
ExecSession wrapper (internal only) -> transport-specific socket
```

All Docker SDK access remains inside `challenge_runtime/`. `terminal/`
imports only `challenge_runtime.service` and bounded exception types. No raw
Docker object, API response, socket, container ID, or exec ID is returned to an
API client.

---

## 3. Installed Docker SDK behavior verified

Environment observed before implementation:

- Python package `docker==7.1.0`;
- Docker Engine `29.6.1`;
- client base URL `http+docker://localnpipe` on this Windows host.

Exact signatures verified by `inspect.signature`:

```text
exec_create(self, container, cmd, stdout=True, stderr=True, stdin=False,
            tty=False, privileged=False, user='', environment=None,
            workdir=None, detach_keys=None)
exec_start(self, exec_id, detach=False, tty=False, stream=False,
           socket=False, demux=False)
exec_resize(self, exec_id, height=None, width=None)
exec_inspect(self, exec_id)
```

`exec_start(..., socket=True)` returns an API-client/transport-specific raw
object, **not a normal Python socket**. On this host it is a `NpipeSocket`
with `recv/sendall`; on Unix it can be a `SocketIO`; over SSH it can be a
channel. `_get_raw_response_socket()` also attaches the HTTP response as
`_response` so closing the returned wrapper and that response releases the
upgrade connection.

The adapter therefore:

- never calls `recv()`/`send()` directly on an assumed socket type;
- uses `docker.utils.socket.read()` for reads;
- uses `sendall`, `send`, `write`, or `os.write` as the transport provides;
- closes both the transport wrapper and its attached response;
- uses separate read and write/control locks so a blocking output read cannot
  deadlock input, resize, or close. This defect was found and fixed during real
  Docker verification.

---

## 4. Files changed or added

### Docker runtime

- `challenge_runtime/errors.py` — added bounded exec exception types.
- `challenge_runtime/exec_session.py` — new internal `ExecSession` wrapper.
- `challenge_runtime/docker_adapter.py` — added seven separated exec operations.
- `challenge_runtime/service.py`
  - `open_terminal_session()` performs all server-side checks and opens one exec;
  - `close_terminal_session()` / `inspect_terminal_session()` delegate to adapter;
  - `confirm_running()` now also checks the managed user label;
  - terminal-mode `connection_meta` is `{'type': 'terminal'}` with no container ID;
  - HTTP-mode `connection_meta` keeps its Stage 1C shape.
- `challenge_runtime/tests/test_exec_adapter_mocked.py` — mocked exec adapter/service tests.
- `challenge_runtime/tests/test_real_exec_integration.py` — opt-in real Docker test.
- `challenge_runtime/tests/test_terminal_mode_lifecycle.py` — terminal port/meta compatibility.

### WebSocket gateway

- `terminal/consumers.py` — replaced placeholder with exec bridge, input/output,
  resize, watchdog, revocation, and cleanup.
- `terminal/models.py` — internal exec coordination fields and conditional
  active-session uniqueness constraints.
- `terminal/migrations/0002_terminalsession_close_reason_and_more.py` — new migration.
- `terminal/services.py` — exec metadata, close requests, stream context,
  pending-close helpers, retained notification tasks, stale worker reaping.
- `terminal/ratelimits.py` — bounded token buckets.
- `terminal/tests/test_exec_stream.py` — mocked WebSocket stream tests.
- `terminal/tests/test_ratelimits.py` — bucket tests.
- `terminal/tests/helpers.py` — deterministic fake exec stream.
- `terminal/tests/test_websocket_gateway.py` — placeholder test replaced with browser-ID rejection.

### Application configuration

- `config/settings.py` — shell path, rate/buffer/resize, watchdog, and stale-session settings.
- `.env.example` — documented new environment variables.
- `instances/services.py` — terminal-mode challenges no longer require a published port; HTTP mode is unchanged.

---

## 5. PTY setup

`ChallengeRuntimeService.open_terminal_session()` performs these checks in order:

1. `instance.user_id == authenticated user.pk`;
2. instance status is `running` and it is not expired;
3. challenge `runtime_access_mode == 'terminal'`;
4. `confirm_running()` resolves the container from the server-side instance and
   verifies `flaghunt.managed=true`, matching instance ID, matching user ID, and
   real Docker status `running`;
5. exec is created only for the confirmed container ID.

The exec call is fixed:

```python
exec_create(container_id, ['/bin/sh'], stdout=True, stderr=True, stdin=True,
            tty=True, privileged=False, user='')
```

The shell path comes only from `FLAGHUNT_TERMINAL_SHELL` (default `/bin/sh`)
and must match `^/[A-Za-z0-9_./-]{1,127}$` with no `..`. No arguments or shell
metacharacters are accepted. The image's configured user is used because
`user=''` means "do not override"; the browser cannot select a user.

An initial bounded resize is applied immediately after `exec_start()`.

---

## 6. WebSocket message handling

Only text JSON frames are accepted. Binary frames and oversized frames are
rejected with an error frame and close code. Base64 is used so terminal bytes
remain binary-safe inside JSON text frames.

Client → server:

```json
{"type": "ping"}
{"type": "input", "data": "ZWNobyBoaQo="}
{"type": "resize", "rows": 40, "cols": 100}
```

Server → client:

```json
{"type": "pong"}
{"type": "status", "state": "connected", "rows": 24, "cols": 80}
{"type": "output", "data": "UFRZLUhFRUFE"}
{"type": "status", "state": "revoked", "reason": "instance_stopped"}
{"type": "status", "state": "error", "reason": "output_rate_exceeded"}
{"type": "error", "code": "invalid_dimensions"}
```

Unknown fields are ignored, especially browser-supplied `container_id`,
`exec_id`, `user_id`, `command`, `endpoint`, or host paths. The accepted
WebSocket subprotocol remains only `flaghunt-terminal-v1`; the ticket is never
echoed.

Resize validation:

- values must be real integers (`bool` is rejected);
- rows default range 24–200;
- columns default range 40–300;
- resize is token-bucket limited;
- no identifiers are accepted in a resize frame.

---

## 7. Lifecycle and cleanup

- A reader thread drains exec output into a bounded asyncio queue; a sender task
  applies output rate limits and emits base64 frames.
- A watchdog rechecks DB session state, instance state, and container existence
  at a configurable interval, covering missed channel notifications.
- `terminal_revoked` group events close active streams across workers when
  Stage 1C stops/expires/fails an instance.
- Disconnect calls `TerminalGatewayConsumer._cleanup()`:
  - stop reader;
  - cancel sender/watchdog tasks;
  - close only the associated `ExecSession`;
  - release the DB session;
  - leave the instance/channel/network untouched.
- Repeat cleanup is idempotent.
- Stale `connected` rows whose `last_seen` is older than the configured threshold
  are reclaimed by the existing Beat task, preventing crashed workers from
  permanently holding session slots.

Stage 1C remains the sole owner of container start, stop, expiry, and removal.
Terminal disconnect never calls `InstanceService.stop()`, `expire()`,
`DockerAdapter.stop_container()`, or `remove_container()`.

---

## 8. Configuration defaults

| Setting | Default |
|---|---|
| `FLAGHUNT_TERMINAL_SHELL` | `/bin/sh` |
| `FLAGHUNT_TERMINAL_INPUT_RATE_BYTES_PER_SECOND` | 65536 |
| `FLAGHUNT_TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND` | 262144 |
| `FLAGHUNT_TERMINAL_OUTPUT_BUFFER_BYTES` | 1048576 |
| `FLAGHUNT_TERMINAL_READ_CHUNK_BYTES` | 4096 |
| `FLAGHUNT_TERMINAL_ROWS_MIN/MAX` | 24 / 200 |
| `FLAGHUNT_TERMINAL_COLS_MIN/MAX` | 40 / 300 |
| `FLAGHUNT_TERMINAL_RESIZE_RATE_PER_SECOND` | 4 |
| `FLAGHUNT_TERMINAL_SESSION_CHECK_INTERVAL_SECONDS` | 5 |
| `FLAGHUNT_TERMINAL_STALE_SESSION_SECONDS` | 300 |

Stage 1D.2 ticket lifetime, frame size, session limits, Origin allowlist, and
Redis channel-layer settings remain in force.
