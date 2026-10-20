"""Standard ranked-retrieval metrics, numerically compatible with trec_eval.

Conventions shared by every metric here:

* ``ranking`` is the ranked list of doc ids, best first (see
  :func:`groundtruth.ranking.rank_documents`); the metric applies its own ``@k`` cutoff.
* Unjudged documents are non-relevant. Binary metrics count a document as
  relevant when its grade is at least ``rel_level``; nDCG uses the graded
  relevance itself as gain and ignores ``rel_level`` (as trec_eval does).
* Normalising quantities that would be zero (no relevant judgments) yield a
  score of 0.0 rather than an error.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import lru_cache

from groundtruth.metrics.base import (
    EMPTY_CONTEXT,
    CutoffPolicy,
    Metric,
    MetricContext,
    register_metric,
)

__all__ = [
    "NDCG",
    "AveragePrecision",
    "Judged",
    "Precision",
    "RPrecision",
    "Recall",
    "ReciprocalRank",
    "Success",
]


def _num_relevant(judgments: Mapping[str, int], rel_level: int) -> int:
    return sum(1 for grade in judgments.values() if grade >= rel_level)


def _hits(metric: Metric, ranking: Sequence[str], judgments: Mapping[str, int]) -> int:
    return sum(1 for doc_id in ranking if metric.is_relevant(judgments.get(doc_id)))


def _required_cutoff(metric: Metric) -> int:
    cutoff = metric.cutoff
    assert cutoff is not None, "guaranteed by CutoffPolicy.REQUIRED"
    return cutoff


@lru_cache(maxsize=4096)
def _discount(rank: int) -> float:
    """``1 / log2(rank + 1)`` for a 1-based rank."""
    return 1.0 / math.log2(rank + 1)


def _dcg(gains: Sequence[int]) -> float:
    """Discounted cumulative gain; identical inputs give bit-identical sums."""
    return math.fsum(gain * _discount(rank) for rank, gain in enumerate(gains, 1) if gain > 0)


@register_metric
class Precision(Metric):
    """Precision@k: relevant documents in the top k divided by k."""

    name = "P"
    aliases = ("precision",)
    description = (
        "Precision at rank k: relevant documents in the top k divided by k "
        "(k is used even when fewer documents were retrieved)."
    )
    cutoff_policy = CutoffPolicy.REQUIRED

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        k = _required_cutoff(self)
        return _hits(self, ranking[:k], judgments) / k


@register_metric
class Recall(Metric):
    """Recall@k: relevant documents in the top k over all relevant documents."""

    name = "R"
    aliases = ("recall",)
    description = "Recall at rank k: relevant documents in the top k over all judged relevant."
    cutoff_policy = CutoffPolicy.REQUIRED

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        total = _num_relevant(judgments, self.rel_level)
        if total == 0:
            return 0.0
        return _hits(self, self.truncate(ranking), judgments) / total


@register_metric
class Success(Metric):
    """Success@k: 1.0 when at least one relevant document is in the top k."""

    name = "Success"
    description = "Success at rank k: 1 if any relevant document appears in the top k, else 0."
    cutoff_policy = CutoffPolicy.REQUIRED

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        found = any(self.is_relevant(judgments.get(doc_id)) for doc_id in self.truncate(ranking))
        return 1.0 if found else 0.0


@register_metric
class RPrecision(Metric):
    """R-Precision: precision at rank R, where R is the number of relevant documents."""

    name = "RPrec"
    aliases = ("R-Precision",)
    description = "R-Precision: precision at rank R, where R is the number of judged relevant."
    cutoff_policy = CutoffPolicy.FORBIDDEN

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        total = _num_relevant(judgments, self.rel_level)
        if total == 0:
            return 0.0
        return _hits(self, ranking[:total], judgments) / total


@register_metric
class ReciprocalRank(Metric):
    """Reciprocal rank of the first relevant document (0 when none is retrieved)."""

    name = "RR"
    aliases = ("MRR",)
    description = (
        "Reciprocal rank: 1/rank of the first relevant document, 0 if none is retrieved "
        "(within the top k when a cutoff is given). Its mean over queries is MRR."
    )
    cutoff_policy = CutoffPolicy.OPTIONAL

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        for rank, doc_id in enumerate(self.truncate(ranking), start=1):
            if self.is_relevant(judgments.get(doc_id)):
                return 1.0 / rank
        return 0.0


@register_metric
class AveragePrecision(Metric):
    """Average precision; the mean over queries is MAP."""

    name = "AP"
    aliases = ("MAP",)
    description = (
        "Average precision: mean of the precision at each relevant document's rank, divided "
        "by the number of judged relevant (relevant documents not retrieved, or below the "
        "cutoff, contribute 0). Its mean over queries is MAP."
    )
    cutoff_policy = CutoffPolicy.OPTIONAL

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        total = _num_relevant(judgments, self.rel_level)
        if total == 0:
            return 0.0
        hits = 0
        precision_sum = 0.0
        for rank, doc_id in enumerate(self.truncate(ranking), start=1):
            if self.is_relevant(judgments.get(doc_id)):
                hits += 1
                precision_sum += hits / rank
        return precision_sum / total


@register_metric
class NDCG(Metric):
    """Normalized discounted cumulative gain with graded (linear) gains."""

    name = "nDCG"
    description = (
        "Normalized discounted cumulative gain: gain = graded relevance, discount "
        "log2(rank + 1), normalized by the ideal ordering of all judged documents "
        "(both truncated at k when a cutoff is given)."
    )
    cutoff_policy = CutoffPolicy.OPTIONAL

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        ideal = sorted((grade for grade in judgments.values() if grade > 0), reverse=True)
        ideal_dcg = _dcg(ideal if self.cutoff is None else ideal[: self.cutoff])
        if ideal_dcg == 0.0:
            return 0.0
        gains = [judgments.get(doc_id, 0) for doc_id in self.truncate(ranking)]
        return _dcg(gains) / ideal_dcg


@register_metric
class Judged(Metric):
    """Judged@k: the fraction of the top k retrieved documents that have a judgment."""

    name = "Judged"
    description = (
        "Judgment coverage at rank k: documents in the top k that have any relevance "
        "judgment, divided by k. Low values mean the other scores are unreliable."
    )
    cutoff_policy = CutoffPolicy.REQUIRED

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002 - part of the Metric contract
    ) -> float:
        k = _required_cutoff(self)
        return sum(1 for doc_id in ranking[:k] if doc_id in judgments) / k
