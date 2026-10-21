# Spec Delta

## Purpose

Scores a run against qrels per query and in aggregate, carrying optional
document and query metadata to metrics that need it, and renders reports.

## ADDED Requirements

### Requirement: Per-query and aggregate scores
The system SHALL compute every requested metric for each evaluated query and report the arithmetic mean over evaluated queries as the aggregate, together with the number of evaluated queries.

#### Scenario: Two queries
- **WHEN** a run scores P@1 of 1.0 on q1 and 0.0 on q2
- **THEN** the aggregate P@1 is 0.5 over 2 queries

### Requirement: Query set alignment
The evaluated query set SHALL be the queries present in the qrels. Queries in the run without qrels SHALL be ignored and reported as warnings. Queries in the qrels missing from the run SHALL score 0 by default, or be excluded when the caller selects the skip policy.

#### Scenario: Missing query scored zero
- **WHEN** qrels contain q1 and q2 and the run only contains q1
- **THEN** q2 is evaluated with every metric equal to 0 and a warning names q2

#### Scenario: Skip policy
- **WHEN** the caller selects the skip policy for the same inputs
- **THEN** only q1 is evaluated

#### Scenario: Empty evaluation rejected
- **WHEN** no query remains to evaluate
- **THEN** evaluation fails with a descriptive error

### Requirement: Evaluation depth
The caller SHALL be able to limit each query's ranking to its top N documents before metrics are computed.

#### Scenario: Depth limit
- **WHEN** depth 5 is set and a relevant document is at rank 6
- **THEN** no metric credits that document

### Requirement: Metadata pass-through
The engine SHALL pass caller-provided document metadata and per-query metadata to each metric, and SHALL reject a request for a metadata-dependent metric when no document metadata was supplied.

#### Scenario: Missing metadata
- **WHEN** a metric that requires metadata is requested without document metadata
- **THEN** evaluation fails with an error naming the metric

### Requirement: Report rendering
The system SHALL render evaluation results as JSON (aggregate, per-query, query count, warnings), as a Markdown table and as CSV with one row per query plus an aggregate row labelled `all`.

#### Scenario: CSV aggregate row
- **WHEN** a result is rendered as CSV
- **THEN** the last row has query id `all` and the aggregate scores
