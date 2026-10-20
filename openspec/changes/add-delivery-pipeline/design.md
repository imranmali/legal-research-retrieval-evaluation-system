# Design

## Context

Library and service code come from the other three changes. The service entry
point is `groundtruth.api.app:create_app` (factory); CLI entry `groundtruth`.

## Goals / Non-Goals

**Goals:** reproducible builds from `uv.lock`; minimal attack surface; zero-downtime rollouts.

**Non-Goals:** environment-specific infrastructure code.

## Decisions

- **uv everywhere** (`astral-sh/setup-uv`), `uv sync --locked` so CI fails on a stale lock.
- **Workflows**: `ci.yml` (jobs: `lint` → ruff/format/mypy; `test` matrix 3.11/3.12/3.13
  with coverage XML artifact; `spec` → `npx @fission-ai/openspec validate --all --strict`;
  `build` → `uv build` + `twine check`-equivalent via `uv build`; `docker` → buildx build,
  run container, curl `/healthz` and POST `/v1/evaluate`; `k8s` → kubeconform validation),
  `cd.yml` (push to `main`: build + push `ghcr.io/<owner>/<repo>` tags `main`, `sha-<short>`),
  `release.yml` (tag `v*`: verify tag matches `pyproject` version, build dist,
  `softprops/action-gh-release`, push image tags `<version>` and `latest`).
  Concurrency groups cancel superseded runs; least-privilege `permissions`.
- **Dockerfile**: builder stage `ghcr.io/astral-sh/uv` + `python:3.12-slim`, `uv sync --locked
  --no-dev --no-editable` into `/opt/venv`; runtime stage `python:3.12-slim`, copies venv and
  sample data, user `groundtruth` (uid 10001), `HEALTHCHECK` via python urllib,
  `CMD gunicorn -k uvicorn.workers.UvicornWorker` with `WEB_CONCURRENCY` workers and
  `--factory`-equivalent `"groundtruth.api.app:create_app()"`.
- **Kubernetes** (`deploy/k8s/`, kustomize): Deployment (3 replicas, rolling update
  maxUnavailable 0, probes, read-only root fs, drop all capabilities), Service, ConfigMap,
  HPA (CPU 70%, 3–20 replicas), PDB (minAvailable 2).

## Risks / Trade-offs

- [GHCR push needs `packages: write`] → granted only in cd/release workflows.
- [Third-party actions supply chain] → pinned to major versions from verified publishers; Dependabot keeps them current.
