"""Scoring a run against relevance judgments, per query and in aggregate."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

from groundtruth.errors import ConfigurationError, GroundTruthError
from groundtruth.metrics import EMPTY_CONTEXT, Metric, MetricContext, get_metric
from groundtruth.ranking import rank_documents
from groundtruth.types import DocMetadata, QueryMetadata

__all__ = [
    "EvaluationError",
    "EvaluationResult",
    "MissingPolicy",
    "evaluate",
    "resolve_metrics",
]

#: How queries judged in the qrels but absent from the run are treated.
MissingPolicy: TypeAlias = Literal["zero", "skip"]

_MAX_IDS_IN_WARNING = 10


class EvaluationError(GroundTruthError):
    """An evaluation or comparison cannot be carried out on the given data."""


class EvaluationResult(BaseModel):
    """Scores of one run: per evaluated query and averaged over them.

    ``metrics`` lists metric labels (e.g. ``nDCG@10``) in request order; every
    entry of ``aggregate`` and of each ``per_query`` row is keyed by those labels.
    """

    model_config = ConfigDict(frozen=True)

    metrics: list[str]
    aggregate: dict[str, float]
    per_query: dict[str, dict[str, float]]
    num_queries: int
    warnings: list[str] = []

    def query_scores(self, metric: str) -> dict[str, float]:
        """Per-query scores of one metric, keyed by query id.

        ``metric`` may be the exact label or any specification resolving to it
        (e.g. ``ndcg@10`` for ``nDCG@10``).

        Raises:
            ConfigurationError: if the metric was not part of this evaluation.
        """
        label = self.resolve_label(metric)
        return {query_id: scores[label] for query_id, scores in self.per_query.items()}

    def resolve_label(self, metric: str) -> str:
        """Map a metric specification to the label used in this result.

        Raises:
            ConfigurationError: if the metric was not part of this evaluation.
        """
        if metric in self.metrics:
            return metric
        try:
            label = get_metric(metric).label
        except GroundTruthError:
            label = None
        if label is None or label not in self.metrics:
            evaluated = ", ".join(self.metrics)
            raise ConfigurationError(
                f"metric {metric!r} is not part of this evaluation; evaluated: {evaluated}"
            )
        return label


def resolve_metrics(metrics: Sequence[str | Metric] | str, rel_level: int = 1) -> list[Metric]:
    """Resolve metric specifications, dropping repeated labels but keeping order.

    String specifications are instantiated with ``rel_level``; ready-made
    :class:`Metric` instances keep their own relevance level.

    Raises:
        UnknownMetricError: for an unknown or malformed specification.
        ConfigurationError: for an invalid cutoff, ``rel_level`` or an empty list.
    """
    specs: Iterable[str | Metric] = [metrics] if isinstance(metrics, str) else metrics
    resolved: dict[str, Metric] = {}
    for spec in specs:
        metric = get_metric(spec, rel_level=rel_level)
        resolved.setdefault(metric.label, metric)
    if not resolved:
        raise ConfigurationError("at least one metric must be requested")
    return list(resolved.values())


def _describe_ids(ids: Sequence[str]) -> str:
    shown = ", ".join(ids[:_MAX_IDS_IN_WARNING])
    extra = len(ids) - _MAX_IDS_IN_WARNING
    return f"{shown} and {extra} more" if extra > 0 else shown


def _check_score(metric: Metric, query_id: str, value: Any) -> float:
    score = float(value)
    if not math.isfinite(score):
        raise EvaluationError(
            f"metric {metric.label} returned a non-finite score {score!r} for query {query_id!r}"
        )
    return score


def evaluate(
    qrels: Mapping[str, Mapping[str, int]],
    run: Mapping[str, Mapping[str, float]],
    metrics: Sequence[str | Metric] | str,
    *,
    doc_metadata: DocMetadata | None = None,
    query_metadata: QueryMetadata | None = None,
    missing: MissingPolicy = "zero",
    depth: int | None = None,
    rel_level: int = 1,
) -> EvaluationResult:
    """Score ``run`` against ``qrels`` with each requested metric.

    The evaluated queries are those in ``qrels`` (in sorted order). Run queries
    without judgments are ignored with a warning. Judged queries missing from
    the run score 0 on every metric with ``missing="zero"`` (like ``trec_eval -c``)
    or are left out with ``missing="skip"``; either way a warning names them.

    Each query is ranked once (descending score, trec_eval tie-break) and
    truncated to ``depth`` documents when given. Metrics receive a
    :class:`MetricContext` holding ``query_metadata[query_id]`` and ``doc_metadata``.

    Args:
        qrels: ``{query_id: {doc_id: grade}}`` relevance judgments.
        run: ``{query_id: {doc_id: score}}`` retrieval scores.
        metrics: Metric specifications such as ``"nDCG@10"`` or :class:`Metric`
            instances; repeated labels are evaluated once.
        doc_metadata: Per-document metadata, required by metadata-dependent metrics.
        query_metadata: Per-query metadata passed to every metric.
        missing: Policy for judged queries absent from the run.
        depth: Keep only the top ``depth`` documents of each query.
        rel_level: Minimum grade counted as relevant by binary metrics.

    Raises:
        ConfigurationError: for invalid options or a metadata-dependent metric
            requested without ``doc_metadata`` (the message names the metric).
        UnknownMetricError: for an unknown metric specification.
        EvaluationError: when no query remains to evaluate.
    """
    if missing not in ("zero", "skip"):
        raise ConfigurationError(f"missing must be 'zero' or 'skip', got {missing!r}")
    if depth is not None and depth < 1:
        raise ConfigurationError(f"depth must be >= 1, got {depth}")
    resolved = resolve_metrics(metrics, rel_level=rel_level)
    needs_metadata = [m.label for m in resolved if m.requires_context]
    if needs_metadata and doc_metadata is None:
        raise ConfigurationError(
            f"metric(s) {', '.join(needs_metadata)} require document metadata, "
            "but none was supplied"
        )

    labels = [metric.label for metric in resolved]
    documents: Mapping[str, Mapping[str, Any]] = doc_metadata if doc_metadata is not None else {}
    queries: Mapping[str, Mapping[str, Any]] = query_metadata if query_metadata is not None else {}
    shared_context = (
        EMPTY_CONTEXT
        if doc_metadata is None and query_metadata is None
        else MetricContext(documents=documents)
    )

    warnings: list[str] = []
    unjudged = sorted(query_id for query_id in run if query_id not in qrels)
    if unjudged:
        warnings.append(
            f"{len(unjudged)} run quer{'y has' if len(unjudged) == 1 else 'ies have'} "
            f"no relevance judgments and {'was' if len(unjudged) == 1 else 'were'} "
            f"ignored: {_describe_ids(unjudged)}"
        )

    per_query: dict[str, dict[str, float]] = {}
    absent: list[str] = []
    for query_id in sorted(qrels):
        scores = run.get(query_id)
        if scores is None:
            absent.append(query_id)
            if missing == "zero":
                per_query[query_id] = dict.fromkeys(labels, 0.0)
            continue
        ranking = rank_documents(scores, depth)
        judgments = qrels[query_id]
        context = shared_context
        query_info = queries.get(query_id)
        if query_info is not None:
            context = MetricContext(query=query_info, documents=documents)
        per_query[query_id] = {
            metric.label: _check_score(
                metric, query_id, metric.compute(ranking, judgments, context)
            )
            for metric in resolved
        }

    if absent:
        action = "scored 0 on every metric" if missing == "zero" else "skipped"
        warnings.append(
            f"{len(absent)} judged quer{'y is' if len(absent) == 1 else 'ies are'} "
            f"missing from the run and {'was' if len(absent) == 1 else 'were'} {action}: "
            f"{_describe_ids(absent)}"
        )

    if not per_query:
        reason = (
            "the qrels contain no queries"
            if not qrels
            else "none of the judged queries appear in the run (missing='skip')"
        )
        raise EvaluationError(f"nothing to evaluate: {reason}")

    count = len(per_query)
    aggregate = {
        label: math.fsum(row[label] for row in per_query.values()) / count for label in labels
    }
    return EvaluationResult(
        metrics=labels,
        aggregate=aggregate,
        per_query=per_query,
        num_queries=count,
        warnings=warnings,
    )
