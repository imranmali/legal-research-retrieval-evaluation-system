# Deployment

The Ground Truth API ships as a container image built from `uv.lock`:

| Tag | Published when |
| --- | --- |
| `ghcr.io/imranmali/legal-research-retrieval-evaluation-system:main` | every push to `main` |
| `...:sha-<short>` | every push to `main` (immutable, use for rollbacks) |
| `...:X.Y.Z`, `...:X.Y`, `...:latest` | a `vX.Y.Z` release tag |

Pin a released version (`X.Y.Z`) or a `sha-` tag in production; `main` moves
with every merge.

## Container image

- Multi-stage build: `uv sync --locked --no-dev --no-editable` in a builder
  stage, then only the virtual environment, `deploy/gunicorn.conf.py` and the
  fictional sample collection (`/app/data/sample`) are copied onto
  `python:3.12-slim`. No compilers, uv, tests or dev dependencies are present.
- Runs as user `groundtruth` (uid/gid 10001) and works on a read-only root
  filesystem; only `/tmp` needs to be writable (gunicorn heartbeats use `/dev/shm`).
- Process model: gunicorn with `uvicorn.workers.UvicornWorker`, serving the app
  factory `groundtruth.api.app:create_app()` on `0.0.0.0:8000`.
- `HEALTHCHECK` calls `http://127.0.0.1:8000/healthz` with Python's `urllib`.
- Configuration is environment-only (table below). `GROUNDTRUTH_CORPUS_PATH`
  is unset by default, so `/v1/search` answers 503 until a corpus is configured.

### Docker

```bash
docker build -t groundtruth:local .
docker run --rm -p 8000:8000 --read-only --tmpfs /tmp \
  -e GROUNDTRUTH_CORPUS_PATH=/app/data/sample/corpus.jsonl \
  groundtruth:local

curl -s localhost:8000/readyz
curl -s -X POST localhost:8000/v1/evaluate -H 'Content-Type: application/json' \
  -d '{"qrels":{"q1":{"d1":1}},"run":{"q1":{"d1":1.0}},"metrics":["P@1"]}'
```

To serve your own corpus, mount it read-only and point the setting at it:

```bash
docker run --rm -p 8000:8000 --read-only --tmpfs /tmp \
  -v "$PWD/corpus.jsonl:/data/corpus.jsonl:ro" \
  -e GROUNDTRUTH_CORPUS_PATH=/data/corpus.jsonl \
  -e GROUNDTRUTH_API_KEYS=change-me \
  ghcr.io/imranmali/legal-research-retrieval-evaluation-system:0.1.0
```

### Docker Compose

`docker-compose.yml` runs the API with the sample corpus, a read-only root
filesystem, a tmpfs `/tmp`, all capabilities dropped and a health check on `/readyz`:

```bash
docker compose up --build -d
docker compose ps          # STATUS shows (healthy) once the corpus is indexed
docker compose logs -f api
docker compose down
```

### Kubernetes

Kustomize manifests live in [`deploy/k8s/`](../deploy/k8s/); see
[`deploy/README.md`](../deploy/README.md) for the full walkthrough.

```bash
kubectl apply -k deploy/k8s
kubectl -n groundtruth rollout status deployment/groundtruth-api
kubectl -n groundtruth port-forward svc/groundtruth-api 8000:80
```

What the manifests provide:

- Namespace `groundtruth` enforcing the `restricted` Pod Security Standard.
- Deployment with 3 replicas, rolling updates with `maxUnavailable: 0` /
  `maxSurge: 1`, startup and liveness probes on `/healthz`, readiness on
  `/readyz`, a 5 s `preStop` delay and `terminationGracePeriodSeconds: 30`
  (gunicorn's graceful timeout is 25 s).
- Requests `250m` CPU / `256Mi` memory, limits `1` CPU / `1Gi`.
- Non-root (uid 10001), read-only root filesystem, no privilege escalation,
  all capabilities dropped, `RuntimeDefault` seccomp, `emptyDir` for `/tmp`,
  no service-account token.
- Topology spread across zones and nodes, Prometheus scrape annotations.
- HorizontalPodAutoscaler (`autoscaling/v2`, 3 to 20 replicas, 70% CPU) and a
  PodDisruptionBudget (`minAvailable: 2`).
- ConfigMap for settings plus an optional Secret `groundtruth-api-keys` for API keys.

## Configuration

Application settings are read by `groundtruth.config.Settings`
(pydantic-settings, prefix `GROUNDTRUTH_`). Values are case-insensitive
environment variables; lists are comma-separated.

| Variable | Default | Description |
| --- | --- | --- |
| `GROUNDTRUTH_API_KEYS` | empty (auth disabled) | Comma-separated keys. When set, every `/v1` endpoint requires a matching `X-API-Key` header (401 otherwise). `/healthz`, `/readyz` and `/metrics` stay open. Provide from a secret store. |
| `GROUNDTRUTH_MAX_BODY_BYTES` | `52428800` (50 MiB) | Largest accepted request body; larger bodies get 413. Checked against `Content-Length` and while streaming. |
| `GROUNDTRUTH_MAX_RUN_ENTRIES` | `5000000` | Maximum number of (query, document) run entries per evaluation; larger inputs get 422. |
| `GROUNDTRUTH_CORPUS_PATH` | unset | JSONL corpus loaded and indexed once per worker at startup, enabling `/v1/search`. The image bundles `/app/data/sample/corpus.jsonl` (fictional). |
| `GROUNDTRUTH_RETRIEVER` | `bm25` | Retriever fitted on the corpus for `/v1/search` (`bm25`, `tfidf`, citation-boosted BM25; `groundtruth retrieve --help` lists names). |
| `GROUNDTRUTH_LOG_LEVEL` | `INFO` | Application log level. |
| `GROUNDTRUTH_LOG_JSON` | `true` | Structured JSON logs with request ids; set `false` for human-readable logs. |
| `GROUNDTRUTH_CORS_ORIGINS` | empty (CORS off) | Comma-separated origins allowed for browser clients. |
| `GROUNDTRUTH_DEFAULT_RESAMPLES` | `10000` | Default resample count for permutation and bootstrap tests in `/v1/compare`. |

Process-manager settings (read by `deploy/gunicorn.conf.py`):

| Variable | Default | Description |
| --- | --- | --- |
| `WEB_CONCURRENCY` | `2` | Gunicorn worker processes per container. |
| `PORT` | `8000` | Listen port. |
| `GUNICORN_TIMEOUT` | `120` | Seconds a worker may spend on one request before it is restarted. |
| `GUNICORN_GRACEFUL_TIMEOUT` | `25` | Seconds to finish in-flight requests on shutdown; keep below the pod's termination grace period. |
| `GUNICORN_KEEPALIVE` | `5` | Keep-alive seconds for idle connections (keep below the load balancer idle timeout). |
| `GUNICORN_MAX_REQUESTS` / `GUNICORN_MAX_REQUESTS_JITTER` | `2000` / `200` | Recycle workers after this many requests to bound memory growth. |
| `GUNICORN_LOG_LEVEL` | `info` | Gunicorn's own log level. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxy addresses trusted for `X-Forwarded-*` headers. |

## Scaling guidance

The API is stateless: evaluations complete within the request and nothing is
persisted, so throughput scales linearly with pods behind the Service.

- **Workers per pod.** Evaluation is CPU-bound Python. Use one worker per CPU
  of the pod's limit (`WEB_CONCURRENCY=2` with a `1` CPU limit leaves headroom
  for request parsing while one worker computes). Prefer more pods over more
  workers per pod: the HPA reacts to pod CPU, and smaller pods reschedule faster.
- **Memory.** Each worker holds its own copy of the corpus index. Budget about
  150 MiB per worker for the runtime plus the in-memory index size per worker
  (the index is a Python postings dictionary, so it is several times the size
  of the corpus text; measure it once with a representative corpus by watching
  `container_memory_working_set_bytes` after startup). Raise the memory limit
  (or lower `WEB_CONCURRENCY`) for large corpora. Very large run payloads also
  cost memory while they are parsed, which `GROUNDTRUTH_MAX_BODY_BYTES` bounds.
- **Request limits.** `GROUNDTRUTH_MAX_BODY_BYTES` and
  `GROUNDTRUTH_MAX_RUN_ENTRIES` bound the work one request can cause. For
  evaluations beyond those limits use the CLI (`groundtruth evaluate`) in a
  batch job instead of raising the limits.
- **Significance tests.** `/v1/compare` cost grows with
  `resamples x queries x system pairs`; lower `GROUNDTRUTH_DEFAULT_RESAMPLES`
  if latency matters more than p-value resolution.
- **Autoscaling.** The HPA keeps 3 to 20 replicas at 70% average CPU, scaling
  up aggressively and down slowly. With a large corpus, startup includes
  indexing: the startup probe allows 60 s; increase `failureThreshold` if
  indexing takes longer, so new pods are not killed before they are ready.
- **Availability.** Three replicas with `minAvailable: 2` survive a node drain;
  rolling updates never reduce ready capacity (`maxUnavailable: 0`).
- **Edge concerns.** Terminate TLS and apply rate limiting at the ingress or API
  gateway; the service intentionally does neither.
- **Metrics.** `/metrics` exposes `groundtruth_http_requests_total` and
  `groundtruth_http_request_duration_seconds` by route template and status.
  Prometheus scrapes pods through the `prometheus.io/*` annotations; with
  several gunicorn workers per pod a scrape reflects the worker that served it
  unless the service is configured for prometheus-client multiprocess mode.
