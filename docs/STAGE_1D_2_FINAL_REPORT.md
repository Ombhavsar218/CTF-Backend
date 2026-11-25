# Stage 1D.2 — Final Report

**Date:** 2026-11-19  
**Stage:** Authenticated WebSocket Gateway and Single-Use Terminal Tickets  
**Final status:** **GATEWAY FOUNDATION IMPLEMENTED — INTERACTIVE TERMINAL FUNCTIONALITY IS NOT COMPLETE.**

## 1. Executive summary

Stage 1D.2 implemented the backend security foundation for future interactive
Docker terminals:

- Django Channels + Daphne now serve HTTP and WebSocket protocols without
  replacing existing Django/DRF behavior.
- A REST endpoint issues a cryptographically random, short-lived, single-use
  ticket only for an authenticated user's active, running, terminal-mode
  challenge instance.
- A WebSocket gateway validates exact Origin and negotiated subprotocol,
  consumes the ticket atomically, resolves all resources server-side, and
  enforces per-user/per-instance session limits.
- A DB-backed session registry coordinates across workers and revokes sessions
  when Stage 1C stops, expires, or fails an instance.
- WebSocket disconnect never stops or removes the Docker container.

The stage intentionally did **not** implement xterm.js, Docker exec, PTY,
terminal input/output, resize, or real interactive terminal tests. Those belong
to Stage 1D.3.

## 2. Baseline inspection

Confirmed before implementation:

- Channels/Daphne were absent; Django 5.2.17, DRF 3.18.3, Docker SDK 7.1.0,
  Redis 5.2.1, and Celery 5.5.3 were installed.
- `config/asgi.py` was plain Django ASGI; JWT/Session DRF auth and scoped
  throttles were already in use.
- Stage 1C confined Docker SDK access to `challenge_runtime/` and owned all
  container lifecycle through `InstanceService`.
- Stage 1D.1 required subprotocol tickets, exact Origin allowlisting, short TTL,
  shared session coordination, no browser-supplied Docker IDs, and no container
  termination on WS disconnect.
- Git baseline was fully preserved: no reset, clean, revert, stage, or commit.

## 3. Deliverables

### Source created

`terminal/` app with: `apps.py`, `auth.py`, `consumers.py`, `exceptions.py`,
`models.py`, `routing.py`, `services.py`, `signals.py`, `tasks.py`,
`throttling.py`, `urls.py`, `views.py`, `migrations/0001_initial.py`, and
mocked tests under `terminal/tests/`.

`challenges/migrations/0003_stage_1d_terminal_access_mode.py` was created and
applied locally.

### Source modified

- `requirements.txt` — channels 4.3.2, daphne 4.2.3, channels-redis 4.3.0.
- `config/asgi.py` — HTTP + WebSocket `ProtocolTypeRouter`.
- `config/settings.py` — apps, `ASGI_APPLICATION`, Redis/in-memory channel
  layers, exact WS origin allowlist, terminal limits, throttle, Beat cleanup,
  development CSP `ws://` origins.
- `config/urls.py` — ticket endpoint under `/api/v1/`.
- `challenges/models.py` and `challenges/serializers.py` — explicit
  `runtime_access_mode` (`http` default, `terminal` opt-in), public
  `instanceMode`, mode-aware validation.
- `challenge_runtime/service.py` — read-only `confirm_running()`.
- `ops/tests.py` — existing untracked Beat expectation updated for Stage 1C and
  Stage 1D.2 cleanup entries.
- `.env.example` — documented gateway configuration.

### Documentation created

- `docs/STAGE_1D_2_WEBSOCKET_GATEWAY_IMPLEMENTATION.md`
- `docs/STAGE_1D_2_TERMINAL_TICKET_SECURITY.md`
- `docs/STAGE_1D_2_TEST_EVIDENCE.md`
- `docs/STAGE_1D_2_FINAL_REPORT.md`

No frontend file was changed. No firewall-controller or manager architecture
was changed. No Docker container, network, database challenge record, or
unrelated migration was modified during inspection.

## 4. ASGI and channel layer

`config/asgi.py` now retains Django's standard HTTP ASGI app under the `http`
protocol and adds a `URLRouter` for:

```text
/ws/challenges/instances/terminal/
```

`CHANNEL_LAYERS` selects Redis (`channels_redis.core.RedisChannelLayer`) when
`FLAGHUNT_CHANNEL_LAYER_REDIS_URL` is present or an existing Redis cache/broker
URL is available. It uses a dedicated `/2` DB and `flaghunt:ws:` key prefix for
derived URLs. Only an explicitly isolated local/test environment without Redis
uses `InMemoryChannelLayer`.

