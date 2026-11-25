# Production-ready Django image for Flaghunt backend.
#
# Default runtime serves HTTP + WebSocket via Daphne (ASGI) so existing Django
# Channels terminal functionality works in production. Gunicorn remains installed
# for WSGI-only use cases. The same image can also run Celery worker/Beat by
# overriding the command.
#
# Build context: ctf-platform-be/
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# System packages: libpq for psycopg PostgreSQL connectivity, curl for optional
# container healthchecks, and ca-certificates for TLS. Removed after use where
# possible to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Override the index when the default PyPI host is unreachable, e.g.
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple -t flaghunt-backend .
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements-production.txt requirements.txt /app/
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r /app/requirements-production.txt

# Copy application source.
COPY . /app

# Create a non-root runtime user and ensure application paths are readable.
# MEDIA_ROOT/STATIC_ROOT defaults live under /app; runtime deployments should
# mount persistent volumes as needed and ensure ownership/permissions.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --home /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app \
    && chmod +x /app/docker/entrypoint.sh

# Collect static files at build time using a safe development configuration.
# No production secrets or external services are required for collectstatic.
RUN ENVIRONMENT=development \
    DJANGO_SETTINGS_MODULE=config.settings \
    DEBUG=True \
    SECRET_KEY=docker-build-collectstatic-placeholder-key-not-for-production \
    python manage.py collectstatic --noinput \
    && chown -R app:app /app/staticfiles

USER app

# Render provides PORT at runtime. Default to 8000 for local use.
ENV PORT=8000

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Default command: ASGI server for HTTP + WebSocket (Django Channels terminal).
# Render sets $PORT. For WSGI-only deployments, override with gunicorn.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
