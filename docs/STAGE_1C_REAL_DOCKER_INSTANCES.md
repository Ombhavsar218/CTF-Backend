# Stage 1C — Real local Docker challenge instances

Status: **IMPLEMENTED — LOCAL DOCKER VERIFIED**

Stage 1C replaces the previous 503/no-op instance flow with a real, local
Docker-backed instance lifecycle. Clicking **Start Instance** now reserves a
DB row, creates an isolated container, starts it, inspects the daemon-confirmed
state and publishes only the confirmed loopback connection details to the UI.

This stage is deliberately scoped to local Flaghunt challenge instances. It
does **not** touch the firewall-controller security architecture, manager/broker
J19 authority boundaries, host firewall, UDS/SO_PEERCRED, privileged helpers or
production deployment.

---

## 1. Architecture

```
React ChallengeDetails
  -> challengeService.startInstance() / getInstance() / stopInstance()
  -> Django /api/v1/challenges/<pk>/instances/start/
  -> instances.views.InstanceStartView
  -> instances.services.InstanceService        (ownership, one-active rule, errors)
  -> challenge_runtime.service.ChallengeRuntimeService (lifecycle orchestration)
  -> challenge_runtime.docker_adapter.DockerAdapter    (only Docker SDK access)
  -> local Docker Engine (Docker Desktop)
```

Docker SDK/socket/endpoint references exist **only** inside the new
`challenge_runtime/` package, which is outside the J19 scan roots
(`broker`, `manager`, `instances`, `config`, `ops`, root `*.py`). No
firewall-controller or manager runtime source/test was modified.

---

## 2. Backend changes

### New Docker runtime package

| File | Purpose |
| --- | --- |
| `challenge_runtime/config.py` | Env configuration (endpoint, timeout, publish host, duration, stop/cleanup timeouts). |
| `challenge_runtime/errors.py` | Bounded runtime error types with stable codes. |
| `challenge_runtime/docker_adapter.py` | Lazy Docker SDK access; image, network, container inspect/stop/remove operations. |
| `challenge_runtime/service.py` | Per-instance start/stop/expire/reconcile and safe connection metadata builder. |
| `challenge_runtime/tests/test_runtime_mocked.py` | Mock-only adapter and lifecycle tests. |
| `challenge_runtime/tests/test_real_docker_integration.py` | Real container/HTTP/removal test, skipped by default. |

### Instance application layer

| File | Change |
| --- | --- |
| `instances/services.py` | New. Ownership checks, expiry retirement, DB reservation, idempotent same-challenge starts, duplicate-conflict handling, fail-closed start errors. |
| `instances/views.py` | Real start/stop/active API; 201/200/400/404/409/503 responses. Docker work removed from views. |
| `instances/serializers.py` | Adds `remaining_seconds` and `failure_reason`; keeps internal container/network IDs private. |
| `instances/tasks.py` | `instances.cleanup_expired` Celery task. |
| `instances/management/commands/cleanup_instances.py` | Host-side cleanup command for deployments without a worker. |
| `instances/tests/test_instances.py` | Updated from 503 assertions to real lifecycle, ownership, failure, expiry and concurrency tests. |

### Challenge runtime configuration

`challenges/migrations/0002_stage_1c_runtime_fields.py` adds admin-managed
fields to `Challenge`:

- `runtime_enabled`
- `runtime_image`
- `runtime_command` (shell string or JSON array; JSON array recommended)
- `runtime_connection_type` (`http`, `https`, `tcp`, `other`)
- `runtime_internal_port`
- `runtime_cpu_limit`
- `runtime_memory_mb`
- `runtime_pids_limit`
- `runtime_read_only`
- `runtime_duration_minutes` (0 uses the global default)

`challenges/serializers.py` exposes these only in the admin serializer. Public
challenge payloads do not reveal image/command/internal configuration. Admin
validation requires an image and internal port when runtime is enabled.

`config/settings.py` registers the cleanup beat entry:

```python
'stage1c-instance-cleanup': {
    'task': 'instances.cleanup_expired',
    'schedule': _env_int('CELERY_INSTANCE_CLEANUP_INTERVAL_SECONDS', 60),
},
```

`requirements.txt` adds `docker==7.1.0`. The local venv was updated with the
same version.

---

## 3. Lifecycle and correctness

### Start

1. Challenge must be published and configured with image + internal port.
2. Expired rows for the user are retired first; cleanup errors are non-fatal.
3. Inside a transaction, any non-terminal instance is locked/checked.
   - Different challenge -> `409 INSTANCE_CONFLICT`.
   - Same challenge -> existing row returned (`200`) instead of a duplicate.
4. A `requested` row is created with expiry. The DB partial unique constraint
   `unique_active_instance_per_user` remains the final guard.
5. Outside the transaction, the adapter pulls/resolves the image, creates a
   per-instance bridge network and container, waits (bounded) for `running`,
   inspects ports and only then stores `running` + real connection metadata.
6. Any failure marks the row `failed` with a bounded reason and cleans partial
   container/network resources. A retry is never blocked by a stale row.

