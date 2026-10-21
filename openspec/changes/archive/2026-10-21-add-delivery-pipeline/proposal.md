# Proposal

## Why

A production evaluation service needs every change verified automatically and
a repeatable path from merged code to a running, horizontally scalable
deployment. Without it, regressions in metric math or the API ship silently.

## What Changes

- GitHub Actions CI on pull requests and pushes: lint, format, strict typing,
  tests with coverage gate on Python 3.11–3.13, OpenSpec validation, package
  build, container build with smoke test.
- Continuous delivery: on `main`, publish the container image to GHCR; on
  `v*` tags, build the distribution, create a GitHub release and publish
  versioned images.
- Hardened multi-stage container image (non-root, health check, gunicorn with
  uvicorn workers), docker-compose for local runs, Kubernetes manifests with
  probes, resource limits, HPA and PodDisruptionBudget.
- Project hygiene: pre-commit, Dependabot, PR template, CONTRIBUTING, SECURITY,
  CHANGELOG, full README.

## Capabilities

### New Capabilities
- `delivery-pipeline`: Verification gates, release artifacts and deployment packaging.

### Modified Capabilities
- None.

## Out of Scope

- Cloud-provider-specific infrastructure (Terraform, managed clusters).
- Publishing to PyPI (needs maintainer credentials; workflow documents the step).

## Impact

- New `.github/`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `deploy/k8s/`,
  docs files. No library code changes.
