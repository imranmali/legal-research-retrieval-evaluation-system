# retrieval-metrics Specification

## Purpose
Defines the per-query effectiveness metrics, how they are named, and the
ranking and relevance conventions they share, so scores are comparable with trec_eval.

## Requirements

### Requirement: Metric specifications
Metrics SHALL be selected by case-insensitive specifications `NAME` or `NAME@K` using canonical names or aliases. Unknown names, malformed specifications and cutoffs that a metric does not accept SHALL be rejected with a descriptive error.

#### Scenario: Alias with cutoff
- **WHEN** a caller requests `ndcg@10`
- **THEN** the nDCG metric with cutoff 10 is used and labelled `nDCG@10`

#### Scenario: Cutoff required
- **WHEN** a caller requests `P` without a cutoff
- **THEN** the request is rejected with an error explaining the cutoff is required

### Requirement: Ranking conventions
Metrics SHALL rank documents by descending score with ties broken by descending document id, and SHALL treat unjudged documents as non-relevant. Binary metrics SHALL count a document as relevant when its grade is at least the relevance level (default 1).

#### Scenario: Tie-break
- **WHEN** documents `a` and `c` share a score
- **THEN** `c` is ranked before `a`

#### Scenario: Relevance level
- **WHEN** relevance level 2 is configured and a document has grade 1
- **THEN** binary metrics treat that document as non-relevant

### Requirement: Set-based and rank-based binary metrics
The system SHALL provide Precision@k (`P`, relevant in top k divided by k), Recall@k (`R`, relevant in top k over all relevant), Success@k (1 if any relevant in top k), R-Precision (`RPrec`), reciprocal rank (`RR`, alias `MRR`, optional cutoff) and average precision (`AP`, alias `MAP`, optional cutoff), matching trec_eval definitions.

#### Scenario: Precision with short ranking
- **WHEN** a query retrieved 3 documents, 2 relevant, and P@10 is requested
- **THEN** the score is 0.2

#### Scenario: Average precision
- **WHEN** relevant documents appear at ranks 1 and 3 and the query has 3 relevant documents
- **THEN** AP is (1/1 + 2/3) / 3

#### Scenario: No relevant documents
- **WHEN** a query has no relevant judgments
- **THEN** Recall, AP, RR, R-Precision and nDCG score 0.0 instead of failing

### Requirement: Graded nDCG
The system SHALL provide nDCG with optional cutoff using gain equal to the graded relevance and a log2(rank + 1) discount, normalized by the ideal ranking of all judged documents for the query.

#### Scenario: Perfect ranking
- **WHEN** documents are ranked in descending order of grade
- **THEN** nDCG is 1.0

### Requirement: Judgment coverage
The system SHALL provide Judged@k: the fraction of the top k retrieved documents that have any judgment, to expose evaluation reliability.

#### Scenario: Half judged
- **WHEN** 5 of the top 10 documents have judgments
- **THEN** Judged@10 is 0.5

### Requirement: Metric discovery
The system SHALL list every registered metric family with its name, aliases, description, cutoff policy, direction (higher or lower is better) and whether it needs document or query metadata.

#### Scenario: Listing
- **WHEN** a caller lists available metrics
- **THEN** each family appears once with its aliases
