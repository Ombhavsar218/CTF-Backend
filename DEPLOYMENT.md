# Flaghunt deployment and recovery runbook

This document is a **preparation and recovery runbook**, not evidence that the
platform has been deployed or is production-ready. The development environment
(Windows host + Django + SQLite + Docker Redis/Celery) is unchanged. No live
deployment, database switch, or destructive operation was performed while
writing it.

The reference production topology is:

```
Internet
  │  TLS
  ▼
Reverse proxy / load balancer
  ├─ /              -> frontend dist/ (React SPA)
  ├─ /api/, /admin/, /health/ -> Gunicorn -> Django
  ├─ /static/       -> STATIC_ROOT
  ├─ /media/avatars/ -> MEDIA_ROOT/avatars (public profile images)
  └─ /media/challenge_files/ -> DENY (served only by the gated API endpoint)
                    │
                    ├─ PostgreSQL or a durable SQLite file
                    └─ Redis: broker (/0) + shared cache (/1)
                              │
                              ├─ Celery worker
                              └─ Celery Beat
```

Django must not be directly reachable from the internet. The proxy terminates
TLS, forwards `Host` and `X-Forwarded-Proto`, and enforces request-body limits.

## 1. External prerequisites

These are deliberately **not** added to the development setup:

- A TLS-terminating reverse proxy (nginx, Caddy, a cloud load balancer, etc.).
- A supported WSGI server. `requirements-production.txt` adds
  `gunicorn==23.0.0`; it is not installed in the Windows development virtualenv
  and has not been exercised by the local test suite.
- A durable database volume (SQLite) or a PostgreSQL instance and driver.
- Redis with authentication/TLS and persistence appropriate to the broker.
- Centralized log collection, uptime monitoring, and an alert route.
- A backup destination outside the application host.

`docker-compose.yml` is a **local development** file: Redis has no password or
persistence, the source tree is bind-mounted, and the worker runs as root. Do
not deploy it as-is.

## 2. Environment preparation

Create a production `.env` from `.env.example` in a secret manager or on the
host with restrictive permissions. Do not commit it. At minimum:

```dotenv
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=<random 50+ character value>
ALLOWED_HOSTS=ctf.example.com
CSRF_TRUSTED_ORIGINS=https://ctf.example.com
CORS_ALLOWED_ORIGINS=            # empty for a same-origin SPA
TRUST_PROXY_HEADERS=True

SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=3600
SECURE_HSTS_INCLUDE_SUBDOMAINS=False   # enable only after verification
SECURE_HSTS_PRELOAD=False              # opt-in, hard to undo
CSP_REPORT_ONLY=True                   # enforce after reviewing reports

DB_ENGINE=django.db.backends.sqlite3
DB_NAME=/srv/flaghunt/db.sqlite3
CACHE_URL=redis://:CACHE_PASSWORD@redis.internal:6379/1
CELERY_BROKER_URL=redis://:BROKER_PASSWORD@redis.internal:6379/0
CELERY_RESULT_BACKEND=                  # empty = no task results stored

MEDIA_ROOT=/srv/flaghunt/media
STATIC_ROOT=/srv/flaghunt/staticfiles
MAX_CHALLENGE_ATTACHMENT_BYTES=26214400
LOG_FILE=/var/log/flaghunt/django.log
DRF_NUM_PROXIES=1                       # exact number of trusted proxies
```

Generate the secret with:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Rules enforced at import time by `config/deploy.py`:

- `ENVIRONMENT` must be `development` or `production`.
- Production cannot run with `DEBUG=True`.
- Any `DEBUG=False` or production run needs an explicit non-placeholder
  `SECRET_KEY` of at least 50 characters and a non-empty `ALLOWED_HOSTS`.
- Production origins must be bare `https://` origins. CORS wildcards are
  rejected; `CSRF_TRUSTED_ORIGINS` may use `https://*.example.com`.
- Production requires `CACHE_URL`, a valid Redis broker URL, and a **different**
  Redis URL for cache and broker.
- Production requires HTTPS redirect, secure session/CSRF cookies, a positive
  HSTS lifetime, and a CSP that contains no localhost or plain-http sources.
- A non-SQLite database engine requires `DB_NAME`.

Startup fails with `ImproperlyConfigured` and a list of problems rather than
silently running with development settings.

