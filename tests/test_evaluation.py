"""Tests for the evaluation engine (spec: evaluation-engine)."""

import math
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pytest

from groundtruth.errors import ConfigurationError, GroundTruthError, UnknownMetricError
from groundtruth.evaluation import EvaluationError, EvaluationResult, evaluate, resolve_metrics
from groundtruth.metrics import EMPTY_CONTEXT, CutoffPolicy, Metric, MetricContext


class _CourtShare(Metric):
    """Fraction of the top documents from the court the query targets (needs metadata)."""

    name = "TestCourtShare"
    cutoff_policy = CutoffPolicy.OPTIONAL
    requires_context = True
    seen: ClassVar[list[MetricContext]] = []

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,
    ) -> float:
        type(self).seen.append(context)
        top = self.truncate(ranking)
        if not top:
            return 0.0
        court = context.query.get("court")
        return sum(1 for d in top if context.documents.get(d, {}).get("court") == court) / len(top)


class _Broken(Metric):
    name = "TestBroken"

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,
    ) -> float:
        return math.nan


QRELS = {"q1": {"d1": 1, "d2": 0}, "q2": {"d3": 2}}


# --- Requirement: Per-query and aggregate scores -----------------------------------


def test_two_queries() -> None:
    run = {"q1": {"d1": 2.0, "d2": 1.0}, "q2": {"d4": 3.0, "d3": 1.0}}
    result = evaluate(QRELS, run, ["P@1"])
    assert result.per_query == {"q1": {"P@1": 1.0}, "q2": {"P@1": 0.0}}
    assert result.aggregate == {"P@1": 0.5}
    assert result.num_queries == 2
    assert result.metrics == ["P@1"]
    assert result.warnings == []


def test_aggregate_is_mean_of_every_metric() -> None:
    run = {"q1": {"d1": 2.0}, "q2": {"x": 2.0, "d3": 1.0}}
    result = evaluate(QRELS, run, ["RR", "nDCG@10", "AP"])
    assert result.metrics == ["RR", "nDCG@10", "AP"]
    assert result.aggregate["RR"] == pytest.approx(0.75)
    for label in result.metrics:
        mean = sum(row[label] for row in result.per_query.values()) / 2
        assert result.aggregate[label] == pytest.approx(mean)


def test_duplicate_metric_labels_are_evaluated_once_in_order() -> None:
    result = evaluate(QRELS, {"q1": {"d1": 1.0}}, ["map", "nDCG", "AP", "ndcg", "MRR"])
    assert result.metrics == ["AP", "nDCG", "RR"]
    assert set(result.per_query["q1"]) == {"AP", "nDCG", "RR"}


def test_single_string_metric_is_accepted() -> None:
    result = evaluate(QRELS, {"q1": {"d1": 1.0}, "q2": {"d3": 1.0}}, "P@1")
    assert result.aggregate == {"P@1": 1.0}


def test_rel_level_applies_to_metric_specifications() -> None:
    run = {"q1": {"d1": 1.0}, "q2": {"d3": 1.0}}
    result = evaluate(QRELS, run, ["P@1"], rel_level=2)
    assert result.per_query == {"q1": {"P@1": 0.0}, "q2": {"P@1": 1.0}}


def test_metric_instances_are_accepted() -> None:
    (rr,) = resolve_metrics(["MRR"])
    result = evaluate(QRELS, {"q1": {"d2": 2.0, "d1": 1.0}, "q2": {}}, [rr])
    assert result.per_query == {"q1": {"RR": 0.5}, "q2": {"RR": 0.0}}


def test_result_is_plain_serializable_data() -> None:
    result = evaluate(QRELS, {"q1": {"d1": 1.0}, "q2": {"d3": 1.0}}, ["P@1"])
    restored = EvaluationResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_non_finite_metric_score_is_rejected() -> None:
    with pytest.raises(EvaluationError, match=r"TestBroken returned a non-finite score"):
        evaluate(QRELS, {"q1": {"d1": 1.0}}, [_Broken()])


# --- Requirement: Query set alignment ----------------------------------------------


def test_missing_query_scored_zero() -> None:
    result = evaluate(QRELS, {"q1": {"d1": 1.0}}, ["P@1", "nDCG"])
    assert result.num_queries == 2
    assert result.per_query["q2"] == {"P@1": 0.0, "nDCG": 0.0}
    assert result.aggregate == {"P@1": 0.5, "nDCG": 0.5}
    assert len(result.warnings) == 1
    assert "q2" in result.warnings[0]
    assert "scored 0" in result.warnings[0]


def test_skip_policy() -> None:
    result = evaluate(QRELS, {"q1": {"d1": 1.0}}, ["P@1"], missing="skip")
    assert list(result.per_query) == ["q1"]
    assert result.num_queries == 1
    assert result.aggregate == {"P@1": 1.0}
    assert any("q2" in w and "skipped" in w for w in result.warnings)


def test_run_queries_without_judgments_are_ignored_with_warning() -> None:
    run = {"q1": {"d1": 1.0}, "q2": {"d3": 1.0}, "q9": {"d1": 1.0}}
    result = evaluate(QRELS, run, ["P@1"])
    assert set(result.per_query) == {"q1", "q2"}
    assert result.warnings == ["1 run query has no relevance judgments and was ignored: q9"]


