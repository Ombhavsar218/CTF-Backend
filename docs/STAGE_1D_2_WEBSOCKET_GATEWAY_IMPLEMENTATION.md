# Stage 1D.2 — WebSocket Gateway Implementation

**Date:** 2026-11-19  
**Scope:** Backend-only foundation. **Interactive terminal execution is not implemented.**

## 1. Outcome

The authenticated WebSocket gateway and single-use terminal-ticket foundation are
implemented. Django Channels serves the existing HTTP/DRF application unchanged
and adds one authenticated WebSocket route:

- REST: `POST /api/v1/challenges/instances/terminal-ticket/`
- WebSocket: `/ws/challenges/instances/terminal/`

The gateway authenticates before upgrade, consumes a one-time ticket atomically,
resolves the user/instance only from server-side ticket data, enforces session
limits, and tracks sessions in the database with cross-worker revocation
notifications. It deliberately stops at connection management: there is **no**
Docker exec, no PTY, no terminal byte proxying, no resize handling, and no
xterm.js integration.

## 2. Baseline confirmed before implementation

- Django 5.2.17, DRF 3.18.3, `docker==7.1.0`, Redis 5.2.1, Celery 5.5.3 were
  installed; Channels/Daphne were not.
- `config/asgi.py` was the generated plain Django ASGI wrapper.
- `CACHE_URL`/`CELERY_BROKER_URL` were the existing shared-infrastructure
  candidates for a production-compatible channel layer.
- Stage 1C owned all container lifecycle through `challenge_runtime/`; instance
  views only called `InstanceService`.
- API authentication is JWT-first with SessionAuthentication fallback; endpoint
  throttles use DRF scoped rates.
- Stage 1D.1 documentation specified subprotocol tickets, exact Origin checking,
  short TTL, DB-backed session coordination, and no Docker IDs in responses.
- Git baseline: BE HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
  (`main`, modified 27, staged 0, untracked 284 collapsed / 744 expanded);
  FE HEAD `453cbe2b0a017dbd643ff6f77746f85f9965b8d7`
  (`main`, modified 36, staged 0, untracked 43 collapsed / 11 expanded).

## 3. Dependencies added

Pinned in `requirements.txt` and installed into `ctf-platform-be/venv`:

| Package | Version | Purpose |
| --- | ---: | --- |
| `channels` | 4.3.2 | ASGI protocol routing/consumers |
| `daphne` | 4.2.3 | ASGI server and `runserver` backend |
| `channels-redis` | 4.3.0 | Redis channel layer for multi-worker deployments |
| `asgiref` | 3.12.1 | Already present; compatible transitive requirement |

No frontend dependency was added.

## 4. ASGI and Channels configuration

`config/asgi.py` now calls `django.setup()` before building the routing table and
exposes:

```python
application = ProtocolTypeRouter({
    'http': django_asgi_application,
    'websocket': URLRouter(websocket_urlpatterns),
})
```

`config/settings.py`:

- `INSTALLED_APPS` adds `daphne`, `channels`, and `terminal.apps.TerminalConfig`.
- `ASGI_APPLICATION = 'config.asgi.application'` was added; the existing
  `WSGI_APPLICATION` remains.
- `CHANNEL_LAYERS['default']` selects `channels_redis.core.RedisChannelLayer`
  when `FLAGHUNT_CHANNEL_LAYER_REDIS_URL` is set, or when an existing Redis
  `CACHE_URL`/`CELERY_BROKER_URL` is available (dedicated DB path `/2` with
  prefix `flaghunt:ws:`). With no Redis configuration it uses
  `channels.layers.InMemoryChannelLayer` for explicitly isolated local runs and
  tests; this mode is not a multi-worker guarantee.
- `WEBSOCKET_ALLOWED_ORIGINS` comes from
  `FLAGHUNT_WS_ALLOWED_ORIGINS`, defaulting in development to CORS origins plus
  `http://localhost:8000` and `http://127.0.0.1:8000`.
- Existing HTTP middleware, DRF authentication, CORS, and all Stage 1C routes
  remain unchanged.

## 5. Challenge access mode

A new explicit mode field was added without changing existing records' behavior:

- `challenges.Challenge.runtime_access_mode`: `http` (default) or `terminal`.
- Migration `challenges/migrations/0003_stage_1d_terminal_access_mode.py` was
  created and applied locally.
- `ChallengePublicSerializer` exposes `instanceMode`.
- `ChallengeWriteSerializer` accepts `runtime_access_mode`. HTTP-mode
  validation is byte-for-byte the Stage 1C rule (image and port required);
  terminal mode does not require a published port.

No existing challenge row was modified during inspection or implementation.

## 6. Ticket lifecycle

1. `POST /api/v1/challenges/instances/terminal-ticket/` requires an
   authenticated REST user and is throttled at `10/minute` per user.
2. `TicketIssuer` resolves the caller's active instance through
   `InstanceService.active(user)`; no browser-supplied instance/container ID is
   accepted.
3. It rejects non-running, expired, non-owned, or non-terminal challenges.
4. `ChallengeRuntimeService.confirm_running(instance)` performs a read-only
   Docker inspect and checks the managed label and instance ID. No exec/start/
   stop/remove occurs.
