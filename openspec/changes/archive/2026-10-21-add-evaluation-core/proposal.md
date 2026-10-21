# Proposal

## Why

Legal research teams cannot tell whether a retrieval change (new ranker, new
embedding model, new index) actually surfaces better authorities. They need a
trustworthy, reproducible way to score ranked results against expert
relevance judgments and to tell a real improvement from noise.

## What Changes

- Read and write relevance judgments (qrels) and system runs in the TREC text
  format and in JSON, with line-precise validation errors.
- Provide the standard ranked-retrieval metrics: Precision@k, Recall@k,
  average precision / MAP, reciprocal rank / MRR, nDCG@k (graded), R-Precision,
  Success@k and Judged@k, numerically compatible with trec_eval.
- An evaluation engine that scores a run per query and in aggregate, with an
  explicit policy for queries the run is missing.
- Paired significance testing between systems (randomization/permutation,
  paired bootstrap, paired t-test), bootstrap confidence intervals and
  Holm–Bonferroni correction for multi-system comparisons.
- Report rendering of evaluation and comparison results as JSON, Markdown and CSV.

## Capabilities

### New Capabilities
- `relevance-data`: Parsing, validating and serializing qrels and runs.
- `retrieval-metrics`: Definitions and resolution of per-query effectiveness metrics.
- `evaluation-engine`: Scoring runs against qrels per query and in aggregate, and rendering reports.
- `significance-testing`: Paired statistical comparison of systems.

### Modified Capabilities
- None.

## Out of Scope

- Retrieval itself and legal-specific metrics (see `add-legal-retrieval`).
- CLI and HTTP access (see `add-service-interfaces`).
- Unbiased estimators for incomplete judgments (infAP, bpref).

## Impact

- New modules under `src/groundtruth/` (`io`, `metrics`, `evaluation`, `stats`, `reporting`).
- No new runtime dependencies beyond numpy and pydantic already declared.
