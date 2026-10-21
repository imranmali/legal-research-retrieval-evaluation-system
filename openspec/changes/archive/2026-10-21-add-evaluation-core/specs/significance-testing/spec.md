# Spec Delta

## Purpose

Tells whether the difference between two systems on the same queries is
statistically meaningful, so teams do not ship noise as improvements.

## ADDED Requirements

### Requirement: Paired comparison
The system SHALL compare two systems on one metric using only queries evaluated for both, reporting mean of each, mean difference (B minus A), p-value, a bootstrap confidence interval of the difference, the number of paired queries and whether the difference is significant at the chosen alpha (default 0.05).

#### Scenario: Identical systems
- **WHEN** both systems have identical per-query scores
- **THEN** the difference is 0 and the result is not significant

#### Scenario: No shared queries
- **WHEN** the systems share no evaluated queries
- **THEN** the comparison fails with a descriptive error

### Requirement: Test selection
The system SHALL support a two-sided paired randomization (permutation) test (default), a paired bootstrap test and a paired t-test. Randomized procedures SHALL be reproducible given a seed.

#### Scenario: Reproducible permutation test
- **WHEN** the same comparison runs twice with the same seed
- **THEN** both p-values are identical

#### Scenario: Clear improvement detected
- **WHEN** system B beats system A by a large margin on 30 of 30 queries
- **THEN** every supported test reports p < 0.05

### Requirement: Multiple comparison correction
When more than two systems are compared, the system SHALL compare every pair and apply Holm–Bonferroni correction to the p-values before deciding significance.

#### Scenario: Corrected p-values
- **WHEN** three systems are compared
- **THEN** three pairwise results are reported with corrected p-values no smaller than the raw p-values
