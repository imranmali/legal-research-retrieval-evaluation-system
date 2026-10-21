# Ground Truth — Legal Research Retrieval Evaluation System

[![CI](https://github.com/imranmali/legal-research-retrieval-evaluation-system/actions/workflows/ci.yml/badge.svg)](https://github.com/imranmali/legal-research-retrieval-evaluation-system/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)

Ground Truth measures how well a legal research search system finds the
authorities a lawyer actually needs. It scores ranked results against expert
relevance judgments, tells real improvements from noise, and adds legal-specific
risk metrics that generic IR tooling ignores: retrieving **overruled law**,
citing **out-of-jurisdiction** authority, or missing the **controlling case**.

It ships as one Python package with three interfaces over the same engine:

- **Library**: `groundtruth.evaluation.evaluate(qrels, run, metrics)`
- **CLI**: `groundtruth evaluate | compare | retrieve | benchmark | validate | metrics | serve`
- **HTTP API**: a stateless FastAPI service (`/v1/evaluate`, `/v1/compare`, `/v1/search`, …)
  packaged as a hardened container with Kubernetes manifests.

## Features

| Area | What you get |
| --- | --- |
| Data | TREC and JSON qrels/runs (gzip ok), streaming parsers, line-precise errors |
| Metrics | `trec_eval`-compatible P@k, R@k, MAP, MRR, graded nDCG@k, R-Precision, Success@k, Judged@k |
| Legal metrics | `BadLaw@k`, `JurisdictionMatch@k`, `KeyAuthorityRecall@k`, `CitationRecall@k` |
| Statistics | Paired permutation, bootstrap and t-tests, bootstrap CIs, Holm–Bonferroni correction |
| Legal text | Citation extraction/normalization (US reporters, U.S.C., C.F.R., UK neutral citations) |
| Baselines | BM25, TF-IDF and citation-boosted BM25 with jurisdiction filtering and safe index persistence |
| Reports | Table, JSON, Markdown and CSV; CI quality gates via `--fail-under` |
| Service | API keys, body/size limits, request ids, JSON logs, Prometheus metrics, health/readiness probes |
| Delivery | GitHub Actions CI/CD, multi-stage non-root image, kustomize manifests with HPA and PDB |

## Relevance scale

Judgments use a graded legal scale:

| Grade | Meaning |
| ---: | --- |
| 0 | Not relevant |
| 1 | Tangential |
| 2 | Relevant |
| 3 | Controlling / key authority |

Binary metrics count grade ≥ 1 as relevant by default (`--rel-level` changes it);
nDCG uses the grade as gain; `KeyAuthorityRecall` looks at grade 3 only.

## Installation

Requires Python 3.11+. With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/imranmali/legal-research-retrieval-evaluation-system.git
cd legal-research-retrieval-evaluation-system
uv sync                      # runtime + dev dependencies from uv.lock
uv run groundtruth version
```

Or with pip: `pip install .` (installs the `groundtruth` command).

## Quick start (sample collection)

`data/sample/` contains a small **fictional** collection: 24 opinions across
US-FED, US-CA, US-NY and UK, 8 research queries and graded judgments. It is
for demos and tests only; see [`data/sample/README.md`](data/sample/README.md).

```bash
# 1. Retrieve with a baseline and write a TREC run
uv run groundtruth retrieve data/sample/corpus.jsonl data/sample/queries.jsonl \
    --retriever bm25 --depth 100 --output bm25.run

# 2. Evaluate it, including legal metrics (they need the corpus/queries metadata)
uv run groundtruth evaluate data/sample/qrels.txt bm25.run \
    --corpus data/sample/corpus.jsonl --queries data/sample/queries.jsonl \
    -m nDCG@10 -m MAP -m BadLaw@5 -m KeyAuthorityRecall@5 --per-query

# 3. Benchmark several retrievers end to end with significance tests
uv run groundtruth benchmark data/sample/corpus.jsonl data/sample/queries.jsonl \
    data/sample/qrels.txt -r bm25 -r tfidf -m nDCG@10 -m MAP -m BadLaw@5 -f markdown
```

Benchmark output on the sample collection:

| System | nDCG@10 | AP | BadLaw@5 | KeyAuthorityRecall@5 |
| --- | ---: | ---: | ---: | ---: |
| bm25 | 0.9559 | 0.9022 | 0.2250 | 1.0000 |
| tfidf | 0.9484 | 0.9052 | 0.2250 | 1.0000 |

Both baselines find the controlling authorities, but 22.5% of their top-5
results are overruled or superseded: exactly the risk `BadLaw@k` is there to expose.

## CLI reference

| Command | Purpose |
| --- | --- |
| `groundtruth evaluate QRELS RUN [-m M]... [-f table\|json\|markdown\|csv] [--per-query] [-o FILE] [--corpus F] [--queries F] [--missing zero\|skip] [--depth N] [--rel-level N] [--fail-under METRIC=VALUE]...` | Score one run |
| `groundtruth compare QRELS RUN RUN [RUN...] [-m M]... [-n NAME]... [--test permutation\|bootstrap\|ttest] [--alpha 0.05] [--resamples 10000] [--seed 0]` | Pairwise significance between systems (Holm-corrected for >2) |
| `groundtruth retrieve CORPUS QUERIES [-r bm25\|bm25-citation\|tfidf] [-k 100] [-o FILE] [--tag TAG] [--jurisdiction-filter]` | Produce a run with a baseline (`.json` output → JSON run) |
| `groundtruth benchmark CORPUS QUERIES QRELS [-r NAME]... [-m M]... [--runs-dir DIR]` | Retrieve + evaluate + compare; first retriever is the baseline |
| `groundtruth validate QRELS [RUN] [--corpus F] [--queries F]` | Check files and print counts |
| `groundtruth metrics [-f table\|json]` | List metric families, aliases and cutoff rules |
| `groundtruth serve [--host] [--port] [--workers] [--corpus F] [--retriever NAME]` | Run the HTTP API with uvicorn |
| `groundtruth version` | Print the version |

Default metrics are `nDCG@10, P@10, R@100, MAP, MRR`. Exit codes: `0` success,
`1` a `--fail-under` quality gate failed, `2` invalid input (one-line message on
stderr). Gates respect metric direction: `--fail-under BadLaw@5=0.1` fails when
BadLaw@5 is **above** 0.1.

### Using it as a CI quality gate

```bash
groundtruth evaluate qrels.txt candidate.run --corpus corpus.jsonl --queries queries.jsonl \
  --fail-under nDCG@10=0.60 --fail-under KeyAuthorityRecall@10=0.90 --fail-under BadLaw@10=0.05
```

## Metrics

| Name (aliases) | Cutoff | Definition |
| --- | --- | --- |
| `P` (`precision`) | required | relevant in top k ÷ k |
| `R` (`recall`) | required | relevant in top k ÷ all relevant |
| `Success` | required | 1 if any relevant in top k |
| `RPrec` (`R-Precision`) | none | precision at rank R (number of relevant) |
| `RR` (`MRR`) | optional | 1 ÷ rank of first relevant |
| `AP` (`MAP`) | optional | average precision; mean over queries = MAP |
| `nDCG` | optional | graded gain, log2 discount, ideal over all judgments |
| `Judged` | required | fraction of top k with any judgment (evaluation reliability) |
| `BadLaw` | required | fraction of top k that is overruled/superseded (**lower is better**) |
| `JurisdictionMatch` | required | fraction of top k in the query's target/binding jurisdictions |
| `KeyAuthorityRecall` (`KAR`) | required | fraction of grade-3 authorities in top k |
| `CitationRecall` | required | fraction of the query's expected citations held by top-k documents |

Conventions follow `trec_eval`: rankings sort by score descending with ties
broken by descending document id, unjudged documents are non-relevant, and
queries judged but missing from a run score 0 (`--missing skip` excludes them).

## Library usage

```python
from groundtruth.io import load_qrels, load_run
from groundtruth.evaluation import evaluate
from groundtruth.stats import compare_systems
from groundtruth.legal import load_documents, load_queries, document_metadata, query_metadata

qrels = load_qrels("data/sample/qrels.txt")
docs = load_documents("data/sample/corpus.jsonl")
queries = load_queries("data/sample/queries.jsonl")

baseline = evaluate(
    qrels,
    load_run("bm25.run"),
    ["nDCG@10", "BadLaw@5"],
    doc_metadata=document_metadata(docs),
    query_metadata=query_metadata(queries),
)
candidate = evaluate(
    qrels,
    load_run("candidate.run"),
    ["nDCG@10", "BadLaw@5"],
    doc_metadata=document_metadata(docs),
    query_metadata=query_metadata(queries),
)

print(baseline.aggregate)
print(compare_systems(baseline, candidate, "nDCG@10", test="permutation", seed=0))
```

Custom metrics subclass `groundtruth.metrics.Metric` and register with
`@register_metric`; they then work everywhere (CLI, API, reports).

## HTTP API

```bash
GROUNDTRUTH_CORPUS_PATH=data/sample/corpus.jsonl uv run groundtruth serve --port 8000
# or: docker compose up
```

```bash
curl -s localhost:8000/v1/evaluate -H 'Content-Type: application/json' -d '{
  "qrels": {"q1": {"d1": 3, "d2": 0}},
  "run":   {"q1": {"d1": 2.1, "d2": 1.4}},
  "metrics": ["nDCG@10", "P@1"]
}'
# {"metrics":["nDCG@10","P@1"],"aggregate":{"nDCG@10":1.0,"P@1":1.0},
#  "per_query":{"q1":{"nDCG@10":1.0,"P@1":1.0}},"num_queries":1,"warnings":[]}
```

| Endpoint | Description |
| --- | --- |
| `POST /v1/evaluate` | `{qrels, run, metrics?, doc_metadata?, query_metadata?, missing?, depth?, rel_level?, include_per_query?}` → evaluation result |
| `POST /v1/compare` | `{qrels, runs: {name: run}, metrics?, test?, alpha?, n_resamples?, seed?}` → Holm-corrected pairwise comparisons |
| `GET /v1/metrics` | Available metrics |
| `POST /v1/search` | `{query, k, jurisdictions?}` → ranked hits from the preloaded corpus (503 if none configured) |
| `GET /healthz`, `GET /readyz` | Liveness / readiness |
| `GET /metrics` | Prometheus metrics |
| `GET /docs` | OpenAPI UI |

Errors are always `{"error": {"code", "message", "request_id"}}`; every response
carries `X-Request-ID`. When `GROUNDTRUTH_API_KEYS` is set, `/v1/*` requires an
`X-API-Key` header. Configuration is environment-only; see
[docs/deployment.md](docs/deployment.md) for every `GROUNDTRUTH_*` variable.

## Deployment and scaling

- **Container**: `docker build -t groundtruth .` produces a slim, non-root (uid 10001)
  image running gunicorn with uvicorn workers (`WEB_CONCURRENCY`), with a health check.
- **Compose**: `docker compose up` serves the sample corpus on port 8000 with a read-only filesystem.
- **Kubernetes**: `kubectl apply -k deploy/k8s` deploys 3+ replicas with probes,
  resource limits, a HorizontalPodAutoscaler (3–20 pods at 70% CPU), a
  PodDisruptionBudget and a hardened security context.

The API is stateless: evaluation inputs arrive with each request and the optional
search corpus is loaded read-only at startup, so it scales horizontally behind any
load balancer. CPU-bound work runs in worker threads, request bodies and run sizes
are capped, and very large offline evaluations are best run with the CLI. See
[docs/architecture.md](docs/architecture.md) and [docs/deployment.md](docs/deployment.md).

## CI/CD

| Workflow | Trigger | Does |
| --- | --- | --- |
| `ci.yml` | PRs, pushes to `main` | ruff, format, mypy --strict, pytest on 3.11–3.13 (coverage ≥ 90%), OpenSpec validation, package build, container smoke test, kubeconform |
| `cd.yml` | push to `main` | Publish `ghcr.io/imranmali/legal-research-retrieval-evaluation-system:main` and `:sha-<short>` |
| `release.yml` | tag `v*` | Verify version, build wheel/sdist, GitHub release, versioned images |

## Development workflow

The project is **spec-driven** with [OpenSpec](https://github.com/Fission-AI/OpenSpec):
every behavior change is proposed under `openspec/changes/<name>/` (proposal,
delta specs, design, tasks), implemented, then archived into `openspec/specs/`,
which is the source of truth for system behavior.

```bash
make check          # ruff, format check, mypy --strict, pytest + coverage
make spec-validate  # openspec validate --all --strict
```

Branches follow `feature/*`, `fix/*`, `docs/*`, `ci/*`, `chore/*` off `main`,
merged through pull requests with Conventional Commits. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Project layout

```
src/groundtruth/
  io/            qrels & run readers/writers (TREC, JSON, gzip)
  metrics/       Metric contract, registry, standard metrics
  legal/         citations, analyzer, corpus model, legal metrics
  retrieval/     inverted index, BM25, TF-IDF, registry, persistence
  evaluation.py  evaluation engine
  stats.py       significance testing
  reporting.py   JSON / Markdown / CSV reports
  cli.py         groundtruth command
  api/           FastAPI service (app factory, routes, middleware, errors)
openspec/        specs (source of truth) and archived changes
deploy/          gunicorn config and Kubernetes manifests
data/sample/     fictional demo collection
```

## Security

Please report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 imranmali and Ground Truth contributors.

The sample collection is fictional and is not legal authority. Ground Truth
evaluates search systems; it does not provide legal advice.
