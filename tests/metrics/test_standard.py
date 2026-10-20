"""Hand-computed checks of the standard metrics (spec: retrieval-metrics)."""

import math

import pytest

from groundtruth.errors import ConfigurationError, UnknownMetricError
from groundtruth.metrics import CutoffPolicy, available_metrics, get_metric, register_metric
from groundtruth.metrics.standard import (
    NDCG,
    AveragePrecision,
    Judged,
    Precision,
    Recall,
    ReciprocalRank,
    RPrecision,
    Success,
)
from groundtruth.ranking import rank_documents


def score(spec: str, ranking: list[str], judgments: dict[str, int], rel_level: int = 1) -> float:
    return get_metric(spec, rel_level=rel_level).compute(ranking, judgments)


# --- Requirement: Metric specifications --------------------------------------------


def test_alias_with_cutoff() -> None:
    metric = get_metric("ndcg@10")
    assert isinstance(metric, NDCG)
    assert metric.cutoff == 10
    assert metric.label == "nDCG@10"


@pytest.mark.parametrize(
    ("spec", "cls", "label"),
    [
        ("p@5", Precision, "P@5"),
        ("Precision@5", Precision, "P@5"),
        ("recall@100", Recall, "R@100"),
        ("success@1", Success, "Success@1"),
        ("rprec", RPrecision, "RPrec"),
        ("R-Precision", RPrecision, "RPrec"),
        ("MRR", ReciprocalRank, "RR"),
        ("mrr@10", ReciprocalRank, "RR@10"),
        ("map", AveragePrecision, "AP"),
        ("MAP@1000", AveragePrecision, "AP@1000"),
        ("NDCG", NDCG, "nDCG"),
        ("judged@10", Judged, "Judged@10"),
        (" nDCG @ 5 ", NDCG, "nDCG@5"),
    ],
)
def test_specifications_resolve_case_insensitively(spec: str, cls: type, label: str) -> None:
    metric = get_metric(spec)
    assert isinstance(metric, cls)
    assert metric.label == label


@pytest.mark.parametrize("spec", ["P", "R", "Success", "Judged"])
def test_cutoff_required(spec: str) -> None:
    with pytest.raises(ConfigurationError, match=r"requires a rank cutoff"):
        get_metric(spec)


def test_cutoff_forbidden_for_r_precision() -> None:
    with pytest.raises(ConfigurationError, match="does not take a rank cutoff"):
        get_metric("RPrec@10")


@pytest.mark.parametrize("spec", ["P@0", "nDCG@0"])
def test_zero_cutoff_rejected(spec: str) -> None:
    with pytest.raises(ConfigurationError, match="cutoff must be >= 1"):
        get_metric(spec)


@pytest.mark.parametrize("spec", ["bpref", "ndcg@", "@10", "P@-1", "nDCG@1.5", ""])
def test_unknown_or_malformed_specification_rejected(spec: str) -> None:
    with pytest.raises(UnknownMetricError):
        get_metric(spec)


def test_metric_repr_shows_label() -> None:
    assert repr(get_metric("ndcg@10")) == "<NDCG nDCG@10>"


def test_registering_a_conflicting_name_is_rejected() -> None:
    class Clash(Precision):
        name = "MyPrecision"
        aliases = ("map",)

    with pytest.raises(ConfigurationError, match=r"'map' already registered by AveragePrecision"):
        register_metric(Clash)
    with pytest.raises(UnknownMetricError):
        get_metric("MyPrecision@5")


# --- Requirement: Ranking conventions ----------------------------------------------


def test_tie_break() -> None:
    ranking = rank_documents({"a": 1.0, "c": 1.0})
    assert ranking == ["c", "a"]
    assert score("RR", ranking, {"a": 1}) == 0.5
    assert score("P@1", ranking, {"c": 1}) == 1.0


def test_relevance_level() -> None:
    ranking = ["d1", "d2"]
    judgments = {"d1": 1, "d2": 2}
    assert score("P@1", ranking, judgments, rel_level=2) == 0.0
    assert score("RR", ranking, judgments, rel_level=2) == 0.5
    assert score("AP", ranking, judgments, rel_level=2) == 0.5
    assert score("R@1", ranking, judgments, rel_level=2) == 0.0
    assert score("Success@1", ranking, judgments, rel_level=2) == 0.0
    assert score("RPrec", ranking, judgments, rel_level=2) == 0.0


def test_unjudged_documents_are_non_relevant() -> None:
    assert score("P@2", ["unjudged", "d1"], {"d1": 1}) == 0.5
    assert score("RR", ["unjudged", "d1"], {"d1": 1}) == 0.5


