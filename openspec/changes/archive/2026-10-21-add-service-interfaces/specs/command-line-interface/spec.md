# Spec Delta

## Purpose

Lets researchers and CI pipelines evaluate, compare and benchmark legal
retrieval systems from files with a single command.

## ADDED Requirements

### Requirement: Evaluate a run
`groundtruth evaluate QRELS RUN` SHALL print aggregate scores for the requested metrics (repeatable `--metric`, default `nDCG@10`, `P@10`, `R@100`, `MAP`, `MRR`) as a table, JSON, Markdown or CSV (`--format`), optionally per query (`--per-query`) and to a file (`--output`). Optional `--corpus` and `--queries` supply legal metadata.

#### Scenario: JSON output
- **WHEN** a user runs `groundtruth evaluate qrels.txt run.txt --metric P@5 --format json`
- **THEN** the command exits 0 and prints JSON containing the aggregate `P@5`

#### Scenario: Legal metrics with metadata
- **WHEN** a user requests `BadLaw@10` and passes `--corpus corpus.jsonl`
- **THEN** the command reports BadLaw@10 computed from the corpus statuses

### Requirement: Compare systems
`groundtruth compare QRELS RUN RUN [RUN...]` SHALL report pairwise mean differences, p-values (Holm-corrected for more than two runs) and significance per metric, with selectable test, alpha, resamples and seed.

#### Scenario: Two runs
- **WHEN** a user compares two runs on `nDCG@10`
- **THEN** one comparison row is printed with delta, p-value and a significance flag

### Requirement: Retrieve and benchmark
`groundtruth retrieve CORPUS QUERIES` SHALL write a TREC run using a named retriever and depth; `groundtruth benchmark CORPUS QUERIES QRELS` SHALL run one or more retrievers end to end and print their scores and significance against the first retriever.

#### Scenario: Benchmark sample data
- **WHEN** a user benchmarks `bm25` and `tfidf` on the sample collection
- **THEN** a score table for both retrievers is printed and the command exits 0

### Requirement: Quality gates
`groundtruth evaluate` SHALL accept repeatable `--fail-under METRIC=VALUE` thresholds and exit with code 1, naming the failed metric, when an aggregate score is below its threshold (or above it for lower-is-better metrics).

#### Scenario: Gate fails
- **WHEN** `--fail-under nDCG@10=0.99` is given and the aggregate is 0.5
- **THEN** the command exits 1 and names nDCG@10

### Requirement: Input errors
Invalid inputs SHALL produce a one-line error on standard error and exit code 2, without a stack trace.

#### Scenario: Malformed run
- **WHEN** the run file has a malformed line
- **THEN** the command exits 2 and the message names the line

### Requirement: Discovery and validation
`groundtruth metrics` SHALL list available metrics, `groundtruth validate QRELS [RUN]` SHALL check files and print summary counts, and `groundtruth version` SHALL print the package version.

#### Scenario: Validate files
- **WHEN** valid qrels and run files are validated
- **THEN** the command prints query and judgment counts and exits 0
