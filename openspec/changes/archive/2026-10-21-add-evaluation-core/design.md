# Design

## Context

The scaffold already defines `Metric`, `MetricContext`, the metric registry
(`groundtruth.metrics.base`), `rank_documents` (`groundtruth.ranking`), the
`Qrels`/`Run` dict aliases (`groundtruth.types`) and the error hierarchy
(`groundtruth.errors`). This change fills in the data layer, metrics, engine and
statistics on top of that contract.

## Goals / Non-Goals

**Goals:**
- trec_eval-compatible numbers for the shared metrics.
- Linear-time evaluation in the size of the run; streaming file parsing.
- Plain-data results that serialize directly to JSON for the API.

**Non-Goals:**
- Distributed evaluation; a single process handles millions of run lines.

## Decisions

- **Plain dicts for qrels/runs** (`dict[str, dict[str, int|float]]`) rather than
  objects per line: lowest memory overhead and the same shape as pytrec_eval,
  so users can pass data straight through. Pydantic is used only for results.
- **Module layout**:
  - `groundtruth/io/trec.py`: `parse_qrels(lines, source)`, `parse_run(lines, source)`,
    `load_qrels(path)`, `load_run(path)`, `dump_run(run, path_or_file, tag)`,
    `dump_qrels(qrels, path_or_file)`. `groundtruth/io/jsonio.py`: `load_qrels_json`,
    `load_run_json`, `dump_json`. `groundtruth/io/__init__.py` re-exports and
    `load_qrels_any/load_run_any` dispatch on `.json` suffix. Files may be gzip (`.gz`).
  - `groundtruth/metrics/standard.py`: `Precision` (`P`, cutoff required),
    `Recall` (`R`, required), `Success` (required), `RPrecision` (`RPrec`, forbidden),
    `ReciprocalRank` (`RR`/`MRR`, optional), `AveragePrecision` (`AP`/`MAP`, optional),
    `NDCG` (`nDCG`, optional), `Judged` (required). Imported by `groundtruth.metrics`
    so registration happens on package import.
  - `groundtruth/evaluation.py`: `evaluate(qrels, run, metrics, *, doc_metadata=None,
    query_metadata=None, missing="zero"|"skip", depth=None, rel_level=1) -> EvaluationResult`.
    `EvaluationResult` (pydantic): `metrics: list[str]`, `aggregate: dict[str, float]`,
    `per_query: dict[str, dict[str, float]]`, `num_queries: int`, `warnings: list[str]`.
  - `groundtruth/stats.py`: `compare_systems(a: EvaluationResult, b: EvaluationResult,
    metric: str, *, test="permutation"|"bootstrap"|"ttest", alpha=0.05,
    n_resamples=10_000, seed=0) -> PairedComparison`; `compare_many(results:
    Mapping[str, EvaluationResult], metric, ...) -> list[PairedComparison]` with Holm
    correction; `holm_bonferroni(pvalues) -> list[float]`; `bootstrap_ci(diffs, ...)`.
    `PairedComparison` (pydantic): `system_a, system_b, metric, test, mean_a, mean_b,
    delta, p_value, p_value_corrected (None for a single pair), ci_low, ci_high,
    num_queries, alpha, significant`.
  - `groundtruth/reporting.py`: `to_json`, `to_markdown`, `to_csv` for
    `EvaluationResult`, and `comparisons_to_markdown`.
- **Permutation test** uses vectorised numpy sign flips of paired differences
  (`n_resamples` × `n_queries` matrix, chunked to bound memory); p-value uses the
  `(count + 1) / (n + 1)` estimator so it is never exactly 0. Bootstrap test
  centres the differences (shift method). t-test uses the t-distribution survival
  function computed via the regularized incomplete beta function implemented with
  numpy/math (no scipy dependency). With zero variance of differences the
  p-value is 1.0 when the mean difference is 0.
- **Missing queries**: default `zero` mirrors `trec_eval -c`, the conservative
  choice for system comparison.

## Risks / Trade-offs

- [Floating point drift from trec_eval] → tests pin hand-computed values and use
  `math.isclose` with 1e-9 tolerance.
- [Large permutation matrices] → resampling processed in chunks of 1,000 rows.
- [No scipy] → t-test CDF implemented locally and checked against known table values.
