# Stage 1D.1 — Terminal Security Boundary

**Status:** DESIGN REQUIREMENTS — NOT IMPLEMENTED

**Date:** 2026-11-18

This document defines the trust boundaries and mandatory controls for a future
Stage 1D interactive terminal. It records how the ten required security
properties will be satisfied. Nothing in this document changes running code or
infrastructure.

---

## 1. Trust boundaries

```
UNTRUSTED                          TRUSTED APPLICATION                    ISOLATED WORKLOAD
---------                          -------------------                    -----------------
Browser / student                  Django REST + ASGI                     Student's container
  - xterm keystrokes                 - JWT / ticket auth                   - exec shell (PTY)
  - resize events                    - origin validation                   - challenge process
  - ticket (opaque)                  - ownership checks                    - /tmp tmpfs only
  - no container IDs                 - limits + audit                      - no host access
         |                                  |                                    |
         | WSS + subprotocol ticket          | docker SDK via adapter only        |
         +--------------------------------->+----------------------------------->+
                                            |
                                    Docker daemon socket
                              (backend process only; never exposed to browser)
```

Hard rules:

1. The browser never talks to the Docker daemon.
2. The browser never supplies a container ID, exec ID, image, command, user or
   host path.
3. Consumers/views/serializers never import `docker`; only
   `challenge_runtime/` does.
4. The gateway never runs a command on the Django host. Every exec targets a
   container ID resolved from the database.
5. Disconnecting a terminal never stops the challenge container.

---

## 2. Required controls mapped to the ten security properties

### 2.1 Users can access only their own active challenge instances

**Control**

- The REST ticket endpoint resolves the active instance with
  `ChallengeInstance.objects.filter(user=request.user)` — never by client ID.
- The Channels middleware reloads the instance with the authenticated user
  from the consumed ticket and rejects anything not owned by that user.
- Every message handler verifies the instance is still active/running before
  forwarding input.
- `TerminalSession` rows include `user_id` and `instance_id`; session lookup is
  scoped by both.

**Denied**

- guessing another user's instance ID;
- reusing a ticket from another user;
- supplying a username/role claim in a WebSocket frame.

### 2.2 Container IDs are resolved server-side, never trusted from browser input

**Control**

- The only identifier the browser sends is the opaque ticket (as a WebSocket
  subprotocol). No `container_id`, `exec_id`, `instance_id`, name or network ID
  is accepted from the browser.
- The adapter reads `instance.internal_container_id` (falling back to
  `internal_name` via server-side lookup) from the DB.
- The ticket is bound server-side to `(user_id, instance_id)`.
- Public `connection_meta` must stop including `container_id`; today it
  inadvertently does, so this is a required Stage 1D pre-remediation item.

**Denied**

- `{"container_id": "<victim container>"}`;
- exec targeting by name pattern;
- Docker API URLs supplied by the client.

### 2.3 The browser never accesses the Docker socket

**Control**

- Only the backend process has Docker SDK/socket access inside
  `challenge_runtime/docker_adapter.py`.
- No Docker socket path, `DOCKER_HOST`, API version or daemon URL is serialized
  to any client.
- Ingress exposes only HTTP `/api/v1/...` and WS `/ws/...`; there is no proxy
  path to `/var/run/docker.sock` or the Windows named pipe.
- The React bundle contains no Docker SDK and no socket URL.

**Denied**

- direct `ws://<docker>/containers/.../exec`;
- host-mounted socket in any challenge or gateway container;
- browser-side `dockerode`/SDK usage.

### 2.4 The gateway never executes commands on the host

**Control**

- Exec is always `api.exec_create(container_id_from_db, ...)` on the student's
  container.
- The shell command is fixed/admin-configured (e.g.
  `runtime_terminal_command`, default `/bin/sh`), never read from a WebSocket
  frame, ticket, query string or challenge description.
- `privileged=False` on exec; no host `user` override from the browser.
- No `docker run`, `docker cp`, host `subprocess`, `shell=True` or file mount is
  triggered by terminal traffic.
