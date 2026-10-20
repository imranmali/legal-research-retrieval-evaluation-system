"""Paired significance testing between retrieval systems.

Systems are compared on the per-query scores of one metric over the queries
both evaluated. Three two-sided paired tests are available:

* ``permutation`` (default): randomization test flipping the sign of each
  paired difference; p-value estimated as ``(count + 1) / (n_resamples + 1)``.
* ``bootstrap``: paired bootstrap test of the centred (shifted) differences.
* ``ttest``: paired Student t-test, using a local implementation of the
  t-distribution (regularized incomplete beta function) instead of scipy.

Randomized procedures are reproducible for a given ``seed``. A percentile
bootstrap confidence interval of the mean difference accompanies every test.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict

from groundtruth.errors import ConfigurationError
from groundtruth.evaluation import EvaluationError, EvaluationResult

__all__ = [
    "PairedComparison",
    "SignificanceTest",
    "bootstrap_ci",
    "compare_many",
    "compare_systems",
    "holm_bonferroni",
    "regularized_incomplete_beta",
    "student_t_sf",
]

#: Name of a supported paired test.
SignificanceTest: TypeAlias = Literal["permutation", "bootstrap", "ttest"]

_TESTS: tuple[str, ...] = ("permutation", "bootstrap", "ttest")
_FloatArray: TypeAlias = npt.NDArray[np.float64]

#: Upper bound on the elements of one resampling matrix (8 MB of float64).
_MAX_CHUNK_ELEMENTS = 1_000_000
#: Upper bound on the rows of one resampling matrix.
_MAX_CHUNK_ROWS = 1_000
#: Relative tolerance when comparing resampled statistics with the observed one,
#: so that floating point noise does not hide resamples equal to the observation.
_TIE_TOLERANCE = 1e-12

_BETACF_MAX_ITERATIONS = 10_000
_BETACF_EPSILON = 1e-15
_BETACF_TINY = 1e-300


class PairedComparison(BaseModel):
    """Outcome of comparing system B against system A on one metric.

    ``delta`` is ``mean_b - mean_a``; ``ci_low``/``ci_high`` bound it with a
    ``1 - alpha`` percentile bootstrap interval. ``p_value_corrected`` holds the
    Holm-Bonferroni adjusted p-value for multi-system comparisons and is
    ``None`` for a stand-alone pair; ``significant`` uses the corrected value
    when present.
    """

    model_config = ConfigDict(frozen=True)

    system_a: str
    system_b: str
    metric: str
    test: SignificanceTest
    mean_a: float
    mean_b: float
    delta: float
    p_value: float
    p_value_corrected: float | None = None
    ci_low: float
    ci_high: float
    num_queries: int
    alpha: float
    significant: bool


# ---------------------------------------------------------------------------
# Student t distribution without scipy
# ---------------------------------------------------------------------------


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz method)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) >= _BETACF_TINY else _BETACF_TINY)
    h = d
    for m in range(1, _BETACF_MAX_ITERATIONS + 1):
        m2 = 2 * m
        for numerator in (
            m * (b - m) * x / ((qam + m2) * (a + m2)),
            -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)),
        ):
            d = 1.0 + numerator * d
            d = 1.0 / (d if abs(d) >= _BETACF_TINY else _BETACF_TINY)
            c = 1.0 + numerator / c
            c = c if abs(c) >= _BETACF_TINY else _BETACF_TINY
            step = d * c
            h *= step
        if abs(step - 1.0) < _BETACF_EPSILON:
            return h
    raise ArithmeticError(  # pragma: no cover - converges for all valid inputs
        f"incomplete beta continued fraction did not converge for a={a}, b={b}, x={x}"
    )


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function ``I_x(a, b)`` for ``a, b > 0``, ``0 <= x <= 1``."""
    if a <= 0 or b <= 0:
        raise ValueError(f"a and b must be positive, got a={a}, b={b}")
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"x must lie in [0, 1], got {x}")
    if x == 0.0 or x == 1.0:
        return x
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def student_t_sf(t: float, df: float) -> float:
    """Survival function ``P(T > t)`` of Student's t distribution with ``df`` degrees of freedom."""
    if df <= 0:
        raise ValueError(f"degrees of freedom must be positive, got {df}")
    if math.isnan(t):
        raise ValueError("t must not be NaN")
    if math.isinf(t):
        return 0.0 if t > 0 else 1.0
    tail = 0.5 * regularized_incomplete_beta(df / 2.0, 0.5, df / (df + t * t))
    return tail if t >= 0 else 1.0 - tail


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------


