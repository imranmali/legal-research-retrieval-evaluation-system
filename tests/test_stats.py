"""Tests for paired significance testing (spec: significance-testing)."""

import math
from typing import get_args

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from groundtruth.errors import ConfigurationError
from groundtruth.evaluation import EvaluationError, EvaluationResult
from groundtruth.stats import (
    SignificanceTest,
    bootstrap_ci,
    compare_many,
    compare_systems,
    holm_bonferroni,
    regularized_incomplete_beta,
    student_t_sf,
)

TESTS: tuple[SignificanceTest, ...] = get_args(SignificanceTest)


def make_result(scores: dict[str, float], metric: str = "AP") -> EvaluationResult:
    per_query = {query_id: {metric: value} for query_id, value in scores.items()}
    mean = sum(scores.values()) / len(scores) if scores else 0.0
    return EvaluationResult(
        metrics=[metric], aggregate={metric: mean}, per_query=per_query, num_queries=len(scores)
    )


def series(values: np.ndarray) -> dict[str, float]:
    return {f"q{i:02d}": float(v) for i, v in enumerate(values)}


RNG = np.random.default_rng(42)
BASE = series(RNG.uniform(0.0, 0.4, 30))
IMPROVED = {q: v + 0.3 + 0.1 * (i % 3) for i, (q, v) in enumerate(BASE.items())}
NOISY = series(RNG.uniform(0.0, 0.4, 30))


# --- Requirement: Paired comparison ------------------------------------------------


@pytest.mark.parametrize("test", TESTS)
def test_identical_systems(test: SignificanceTest) -> None:
    result = make_result(BASE)
    comparison = compare_systems(result, result, "AP", test=test)
    assert comparison.delta == 0.0
    assert comparison.p_value == 1.0
    assert comparison.significant is False
    assert comparison.ci_low == comparison.ci_high == 0.0
    assert comparison.p_value_corrected is None


def test_no_shared_queries() -> None:
    a = make_result({"q1": 0.5})
    b = make_result({"q2": 0.5})
    with pytest.raises(EvaluationError, match="share no evaluated queries"):
        compare_systems(a, b, "AP")


def test_comparison_uses_only_shared_queries_and_reports_b_minus_a() -> None:
    a = make_result({"q1": 0.2, "q2": 0.4, "only_a": 1.0})
    b = make_result({"q1": 0.6, "q2": 0.4, "only_b": 0.0})
    comparison = compare_systems(a, b, "ap", name_a="bm25", name_b="dense")
    assert comparison.num_queries == 2
    assert comparison.mean_a == pytest.approx(0.3)
    assert comparison.mean_b == pytest.approx(0.5)
    assert comparison.delta == pytest.approx(0.2)
    assert (comparison.system_a, comparison.system_b) == ("bm25", "dense")
    assert comparison.metric == "AP"
    assert comparison.alpha == 0.05
    assert comparison.ci_low <= comparison.delta <= comparison.ci_high


def test_metric_must_be_in_both_results() -> None:
    a = make_result({"q1": 0.5}, metric="AP")
    b = make_result({"q1": 0.5}, metric="nDCG@10")
    with pytest.raises(ConfigurationError, match="not part of this evaluation"):
        compare_systems(a, b, "AP")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"test": "wilcoxon"}, "unknown test"),
        ({"alpha": 0.0}, "alpha must lie"),
        ({"alpha": 1.0}, "alpha must lie"),
        ({"n_resamples": 0}, "n_resamples must be >= 1"),
    ],
)
def test_invalid_options_rejected(kwargs: dict[str, object], message: str) -> None:
    result = make_result(BASE)
    with pytest.raises(ConfigurationError, match=message):
        compare_systems(result, result, "AP", **kwargs)  # type: ignore[arg-type]


# --- Requirement: Test selection ---------------------------------------------------


@pytest.mark.parametrize("test", ["permutation", "bootstrap"])
def test_reproducible_permutation_test(test: SignificanceTest) -> None:
    a, b = make_result(BASE), make_result(NOISY)
    first = compare_systems(a, b, "AP", test=test, seed=7)
    second = compare_systems(a, b, "AP", test=test, seed=7)
    assert first.p_value == second.p_value
    assert (first.ci_low, first.ci_high) == (second.ci_low, second.ci_high)
    assert first == second


def test_different_seeds_can_change_randomized_estimates() -> None:
    a, b = make_result(BASE), make_result(NOISY)
    p_values = {compare_systems(a, b, "AP", seed=s, n_resamples=500).p_value for s in range(5)}
    assert len(p_values) > 1


@pytest.mark.parametrize("test", TESTS)
def test_clear_improvement_detected(test: SignificanceTest) -> None:
    comparison = compare_systems(make_result(BASE), make_result(IMPROVED), "AP", test=test)
    assert comparison.p_value < 0.05
    assert comparison.significant is True
    assert comparison.delta > 0
    assert comparison.ci_low > 0


@pytest.mark.parametrize("test", ["permutation", "bootstrap"])
def test_randomized_p_value_is_never_zero(test: SignificanceTest) -> None:
    comparison = compare_systems(
        make_result(BASE), make_result(IMPROVED), "AP", test=test, n_resamples=999
    )
    assert comparison.p_value == pytest.approx(1 / 1000)