- Stage 1C container hardening stays intact: no privileged container, no host
  bind mounts, `cap_drop=ALL`, `no-new-privileges`, read-only root FS.

**Denied**

- "run this command on the host first";
- escalating the exec to privileged;
- mounting `C:\` or `/etc` into the challenge.

### 2.5 Each terminal session is bound to an authenticated user and active instance

**Control**

- Login still issues the existing SimpleJWT pair; the ticket endpoint uses
  DRF `IsAuthenticated`.
- Ticket payload in cache: `{user_id, instance_id, expires_at, used}`; one-time
  consume via an atomic cache operation or DB row with a unique constraint.
- Consumer scope contains `user`, `instance`, `session`.
- `TerminalSession` records are internal, with `status`, `created_at`,
  `closed_at`, `last_seen`, bounded rows/cols and no public exec ID.
- Max active sessions per instance defaults to 1; max per user is configurable.

**Denied**

- anonymous WebSocket connection;
- two students sharing one exec session;
- a session outliving its ticket owner.

### 2.6 Expired, stopped or failed instances cannot receive terminal connections

**Control**

At ticket issue and at socket connect, reject unless all are true:

- `instance.user_id == authenticated user`;
- `instance.status == 'running'`;
- `not instance.is_expired`;
- `instance.internal_container_id` or `internal_name` exists;
- Docker inspect confirms the container is running (cached briefly if needed).

While connected:

- the consumer polls/checks `instance.expires_at` on a bounded interval;
- on terminal status or expiry, send a `status: expired|closed` frame, close the
  socket with a policy code and close the exec session;
- `InstanceActiveView` and Stage 1C cleanup remain authoritative.

**Denied**

- keeping a shell after Stop was pressed;
- reconnecting to an expired/failed container;
- reusing an old ticket after the instance changed.

### 2.7 WebSocket authentication and origin validation are enforced

**Control**

- Native WebSockets cannot send `Authorization`, so use a short-lived,
  single-use ticket delivered in `Sec-WebSocket-Protocol`:
  `['flaghunt-terminal-v1', <ticket>]`.
- Middleware rejects:
  - missing/unknown subprotocol;
  - malformed or consumed ticket;
  - missing `Origin`;
  - origin not in an explicit allowlist derived from `CORS_ALLOWED_ORIGINS`
    plus same-origin (`ws` maps to `http`, `wss` to `https`);
  - production wildcard origins.
- TLS (`wss`) is required outside localhost.
- Access token lifetime stays 15 minutes; ticket lifetime is ~30 seconds.
- Failed authentication produces no Docker operation and no useful error
  detail.

**Denied**

- cross-site WebSocket hijacking from an attacker-controlled page;
- token replay from browser history/proxy logs;
- `null`/blank Origin bypass.

### 2.8 Input/output limits and connection limits are defined

**Starting limits (to be configurable, not hard-coded in consumers):**

| Limit | Proposed default | Purpose |
| --- | --- | --- |
| Ticket lifetime | 30 s | Bound replay window |
| Ticket reuse | 1 | Prevent session duplication |
| Active sessions per instance | 1 | One shell per student instance |
| Active sessions per user | 1 | Matches one-active-instance invariant |
| WS frame size | 32 KiB | Stop oversized single frames |
| Input rate | 64 KiB/s | Prevent flooding |
| Output buffer per session | 1 MiB | Bound memory; drop/close on overflow |
| Output rate | 256 KiB/s | Prevent runaway output |
| Scrollback in xterm | 5,000 lines | Bound browser memory |
| Rows / cols | 24–200 rows, 40–300 cols | Resize sanity range |
| Resize events | 4/s | Prevent resize churn |
| Ticket endpoint throttle | 10/minute/user | Reuse DRF throttle infrastructure |
| Max concurrent WS connections | global cap | Protect ASGI worker |

### 2.9 Disconnects do not unintentionally terminate the challenge container

**Control**

- `consumer.disconnect()` closes only the exec socket and marks the
  `TerminalSession` disconnected/closed.
- No call to `InstanceService.stop()`, `expire()`, `DockerAdapter.stop_container`
  or `remove_container` on disconnect.
- Container lifetime remains controlled by explicit Stop, `expires_at`,
  `cleanup_expired_instances` and restart reconciliation.
- Container restart policy is already `no` and `auto_remove=False`; Stage 1D
  must not change that.

**Denied**

- refreshing the browser killing the challenge;
- network blip destroying student work in the container filesystem;
- a malicious close frame triggering container teardown.

### 2.10 Terminal sessions are cleaned up when instances stop or expire

**Control**

- A `TerminalSession` is closed when:
  - the browser disconnects;
  - the shell exits or exec socket EOFs;
  - the instance enters `stopping`, `stopped`, `expired` or `failed`;
  - `reconcile()` discovers the container missing/non-running;
  - the session exceeds its own TTL/instance expiry, as a defence in depth.
- Cleanup closes Docker exec sockets, marks DB rows closed and sends a channel
  message so open consumers close promptly.
- Cleanup is idempotent: repeated Beat runs and concurrent Stop requests must
  not raise host-level errors.
- Audit events (actor, instance, action, reason) use the existing
  `audit.services.log_admin_action` where appropriate, without logging raw
  terminal output or commands.

**Denied**

- orphaned exec processes after expiry;
- unbounded session rows;
- cleanup code importing Docker SDK outside `challenge_runtime`.

---

## 3. Data classification

| Data | May cross to browser? | Notes |
| --- | --- | --- |
| JWT access/refresh | Already does, via API client | Existing design; not changed by terminal |
| One-time terminal ticket | Yes, once | Opaque, short-lived, bound to user/instance |
| Terminal output bytes | Yes | Confined to the student's own container |
| Terminal input bytes | Yes | Forwarded only to that container's exec shell |
| xterm rows/cols | Yes | Clamped and rate-limited |
| Instance id | Prefer no | Ticket resolves it server-side |
| Container ID / exec ID | **No** | Internal only; current public `connection_meta` leak must be fixed |
| Docker socket URL / daemon details | **No** | Never serialized |
| Host paths / host command output | **No** | Gateway never executes on host |
| Other users' data | **No** | Ownership checks on connect and per message |
| Flags/hashes | **No** | Existing flag model remains write-only/hashed |

---

## 4. Explicit non-goals and prohibitions

Stage 1D must not introduce:

- privileged containers or privileged exec;
- host bind mounts for the terminal gateway or challenge container;
- Docker socket exposure to the frontend, ingress or browser;
- unrestricted shell execution on the Django host;
- browser-supplied `cmd`, `user`, `container_id`, `exec_id` or mount paths;
- host firewall/nftables/iptables changes;
- CAP_NET_ADMIN or privileged helper processes;
- reuse of the firewall-controller architecture for terminal access;
- modifications to existing challenge records during inspection.

Terminal commands run **inside** the container, where the challenge is already
intended to be mutable by the student. Isolation relies on the existing Docker
boundary plus resource limits — not on trusting terminal input.

---

## 5. Future verification checklist

Implementation is not complete until mocked and opt-in real-Docker tests prove:

- anonymous WS rejected;
- invalid/consumed ticket rejected;
- wrong `Origin` rejected;
- user A cannot use a ticket for user B's instance;
- stopped/expired/failed instance rejected;
- no Docker call occurs on failed auth;
- exec is created with `tty=True`, `stdin=True`, `privileged=False`;
- `exec_resize` is called with clamped rows/cols;
- a socket disconnect closes exec/session but leaves the container running;
- Stop/expiry closes all sessions for the instance;
- limits reject oversized/fast input and oversized output;
- public payloads contain no container or exec IDs;
- no managed containers/networks remain after the opt-in real-Docker test.

Until these checks exist and pass, terminal access must be described as
**not implemented**.
