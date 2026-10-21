"""Legal-domain effectiveness and risk metrics.

Importing this module registers ``BadLaw``, ``JurisdictionMatch``,
``KeyAuthorityRecall`` (alias ``KAR``) and ``CitationRecall`` in the shared
metric registry. All four require a rank cutoff (``BadLaw@10``).

Context-dependent metrics read document metadata produced by
:func:`groundtruth.legal.corpus.document_metadata` (``status``,
``jurisdiction``, ``citations``) and query metadata produced by
:func:`groundtruth.legal.corpus.query_metadata` (``jurisdiction``,
``binding_jurisdictions``, ``expected_citations``). Documents missing from the
metadata are treated as having unknown status, no jurisdiction and no citations.

Only :mod:`groundtruth.metrics.base` is imported (never the
:mod:`groundtruth.metrics` package) so that package can import this module
without a cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any, Final

from groundtruth.legal.citations import normalize_citation
from groundtruth.metrics.base import (
    EMPTY_CONTEXT,
    CutoffPolicy,
    Metric,
    MetricContext,
    register_metric,
)

__all__ = [
    "BAD_LAW_STATUSES",
    "KEY_AUTHORITY_GRADE",
    "BadLaw",
    "CitationRecall",
    "JurisdictionMatch",
    "KeyAuthorityRecall",
]

#: Precedential statuses counted as bad law.
BAD_LAW_STATUSES: Final[frozenset[str]] = frozenset({"overruled", "superseded"})

#: Minimum relevance grade marking controlling (key) authority.
KEY_AUTHORITY_GRADE: Final = 3


def _doc_field(context: MetricContext, doc_id: str, key: str) -> Any:
    meta = context.documents.get(doc_id)
    return None if meta is None else meta.get(key)


def _as_strings(value: Any) -> list[str]:
    """Coerce a metadata value into a list of strings (tolerating None / scalars)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None]
    return [str(value)]


@lru_cache(maxsize=65536)
def _canonical(text: str) -> str:
    return normalize_citation(text) or text


def _canonical_set(values: Iterable[str]) -> set[str]:
    return {_canonical(text) for value in values if (text := value.strip())}


@register_metric
class BadLaw(Metric):
    """Fraction of the top-k documents that are overruled or superseded (lower is better)."""

    name = "BadLaw"
    description = (
        "Fraction of the top-k retrieved documents whose precedential status is "
        "overruled or superseded; lower is better, 0.0 when nothing is retrieved."
    )
    cutoff_policy = CutoffPolicy.REQUIRED
    higher_is_better = False
    requires_context = True

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],  # noqa: ARG002
        context: MetricContext = EMPTY_CONTEXT,
    ) -> float:
        top = self.truncate(ranking)
        if not top:
            return 0.0
        bad = sum(
            1
            for doc_id in top
            if str(_doc_field(context, doc_id, "status") or "").strip().lower() in BAD_LAW_STATUSES
        )
        return bad / len(top)


@register_metric
class JurisdictionMatch(Metric):
    """Fraction of the top-k documents from the query's target or binding jurisdictions."""

    name = "JurisdictionMatch"
    description = (
        "Fraction of the top-k retrieved documents whose jurisdiction is the query's "
        "target or a binding jurisdiction; 1.0 for queries without a target jurisdiction."
    )
    cutoff_policy = CutoffPolicy.REQUIRED
    requires_context = True

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],  # noqa: ARG002
        context: MetricContext = EMPTY_CONTEXT,
    ) -> float:
        target = context.query.get("jurisdiction")
        if not target:
            return 1.0
        allowed = {str(target), *_as_strings(context.query.get("binding_jurisdictions"))}
        top = self.truncate(ranking)
        if not top:
            return 0.0
        matched = sum(1 for doc_id in top if _doc_field(context, doc_id, "jurisdiction") in allowed)
        return matched / len(top)


@register_metric
class KeyAuthorityRecall(Metric):
    """Fraction of controlling (grade >= 3) documents retrieved in the top k."""

    name = "KeyAuthorityRecall"
    aliases = ("KAR",)
    description = (
        "Fraction of documents judged controlling authority (grade >= 3) that appear "
        "in the top k; 0.0 when the query has none."
    )
    cutoff_policy = CutoffPolicy.REQUIRED

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,  # noqa: ARG002
    ) -> float:
        key = {doc_id for doc_id, grade in judgments.items() if grade >= KEY_AUTHORITY_GRADE}
        if not key:
            return 0.0
        return len(key.intersection(self.truncate(ranking))) / len(key)


@register_metric
class CitationRecall(Metric):
    """Fraction of the query's expected citations carried by any top-k document."""

    name = "CitationRecall"
    description = (
        "Fraction of the query's expected citations (canonical form) carried by any "
        "document in the top k; 0.0 when the query lists none."
    )
    cutoff_policy = CutoffPolicy.REQUIRED
    requires_context = True

    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],  # noqa: ARG002
        context: MetricContext = EMPTY_CONTEXT,
    ) -> float:
        expected = _canonical_set(_as_strings(context.query.get("expected_citations")))
        if not expected:
            return 0.0
        found: set[str] = set()
        for doc_id in self.truncate(ranking):
            found |= _canonical_set(_as_strings(_doc_field(context, doc_id, "citations")))
        return len(expected & found) / len(expected)
