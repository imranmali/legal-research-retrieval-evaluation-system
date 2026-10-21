# Design

## Context

Builds on `groundtruth.io`, `groundtruth.evaluation.evaluate`,
`groundtruth.stats.compare_many`, `groundtruth.reporting`, `groundtruth.legal`
and `groundtruth.retrieval` (see the two earlier changes).

## Goals / Non-Goals

**Goals:**
- Stateless API so it scales horizontally behind a load balancer.
- Same results from CLI, API and library.

**Non-Goals:**
- Async job queue; evaluations are bounded by request limits and complete in-request.

## Decisions

- **Typer** for the CLI (`groundtruth/cli.py`, `app = typer.Typer()`), rich tables
  for terminal output. Domain errors (`GroundTruthError`) map to exit code 2;
  failed quality gates to exit code 1.
- **FastAPI app factory** `groundtruth.api.app:create_app(settings: Settings | None = None)`
  so tests inject settings; module-level `app = create_app()` is not created at import —
  production uses `uvicorn --factory groundtruth.api.app:create_app` /
  gunicorn with `groundtruth.api.app:create_app()`.
- **Configuration** via pydantic-settings `groundtruth/config.py` `Settings` with
  prefix `GROUNDTRUTH_`: `api_keys` (comma-separated), `max_body_bytes`
  (default 50 MiB), `max_run_entries` (default 5,000,000), `corpus_path`,
  `retriever` (default `bm25`), `log_level`, `log_json` (default true),
  `cors_origins`, `default_resamples`.
- **Endpoint handlers are sync `def`** so CPU-bound evaluation runs in the
  FastAPI threadpool and never blocks the event loop.
- **Middleware**: pure ASGI middleware for request id, body-size limit
  (checks `Content-Length` and counts streamed bytes) and Prometheus
  instrumentation (`groundtruth_http_requests_total`,
  `groundtruth_http_request_duration_seconds`, labelled by route template).
- **Logging** `groundtruth/logging.py`: JSON formatter with request id via contextvar.
- **Corpus preload**: in the lifespan handler, load `corpus_path` and fit the
  configured retriever once; shared read-only across requests.

## Implementation notes

- Package layout: `api/app.py` (factory, lifespan), `api/state.py` (`ServiceState`:
  settings, per-app Prometheus `CollectorRegistry`, ready flag, corpus and retriever),
  `api/routes.py`, `api/schemas.py`, `api/middleware.py`, `api/errors.py`.
- `configure_logging(level, *, json_format=True)`; JSON lines carry `request_id`
  from a contextvar. The middleware writes one `groundtruth.access` line per
  request, so the server access log (`uvicorn.access`) is silenced.
- The body limit is enforced when the application first reads the body
  (declared `Content-Length` or streamed byte count), so rejected requests are
  still routed and labelled with their route template in metrics and logs.
- Unexpected exceptions are turned into `500 internal_error` by the outermost
  request middleware so that the response still carries `X-Request-ID`.
- API keys are `SecretStr` values compared with `secrets.compare_digest` against
  every configured key.
- Gunicorn uses `uvicorn_worker.UvicornWorker` from the `uvicorn-worker`
  package (`uvicorn.workers` is deprecated).

## Risks / Trade-offs

- [Very large payloads tie up workers] → body-size and run-entry limits, and the
  documented guidance to evaluate huge runs via the CLI.
- [Per-worker corpus memory] → index is built once per worker process; documented sizing.