If the SPA is served from a different origin, set its exact origin in
`CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`, and set
`VITE_API_BASE_URL` to the backend API URL at build time.

## 3. Build and start

### Backend

```bash
cd /srv/flaghunt/ctf-platform-be
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-production.txt

python manage.py check
python manage.py check --deploy          # review warnings; do not ignore blindly
python manage.py migrate --plan          # inspect before applying
python manage.py migrate
python manage.py setup_groups            # reconcile Admin group permissions
python manage.py collectstatic --noinput
```

Start Gunicorn behind the proxy:

```bash
gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 3 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile -
```

Gunicorn access logs include the query string. Keep them out of shared logs, or
use a sanitized format, because the Django request logger deliberately does not
log query strings. Tune worker count for the host; SQLite is the limiting
factor and generally supports **one** application instance, not several.

### Frontend

```bash
cd /srv/flaghunt/ctf-platform
npm ci
VITE_API_BASE_URL=/api/v1/ npm run build
```

`VITE_*` values are embedded at build time, so changing the API URL requires a
rebuild. Serve `dist/` from the proxy:

- Hashed `/assets/*` files: long-lived immutable caching.
- `index.html`: `no-cache` / revalidate, with SPA fallback to `index.html`.
- Apply the frontend CSP at the proxy. Django's CSP header only covers API and
  admin responses; it does not protect static SPA files.

### Worker and Beat

Run outside the development Compose file. Example commands:

```bash
celery -A config worker --loglevel=INFO --concurrency=2
celery -A config beat --loglevel=INFO \
  --schedule=/var/lib/celery/celerybeat-schedule \
  --pidfile=/var/lib/celery/celerybeat.pid
```

Use a persistent volume for `/var/lib/celery`. Worker and Beat must use the same
broker database.

## 4. Database: backup, restore, migration, rollback

### SQLite limitations

SQLite is the development default and is acceptable only for a single
application instance with modest write concurrency. It has no point-in-time
recovery, streaming replication, or network clients. A file copy while the
database is open can be inconsistent; use SQLite's backup API or stop writes.
Cross-boundary locking between Windows and Docker is not guaranteed, which is
why background jobs must remain read-free/idempotent. Do not scale Django to
multiple hosts on SQLite.

### Backup

Use a maintenance window or stop application writes. A consistent SQLite backup:

```bash
python - <<'PY'
import sqlite3
src = sqlite3.connect('/srv/flaghunt/db.sqlite3')
dst = sqlite3.connect('/backups/flaghunt-YYYYmmdd-HHMMSS.sqlite3')
src.backup(dst)
dst.close()
src.close()
PY
```

Then verify and record:

```bash
python - <<'PY'
import sqlite3
db = sqlite3.connect('/backups/flaghunt-YYYYmmdd-HHMMSS.sqlite3')
print(db.execute('PRAGMA integrity_check').fetchone())
print(db.execute('PRAGMA foreign_key_check').fetchall())
for table in ('users_user', 'challenges_challenge', 'submissions_solve'):
    print(table, db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
db.close()
PY
```

Back up `MEDIA_ROOT` (avatars and challenge files) separately, preserving
filenames. The database does **not** contain uploaded file bytes. Also back up
the non-secret deployment configuration and the release artifact/commit ID.
Store backups off-host, encrypt them if they contain personal data, and define a
retention period.

### Restore

1. Announce maintenance and stop the proxy upstream, Gunicorn, the worker, and
   Beat.
2. Move the current database aside as `db.sqlite3.failed-<timestamp>`; do not
   delete it.
3. Copy the verified backup into place and set ownership/permissions for the
   service account.
4. Restore `MEDIA_ROOT` from the matching media backup.
5. Run `python manage.py check`, `python manage.py migrate --plan` (normally no
   migrations), and query row counts.
6. Start the services, then check `/health/live/`, `/health/ready/`, and
   `/health/celery/` and run the smoke tests below.
7. Keep the failed database and logs until the incident is closed.

### Isolated restore validation

Never test a restore against the live database. On a separate host or directory:

```bash
export DB_NAME=/srv/flaghunt/restore-test/db.sqlite3
export MEDIA_ROOT=/srv/flaghunt/restore-test/media
export ENVIRONMENT=development
export DEBUG=True
python manage.py check
python manage.py showmigrations
python manage.py shell -c "from django.contrib.auth import get_user_model; from challenges.models import Challenge; from submissions.models import Solve; print(get_user_model().objects.count(), Challenge.objects.count(), Solve.objects.count())"
```

Compare the counts and a representative record with the backup manifest. Exercise
a login, a challenge read, and an attachment download in the isolated copy.

### Migrations and rollback

```bash
python manage.py makemigrations --check --dry-run   # must report no changes
python manage.py migrate --plan
python manage.py migrate
```

Take a backup immediately before every schema migration. If a migration fails,
prefer restoring the pre-migration backup over improvising a reverse migration.
Only run `migrate <app> <previous>` when its reverse path has been reviewed and
tested. Never use `--fake` to skip a failed migration. A rollback of application
code without rolling back an incompatible schema can break the old release;
deploy code and schema together.

### PostgreSQL path (not enabled by default)

Do not switch the development database silently. When explicitly moving to
PostgreSQL:

1. Provision PostgreSQL and take a baseline backup.
2. Install a psycopg driver compatible with the chosen PostgreSQL version.
3. Set `DB_ENGINE=django.db.backends.postgresql`, `DB_NAME`, `DB_USER`,
   `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and optionally `DB_SSLMODE`.
4. Run `migrate --plan` and `migrate` against a new empty database.
5. Export/import data deliberately (`dumpdata`/`loaddata` or a reviewed ETL) and
   reconcile user, challenge, solve, submission, achievement, and audit counts.
6. Copy `MEDIA_ROOT` separately; it is not part of the database dump.
7. Cut over in maintenance, keep the SQLite file and a verified dump as
   rollback artifacts, and run the full smoke test.

PostgreSQL adds transactional DDL, concurrent access, and `pg_dump`/`pg_restore`
based recovery. Those benefits are not available until the switch is performed
and verified; the current environment remains SQLite.

## 5. Redis and Celery

- Broker: use a dedicated Redis database or instance. Enable authentication and
  TLS (`rediss://`) if Redis is not on a private network.
- Cache: use a different database/instance from the broker. The application
  rejects an identical `CACHE_URL` and `CELERY_BROKER_URL` in production so
  cache eviction cannot discard task messages.
- Broker persistence: enable AOF/append-only or an appropriate snapshot policy
  with a persistent volume if queued work must survive a restart. The only
  scheduled task today is an idempotent heartbeat, so losing messages is not
  currently a data-loss event, but that assumption must be revisited before
  adding DB-writing tasks.
- Cache persistence is not required; it only holds throttle counters.
- Health: `/health/ready/` checks the Django database and configured broker;
  `/health/celery/` checks a live worker control ping and a fresh Beat heartbeat.
  Readiness intentionally does not depend on Celery.
- Beat freshness uses the existing `ops.heartbeat` task and Redis marker. Do not
  add a separate fake health task.

## 6. Media and static files

- `MEDIA_ROOT` must be a durable, backed-up volume writable by the Django
  service account. It is not inside the code release directory.
- **Avatars:** `MEDIA_ROOT/avatars/` is public profile data. The proxy may serve
  it directly at `/media/avatars/`.
- **Challenge files:** stored under `MEDIA_ROOT/challenge_files/`. The API
  returns a gated URL:
  `GET /api/v1/challenges/{id}/attachments/{attachment_id}/download/`.
  Published challenge files are public; draft/scheduled files require
  `challenges.view_challenge`, otherwise the endpoint returns 404. Files are
  sent as attachments with `Cache-Control: private, no-store`.
- **Block direct challenge-file access at the proxy.** Deny
  `/media/challenge_files/`; do not map all of `/media/`. Django only serves
  media when `DEBUG=True`, but a reverse proxy that serves `MEDIA_ROOT` wholesale
  would bypass the authorization endpoint.
- The application caps challenge uploads at
  `MAX_CHALLENGE_ATTACHMENT_BYTES` (25 MiB by default). The proxy should reject
  larger request bodies too. Uploads are not virus-scanned and any file type can
  be attached; treat challenge files as untrusted downloads and keep
  `X-Content-Type-Options: nosniff`.
- `STATIC_ROOT` is for `collectstatic` only. The proxy serves `/static/`; Django
  does not serve static files in production.