### Stop

- Only the caller's own active row is selected (`filter(user=request.user)`).
- Container is stopped and removed by stored ID, or adopted by stored name for
  restart recovery.
- The private network is removed. Already-stopped/missing containers are
  handled as success.
- Connection metadata is cleared and `stopped_at` is set.

### Expiry / restart recovery

- `GET /instances/active/` retires an expired row before returning.
- `POST .../start/` retires expired rows before reserving a new one.
- `instances.cleanup_expired` (Beat every 60s by default) and
  `manage.py cleanup_instances` call `ChallengeRuntimeService.reconcile()`.
- Reconciliation inspects running/starting containers, refreshes published
  ports, and marks missing/exited containers `failed` so stale access details
  are not served after a backend restart.

---

## 4. Container security restrictions

Each container is created with:

- dedicated Docker bridge network per instance
- `com.docker.network.bridge.enable_icc=false`
- published port bound to `127.0.0.1` only, dynamic host port
- `privileged=False`
- `cap_drop=['ALL']`
- `security_opt=['no-new-privileges:true']`
- `pids_limit`, `mem_limit` and CPU period/quota from challenge config
- read-only root filesystem with a bounded `tmpfs` on `/tmp`
- `restart_policy={'Name': 'no'}`, `auto_remove=False`
- tracking labels (`flaghunt.managed=true`, instance/user/challenge IDs)
- no host bind mounts

API responses expose only public connection metadata. Internal container IDs,
network IDs, daemon socket details and exception tracebacks are never sent to
clients.

---

## 5. API contract

| Method | Endpoint | Result |
| --- | --- | --- |
| `POST` | `/api/v1/challenges/<pk>/instances/start/` | `201` serialized running instance; `200` if same challenge already active; `400` not eligible; `404` missing; `409` different active instance; `503` runtime failure. |
| `GET` | `/api/v1/challenges/instances/active/` | `200` serialized active instance or `204`. |
| `DELETE` | `/api/v1/challenges/instances/active/` | `200` serialized stopped instance or `204`; `503` on runtime cleanup failure. |

Serialized shape now includes:

```json
{
  "id": 11,
  "challenge_id": 7,
  "challenge_title": "Example",
  "status": "running",
  "expires_at": "2099-01-01T00:10:00Z",
  "remaining_seconds": 600,
  "created_at": "2099-01-01T00:00:00Z",
  "stopped_at": null,
  "connection_meta": {
    "type": "http",
    "host": "127.0.0.1",
    "port": 45001,
    "target": "127.0.0.1:45001",
    "url": "http://127.0.0.1:45001",
    "container_id": "<daemon id>"
  },
  "failure_reason": ""
}
```

`container_id` inside `connection_meta` is a daemon-side identifier for traceability,
not a privileged API control surface. Internal DB fields remain unserialized.

---

## 6. Frontend changes

| File | Change |
| --- | --- |
| `src/services/challengeService.js` | Replaced `setTimeout` mocks with real POST/GET/DELETE calls and a `normalizeInstance()` adapter for the snake_case wire shape. |
| `src/pages/ChallengeDetails.jsx` | Real status display (Starting/Running/Stopping/Stopped/Expired/Failed), countdown, connection URL/copy/open, backend error messages, polling while starting/stopping. |
| `src/pages/admin/CreateChallenge.jsx` | Deployment tab now exposes the real Docker runtime fields (enable, image, command, connection type, internal port, limits, duration, read-only root FS) in the existing admin form. |
| `src/pages/admin/ManageChallenges.jsx` | Duplicate action copies the Docker runtime configuration. |
| `scripts/challenges-harness/entry.mjs` | Six service-level tests for real endpoints, normalization, 204, foreign-challenge isolation and error propagation. Generated `out/harness.mjs` was refreshed by the harness runner. |

The frontend never invents connection details. It derives the displayed
command/open target only from `connection_meta` returned by the backend after
Docker confirmed a published port.

---

## 7. Configuration

New optional variables in `ctf-platform-be/.env.example`:

```dotenv
FLAGHUNT_DOCKER_TIMEOUT=60
FLAGHUNT_INSTANCE_DURATION_MINUTES=60
FLAGHUNT_PUBLISH_HOST=127.0.0.1
FLAGHUNT_CONTAINER_STOP_TIMEOUT=10
CELERY_INSTANCE_CLEANUP_INTERVAL_SECONDS=60
# FLAGHUNT_DOCKER_HOST=npipe:////./pipe/dockerDesktopLinuxEngine
```

Leaving the endpoint blank uses the active Docker CLI context. Docker Desktop
29.6.1 was available locally via the `desktop-linux`/default named pipe.

---

## 7a. Follow-up correction: UI 404 and unconfigured challenges

Two issues found during manual UI verification were fixed:

1. **Misleading “That resource was not found.”** — `getInstance()` and
   `stopInstance()` initially called `/api/v1/instances/active/`, but the
   registered route is `/api/v1/challenges/instances/active/`. The URLs in
   `challengeService.js` and the harness assertions were corrected. A Django
   routing test (`InstanceRoutingTests`) now asserts both public instance URLs
   so this contract cannot silently drift again.

