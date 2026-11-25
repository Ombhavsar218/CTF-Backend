# Shared image for the Celery worker and Celery Beat.
#
# Django itself is NOT containerised: it keeps running on the Windows host
# against SQLite. Only this image's two entrypoints (celery worker / celery
# beat) are used by the compose project.
#
# Build context is this backend directory. The source is also bind-mounted at
# runtime (read-only at /app) so edits on the host are picked up without a
# rebuild; the COPY below only makes the image usable on its own.
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# All runtime dependencies ship manylinux wheels, so no compiler toolchain is
# installed. Override the index when the default PyPI host is unreachable, e.g.
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r /app/requirements.txt

COPY . /app