def test_ndcg_ignores_relevance_level_and_uses_graded_gain() -> None:
    judgments = {"d1": 1, "d2": 3}
    assert score("nDCG", ["d2", "d1"], judgments, rel_level=3) == 1.0
    expected = (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
    assert math.isclose(score("nDCG", ["d1", "d2"], judgments, rel_level=3), expected)


# --- Requirement: Set-based and rank-based binary metrics --------------------------


def test_precision_with_short_ranking() -> None:
    assert score("P@10", ["d1", "d2", "d3"], {"d1": 1, "d3": 2, "d9": 1}) == pytest.approx(0.2)


def test_precision_at_cutoff_counts_only_top_k() -> None:
    assert score("P@2", ["d1", "x", "d2"], {"d1": 1, "d2": 1}) == 0.5


def test_recall_at_k() -> None:
    judgments = {"d1": 1, "d2": 1, "d3": 1, "d4": 0}
    assert score("R@2", ["d1", "d4", "d2"], judgments) == pytest.approx(1 / 3)
    assert score("R@3", ["d1", "d4", "d2"], judgments) == pytest.approx(2 / 3)


def test_success_at_k() -> None:
    assert score("Success@1", ["x", "d1"], {"d1": 1}) == 0.0
    assert score("Success@2", ["x", "d1"], {"d1": 1}) == 1.0


def test_r_precision() -> None:
    # R = 3 relevant; 2 of the top 3 are relevant.
    judgments = {"a": 1, "b": 2, "c": 1}
    assert score("RPrec", ["a", "x", "b", "c"], judgments) == pytest.approx(2 / 3)


def test_reciprocal_rank_with_and_without_cutoff() -> None:
    ranking = ["x", "y", "d1"]
    assert score("RR", ranking, {"d1": 1}) == pytest.approx(1 / 3)
    assert score("RR@2", ranking, {"d1": 1}) == 0.0
    assert score("RR", ranking, {"d1": 0}) == 0.0


def test_average_precision() -> None:
    judgments = {"a": 1, "b": 1, "c": 1}
    ap = score("AP", ["a", "x", "b", "y"], judgments)
    assert math.isclose(ap, (1 / 1 + 2 / 3) / 3, rel_tol=1e-9)


def test_average_precision_with_cutoff_divides_by_all_relevant() -> None:
    judgments = {"a": 1, "b": 1, "c": 1}
    assert math.isclose(score("AP@2", ["a", "x", "b"], judgments), 1 / 3, rel_tol=1e-9)


def test_trec_eval_reference_example() -> None:
    # Ranking R N R N N R, 4 relevant judged (one never retrieved).
    ranking = ["r1", "n1", "r2", "n2", "n3", "r3"]
    judgments = {"r1": 1, "r2": 1, "r3": 1, "r4": 1, "n1": 0}
    assert math.isclose(score("AP", ranking, judgments), (1 + 2 / 3 + 3 / 6) / 4, rel_tol=1e-9)
    assert score("RPrec", ranking, judgments) == 0.5
    assert score("P@5", ranking, judgments) == pytest.approx(0.4)
    assert score("RR", ranking, judgments) == 1.0
    assert score("R@6", ranking, judgments) == pytest.approx(0.75)


@pytest.mark.parametrize("spec", ["R@10", "AP", "AP@5", "RR", "RR@3", "RPrec", "nDCG", "nDCG@5"])
def test_no_relevant_documents(spec: str) -> None:
    assert score(spec, ["d1", "d2"], {"d1": 0, "d2": 0}) == 0.0
    assert score(spec, ["d1"], {}) == 0.0


def test_empty_ranking_scores_zero() -> None:
    for spec in ["P@5", "R@5", "Success@5", "RPrec", "RR", "AP", "nDCG@5", "Judged@5"]:
        assert score(spec, [], {"d1": 2}) == 0.0


# --- Requirement: Graded nDCG ------------------------------------------------------


def test_perfect_ranking() -> None:
    judgments = {"a": 3, "b": 2, "c": 2, "d": 1, "e": 0}
    assert score("nDCG", ["a", "c", "b", "d", "e"], judgments) == 1.0
    assert score("nDCG@2", ["a", "b"], judgments) == 1.0


def test_ndcg_hand_computed_with_cutoff() -> None:
    judgments = {"a": 3, "b": 2, "c": 1}
    ranking = ["c", "x", "a", "b"]
    dcg = 1 / math.log2(2) + 3 / math.log2(4) + 2 / math.log2(5)
    idcg = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert math.isclose(score("nDCG", ranking, judgments), dcg / idcg, rel_tol=1e-9)
    dcg3 = 1 + 3 / math.log2(4)
    assert math.isclose(score("nDCG@3", ranking, judgments), dcg3 / idcg, rel_tol=1e-9)
    idcg2 = 3 + 2 / math.log2(3)
    assert math.isclose(score("nDCG@2", ranking, judgments), 1 / idcg2, rel_tol=1e-9)


# --- Requirement: Judgment coverage ------------------------------------------------


def test_half_judged() -> None:
    ranking = [f"d{i}" for i in range(10)]
    judgments = {f"d{i}": i % 2 for i in range(0, 10, 2)}  # 5 judged, all grade 0
    assert score("Judged@10", ranking, judgments) == 0.5


def test_judged_divides_by_k_even_for_short_rankings() -> None:
    assert score("Judged@10", ["d1", "d2"], {"d1": 0, "d2": 3}) == pytest.approx(0.2)


# --- Requirement: Metric discovery -------------------------------------------------


def test_listing() -> None:
    infos = available_metrics()
    names = [info.name for info in infos]
    assert len(names) == len(set(names))
    by_name = {info.name: info for info in infos}
    expected = {
        "P": (("precision",), CutoffPolicy.REQUIRED),
        "R": (("recall",), CutoffPolicy.REQUIRED),
        "Success": ((), CutoffPolicy.REQUIRED),
        "RPrec": (("R-Precision",), CutoffPolicy.FORBIDDEN),
        "RR": (("MRR",), CutoffPolicy.OPTIONAL),
        "AP": (("MAP",), CutoffPolicy.OPTIONAL),
        "nDCG": ((), CutoffPolicy.OPTIONAL),
        "Judged": ((), CutoffPolicy.REQUIRED),
    }
    for name, (aliases, policy) in expected.items():
        info = by_name[name]
        assert info.aliases == aliases
        assert info.cutoff_policy is policy
        assert info.higher_is_better is True
        assert info.requires_context is False
        assert info.description