2. **“This challenge does not have a Docker runtime configured.”** — existing
   seeded challenges had `runtime_enabled=False` because the migration adds the
   field with a safe default. The React admin form now exposes all Stage 1C
   runtime fields, and the local database’s eight challenges were configured
   with a safe generic demo runtime:
   `python:3.12-alpine`, internal port `8080`, JSON-array command that starts
   `python -m http.server` from `/tmp/www`, 128 MB memory, 0.25 CPU, 32 PIDs,
   read-only root FS and a 60-minute lifetime. Administrators can override
   these per challenge from the Deployment tab or Django admin.

A live API smoke test against the configured challenge then returned:

```
GET  /api/v1/challenges/instances/active/  -> 204
POST /api/v1/challenges/7/instances/start/  -> 201 running
     connection_meta = http://127.0.0.1:14773
GET  /api/v1/challenges/instances/active/  -> 200 running
DELETE /api/v1/challenges/instances/active/ -> 200 stopped
```

The temporary smoke-test user was removed afterward and no managed containers
or networks remained.

---

## 8. Test evidence

All commands were run from `E:\Flag-hunt\ctf-platform-be` unless noted.

### Mock-only + API suite (real Docker test skipped)

```
$env:FLAGHUNT_REAL_DOCKER_TESTS is unset
.\venv\Scripts\python.exe manage.py test instances challenge_runtime -v 1
EXIT=0
Found 61 test(s).
OK (skipped=1)
Ran 61 tests in 25.191s
```

Covers API auth/ownership, one-active constraint, 201/200/400/409/503 paths,
concurrent start (one container start only), failure marking, stop, expiry,
adapter restrictions, image failure, restart reconciliation and metadata
safety.

### Real Docker integration (explicitly enabled)

```
$env:FLAGHUNT_REAL_DOCKER_TESTS='1'
.\venv\Scripts\python.exe manage.py test challenge_runtime.tests.test_real_docker_integration -v 2
EXIT=0
Ran 1 test in 14.029s
OK
```

The test created a real `python:3.12-alpine` container, published a loopback
port, performed a real HTTP request returning `FLAG{REAL_DOCKER_OK}`, then
stopped/removed the container and network. Post-test checks showed no
`flaghunt.managed=true` containers or networks left behind.

This test is skipped by default via `unittest.skipUnless` and also carries a
`pytest.mark.real_docker` marker. Mock-only and real-Docker evidence are
therefore clearly separated.

### Firewall/manager J19 governance boundary unchanged

```
.\venv\Scripts\python.exe -m pytest `
  manager/tests/test_manager_j19_docker_runtime_authority.py `
  broker/tests/test_firewall_controller_j19_docker_runtime_authority.py -q
EXIT=0
44 passed, 2 warnings in 7.48s
```

### Frontend service harness

Run from `E:\Flag-hunt\ctf-platform`:

```
node scripts\challenges-harness\run.mjs
EXIT=0
124/124 passed
```

### Frontend production build

```
npm run build
✓ built in 24.38s
```

### Full backend suite note

A full `manage.py test -v 1` run was attempted but exceeded the 7-minute
command budget in this environment (it reached unrelated health/celery and
settings-audit tests). It is **not** claimed as a passing gate. The targeted
instance/runtime suites and J19 boundary suites above completed with exit code 0.

---

## 9. Out of scope / limitations

- Local Docker only. No cloud/production deployment, remote instance access,
  firewall-controller integration or host firewall changes.
- Only loopback port publication is supported. External exposure needs a
  separately authorized ingress design.
- Challenges must be explicitly configured by an administrator before they can
  start a real container.
- Fully automatic expiry cleanup requires the Celery worker/Beat to be running;
  `manage.py cleanup_instances` is provided for host cron/operator use.
- The real Docker test requires Docker Desktop/Engine and network access to
  pull `python:3.12-alpine` when it is not cached locally.
- Historical Stage 1B authority residuals T-11/T-13/T-27 were not modified and
  remain outside this stage.

---

## 10. Git preservation

No reset, clean, revert, stage or commit was performed.

### Backend (`ctf-platform-be`, repo root `E:\Flag-hunt`)

| Metric | Before Stage 1C | After Stage 1C |
| --- | --- | --- |
| HEAD | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | unchanged |
| Branch | `main` | unchanged |
| Modified tracked | 26 | 27 |
| Staged | 0 | 0 |
| Untracked collapsed | 281 | 284 |
| Untracked expanded | 724 | 740 |

### Frontend (`ctf-platform`)

| Metric | Before Stage 1C | After Stage 1C |
| --- | --- | --- |
| HEAD | `453cbe2b0a017dbd643ff6f77746f85f9965b8d7` | unchanged |
| Branch | `main` | unchanged |
| Modified tracked | 33 | 36 |
| Staged | 0 | 0 |
| Untracked collapsed | 40 | 43 |
| Untracked expanded | 11 | 11 |

All pre-existing user changes were preserved.
