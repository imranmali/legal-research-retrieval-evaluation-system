# retrieval-baselines Specification

## Purpose
Provides reproducible lexical retrieval baselines over legal text that produce
runs directly consumable by the evaluation engine.

## Requirements

### Requirement: Citation-preserving analysis
Text analysis SHALL lowercase, remove stopwords and punctuation, and keep every recognized citation as a single canonical token, so a query citing `42 USC 1983` matches a document citing `42 U.S.C. § 1983`.

#### Scenario: Citation match across variants
- **WHEN** a document contains `42 U.S.C. § 1983` and the query is `42 USC 1983 claim`
- **THEN** BM25 ranks that document above documents without the citation

### Requirement: Baseline retrievers
The system SHALL provide `bm25` (parameters k1, b), `tfidf` (cosine similarity) and `bm25-citation` (BM25 with a configurable boost for citation tokens) retrievers selectable by name, returning at most k hits ordered by descending score.

#### Scenario: Unknown retriever
- **WHEN** a retriever named `magic` is requested
- **THEN** an error lists the available retrievers

#### Scenario: Deterministic results
- **WHEN** the same corpus and query are searched twice
- **THEN** both result lists are identical, ties broken by doc id

### Requirement: Jurisdiction filtering
Retrievers SHALL optionally restrict results to documents whose jurisdiction is in a given set.

#### Scenario: Filter applied
- **WHEN** searching with jurisdictions `{US-CA}`
- **THEN** every hit has jurisdiction `US-CA`

### Requirement: Batch retrieval to runs
Retrievers SHALL produce a run for a collection of queries, optionally filtering each query by its own target and binding jurisdictions.

#### Scenario: Run for queries
- **WHEN** retrieving 3 queries with k = 10
- **THEN** the run has 3 query entries with at most 10 documents each

### Requirement: Index persistence
A fitted retriever SHALL be saved to and restored from a versioned, non-executable file format, producing identical search results after loading; files with an unknown format version SHALL be rejected.

#### Scenario: Save and load
- **WHEN** a fitted BM25 index is saved and loaded
- **THEN** searches return the same hits and scores
