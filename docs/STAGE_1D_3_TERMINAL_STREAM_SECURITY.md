# Stage 1D.3 — Terminal Stream Security

**Date:** 2026-11-19  
**Status:** Backend stream controls implemented. Live firewall integration and browser terminal UI remain out of scope.

---

## 1. Mandatory safety status

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

T-11, T-13 and T-27 remain:

**OPEN — ACCEPTANCE REQUIRED**

This stage does not authorize:

- live firewall-controller integration;
- UDS/SO_PEERCRED or privileged helpers;
- host firewall changes or CAP_NET_ADMIN;
- cloud/production deployment;
- Stage 1B formal acceptance or security-gate closure.

Previously identified findings remain deferred and open. Nothing in Stage 1D.3
marks them accepted or fixed.

---

## 2. Trust boundary

```
Untrusted browser frame
   type/input/base64/resize/ping only
        |
        v
Stage 1D.2 auth: Origin + subprotocol + single-use ticket
        |
        v
Server-side user/instance/ticket context
   ownership + active + mode + running rechecks
        |
        v
DockerAdapter in challenge_runtime only
   exec_create/start/resize/inspect/close
        |
        v
User's own running challenge container
```

The browser never sees or supplies:

- Docker socket path or endpoint;
- container ID;
- exec ID;
- host path;
- startup command;
- Docker user;
- another user's identity.

No terminal input, output, ticket, or secret is written to application logs.
Error frames use generic codes and reasons only; daemon exception text is
swallowed at the adapter boundary.

---

## 3. Authentication and authorization

Stage 1D.2 pre-accept controls are preserved unchanged:

- exact `WEBSOCKET_ALLOWED_ORIGINS` match;
- client offers `flaghunt-terminal-v1` plus a single opaque ticket;
- server accepts only `flaghunt-terminal-v1`, so the ticket is not echoed;
- ticket is SHA-256 hashed at rest and consumed atomically;
- user and instance are resolved only from the consumed server-side ticket.

Stage 1D.3 adds a second authorization gate immediately before exec creation:

- `instance.user_id` must equal the authenticated user;
- instance must be `running` and not expired;
- challenge must have `runtime_access_mode='terminal'`;
- `confirm_running()` must inspect the real container and confirm managed
  labels, instance ID, user ID, and Docker status `running`.

This closes the ticket-issue-to-connect TOCTOU for exec creation. The Stage 1D.2
behavior where a failed post-consume check burns the one-time ticket is still
present and is documented as a residual limitation.

---

## 4. Exec isolation

- One dedicated exec per authorized WebSocket connection.
- `tty=True`, `stdin=True`, `stdout=True`, `stderr=True`.
- `privileged=False`.
- `user=''`, so Docker uses the image's configured user; no root escalation is
  requested by the platform.
- Fixed backend shell `/bin/sh` by default.
- Configured shell override must be an absolute conservative path; no relative
  traversal, whitespace, shell metacharacters, or arguments.
- No `container.attach()` and no PID 1 modification.
- No host command execution, host mounts, privileged containers, or new capabilities.
- Existing Stage 1C restrictions are not weakened (ICC disabled network,
  `cap_drop=ALL`, `no-new-privileges`, pids/memory/CPU limits, read-only root
  filesystem, 64 MB noexec `tmpfs`, no restart policy).

The exec shell runs with the container's own restrictions. It is intentionally
an interactive shell inside the challenge container, not a host shell.

---

## 5. Message and buffer controls

| Control | Enforcement |
|---|---|
| Inbound frame size | `TERMINAL_MAX_FRAME_BYTES` (default 32768), checked before JSON decode |
| Binary frames | Rejected with `binary_frames_unsupported` |
| Malformed JSON/empty frames | Explicit `invalid_json` / `invalid_frame` error, no unhandled exception |
| Input payload | Strict base64; decoded size must be 1..frame limit |
| Input rate | Token bucket, default 65536 bytes/sec with one-frame burst |
| Output chunk | `TERMINAL_READ_CHUNK_BYTES`, default 4096 |
| Output queue | Bounded by `OUTPUT_BUFFER_BYTES / READ_CHUNK_BYTES` |
| Output buffer | Default 1 MiB hard cap; overflow closes with `output_buffer_overflow` |
| Output rate | Token bucket, default 262144 bytes/sec with bounded burst |
| Resize values | Integers only; rows 24–200, cols 40–300 by default |
| Resize rate | Token bucket, default 4/sec |
| Heartbeat | Client `ping` and server watchdog update `last_seen` |
| Stale sessions | Reclaimed after `TERMINAL_STALE_SESSION_SECONDS` (default 300) |

These byte/rate controls are per ASGI worker. Session ownership and lifecycle
are DB-backed and shared across workers through the existing Redis channel
layer where configured.

---

## 6. Cross-worker coordination

`TerminalSession` now stores internal `exec_id`, confirmed `container_id`,
dimensions, `worker_id`, `close_requested`, and `close_reason`. These fields are
never serialized to clients.

- Conditional unique constraints enforce one active session per user and per
  instance even on SQLite where `SELECT FOR UPDATE` is a no-op.
- Revocation writes DB state first and then broadcasts an opaque reason via the
  existing per-instance channel group.
- Fire-and-forget channel tasks are retained until completion.
- The consumer watchdog independently rechecks DB state and Docker state, so a
  missed channel notification still converges.
- Beat cleanup reaps stale `connected` rows and terminal/inactive sessions.

The in-memory channel layer fallback is acceptable only for isolated local
tests/development. Production requires the Redis channel layer already
supported by Stage 1D.2.

---

## 7. Lifecycle safety

- Disconnect closes only that connection's exec stream and DB session.
- Disconnect never stops, kills, expires, or removes the container.
- Container stop/expiry/failure/reconciliation closes all associated terminal
  sessions through DB revocation plus group notification.
- Repeated cleanup is idempotent.
- Container disappearance is detected by rechecks and closes the stream with a
  generic `container_unavailable` reason.
- Closing an exec does not terminate the challenge container; Stage 1C remains
  the only container lifecycle owner.

---

## 8. Residual and deferred concerns

1. Stage 1C HTTP `connection_meta` still contains `container_id`; terminal-mode
   metadata does not. Removing the HTTP field would change existing HTTP
   behavior, so it was left for an explicit later decision.
2. Stage 1D.2 ticket consumption occurs before all post-authentication checks;
   a failed connect can burn a valid ticket. Exec creation is nevertheless
   rechecked server-side.
3. `post_save` revocation does not fire for Stage 1C `QuerySet.update()`
   transitions. The watchdog and Beat cleanup cover those paths within their
   configured intervals.
4. `revoke_for_user()` remains unwired to user-disable events.
5. Rate and buffer limits are per worker, not global.
6. Redis channel layer and PostgreSQL are required for production-grade
   cross-worker behavior; SQLite/in-memory defaults are development-oriented.
7. No reconnect/resume, frontend xterm.js, or end-to-end browser testing exists.
8. T-11, T-13, T-27, firewall integration, privileged helpers, and Stage 1B
   acceptance remain explicitly open and unauthorized.
