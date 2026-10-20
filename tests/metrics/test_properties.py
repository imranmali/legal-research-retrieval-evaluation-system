"""Hypothesis property tests for the standard metrics."""

import math

from hypothesis import given
from hypothesis import strategies as st

from groundtruth.metrics import get_metric

_SPECS = [
    "P@1",
    "P@5",
    "R@5",
    "Success@3",
    "RPrec",
    "RR",
    "RR@3",
    "AP",
    "AP@5",
    "nDCG",
    "nDCG@3",
    "Judged@5",
]

_doc_ids = st.sampled_from([f"d{i}" for i in range(12)])
_judgments = st.dictionaries(_doc_ids, st.integers(min_value=0, max_value=3), max_size=12)
_rankings = st.lists(_doc_ids, unique=True, max_size=12)
_rel_levels = st.integers(min_value=1, max_value=3)


@given(_rankings, _judgments, _rel_levels)
def test_property_scores_are_bounded(
    ranking: list[str], judgments: dict[str, int], rel_level: int
) -> None:
    for spec in _SPECS:
        value = get_metric(spec, rel_level=rel_level).compute(ranking, judgments)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0 + 1e-12, (spec, value)


@given(_judgments.filter(lambda j: any(g >= 1 for g in j.values())))
def test_property_perfect_ranking_scores_one(judgments: dict[str, int]) -> None:
    ideal = sorted(judgments, key=lambda d: (-judgments[d], d))
    for spec in ["nDCG", "nDCG@3", "AP", "RR", "RPrec"]:
        assert get_metric(spec).compute(ideal, judgments) == 1.0, spec


@given(_rankings, _judgments)
def test_property_recall_is_monotone_in_cutoff(
    ranking: list[str], judgments: dict[str, int]
) -> None:
    values = [get_metric(f"R@{k}").compute(ranking, judgments) for k in range(1, 14)]
    assert values == sorted(values)


@given(_rankings, _judgments, _rel_levels)
def test_property_matches_reference_definitions(
    ranking: list[str], judgments: dict[str, int], rel_level: int
) -> None:
    relevant = {d for d, g in judgments.items() if g >= rel_level}
    flags = [d in relevant for d in ranking]

    precisions = [sum(flags[: i + 1]) / (i + 1) for i, hit in enumerate(flags) if hit]
    ap = sum(precisions) / len(relevant) if relevant else 0.0
    first = next((i + 1 for i, hit in enumerate(flags) if hit), None)
    rr = 1 / first if first else 0.0
    gains = [judgments.get(d, 0) for d in ranking]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(judgments.values(), reverse=True)
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    ndcg = dcg / idcg if idcg else 0.0

    def compute(spec: str) -> float:
        return get_metric(spec, rel_level=rel_level).compute(ranking, judgments)

    assert math.isclose(compute("AP"), ap, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(compute("RR"), rr, rel_tol=1e-9)
    assert math.isclose(compute("nDCG"), ndcg, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(compute("P@5"), sum(flags[:5]) / 5)
    assert compute("Success@5") == float(any(flags[:5]))
