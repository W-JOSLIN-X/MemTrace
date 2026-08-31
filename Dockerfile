# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436
ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91

FROM ${NODE_IMAGE} AS web-builder

WORKDIR /build/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY apps/web/ ./
RUN npm run build


FROM ${PYTHON_IMAGE} AS runtime

ARG VCS_REF=unknown
ARG IMAGE_SOURCE=https://github.com/W-JOSLIN-X/MemTrace

LABEL org.opencontainers.image.title="MemTrace" \
    org.opencontainers.image.version="0.1.0" \
    org.opencontainers.image.revision="${VCS_REF}" \
    org.opencontainers.image.source="${IMAGE_SOURCE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    MEMTRACE_DATA_DIR=/app/data \
    MEMTRACE_WEB_DIST=/app/static \
    PYTHONPATH=/app/apps/api/src

WORKDIR /app

RUN groupadd --gid 10001 memtrace \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin memtrace \
    && mkdir -p /app/apps/api/src /app/contracts/schemas /app/static /app/data /app/backups /app/ops \
    && chown -R memtrace:memtrace /app

COPY apps/api/requirements.runtime.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --require-hashes --no-deps -r /tmp/requirements.lock \
    && python -m pip uninstall --yes setuptools \
    && python -m pip uninstall --yes pip \
    && rm -f /tmp/requirements.lock

COPY --chown=memtrace:memtrace apps/api/src/ /app/apps/api/src/
COPY --chown=memtrace:memtrace apps/api/alembic.ini /app/apps/api/alembic.ini
COPY --chown=memtrace:memtrace apps/api/alembic/ /app/apps/api/alembic/
COPY --chown=memtrace:memtrace contracts/schemas/memory-pack.schema.json /app/contracts/schemas/memory-pack.schema.json
COPY --chown=memtrace:memtrace contracts/schemas/memory-pack-v2.schema.json /app/contracts/schemas/memory-pack-v2.schema.json
COPY --chown=memtrace:memtrace scripts/day7/backup_sqlite.py /app/ops/backup_sqlite.py
COPY --chown=memtrace:memtrace scripts/day7/restore_sqlite.py /app/ops/restore_sqlite.py
COPY --from=web-builder --chown=memtrace:memtrace /build/apps/web/dist/ /app/static/

USER memtrace

EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=2).read()"]

CMD ["python", "/app/apps/api/src/memtrace_api/docker_entrypoint.py"]