def test_warnings_truncate_long_id_lists() -> None:
    run = {f"x{i:02d}": {"d": 1.0} for i in range(13)} | {"q1": {"d1": 1.0}, "q2": {"d3": 1.0}}
    result = evaluate(QRELS, run, ["P@1"])
    (warning,) = result.warnings
    assert warning.startswith("13 run queries have no relevance judgments and were ignored: x00")
    assert warning.endswith("x09 and 3 more")


def test_query_with_empty_ranking_is_evaluated_not_missing() -> None:
    result = evaluate(QRELS, {"q1": {}, "q2": {"d3": 1.0}}, ["P@1"])
    assert result.per_query["q1"] == {"P@1": 0.0}
    assert result.warnings == []


def test_empty_evaluation_rejected() -> None:
    with pytest.raises(EvaluationError, match="nothing to evaluate"):
        evaluate(QRELS, {"other": {"d1": 1.0}}, ["P@1"], missing="skip")
    with pytest.raises(EvaluationError, match="qrels contain no queries"):
        evaluate({}, {"q1": {"d1": 1.0}}, ["P@1"])


def test_evaluation_error_is_a_ground_truth_error() -> None:
    assert issubclass(EvaluationError, GroundTruthError)


# --- Requirement: Evaluation depth -------------------------------------------------


def test_depth_limit() -> None:
    qrels = {"q1": {"d6": 1}}
    run = {"q1": {f"d{i}": 10.0 - i for i in range(1, 8)}}
    metrics = ["P@10", "R@10", "Success@10", "RR", "AP", "nDCG", "RPrec", "Judged@10"]
    shallow = evaluate(qrels, run, metrics, depth=5)
    assert all(value == 0.0 for value in shallow.aggregate.values())
    deep = evaluate(qrels, run, metrics, depth=6)
    assert deep.aggregate["RR"] == pytest.approx(1 / 6)


@pytest.mark.parametrize("depth", [0, -3])
def test_invalid_depth_rejected(depth: int) -> None:
    with pytest.raises(ConfigurationError, match="depth must be >= 1"):
        evaluate(QRELS, {}, ["P@1"], depth=depth)


def test_invalid_missing_policy_rejected() -> None:
    with pytest.raises(ConfigurationError, match="missing must be"):
        evaluate(QRELS, {}, ["P@1"], missing="drop")  # type: ignore[arg-type]


def test_invalid_metric_requests_rejected() -> None:
    with pytest.raises(ConfigurationError, match="at least one metric"):
        evaluate(QRELS, {}, [])
    with pytest.raises(UnknownMetricError):
        evaluate(QRELS, {}, ["bpref"])
    with pytest.raises(ConfigurationError, match="rel_level"):
        evaluate(QRELS, {}, ["P@1"], rel_level=0)


# --- Requirement: Metadata pass-through --------------------------------------------


def test_missing_metadata() -> None:
    with pytest.raises(ConfigurationError, match="TestCourtShare@2 require document metadata"):
        evaluate(QRELS, {"q1": {"d1": 1.0}}, ["P@1", _CourtShare(cutoff=2)])


def test_metadata_is_passed_to_metrics() -> None:
    _CourtShare.seen.clear()
    docs: dict[str, dict[str, Any]] = {
        "d1": {"court": "SCOTUS"},
        "d2": {"court": "9th Cir."},
        "d3": {"court": "9th Cir."},
    }
    queries = {"q1": {"court": "SCOTUS"}}
    run = {"q1": {"d1": 2.0, "d2": 1.0}, "q2": {"d3": 1.0}}
    result = evaluate(
        QRELS, run, [_CourtShare(cutoff=2)], doc_metadata=docs, query_metadata=queries
    )
    assert result.per_query == {"q1": {"TestCourtShare@2": 0.5}, "q2": {"TestCourtShare@2": 0.0}}
    q1_context, q2_context = _CourtShare.seen
    assert q1_context.query == {"court": "SCOTUS"}
    assert q2_context.query == {}
    assert q1_context.documents is docs
    assert q2_context.documents is docs


def test_query_metadata_without_document_metadata() -> None:
    _CourtShare.seen.clear()
    result = evaluate(QRELS, {"q1": {"d1": 1.0}}, ["RR"], query_metadata={"q1": {"k": 1}})
    assert result.aggregate["RR"] == 0.5


# --- EvaluationResult helpers ------------------------------------------------------


def test_query_scores_resolves_specifications() -> None:
    result = evaluate(QRELS, {"q1": {"d1": 1.0}, "q2": {"d3": 1.0}}, ["nDCG@10"])
    assert result.query_scores("ndcg@10") == {"q1": 1.0, "q2": 1.0}
    assert result.query_scores("nDCG@10") == {"q1": 1.0, "q2": 1.0}
    with pytest.raises(ConfigurationError, match="not part of this evaluation"):
        result.query_scores("P@5")
    with pytest.raises(ConfigurationError, match="not part of this evaluation"):
        result.query_scores("unknown-metric")
