# Proposal

## Why

Generic IR metrics miss what makes legal research results good or dangerous:
retrieving an overruled case, citing out-of-jurisdiction authority, or missing
the controlling precedent. Teams also need reproducible lexical baselines to
measure new systems against, and a citation-aware text pipeline because legal
queries are dense with citations like `42 U.S.C. § 1983` or `410 U.S. 113`.

## What Changes

- Citation extraction and normalization for US case reporters, the U.S. Code,
  the C.F.R. and UK neutral citations.
- A legal document / query data model with precedential status and
  jurisdiction, loaded from JSONL, and conversion to evaluation metadata.
- Baseline retrievers (BM25, TF-IDF, citation-boosted BM25) over a
  citation-preserving legal analyzer, with jurisdiction filtering and index
  persistence, producing runs ready for evaluation.
- Legal-domain metrics: BadLaw@k, JurisdictionMatch@k, KeyAuthorityRecall@k and
  CitationRecall@k, registered in the shared metric registry.
- A small synthetic (fictional) sample collection for demos and tests.

## Capabilities

### New Capabilities
- `legal-citations`: Recognizing and normalizing legal citations in text.
- `legal-corpus`: Legal document and research query data model and loading.
- `retrieval-baselines`: Reproducible baseline retrievers producing runs.
- `legal-metrics`: Legal-domain effectiveness and risk metrics.

### Modified Capabilities
- None.

## Out of Scope

- Dense / neural retrievers and external search engines (pluggable later via the retriever interface).
- Shepardizing or live citator lookups; precedential status comes from the corpus data.
- Pin cites, short-form (`id.`, `supra`) resolution.

## Impact

- New packages `groundtruth/legal/` and `groundtruth/retrieval/`, sample data in `data/sample/`.
- Depends on the metric contract from the scaffold; no new dependencies.
