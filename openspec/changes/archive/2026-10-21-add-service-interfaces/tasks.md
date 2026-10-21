# Tasks

## 1. Configuration and logging

- [x] 1.1 Implement `Settings` in `groundtruth/config.py` and JSON logging in `groundtruth/logging.py`; verify `tests/test_config.py`

## 2. CLI

- [x] 2.1 Implement `evaluate`, `compare`, `validate`, `metrics`, `version` with output formats and quality gates in `groundtruth/cli.py`; verify `tests/cli/test_cli.py` using Typer's CliRunner
- [x] 2.2 Implement `retrieve`, `benchmark` and `serve`; verify benchmark on `data/sample` in `tests/cli/test_cli_retrieval.py`

## 3. HTTP API

- [x] 3.1 Implement schemas, app factory, `/v1/evaluate`, `/v1/compare`, `/v1/metrics`, `/v1/search`; verify `tests/api/test_endpoints.py` with TestClient
- [x] 3.2 Implement request id, body limit, auth, error handlers and Prometheus metrics; verify `tests/api/test_middleware.py` (401, 413, request id echo, 500 format, /metrics content)

## 4. Integration

- [x] 4.1 Run `make check`; verify ruff, mypy --strict and pytest with coverage >= 90% pass

## Workflow follow-up

- Archive with `openspec archive add-service-interfaces -y` after merge review.
