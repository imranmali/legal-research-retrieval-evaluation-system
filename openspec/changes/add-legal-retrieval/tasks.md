# Tasks

## 1. Citations and analysis

- [ ] 1.1 Implement `groundtruth/legal/citations.py` (reporters, U.S.C., C.F.R., UK neutral); verify `tests/legal/test_citations.py` covers every spec scenario
- [ ] 1.2 Implement `LegalAnalyzer` in `groundtruth/legal/analysis.py`; verify `tests/legal/test_analysis.py` (citation tokens, stopwords, stemming)

## 2. Corpus model

- [ ] 2.1 Implement documents, queries, JSONL loaders and metadata conversion in `groundtruth/legal/corpus.py`; verify `tests/legal/test_corpus.py` (defaults, duplicate ids, gzip)
- [ ] 2.2 Add fictional sample collection in `data/sample/` with README; verify it loads in `tests/legal/test_sample_data.py`

## 3. Retrievers

- [ ] 3.1 Implement inverted index, BM25, TF-IDF and citation-boosted BM25 plus registry in `groundtruth/retrieval/`; verify `tests/retrieval/test_retrievers.py` (ranking sanity, determinism, jurisdiction filter, unknown retriever)
- [ ] 3.2 Implement versioned save/load; verify identical results after round trip and rejection of unknown versions in `tests/retrieval/test_persistence.py`

## 4. Legal metrics

- [ ] 4.1 Implement BadLaw, JurisdictionMatch, KeyAuthorityRecall and CitationRecall in `groundtruth/legal/metrics.py`; verify `tests/legal/test_legal_metrics.py` covers each spec scenario

## 5. Integration

- [ ] 5.1 Run `make check`; verify ruff, mypy --strict and pytest with coverage >= 90% pass

## Workflow follow-up

- Archive with `openspec archive add-legal-retrieval -y` after merge review.
