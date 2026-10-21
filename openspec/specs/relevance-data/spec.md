# relevance-data Specification

## Purpose
Defines how relevance judgments (qrels) and system runs are read, validated and
written so every other capability works from the same, trustworthy data.

## Requirements

### Requirement: Parse TREC qrels
The system SHALL parse TREC qrels lines of the form `query_id iteration doc_id relevance`, separated by any whitespace, ignoring blank lines and lines starting with `#`. Relevance SHALL be an integer; negative grades SHALL be treated as 0.

#### Scenario: Valid qrels file
- **WHEN** a file contains `q1 0 d1 2` and `q1 0 d2 0`
- **THEN** the parsed qrels map `q1` to `{d1: 2, d2: 0}`

#### Scenario: Negative grade
- **WHEN** a qrels line has relevance `-1`
- **THEN** the judgment is stored with grade 0

### Requirement: Parse TREC runs
The system SHALL parse TREC run lines of the form `query_id Q0 doc_id rank score tag`. Ranking order SHALL be derived from the score, not from the rank column. A repeated `(query_id, doc_id)` pair SHALL keep the highest score.

#### Scenario: Score defines order
- **WHEN** a run lists `d1` at rank 1 with score 1.0 and `d2` at rank 2 with score 5.0
- **THEN** `d2` is ranked before `d1` during evaluation

#### Scenario: Duplicate document
- **WHEN** the same document appears twice for one query with scores 1.0 and 3.0
- **THEN** the run keeps a single entry with score 3.0

### Requirement: Report malformed input precisely
The system SHALL reject malformed qrels or run input with a format error that names the source and the 1-based line number, and SHALL NOT return partially parsed data.

#### Scenario: Wrong column count
- **WHEN** line 3 of a run file has five columns
- **THEN** parsing fails with a format error mentioning line 3

#### Scenario: Non-numeric score
- **WHEN** a run line has score `high`
- **THEN** parsing fails with a format error mentioning that line

### Requirement: JSON interchange
The system SHALL read and write qrels and runs as JSON objects of the shape `{query_id: {doc_id: value}}`, applying the same value validation as the TREC readers.

#### Scenario: Round trip
- **WHEN** a run is written to JSON and read back
- **THEN** the result equals the original run

### Requirement: Write TREC runs
The system SHALL write runs in TREC format with ranks starting at 1, ordered by descending score using the trec_eval tie-break, with a caller-supplied run tag.

#### Scenario: Written run re-reads identically
- **WHEN** a run is written in TREC format and parsed again
- **THEN** each query's ranking is unchanged
