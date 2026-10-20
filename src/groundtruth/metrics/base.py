"""Metric contract and registry.

Every metric (standard IR metrics and the legal-domain ones) implements
:class:`Metric` and is registered with :func:`register_metric`, which makes it
resolvable from a textual specification such as ``"nDCG@10"`` or ``"MAP"``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, TypeVar

from groundtruth.errors import ConfigurationError, UnknownMetricError


class CutoffPolicy(StrEnum):
    """Whether a metric family takes an ``@k`` rank cutoff."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class MetricContext:
    """Side information for metrics that need more than relevance labels.

    ``query`` holds metadata of the query being scored; ``documents`` maps doc
    ids to their metadata. Both are empty when the caller supplied none.
    """

    query: Mapping[str, Any] = field(default_factory=dict)
    documents: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


EMPTY_CONTEXT = MetricContext()


class Metric(ABC):
    """A per-query effectiveness measure.

    Subclasses set the class attributes and implement :meth:`compute`.
    ``rel_level`` is the minimum graded relevance counted as relevant by
    binary metrics.
    """

    name: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]] = ()
    description: ClassVar[str] = ""
    cutoff_policy: ClassVar[CutoffPolicy] = CutoffPolicy.OPTIONAL
    higher_is_better: ClassVar[bool] = True
    requires_context: ClassVar[bool] = False

    def __init__(self, cutoff: int | None = None, rel_level: int = 1) -> None:
        if cutoff is not None and cutoff < 1:
            raise ConfigurationError(f"{self.name}: cutoff must be >= 1, got {cutoff}")
        if self.cutoff_policy is CutoffPolicy.REQUIRED and cutoff is None:
            raise ConfigurationError(f"{self.name} requires a rank cutoff, e.g. {self.name}@10")
        if self.cutoff_policy is CutoffPolicy.FORBIDDEN and cutoff is not None:
            raise ConfigurationError(f"{self.name} does not take a rank cutoff")
        if rel_level < 1:
            raise ConfigurationError(f"rel_level must be >= 1, got {rel_level}")
        self.cutoff = cutoff
        self.rel_level = rel_level

    @property
    def label(self) -> str:
        """Canonical display name, e.g. ``nDCG@10``."""
        return self.name if self.cutoff is None else f"{self.name}@{self.cutoff}"

    def truncate(self, ranking: Sequence[str]) -> Sequence[str]:
        """Apply this metric's cutoff to a ranking."""
        return ranking if self.cutoff is None else ranking[: self.cutoff]

    def is_relevant(self, grade: int | None) -> bool:
        return grade is not None and grade >= self.rel_level

    @abstractmethod
    def compute(
        self,
        ranking: Sequence[str],
        judgments: Mapping[str, int],
        context: MetricContext = EMPTY_CONTEXT,
    ) -> float:
        """Score one query.

        ``ranking`` is the full ranked list of doc ids (best first);
        ``judgments`` maps judged doc ids to graded relevance. Unjudged
        documents count as non-relevant. Must return a finite float.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.label}>"


@dataclass(frozen=True)
class MetricInfo:
    """Public description of a registered metric family."""

    name: str
    aliases: tuple[str, ...]
    description: str
    cutoff_policy: CutoffPolicy
    higher_is_better: bool
    requires_context: bool


_REGISTRY: dict[str, type[Metric]] = {}
_SPEC_RE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z0-9_\-]*)\s*(?:@\s*(?P<cutoff>\d+))?\s*$")

M = TypeVar("M", bound=type[Metric])


def register_metric(cls: M) -> M:
    """Class decorator registering a metric family under its name and aliases."""
    for key in (cls.name, *cls.aliases):
        normalized = key.lower()
        existing = _REGISTRY.get(normalized)
        if existing is not None and existing is not cls:
            raise ConfigurationError(
                f"metric name {key!r} already registered by {existing.__name__}"
            )
        _REGISTRY[normalized] = cls
    return cls


def get_metric(spec: str | Metric, rel_level: int = 1) -> Metric:
    """Resolve ``"NAME[@CUTOFF]"`` (case-insensitive) to a metric instance."""
    if isinstance(spec, Metric):
        return spec
    match = _SPEC_RE.match(spec)
    if match is None:
        raise UnknownMetricError(f"invalid metric specification {spec!r}; expected NAME or NAME@K")
    cls = _REGISTRY.get(match["name"].lower())
    if cls is None:
        known = ", ".join(info.name for info in available_metrics())
        raise UnknownMetricError(f"unknown metric {match['name']!r}; available: {known}")
    cutoff = int(match["cutoff"]) if match["cutoff"] is not None else None
    return cls(cutoff=cutoff, rel_level=rel_level)


def available_metrics() -> list[MetricInfo]:
    """Registered metric families, sorted by name, without alias duplicates."""
    seen: dict[str, type[Metric]] = {cls.name: cls for cls in _REGISTRY.values()}
    return [
        MetricInfo(
            name=cls.name,
            aliases=cls.aliases,
            description=cls.description,
            cutoff_policy=cls.cutoff_policy,
            higher_is_better=cls.higher_is_better,
            requires_context=cls.requires_context,
        )
        for _, cls in sorted(seen.items(), key=lambda kv: kv[0].lower())
    ]
