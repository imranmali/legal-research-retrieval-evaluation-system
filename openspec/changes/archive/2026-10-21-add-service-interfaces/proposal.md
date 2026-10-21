# Proposal

## Why

The evaluation engine, retrievers and legal metrics are only useful to legal
research teams if they can be driven from a terminal, a CI job and other
services. Evaluation-as-a-service lets search platforms gate releases on
retrieval quality without embedding Python.

## What Changes

- A `groundtruth` command-line tool: `evaluate`, `compare`, `retrieve`,
  `benchmark`, `validate`, `metrics`, `serve` and `version`.
- A versioned HTTP API (`/v1`) for evaluating runs, comparing systems, listing
  metrics and searching an optionally preloaded legal corpus.
- Production concerns for the service: environment-based configuration,
  optional API-key authentication, request size limits, request ids,
  structured JSON logging, Prometheus metrics, liveness/readiness probes.

## Capabilities

### New Capabilities
- `command-line-interface`: Terminal workflows over files.
- `evaluation-api`: HTTP evaluation, comparison and search service.

### Modified Capabilities
- None.

## Out of Scope

- Persisting evaluation history or a web UI.
- User management; API keys are configured by the operator.
- Rate limiting (delegated to the ingress / API gateway).

## Impact

- New modules `groundtruth/cli.py`, `groundtruth/config.py`, `groundtruth/logging.py`,
  `groundtruth/api/`. Uses FastAPI, uvicorn, typer, prometheus-client (already declared).
