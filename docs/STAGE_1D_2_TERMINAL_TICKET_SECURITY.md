# Stage 1D.2 — Terminal Ticket Security

**Date:** 2026-11-19  
**Status:** Gateway/ticket foundation implemented. No terminal I/O exists yet.

## 1. Security objective

Issue a short-lived, opaque capability that allows exactly one authenticated
WebSocket handshake for exactly one owned, active challenge instance, then
immediately cease to be usable. The browser must never need to know Docker
identifiers, host paths, user IDs, or instance IDs to use it.

## 2. Trust boundary

```
Browser (JWT-authenticated REST client)
   |  POST ticket  -> DRF IsAuthenticated + per-user throttle
   v
Django / InstanceService  ---- owner + active-state checks ----> ORM
   |
   |  ChallengeRuntimeService.confirm_running() (read-only inspect)
   v
challenge_runtime/ DockerAdapter ----> Docker daemon (adapter only)
   |
   v
Ticket row (hash only) + WebSocket subprotocol ticket
   |
   v
TicketAuthMiddleware -> TerminalGatewayConsumer -> DB session registry
```

The browser never reaches the Docker daemon. No terminal or host command path
crosses this boundary. The firewall-controller/manager architecture is not
involved or modified.

## 3. Ticket properties

| Property | Implementation |
| --- | --- |
| Randomness | `secrets.token_urlsafe(32)` (256 bits of entropy) |
| Lifetime | 30 s default; `FLAGHUNT_TERMINAL_TICKET_TTL_SECONDS`, minimum 5 s |
| Storage | SHA-256 hex digest only (`token_hash`), never the raw token |
| Binding | `user_id`, `instance_id`, `expires_at`, `created_at` |
| One-time gate | Atomic conditional `UPDATE` on `used_at` inside a transaction |
| Replay defence | Consumed, revoked, expired, or malformed tickets all fail closed |
| Revocation | Instance stop/expiry/failure and periodic cleanup set `revoked_at` |
| Rate limit | DRF `UserRateThrottle` scope `terminal_ticket`, default 10/minute |
| Transport | HTTPS REST body, then `Sec-WebSocket-Protocol`; never URL/query/log |

## 4. Issuance checks

`TicketIssuer.issue(user)` performs, in order:

1. Feature gate `FLAGHUNT_TERMINAL_ENABLED` (default on).
2. `InstanceService.active(user)` — resolves the single active instance from
   the authenticated user. Browser-supplied `instance_id` is ignored.
3. Instance must be `running`, not expired, and owned by that user.
4. `challenge.runtime_access_mode == 'terminal'`.
5. `ChallengeRuntimeService.confirm_running(instance)` confirms the Docker
   container is actually running and carries the expected managed label and
   instance ID.

Docker failure messages are translated to
`TERMINAL_RUNTIME_UNAVAILABLE` / HTTP 503 with a generic body. No daemon detail,
file path, container ID, or exec ID is returned.

## 5. Consumption and replay prevention

`TerminalTicket.consume(token, user=None)`:

- validates token shape before hashing (`[A-Za-z0-9_-]{32,128}`);
- hashes with SHA-256 and looks up the unique `token_hash`;
- locks the row with `select_for_update()`;
- optionally verifies an expected user;
- rejects `used_at`, `revoked_at`, `expires_at <= now`;
- performs `UPDATE ... SET used_at=now WHERE id=? AND used_at IS NULL AND
  revoked_at IS NULL AND expires_at > now`;
- requires exactly one updated row, then returns the server-side ticket row.

The conditional update is the authoritative single-use guard even on databases
where `SELECT FOR UPDATE` is a no-op. A short retry handles SQLite table locks
in local tests; production behavior relies on row-level locks.

Concurrent-consumption evidence: two barrier-synchronized threads produced
exactly one `consumed` and one `rejected` outcome.

## 6. WebSocket subprotocol handling

The client offers:

```
Sec-WebSocket-Protocol: flaghunt-terminal-v1, <ticket>
```

