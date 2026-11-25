#!/bin/sh
set -eu

# Docker entrypoint for Flaghunt backend.
#
# Responsibilities:
# - Optionally wait for PostgreSQL readiness.
# - Optionally run Django deployment checks.
# - Optionally collect static files (off by default; image build collects them).
# - Start the requested command (Daphne ASGI by default; Gunicorn supported).
#
# Migrations are intentionally NOT run automatically on every container start.
# Run them explicitly as a one-off deployment step:
#   docker compose run --rm backend python manage.py migrate

log() {
  printf '[entrypoint] %s\n' "$*"
}

warn() {
  printf '[entrypoint] WARNING: %s\n' "$*" >&2
}

die() {
  printf '[entrypoint] ERROR: %s\n' "$*" >&2
  exit 1
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_db() {
  max_attempts="${DB_WAIT_MAX_ATTEMPTS:-60}"
  interval="${DB_WAIT_INTERVAL_SECONDS:-2}"

  case "$max_attempts" in
    ''|*[!0-9]*) max_attempts=60 ;;
  esac
  case "$interval" in
    ''|*[!0-9]*) interval=2 ;;
  esac
  [ "$max_attempts" -ge 1 ] || max_attempts=1
  [ "$interval" -ge 1 ] || interval=1

  attempt=1
  log "Waiting for database readiness (max_attempts=${max_attempts}, interval=${interval}s)..."
  while [ "$attempt" -le "$max_attempts" ]; do
    if python - <<'PY'
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings"))

try:
    import django
    django.setup()
    from django.db import connections
    for conn in connections.all():
        conn.close_if_unusable_or_obsolete()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
except Exception as exc:
    print(exc.__class__.__name__, file=sys.stderr)
    raise SystemExit(1)
PY
    then
      log "Database is ready."
      return 0
    fi

    log "Database not ready (attempt ${attempt}/${max_attempts}); retrying in ${interval}s."
    attempt=$((attempt + 1))
    sleep "$interval"
  done

  die "Database was not ready after ${max_attempts} attempts."
}

should_wait_for_db() {
  if is_truthy "${DJANGO_WAIT_FOR_DB:-}"; then
    return 0
  fi
  if is_truthy "${DJANGO_SKIP_DB_WAIT:-0}"; then
    return 1
  fi

  db_engine="${DB_ENGINE:-django.db.backends.sqlite3}"
  case "$db_engine" in
    *sqlite3*) return 1 ;;
    *) return 0 ;;
  esac
}

run_deploy_checks() {
  if is_truthy "${DJANGO_RUN_CHECKS:-0}"; then
    log "Running Django system checks..."
    python manage.py check --fail-level WARNING
  fi

  if is_truthy "${DJANGO_RUN_DEPLOY_CHECKS:-0}"; then
    log "Running Django deploy checks..."
    python manage.py check --deploy --fail-level ERROR
  fi
}

run_collectstatic() {
  if is_truthy "${DJANGO_COLLECTSTATIC_ON_START:-0}"; then
    log "Collecting static files..."
    python manage.py collectstatic --noinput
  fi
}

# Gunicorn PORT normalization is handled in main() to keep runtime behavior explicit.

main() {
  if should_wait_for_db; then
    wait_for_db
  else
    log "Skipping database wait."
  fi

  run_deploy_checks
  run_collectstatic

  # Ensure the web server binds to Render's $PORT.
  if [ "${1:-}" = "gunicorn" ]; then
    port="${PORT:-8000}"
    fixed_args=""
    for arg in "$@"; do
      case "$arg" in
        0.0.0.0:8000) fixed_args="$fixed_args 0.0.0.0:${port}" ;;
        *) fixed_args="$fixed_args $(printf '%s' "$arg" | sed "s/'/'\\\\''/g;1s/^/'/;\$s/\$/'/")" ;;
      esac
    done
    # shellcheck disable=SC2086
    eval "set -- $fixed_args"
    has_bind=0
    for arg in "$@"; do
      [ "$arg" = "--bind" ] && has_bind=1
    done
    if [ "$has_bind" -eq 0 ]; then
      set -- "$@" --bind "0.0.0.0:${port}"
    fi
  elif [ "${1:-}" = "daphne" ]; then
    port="${PORT:-8000}"
    # Replace explicit -p 8000 with Render PORT and add -p/-b if missing.
    fixed_args=""
    skip_next=0
    has_port=0
    has_bind=0
    for arg in "$@"; do
      if [ "$skip_next" -eq 1 ]; then
        skip_next=0
        continue
      fi
      case "$arg" in
        -p|--port)
          skip_next=1
          has_port=1
          fixed_args="$fixed_args -p ${port}"
          ;;
        -b|--bind)
          skip_next=1
          has_bind=1
          fixed_args="$fixed_args -b 0.0.0.0"
          ;;
        *)
          fixed_args="$fixed_args $(printf '%s' "$arg" | sed "s/'/'\\\\''/g;1s/^/'/;\$s/\$/'/")"
          ;;
      esac
    done
    # shellcheck disable=SC2086
    eval "set -- $fixed_args"
    if [ "$has_bind" -eq 0 ]; then
      set -- "$@" -b 0.0.0.0
    fi
    if [ "$has_port" -eq 0 ]; then
      set -- "$@" -p "${port}"
    fi
    if is_truthy "${TRUST_PROXY_HEADERS:-0}" && [ "${DAPHNE_PROXY_HEADERS:-1}" != "0" ]; then
      has_proxy_headers=0
      for arg in "$@"; do
        [ "$arg" = "--proxy-headers" ] && has_proxy_headers=1
      done
      if [ "$has_proxy_headers" -eq 0 ]; then
        set -- "$@" --proxy-headers
      fi
    fi
  fi

  log "Starting: $*"
  exec "$@"
}

main "$@"