def test_no_difference_detected_between_similar_systems() -> None:
    shifted = {q: v + (0.01 if i % 2 else -0.01) for i, (q, v) in enumerate(BASE.items())}
    for test in TESTS:
        comparison = compare_systems(make_result(BASE), make_result(shifted), "AP", test=test)
        assert comparison.significant is False, test


def test_permutation_single_query_cannot_be_significant() -> None:
    comparison = compare_systems(make_result({"q1": 0.1}), make_result({"q1": 0.9}), "AP")
    assert comparison.p_value == 1.0


def test_permutation_matches_exact_enumeration_for_small_samples() -> None:
    diffs = np.array([0.3, 0.1, -0.05, 0.2, 0.15])
    observed = abs(diffs.mean())
    signs = np.array(np.meshgrid(*[[-1.0, 1.0]] * len(diffs))).reshape(len(diffs), -1).T
    exact = np.mean(np.abs(signs @ diffs / len(diffs)) >= observed - 1e-12)
    a = make_result(series(np.zeros(5)))
    b = make_result(series(diffs))
    comparison = compare_systems(a, b, "AP", n_resamples=50_000, seed=1)
    assert comparison.p_value == pytest.approx(exact, abs=0.01)


def test_ttest_known_paired_example() -> None:
    # diffs 1, 2, 3, 4, 5: mean 3, sd sqrt(2.5), t = 3 / (sqrt(2.5)/sqrt(5)) = 4.2426, df 4.
    a = make_result(series(np.zeros(5)))
    b = make_result(series(np.arange(1.0, 6.0)))
    comparison = compare_systems(a, b, "AP", test="ttest")
    assert comparison.p_value == pytest.approx(0.013236, abs=1e-5)


def test_ttest_edge_cases() -> None:
    a = make_result({"q1": 0.0, "q2": 0.0})
    constant = make_result({"q1": 0.5, "q2": 0.5})
    assert compare_systems(a, constant, "AP", test="ttest").p_value == 0.0
    single_a, single_b = make_result({"q1": 0.0}), make_result({"q1": 1.0})
    assert compare_systems(single_a, single_b, "AP", test="ttest").p_value == 1.0


def test_bootstrap_with_constant_nonzero_difference_is_significant() -> None:
    a = make_result({"q1": 0.0, "q2": 0.1, "q3": 0.2})
    b = make_result({"q1": 0.5, "q2": 0.6, "q3": 0.7})
    comparison = compare_systems(a, b, "AP", test="bootstrap", n_resamples=99)
    assert comparison.p_value == pytest.approx(0.01)


# --- Student t distribution --------------------------------------------------------


@pytest.mark.parametrize(
    ("t", "df", "two_sided_p"),
    [
        (2.045, 29, 0.05),
        (12.706, 1, 0.05),
        (4.303, 2, 0.05),
        (2.228, 10, 0.05),
        (2.086, 20, 0.05),
        (4.032, 5, 0.01),
        (2.845, 20, 0.01),
        (1.753, 15, 0.10),
        (3.646, 17, 0.002),
        (1.959964, 1_000_000, 0.05),
    ],
)
def test_student_t_matches_table_values(t: float, df: float, two_sided_p: float) -> None:
    assert 2 * student_t_sf(t, df) == pytest.approx(two_sided_p, rel=2e-3)


@pytest.mark.parametrize("t", [-7.5, -1.0, -0.1, 0.0, 0.3, 1.0, 2.5, 40.0, 1e6])
def test_student_t_matches_closed_forms(t: float) -> None:
    cauchy = 0.5 - math.atan(t) / math.pi
    assert student_t_sf(t, 1) == pytest.approx(cauchy, rel=1e-10, abs=1e-15)
    df2 = 0.5 - t / (2 * math.sqrt(2 + t * t))
    assert student_t_sf(t, 2) == pytest.approx(df2, rel=1e-10, abs=1e-15)


def test_student_t_limits_and_validation() -> None:
    assert student_t_sf(math.inf, 3) == 0.0
    assert student_t_sf(-math.inf, 3) == 1.0
    assert student_t_sf(0.0, 9) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="degrees of freedom"):
        student_t_sf(1.0, 0)
    with pytest.raises(ValueError, match="NaN"):
        student_t_sf(math.nan, 3)


def test_regularized_incomplete_beta_known_values() -> None:
    assert regularized_incomplete_beta(1.0, 1.0, 0.3) == pytest.approx(0.3)
    assert regularized_incomplete_beta(2.5, 1.0, 0.4) == pytest.approx(0.4**2.5)
    assert regularized_incomplete_beta(1.0, 3.0, 0.2) == pytest.approx(1 - 0.8**3)
    assert regularized_incomplete_beta(7.0, 7.0, 0.5) == pytest.approx(0.5)
    assert regularized_incomplete_beta(2.0, 3.0, 0.0) == 0.0
    assert regularized_incomplete_beta(2.0, 3.0, 1.0) == 1.0
    with pytest.raises(ValueError, match="positive"):
        regularized_incomplete_beta(0.0, 1.0, 0.5)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        regularized_incomplete_beta(1.0, 1.0, 1.5)