def _chunks(n_resamples: int, width: int) -> list[int]:
    rows = max(1, min(_MAX_CHUNK_ROWS, _MAX_CHUNK_ELEMENTS // max(width, 1)))
    full, rest = divmod(n_resamples, rows)
    return [rows] * full + ([rest] if rest else [])


def _bootstrap_means(
    values: _FloatArray, n_resamples: int, rng: np.random.Generator
) -> _FloatArray:
    """Means of ``n_resamples`` bootstrap samples (with replacement) of ``values``."""
    n = values.shape[0]
    parts = [
        values[rng.integers(0, n, size=(rows, n))].mean(axis=1) for rows in _chunks(n_resamples, n)
    ]
    return np.concatenate(parts)


def _as_array(values: Sequence[float] | _FloatArray) -> _FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ConfigurationError("expected a non-empty one-dimensional sequence of numbers")
    if not np.all(np.isfinite(array)):
        raise ConfigurationError("values must be finite numbers")
    return array


def _check_resamples(n_resamples: int) -> None:
    if n_resamples < 1:
        raise ConfigurationError(f"n_resamples must be >= 1, got {n_resamples}")


def bootstrap_ci(
    diffs: Sequence[float] | _FloatArray,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int | None = 0,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval of the mean of ``diffs``.

    Raises:
        ConfigurationError: for empty or non-finite input, ``confidence`` outside
            (0, 1) or ``n_resamples < 1``.
    """
    if not 0.0 < confidence < 1.0:
        raise ConfigurationError(f"confidence must lie in (0, 1), got {confidence}")
    _check_resamples(n_resamples)
    values = _as_array(diffs)
    means = _bootstrap_means(values, n_resamples, np.random.default_rng(seed))
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])
    return float(low), float(high)


def _permutation_p(diffs: _FloatArray, n_resamples: int, seed: int | None) -> float:
    if not np.any(diffs):
        return 1.0
    n = diffs.shape[0]
    observed = abs(float(diffs.mean()))
    threshold = observed - _TIE_TOLERANCE * max(1.0, observed)
    rng = np.random.default_rng(seed)
    count = 0
    for rows in _chunks(n_resamples, n):
        signs = np.where(rng.integers(0, 2, size=(rows, n), dtype=np.int8) == 1, 1.0, -1.0)
        means = np.abs(signs @ diffs) / n
        count += int(np.count_nonzero(means >= threshold))
    return (count + 1) / (n_resamples + 1)


def _bootstrap_p(diffs: _FloatArray, n_resamples: int, seed: int | None) -> float:
    if not np.any(diffs):
        return 1.0
    observed = abs(float(diffs.mean()))
    threshold = observed - _TIE_TOLERANCE * max(1.0, observed)
    centred = diffs - diffs.mean()
    means = np.abs(_bootstrap_means(centred, n_resamples, np.random.default_rng(seed)))
    count = int(np.count_nonzero(means >= threshold))
    return (count + 1) / (n_resamples + 1)


def _ttest_p(diffs: _FloatArray) -> float:
    n = diffs.shape[0]
    mean = float(diffs.mean())
    if n < 2:
        return 1.0
    sd = float(diffs.std(ddof=1))
    if sd == 0.0:
        return 1.0 if mean == 0.0 else 0.0
    t = mean / (sd / math.sqrt(n))
    return min(1.0, 2.0 * student_t_sf(abs(t), n - 1))


# ---------------------------------------------------------------------------
# Public comparison API
# ---------------------------------------------------------------------------


def holm_bonferroni(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, returned in the input order.

    Adjusted values are monotone in the raw p-values, capped at 1 and never
    smaller than the corresponding raw p-value.

    Raises:
        ConfigurationError: if a p-value is not in [0, 1].
    """
    for p in pvalues:
        if not 0.0 <= p <= 1.0:
            raise ConfigurationError(f"p-values must lie in [0, 1], got {p}")
    m = len(pvalues)
    adjusted = [0.0] * m
    running = 0.0
    for position, index in enumerate(sorted(range(m), key=lambda i: pvalues[i])):
        running = max(running, min(1.0, (m - position) * pvalues[index]))
        adjusted[index] = running
    return adjusted


def _validate(test: str, alpha: float, n_resamples: int) -> None:
    if test not in _TESTS:
        raise ConfigurationError(f"unknown test {test!r}; choose one of {', '.join(_TESTS)}")
    if not 0.0 < alpha < 1.0:
        raise ConfigurationError(f"alpha must lie in (0, 1), got {alpha}")
    _check_resamples(n_resamples)


def compare_systems(
    a: EvaluationResult,
    b: EvaluationResult,
    metric: str,
    *,
    test: SignificanceTest = "permutation",
    alpha: float = 0.05,
    n_resamples: int = 10_000,
    seed: int | None = 0,
    name_a: str = "A",
    name_b: str = "B",
) -> PairedComparison:
    """Compare system B against system A on ``metric`` over the queries both evaluated.

    ``metric`` may be the label or any specification resolving to it (``ndcg@10``).
    The difference is significant when the two-sided p-value is below ``alpha``;
    the confidence interval has level ``1 - alpha``.

    Raises:
        ConfigurationError: for an unknown test, invalid ``alpha``/``n_resamples``
            or a metric missing from either result.
        EvaluationError: when the systems share no evaluated query.
    """
    _validate(test, alpha, n_resamples)
    label_a = a.resolve_label(metric)
    label_b = b.resolve_label(metric)
    shared = sorted(a.per_query.keys() & b.per_query.keys())
    if not shared:
        raise EvaluationError(
            f"systems {name_a!r} and {name_b!r} share no evaluated queries; "
            "they must be evaluated on the same query set"
        )
    scores_a = np.array([a.per_query[q][label_a] for q in shared], dtype=np.float64)
    scores_b = np.array([b.per_query[q][label_b] for q in shared], dtype=np.float64)
    diffs = scores_b - scores_a

    if test == "permutation":
        p_value = _permutation_p(diffs, n_resamples, seed)
    elif test == "bootstrap":
        p_value = _bootstrap_p(diffs, n_resamples, seed)
    else:
        p_value = _ttest_p(diffs)
    ci_low, ci_high = bootstrap_ci(diffs, 1.0 - alpha, n_resamples, seed)

    return PairedComparison(
        system_a=name_a,
        system_b=name_b,
        metric=label_a,
        test=test,
        mean_a=float(scores_a.mean()),
        mean_b=float(scores_b.mean()),
        delta=float(diffs.mean()),
        p_value=p_value,
        ci_low=ci_low,
        ci_high=ci_high,
        num_queries=len(shared),
        alpha=alpha,
        significant=p_value < alpha,
    )


def compare_many(
    results: Mapping[str, EvaluationResult],
    metric: str,
    *,
    test: SignificanceTest = "permutation",
    alpha: float = 0.05,
    n_resamples: int = 10_000,
    seed: int | None = 0,
) -> list[PairedComparison]:
    """Compare every pair of named systems and apply Holm-Bonferroni correction.

    Pairs follow the insertion order of ``results`` (``(s1, s2), (s1, s3), (s2, s3)``,
    with the earlier system as A). Every comparison carries ``p_value_corrected``
    (equal to the raw p-value when only one pair exists) and its significance is
    decided on the corrected value.

    Raises:
        ConfigurationError: for fewer than two systems or invalid options.
        EvaluationError: when a pair of systems shares no evaluated query.
    """
    if len(results) < 2:
        raise ConfigurationError(f"at least two systems are needed, got {len(results)}")
    _validate(test, alpha, n_resamples)
    raw = [
        compare_systems(
            results[name_a],
            results[name_b],
            metric,
            test=test,
            alpha=alpha,
            n_resamples=n_resamples,
            seed=seed,
            name_a=name_a,
            name_b=name_b,
        )
        for name_a, name_b in itertools.combinations(results, 2)
    ]
    corrected = holm_bonferroni([c.p_value for c in raw])
    return [
        c.model_copy(update={"p_value_corrected": p, "significant": p < alpha})
        for c, p in zip(raw, corrected, strict=True)
    ]