## 5. Ticket lifecycle

```text
authenticated POST
  -> InstanceService.active(user)
  -> status/expiry/ownership/terminal-mode checks
  -> read-only Docker inspect via challenge_runtime
  -> token_urlsafe(32)
  -> SHA-256 hash stored with user + instance + 30s expiry
  -> one-time subprotocol handshake
  -> atomic consume
  -> server-side user/instance recheck
  -> session acquisition
  -> revocation on instance stop/expiry/failure or cleanup task
```

The ticket is never placed in a URL, query string, application log, generic
error, or downstream `scope`. The accepted WebSocket subprotocol is only the
constant label, not the secret.

## 6. WebSocket authentication and session management

- Exact Origin allowlist; `null`, wildcard, missing, or unknown origins rejected.
- Subprotocol must be exactly `['flaghunt-terminal-v1', <ticket>]`.
- Ownership and active state are rechecked from the ticket row's server-side
  user/instance; no browser-supplied IDs are trusted.
- Session registry is ORM-backed with user/instance row locks, configurable
  caps (default 1/1), lifecycle status, heartbeat, release, revocation, and
  periodic cleanup.
- Cross-worker revocation uses channel-layer groups. In-memory state is never
  relied upon for guarantees.
- Disconnect closes only the gateway session; Stage 1C remains solely
  responsible for container lifecycle.

## 7. Verification

Exact evidence is recorded in `STAGE_1D_2_TEST_EVIDENCE.md`.

| Check | Result |
| --- | --- |
| `manage.py check` | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| `manage.py migrate` | Applied `challenges.0003` and `terminal.0001` |
| `manage.py test terminal -v 1` | 36 tests, OK |
| Stage 1C/API/config/challenges | 151 tests, OK, 1 skipped |
| Remaining app suites | 519 tests, OK |
| Combined app-scoped | 706 tests, OK, 1 skipped |
| Full `manage.py test` | Not claimed: pre-existing untracked `test_digest.py` import error and 600s budget exceeded |
| Real Docker terminal test | Not run; deferred to Stage 1D.3 |
| Frontend harness/build | Not run; no frontend change |

All new tests are mocked/isolated. They do not demonstrate interactive terminal
execution.

## 8. Git state

| Point | BE HEAD | BE branch | Modified tracked | Staged | Untracked collapsed | Untracked expanded |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Before Stage 1D.2 | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | `main` | 27 | 0 | 284 | 744 |
| After Stage 1D.2 | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | `main` | 28 | 0 | 287 | 770 |

| Point | FE HEAD | FE branch | Modified tracked | Staged | Untracked collapsed | Untracked expanded |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Before Stage 1D.2 | `453cbe2b0a017dbd643ff6f77746f85f9965b8d7` | `main` | 36 | 0 | 43 | 11 |
| After Stage 1D.2 | `453cbe2b0a017dbd643ff6f77746f85f9965b8d7` | `main` | 36 | 0 | 43 | 11 |

Nothing was reset, cleaned, reverted, staged, or committed. All pre-existing
uncommitted work was preserved.

## 9. Known limitations and residual risks

1. **No interactive terminal functionality.** No exec/PTY, byte streaming,
   resize, or xterm.js. The consumer explicitly replies
   `terminal_execution_not_enabled`.
2. **Stage 1C public metadata still includes `container_id`.** New Stage 1D.2
   responses do not, but the existing Stage 1C `connection_meta` leak remains a
   public-rollout prerequisite.
3. **React admin form not updated.** Backend model/write serializer support
   `runtime_access_mode`, but the SPA admin UI was out of scope.
4. **Production configuration is operator-owned.** Set explicit
   `FLAGHUNT_WS_ALLOWED_ORIGINS`, TLS/WSS termination, and Redis channel layer;
   there is no new fail-fast deployment validator in this stage.
5. **No byte-rate/output-buffer limits yet.** Deferred until an actual terminal
   stream exists. Frame size and ticket/session/connection rate limits are in
   place.
6. **Full discovery suite not clean.** A pre-existing untracked root
   `test_digest.py` fails at import; app-scoped suites are green.
7. **No real Docker integration proof.** Stage 1D.3 must add opt-in tests for
   exec creation, PTY flags, resize, cleanup, and no managed leftovers.

## 10. Final status

**Stage 1D.2 is complete as a backend gateway foundation.** The authenticated
ticket/WebSocket/session layer is implemented and mocked-tested.

**Interactive Docker terminal functionality is not complete.** It remains
blocked on Stage 1D.3 (Docker exec/PTY/resize/streaming inside
`challenge_runtime/`) and subsequent frontend integration (xterm.js), followed
 by opt-in real-Docker verification.