# --- Bootstrap confidence interval -------------------------------------------------


def test_bootstrap_ci_brackets_the_mean_and_is_reproducible() -> None:
    diffs = RNG.normal(0.1, 0.05, 50)
    low, high = bootstrap_ci(diffs, confidence=0.95, n_resamples=2_000, seed=3)
    assert low < diffs.mean() < high
    assert (low, high) == bootstrap_ci(diffs, confidence=0.95, n_resamples=2_000, seed=3)
    narrow = bootstrap_ci(diffs, confidence=0.5, n_resamples=2_000, seed=3)
    assert low < narrow[0] < narrow[1] < high


def test_bootstrap_ci_single_value() -> None:
    assert bootstrap_ci([0.25]) == (0.25, 0.25)


def test_bootstrap_ci_chunks_large_inputs() -> None:
    diffs = np.linspace(-1.0, 1.0, 5_001)
    low, high = bootstrap_ci(diffs, n_resamples=300, seed=0)
    assert low < 0.0 < high


@pytest.mark.parametrize(
    ("diffs", "kwargs", "message"),
    [
        ([], {}, "non-empty"),
        ([[0.1, 0.2]], {}, "one-dimensional"),
        ([0.1, math.nan], {}, "finite"),
        ([0.1], {"confidence": 1.0}, "confidence must lie"),
        ([0.1], {"n_resamples": 0}, "n_resamples"),
    ],
)
def test_bootstrap_ci_validation(
    diffs: list[float], kwargs: dict[str, float], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        bootstrap_ci(diffs, **kwargs)  # type: ignore[arg-type]


# --- Requirement: Multiple comparison correction -----------------------------------


def test_corrected_p_values() -> None:
    results = {
        "bm25": make_result(BASE),
        "dense": make_result(IMPROVED),
        "hybrid": make_result(NOISY),
    }
    comparisons = compare_many(results, "AP", n_resamples=2_000)
    assert [(c.system_a, c.system_b) for c in comparisons] == [
        ("bm25", "dense"),
        ("bm25", "hybrid"),
        ("dense", "hybrid"),
    ]
    for comparison in comparisons:
        assert comparison.p_value_corrected is not None
        assert comparison.p_value_corrected >= comparison.p_value
        assert comparison.significant == (comparison.p_value_corrected < comparison.alpha)


def test_significance_uses_corrected_p_value() -> None:
    a = make_result({"q1": 0.0, "q2": 0.0, "q3": 0.0})
    results = {"a": a, "b": a, "c": make_result({"q1": 0.3, "q2": 0.5, "q3": 0.4})}
    comparisons = compare_many(results, "AP", test="ttest", alpha=0.05)
    a_vs_c = comparisons[1]
    assert a_vs_c.p_value < 0.05
    assert a_vs_c.p_value_corrected is not None
    assert a_vs_c.p_value_corrected > 0.05
    assert a_vs_c.significant is False


def test_compare_many_with_two_systems_keeps_raw_p_value() -> None:
    (comparison,) = compare_many({"a": make_result(BASE), "b": make_result(IMPROVED)}, "AP")
    assert comparison.p_value_corrected == comparison.p_value
    assert comparison.significant is True


def test_compare_many_needs_two_systems() -> None:
    with pytest.raises(ConfigurationError, match="at least two systems"):
        compare_many({"a": make_result(BASE)}, "AP")


def test_holm_bonferroni_known_example() -> None:
    assert holm_bonferroni([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm_bonferroni([0.5, 0.6]) == pytest.approx([1.0, 1.0])
    assert holm_bonferroni([]) == []


@pytest.mark.parametrize("bad", [-0.1, 1.1, math.nan])
def test_holm_bonferroni_rejects_invalid_p_values(bad: float) -> None:
    with pytest.raises(ConfigurationError, match="p-values must lie"):
        holm_bonferroni([0.1, bad])


@given(st.lists(st.floats(min_value=0.0, max_value=1.0), max_size=12))
def test_property_holm_bonferroni(pvalues: list[float]) -> None:
    adjusted = holm_bonferroni(pvalues)
    assert len(adjusted) == len(pvalues)
    for raw, corrected in zip(pvalues, adjusted, strict=True):
        assert raw <= corrected <= 1.0
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    assert [adjusted[i] for i in order] == sorted(adjusted)


@given(
    st.lists(st.floats(min_value=-1.0, max_value=1.0), min_size=1, max_size=15),
    st.sampled_from(TESTS),
)
def test_property_p_values_are_probabilities(diffs: list[float], test: SignificanceTest) -> None:
    a = make_result({f"q{i}": 0.0 for i in range(len(diffs))})
    b = make_result({f"q{i}": d for i, d in enumerate(diffs)})
    comparison = compare_systems(a, b, "AP", test=test, n_resamples=200)
    assert 0.0 <= comparison.p_value <= 1.0
    if test != "ttest":
        assert comparison.p_value > 0.0
    assert comparison.ci_low <= comparison.ci_high
