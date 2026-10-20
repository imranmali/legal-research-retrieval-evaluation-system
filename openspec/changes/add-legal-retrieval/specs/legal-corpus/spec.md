# Spec Delta

## Purpose

Defines legal documents and research queries, how they are loaded, and how
their attributes become metadata for evaluation.

## ADDED Requirements

### Requirement: Legal documents
A legal document SHALL have a unique id and text and MAY carry title, jurisdiction, court, decision date, its own citations, the citations it makes and a precedential status of `good_law`, `questioned`, `overruled`, `superseded` or `unknown` (default `unknown`).

#### Scenario: Default status
- **WHEN** a document is loaded without a status
- **THEN** its status is `unknown`

### Requirement: Research queries
A research query SHALL have a unique id and text and MAY carry a target jurisdiction, additional binding jurisdictions and expected citations.

#### Scenario: Query with jurisdiction
- **WHEN** a query specifies jurisdiction `US-CA`
- **THEN** that jurisdiction is available to jurisdiction-aware retrieval and metrics

### Requirement: JSONL loading
The system SHALL load documents and queries from JSONL files (optionally gzip-compressed), one object per line, rejecting invalid records and duplicate ids with an error naming the line.

#### Scenario: Duplicate id
- **WHEN** two lines share id `d1`
- **THEN** loading fails with an error naming the second line

### Requirement: Evaluation metadata
The system SHALL convert documents and queries into document and query metadata for the evaluation engine, with citations in canonical form.

#### Scenario: Metadata from corpus
- **WHEN** a corpus with an overruled document is converted
- **THEN** that document's metadata has status `overruled`