5. `secrets.token_urlsafe(32)` generates the raw ticket. Only its SHA-256 hash
   is stored in `TerminalTicket` with user, instance, and a 30-second default
   expiry (`FLAGHUNT_TERMINAL_TICKET_TTL_SECONDS`).
6. The REST response contains only `ticket`, `url`, `subprotocol`, and
   `expiresIn`. The URL has no query parameters and contains no instance,
   container, network, or exec identifier.
7. `TerminalTicket.consume()` uses `select_for_update()` plus a conditional
   `UPDATE ... WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > now`
   so exactly one concurrent consumer can win. Expired, revoked, reused, and
   malformed tickets are rejected.
8. Instance stop/expiry/failure revokes unused tickets through a Django signal;
   periodic cleanup revokes stale tickets and deletes old rows.

## 7. WebSocket authentication

`TicketAuthMiddleware` runs before the consumer accepts the connection:

- Requires an exact allowed `Origin`; `ws://`/`wss://` values are normalized to
  the documented `http://`/`https://` allowlist. `null`, missing, wildcard, and
  unknown origins are rejected with close code `4403`.
- Requires exactly `['flaghunt-terminal-v1', <ticket>]` in
  `Sec-WebSocket-Protocol`; wrong label/count gives `4400`, malformed ticket
  gives `4401`.
- Consumes the ticket atomically, then reloads the user and instance from the
  ticket row. The raw ticket is not placed in `scope`.
- Rechecks ownership, active status, expiry, and terminal mode through server
  state. Failed authentication closes with a generic reason before terminal
  access exists.
- The consumer accepts only the constant label `flaghunt-terminal-v1`. The
  secret ticket is never echoed in the negotiated subprotocol.
- No user ID, instance ID, container ID, exec ID, command, or path is read from
  the browser.

## 8. Session management

`TerminalSession` is the shared, DB-backed source of truth:

- Bound to user, instance, consumed ticket, channel name, and lifecycle status.
- `SessionRegistry.acquire()` locks the user and instance rows, counts active
  sessions, and rejects duplicates above the configurable caps (defaults: 1
  per user, 1 per instance).
- `mark_connected()`, `heartbeat()`, and `release()` track connection lifetime.
- `revoke_for_instance()` closes active sessions and unused tickets when Stage
  1C moves an instance to `stopping`, `stopped`, `expired`, or `failed`.
- `terminal.cleanup_stale` Beat task (default every 60 s) converges expired
  tickets/sessions and stale connecting rows.
- Cross-worker close notifications use `channel_layer.group_send()` on
  `terminal.instance.<id>`; the database decision does not depend on in-process
  memory.
- A WebSocket disconnect only calls `SessionRegistry.release()`. It never calls
  `InstanceService.stop()`, `expire()`, `DockerAdapter.stop_container()`, or
  `remove_container()`.

## 9. Files created

Backend source:

- `terminal/__init__.py`
- `terminal/apps.py`
- `terminal/auth.py`
- `terminal/consumers.py`
- `terminal/exceptions.py`
- `terminal/models.py`
- `terminal/routing.py`
- `terminal/services.py`
- `terminal/signals.py`
- `terminal/tasks.py`
- `terminal/throttling.py`
- `terminal/urls.py`
- `terminal/views.py`
- `terminal/migrations/__init__.py`
- `terminal/migrations/0001_initial.py`
- `challenges/migrations/0003_stage_1d_terminal_access_mode.py`

Tests:

- `terminal/tests/__init__.py`
- `terminal/tests/helpers.py`
- `terminal/tests/test_ticket_api.py`
- `terminal/tests/test_websocket_gateway.py`
- `terminal/tests/test_session_registry.py`
- `terminal/tests/test_runtime_confirm.py`

## 10. Files modified

- `requirements.txt` — pinned Channels stack.
- `config/asgi.py` — ProtocolTypeRouter + WebSocket URLRouter.
- `config/settings.py` — apps, ASGI setting, channel layer, origins, terminal
  limits, throttle rate, Beat task, dev CSP `ws://` origins.
- `config/urls.py` — includes `terminal.urls` under `/api/v1/`.
- `challenges/models.py` — `runtime_access_mode`.
- `challenges/serializers.py` — `instanceMode`, write field, mode-aware validation.
- `challenge_runtime/service.py` — read-only `confirm_running()`.
- `ops/tests.py` — existing untracked test updated to expect the Stage 1C and
  Stage 1D.2 Beat cleanup entries.
- `.env.example` — documented new gateway variables.

No frontend files were changed. No firewall-controller or manager files were
changed. No reset, clean, revert, stage, or commit was performed.

## 11. Explicit non-goals delivered as non-goals

The following remain intentionally absent:

- xterm.js or any frontend terminal UI;
- Docker `exec_create`, `exec_start`, PTY, TTY, resize, or byte proxying;
- host command execution, host paths, privileged containers, or socket exposure;
- browser-supplied container/exec identifiers accepted anywhere;
- changes to Stage 1C HTTP start/open/stop behavior or existing challenge data;
- production/cloud deployment.

See `STAGE_1D_2_TEST_EVIDENCE.md` for exact verification results and
`STAGE_1D_2_FINAL_REPORT.md` for the consolidated status.