## 7. Logs and observability

- Console/stdout logging is always enabled. `LOG_FILE` adds a rotating file
  (`LOG_FILE_MAX_BYTES`, `LOG_FILE_BACKUP_COUNT`); the parent directory must exist
  and be writable. Container log collection should replace file logging if
  stdout is already captured.
- `REQUEST_LOG_ENABLED=True` writes one line per request with method, path,
  status, duration, user id, and request ID. It does not log bodies, query
  strings, or headers.
- Every response carries `X-Request-ID`. Use it to correlate a user report with
  server logs. A redaction filter scrubs common credential/flag shapes, but it is
  a safety net, not permission to log sensitive data.
- Collect Gunicorn, Django, Celery worker, and Beat logs; alert on 5xx rates,
  `/health/live/` failures, readiness failures, Celery heartbeat staleness, and
  backup failures. A green health endpoint is not a substitute for monitoring.

## 8. Smoke tests after release

```bash
curl -fsS https://ctf.example.com/health/live/
curl -fsS https://ctf.example.com/health/ready/
curl -fsS https://ctf.example.com/health/celery/
```

Then verify, using a staging or dedicated smoke-test account:

1. SPA loads over HTTPS with no mixed-content/CSP failures.
2. Login, refresh, logout; tokens rotate and the old refresh token is rejected.
3. Public challenge list/detail loads; a draft is not visible.
4. A published attachment downloads through the gated endpoint; a draft
   attachment returns 404 to an ordinary user; direct `/media/challenge_files/`
   returns 404/403 at the proxy.
5. Flag submission, hint reveal, streaks/achievements/leaderboard still work.
6. Admin challenge/category/settings mutations work and produce audit rows.
7. `/health/celery/` is healthy after one Beat interval.
8. Logs contain request IDs and no secrets/flags; backups completed.

Run the repository checks before promoting the release:

```bash
cd ctf-platform-be
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
cd ../ctf-platform
node scripts/admin-users-harness/run.mjs
node scripts/challenges-harness/run.mjs
node scripts/settings-harness/run.mjs
node scripts/history-harness/run.mjs
node scripts/api-harness/run.mjs
npm run build
```

## 9. Rollback

1. Stop new traffic at the proxy.
2. Redeploy the previous frontend `dist/` and backend release.
3. If the rollback includes a database restore, follow the restore procedure
   above; do not run an untested reverse migration.
4. Restore the matching `MEDIA_ROOT` only if the rollback also needs the older
   uploads. Newer uploaded files are not harmful to an older read path unless the
   older schema cannot represent them.
5. Restart Gunicorn, worker, and Beat; verify health, a login, challenge reads,
   and the gated attachment path.
6. Keep the failed release's database, media, and logs for analysis.

## 10. Known risks and unresolved items

- No live deployment, domain, TLS certificate, proxy, Redis auth, monitoring, or
  off-host backup has been exercised here. Docker runtime verification was
  blocked because the Linux engine was unavailable.
- The Gunicorn pin and production dependency install are documented but not
  locally exercised on Windows.
- SQLite remains the active database and has the limitations above. PostgreSQL
  is a documented migration path, not a completed migration.
- CSP is report-only by default and allows inline scripts for Django admin. The
  SPA needs its own CSP at the proxy. Review reports before enforcing.
- Rate limiting is only as consistent as the configured shared cache. Edge/WAF
  limits, connection limits, and DDoS protection are still required.
- JWTs live in browser `localStorage`; XSS would expose them. Keep the CSP
  strict and dependencies patched.
- Dependency advisories remain, including `xlsx@0.18.5` and Pillow `12.3.0`.
  Do not wire the Excel parser to uploads without replacing or validating it.
- Challenge attachments are not malware-scanned. The gated endpoint and proxy
  rules prevent draft disclosure, not malicious content.
- There is no browser/E2E test suite; verification is limited to backend tests,
  Node service harnesses, the Vite build, and manual smoke checks.
- Alert delivery, log retention, backup restore drills, and a maintenance
  calendar are operational responsibilities not implemented in this repository.

## Related documentation

- [Backend README](README.md) — API, security settings, Redis/Celery details.
- [Repository README](../README.md) — development setup and known limitations.
- [Frontend README](../ctf-platform/README.md) — build and environment setup.
