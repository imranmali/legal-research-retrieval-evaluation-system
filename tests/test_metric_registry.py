from collections.abc import Mapping, Sequence

import pytest

from groundtruth.errors import ConfigurationError, UnknownMetricError
from groundtruth.metrics import CutoffPolicy, Metric, MetricContext, get_metric, register_metric
from groundtruth.ranking import rank_documents


@register_metric
class _FirstHit(Metric):
    name = "TestFirstHit"
    aliases = ("tfh",)
    description = "1.0 when the first ranked document is relevant."
    cutoff_policy = CutoffPolicy.FORBIDDEN

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = MetricContext(),
    ) -> float:
        return float(bool(ranking) and self.is_relevant(judgments.get(ranking[0])))


def test_get_metric_resolves_aliases_case_insensitively() -> None:
    metric = get_metric("TFH")
    assert isinstance(metric, _FirstHit)
    assert metric.label == "TestFirstHit"
    assert metric.compute(["d1"], {"d1": 2}) == 1.0


def test_get_metric_rejects_bad_specs() -> None:
    with pytest.raises(UnknownMetricError):
        get_metric("no-such-metric")
    with pytest.raises(UnknownMetricError):
        get_metric("nDCG@ten")
    with pytest.raises(ConfigurationError):
        get_metric("TestFirstHit@5")


def test_rank_documents_breaks_ties_like_trec_eval() -> None:
    assert rank_documents({"a": 1.0, "c": 1.0, "b": 2.0}) == ["b", "c", "a"]
    assert rank_documents({"a": 1.0, "b": 2.0}, depth=1) == ["b"]
