# Tasks

## 1. Relevance data I/O

- [ ] 1.1 Implement TREC qrels/run parsers and writers in `groundtruth/io/trec.py` with gzip support; verify with `tests/io/test_trec.py` (valid input, duplicates, negative grades, line-numbered errors, round trip)
- [ ] 1.2 Implement JSON readers/writers and suffix dispatch in `groundtruth/io/`; verify with `tests/io/test_jsonio.py` round-trip and validation tests

## 2. Metrics

- [ ] 2.1 Implement P, R, Success, RPrec, RR, AP, nDCG and Judged in `groundtruth/metrics/standard.py`; verify hand-computed cases in `tests/metrics/test_standard.py`
- [ ] 2.2 Add Hypothesis property tests (bounds in [0, 1], perfect ranking gives 1.0 for nDCG/AP/RR); verify `pytest tests/metrics` passes

## 3. Evaluation engine and reports

- [ ] 3.1 Implement `evaluate` and `EvaluationResult` in `groundtruth/evaluation.py` with missing-query policy, depth and metadata checks; verify `tests/test_evaluation.py`
- [ ] 3.2 Implement JSON/Markdown/CSV rendering in `groundtruth/reporting.py`; verify `tests/test_reporting.py`

## 4. Significance testing

- [ ] 4.1 Implement permutation, bootstrap and t-test comparisons plus Holm correction in `groundtruth/stats.py`; verify `tests/test_stats.py` (identical systems, clear improvement, seed reproducibility, t-test against table values)

## 5. Integration

- [ ] 5.1 Run `make check`; verify ruff, mypy --strict and pytest with coverage >= 90% all pass

## Workflow follow-up

- Archive the change with `openspec archive add-evaluation-core -y` after merge review.
