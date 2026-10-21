# Design

## Context

The metric registry and `MetricContext` (scaffold) let legal metrics read
document metadata (`context.documents[doc_id]`) and query metadata
(`context.query`). The evaluation engine (`add-evaluation-core`) passes these
through. This change supplies the producers (corpus → metadata) and consumers
(legal metrics), plus retrievers that emit `Run` dicts.

## Goals / Non-Goals

**Goals:**
- Zero new dependencies; pure Python + numpy, deterministic output.
- Sub-second indexing/search on tens of thousands of documents.

**Non-Goals:**
- Competing with production search engines; these are baselines.

## Decisions

- **Module layout**
  - `groundtruth/legal/citations.py`: `Citation` (frozen dataclass: `kind` in
    `case|usc|cfr|neutral`, `canonical`, `start`, `end`), `extract_citations(text)`,
    `normalize_citation(text) -> str | None`. Regexes compiled once; reporter table
    maps loose spellings to canonical (`F. 3d`→`F.3d`, `S.Ct.`→`S. Ct.`).
  - `groundtruth/legal/corpus.py`: pydantic `PrecedentialStatus` (StrEnum),
    `LegalDocument` (`doc_id`, `text`, `title=""`, `jurisdiction: str|None`,
    `court: str|None`, `decision_date: date|None`, `citations: list[str]`,
    `cites: list[str]`, `status`), `LegalQuery` (`query_id`, `text`,
    `jurisdiction: str|None`, `binding_jurisdictions: list[str]`,
    `expected_citations: list[str]`), `load_documents(path)`, `load_queries(path)`,
    `document_metadata(docs) -> dict`, `query_metadata(queries) -> dict`.
    Metadata keys: `status`, `jurisdiction`, `citations` (docs);
    `jurisdiction`, `binding_jurisdictions`, `expected_citations` (queries).
  - `groundtruth/legal/analysis.py`: `LegalAnalyzer(stopwords=..., stem=True)`
    `.analyze(text) -> list[str]`; citations replaced by tokens `§cite:<canonical>`
    (prefix cannot collide with word tokens); light English suffix stemmer.
  - `groundtruth/legal/metrics.py`: `BadLaw`, `JurisdictionMatch`,
    `KeyAuthorityRecall`, `CitationRecall`; imported from `groundtruth.legal`
    so registration happens when the package is imported. The `groundtruth.metrics`
    package imports `groundtruth.legal.metrics` lazily at the end so every metric is
    available after `import groundtruth.metrics`.
  - `groundtruth/retrieval/`: `base.py` (`SearchHit`, `Retriever` ABC with
    `fit`, `search(query, k=10, jurisdictions=None)`, `retrieve(queries, k=100,
    use_query_jurisdiction=False) -> Run`, `save(path)`, `load(path)` classmethod),
    `index.py` (`InvertedIndex`: postings `term -> {doc_index: tf}`, doc lengths,
    doc ids, jurisdictions), `bm25.py`, `tfidf.py`, `registry.py`
    (`get_retriever(name, **params)`, `available_retrievers()`).
- **Persistence**: gzip-compressed JSON with `{"format": "groundtruth-index",
  "version": 1, "retriever": name, "params": {...}, "index": {...}}`. Chosen over
  pickle because loading pickles from untrusted files executes code.
- **Scoring**: term-at-a-time accumulation into a dict of doc index → score, then
  `heapq.nlargest(k, ..., key=(score, doc_id))` for deterministic top-k.
  BM25 idf = `ln(1 + (N - df + 0.5)/(df + 0.5))` (Lucene variant, never negative).
- **Synthetic sample data** in `data/sample/` (24 fictional opinions across
  `US-FED`, `US-CA`, `US-NY`, `UK`, 8 queries, graded qrels) with a README
  stating it is fictional and must not be cited.

## Risks / Trade-offs

- [Regex citation recall is imperfect] → covers the high-volume forms; unrecognized
  citations still match as ordinary words.
- [In-memory index] → fine for evaluation collections up to ~1M short docs;
  larger corpora should plug in an external retriever and evaluate its run files.
