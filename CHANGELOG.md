# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-20

First release of Ground Truth: a library, CLI and HTTP service for evaluating
legal research retrieval systems.

### Added

#### Evaluation core (`add-evaluation-core`)

- Reading, validating and writing qrels and runs in TREC text and JSON
  formats (optionally gzip-compressed) with line-precise error messages.
- Standard ranked-retrieval metrics, numerically compatible with `trec_eval`:
  `P@k`, `R@k`, `MAP`/`AP`, `MRR`/`RR`, graded `nDCG@k`, `RPrec`, `Success@k`
  and `Judged@k`, resolved by name through a shared metric registry.
- Evaluation engine producing per-query and aggregate scores with an explicit
  policy for queries missing from a run (`zero`, as `trec_eval -c`, or `skip`).
- Paired significance testing (randomization, paired bootstrap, paired t-test),
  bootstrap confidence intervals and Holm-Bonferroni correction for
  multi-system comparisons.
- JSON, Markdown and CSV report rendering.

#### Legal retrieval (`add-legal-retrieval`)

- Citation extraction and normalization for US case reporters, the U.S. Code,
  the C.F.R. and UK neutral citations.
- Legal document and query model with jurisdiction and precedential status,
  loaded from JSONL.
- Baseline retrievers (BM25, TF-IDF, citation-boosted BM25) over a
  citation-preserving legal analyzer, with jurisdiction filtering and
  versioned, pickle-free index persistence.
- Legal-domain metrics: `BadLaw@k`, `JurisdictionMatch@k`,
  `KeyAuthorityRecall@k` and `CitationRecall@k`.
- Fictional sample collection in `data/sample/` for demos and tests.

#### Service interfaces (`add-service-interfaces`)

- `groundtruth` command-line tool: `evaluate`, `compare`, `retrieve`,
  `benchmark`, `validate`, `metrics`, `serve` and `version`, with table, JSON,
  Markdown and CSV output and `--fail-under` quality gates.
- Versioned HTTP API: `POST /v1/evaluate`, `POST /v1/compare`,
  `GET /v1/metrics`, `POST /v1/search`.
- Service operations: environment configuration (`GROUNDTRUTH_*`), optional
  API-key authentication, request-size and run-size limits, request ids,
  structured JSON logs, Prometheus metrics, `/healthz` and `/readyz` probes.

#### Delivery pipeline (`add-delivery-pipeline`)

- CI on every pull request and push to `main`: ruff lint and format check,
  `mypy --strict`, tests with a 90% coverage gate on Python 3.11, 3.12 and
  3.13, strict OpenSpec validation, package build with metadata check,
  container build with a smoke test and Kubernetes manifest validation.
- Continuous delivery of the container image to GHCR (`main`, `sha-<short>`)
  and tag-driven releases (`vX.Y.Z`) that publish the wheel, sdist, a GitHub
  release and versioned image tags.
- Hardened multi-stage container image (non-root, read-only friendly, health
  check, gunicorn with uvicorn workers) and `docker-compose.yml`.
- Kustomize manifests for Kubernetes with probes, resource limits, restricted
  security context, HorizontalPodAutoscaler and PodDisruptionBudget.
- Project hygiene: pre-commit hooks, Dependabot, issue and pull request
  templates, CODEOWNERS, contributing guide, security policy, code of conduct,
  architecture and deployment documentation.

[Unreleased]: https://github.com/imranmali/legal-research-retrieval-evaluation-system/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/imranmali/legal-research-retrieval-evaluation-system/releases/tag/v0.1.0
