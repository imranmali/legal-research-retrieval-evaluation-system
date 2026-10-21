# legal-metrics Specification

## Purpose
Measures legal-research-specific quality and risk: bad law exposure,
jurisdictional fit, coverage of controlling authority and expected citations.

## Requirements

### Requirement: Bad law exposure
The system SHALL provide `BadLaw@k`: the fraction of retrieved documents in the top k whose status is `overruled` or `superseded`, where lower is better. It SHALL be 0.0 when nothing was retrieved.

#### Scenario: One overruled in top 4
- **WHEN** 1 of the top 4 documents is overruled
- **THEN** BadLaw@4 is 0.25

### Requirement: Jurisdictional fit
The system SHALL provide `JurisdictionMatch@k`: the fraction of retrieved documents in the top k whose jurisdiction is the query's target or binding jurisdiction. Queries without a target jurisdiction SHALL score 1.0.

#### Scenario: Mixed jurisdictions
- **WHEN** the query targets `US-CA` and 3 of the top 4 documents are `US-CA`
- **THEN** JurisdictionMatch@4 is 0.75

### Requirement: Key authority recall
The system SHALL provide `KeyAuthorityRecall@k` (alias `KAR`): the fraction of documents judged grade 3 (controlling authority) that appear in the top k, and 0.0 when the query has none.

#### Scenario: Missing the controlling case
- **WHEN** a query has 2 grade-3 documents and only one is in the top 10
- **THEN** KeyAuthorityRecall@10 is 0.5

### Requirement: Citation recall
The system SHALL provide `CitationRecall@k`: the fraction of the query's expected citations (canonical form) held by any document in the top k, and 0.0 when the query lists none.

#### Scenario: Citation found
- **WHEN** the query expects `410 U.S. 113` and the third-ranked document carries that citation
- **THEN** CitationRecall@3 is 1.0