Middleware rules:

- exactly two entries are accepted;
- the first must equal `settings.TERMINAL_SUBPROTOCOL`;
- the second must be a well-formed ticket;
- the raw ticket is consumed and then discarded from `scope`;
- only `terminal_ticket_id` (an integer DB key) is retained.

The consumer calls `accept(subprotocol='flaghunt-terminal-v1')`. The server
therefore advertises only the protocol label, never the secret. Tests assert
the accepted protocol does not contain the ticket.

## 7. Origin validation

- Missing, blank, or literal `null` Origin: rejected (`4403`).
- Wildcard entries in the allowlist are ignored; an empty effective allowlist
  rejects every connection.
- `ws://`/`wss://` offered by non-browser clients are normalized to
  `http://`/`https://` before matching the documented allowlist.
- Only exact scheme + host + port matches pass; paths, query strings, and
  fragments are rejected.
- Development default: `CORS_ALLOWED_ORIGINS` plus localhost:8000.
- Production should set `FLAGHUNT_WS_ALLOWED_ORIGINS` explicitly to the exact
  SPA origin(s).

Origin and subprotocol are checked **before** ticket consumption, so malformed
cross-site attempts do not burn a legitimate ticket.

## 8. Session binding and revocation

After ticket authentication, the middleware resolves user and instance from the
ticket row and rechecks active/running/expired/non-terminal state in the ORM.
The consumer then acquires a `TerminalSession` under row locks.

- Active sessions are counted per user and per instance. Defaults are 1 and 1;
  both are configurable.
- Duplicate attempts receive WebSocket close `4409` and do not create a second
  session.
- Stage 1C status transitions to `stopping`, `stopped`, `expired`, or `failed`
  trigger `SessionRegistry.revoke_for_instance()`, revoking active sessions and
  unused tickets.
- Broadcast close events go through the shared channel layer, not process-local
  state.
- A browser disconnect calls only `release()`; it cannot stop or delete the
  container.

## 9. Explicitly denied inputs

The gateway does not accept or act on:

- browser-supplied `user_id`, `instance_id`, `container_id`, `exec_id`;
- arbitrary commands, shell selection, host paths, or mount paths;
- privileged flags, Docker socket URLs, or daemon endpoints;
- query-string tickets or tickets embedded in WS paths;
- second-hand credentials in JSON frames (all non-ping frames currently return
  `terminal_execution_not_enabled`).

## 10. Resource bounds

| Control | Default | Source |
| --- | ---: | --- |
| Ticket lifetime | 30 s | `FLAGHUNT_TERMINAL_TICKET_TTL_SECONDS` |
| Ticket endpoint | 10/min/user | `DRF_THROTTLE_TERMINAL_TICKET` |
| Sessions/user | 1 | `FLAGHUNT_TERMINAL_MAX_SESSIONS_PER_USER` |
| Sessions/instance | 1 | `FLAGHUNT_TERMINAL_MAX_SESSIONS_PER_INSTANCE` |
| WS text frame | 32 KiB | `FLAGHUNT_TERMINAL_MAX_FRAME_BYTES` |
| Cleanup task | 60 s | `FLAGHUNT_TERMINAL_CLEANUP_INTERVAL_SECONDS` |

Input/output byte-rate limits and PTY buffer limits are intentionally deferred
to Stage 1D.3 because no terminal byte path exists yet.

## 11. Residual limitations

- Stage 1C public `connection_meta` still contains `container_id`; this stage
  did not change existing HTTP payloads. It must be removed before public
  terminal rollout. New ticket/gateway responses contain no container IDs.
- The React admin form has not been updated for `runtime_access_mode`; the
  backend write serializer and Django model/admin support it.
- Production deployment must explicitly configure TLS/WSS, the Redis channel
  layer, and `FLAGHUNT_WS_ALLOWED_ORIGINS`.
- The gateway cannot yet prove end-to-end terminal safety because no Docker
  exec/PTY exists. Stage 1D.3 must add and test that boundary separately.
