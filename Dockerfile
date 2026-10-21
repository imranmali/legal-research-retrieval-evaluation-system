#
# Ground Truth evaluation service image.
#
# Stage 1 resolves and installs the locked runtime dependencies plus the
# project itself (as a regular, non-editable install) into /opt/venv.
# Stage 2 copies only that virtual environment and the sample collection into
# a slim Python base: no uv, no compilers, no tests, no dev dependencies.

# Base images are spelled out literally (not via ARG) so Dependabot can bump them.
# Builder and runtime must use the same Python image: the venv links to it.
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=uv /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

# Dependencies first so the layer is reused while only application code changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-editable --no-install-project

# pyproject.toml references README.md and LICENSE, so the build needs them.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ARG VERSION=0.0.0+local
ARG REVISION=unknown

LABEL org.opencontainers.image.title="groundtruth" \
      org.opencontainers.image.description="Ground Truth: evaluation service for legal research retrieval systems" \
      org.opencontainers.image.source="https://github.com/imranmali/legal-research-retrieval-evaluation-system" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    WEB_CONCURRENCY=2 \
    PORT=8000

RUN groupadd --system --gid 10001 groundtruth \
 && useradd --system --uid 10001 --gid groundtruth --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin groundtruth

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=root:root deploy/gunicorn.conf.py /app/gunicorn.conf.py
COPY --chown=root:root data/sample /app/data/sample

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

# GROUNDTRUTH_CORPUS_PATH is intentionally unset: /v1/search answers 503 until
# an operator points it at a corpus (e.g. /app/data/sample/corpus.jsonl).
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "groundtruth.api.app:create_app()"]
