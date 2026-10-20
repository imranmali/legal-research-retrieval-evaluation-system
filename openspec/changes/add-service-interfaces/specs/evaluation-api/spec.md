# Spec Delta

## Purpose

Exposes evaluation, system comparison and baseline search over HTTP so search
platforms and CI systems can gate releases on legal retrieval quality.

## ADDED Requirements

### Requirement: Evaluate endpoint
`POST /v1/evaluate` SHALL accept JSON qrels, run, metrics, optional document and query metadata, missing-query policy and depth, and return the evaluation result (aggregate, per-query, query count, warnings).

#### Scenario: Successful evaluation
- **WHEN** a client posts valid qrels, a run and metrics `["P@1"]`
- **THEN** the response is 200 with `aggregate["P@1"]`

#### Scenario: Unknown metric
- **WHEN** a client requests metric `foo`
- **THEN** the response is 422 with an error message naming `foo`

### Requirement: Compare endpoint
`POST /v1/compare` SHALL accept qrels, two or more named runs, metrics and test options, and return pairwise comparisons with corrected p-values.

#### Scenario: Two systems
- **WHEN** a client posts two runs and metric `nDCG@10`
- **THEN** the response contains one comparison with delta and p-value

### Requirement: Metrics and search endpoints
`GET /v1/metrics` SHALL list available metrics. `POST /v1/search` SHALL search the corpus configured at startup with a query, k and optional jurisdictions, and return 503 when no corpus is configured.

#### Scenario: Search without corpus
- **WHEN** the service started without a corpus and a client calls search
- **THEN** the response is 503

### Requirement: Health and observability
The service SHALL expose `GET /healthz` (liveness), `GET /readyz` (ready once startup finished), and `GET /metrics` in Prometheus format with request counts and latencies by route and status. Every response SHALL carry an `X-Request-ID` header, echoing the client's value when provided.

#### Scenario: Request id echo
- **WHEN** a client sends `X-Request-ID: abc`
- **THEN** the response header `X-Request-ID` is `abc`

### Requirement: Authentication
When API keys are configured, every `/v1` endpoint SHALL require a matching `X-API-Key` header and respond 401 otherwise; health, readiness and metrics endpoints SHALL stay open.

#### Scenario: Missing key
- **WHEN** keys are configured and a request has no `X-API-Key`
- **THEN** the response is 401

### Requirement: Request limits
The service SHALL reject request bodies larger than the configured maximum with 413, and evaluation inputs exceeding the configured maximum number of run entries with 422.

#### Scenario: Oversized body
- **WHEN** the body exceeds the limit
- **THEN** the response is 413

### Requirement: Error format
Errors SHALL be JSON objects `{"error": {"code": ..., "message": ..., "request_id": ...}}` and SHALL NOT expose stack traces.

#### Scenario: Internal error
- **WHEN** an unexpected exception occurs
- **THEN** the response is 500 with code `internal_error` and no traceback
