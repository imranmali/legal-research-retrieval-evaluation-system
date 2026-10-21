"""Request and response models of the HTTP API.

Qrels and runs use the library's JSON shape ``{query_id: {doc_id: value}}``
and are validated by :func:`groundtruth.io.qrels_from_mapping` and
:func:`groundtruth.io.run_from_mapping`, so the API accepts exactly what the
CLI accepts from JSON files: integer grades (negative grades become 0) and
finite numeric scores, never booleans or numeric strings.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from groundtruth.config import DEFAULT_METRICS
from groundtruth.errors import FormatError
from groundtruth.evaluation import EvaluationResult, MissingPolicy
from groundtruth.io import qrels_from_mapping, run_from_mapping
from groundtruth.metrics import CutoffPolicy
from groundtruth.stats import PairedComparison, SignificanceTest

__all__ = [
    "MAX_METRICS",
    "MAX_SYSTEMS",
    "CompareRequest",
    "CompareResponse",
    "CorpusInfo",
    "EvaluateRequest",
    "EvaluationResult",
    "HealthResponse",
    "MetricDescription",
    "MetricsResponse",
    "ReadinessResponse",
    "SearchHitModel",
    "SearchRequest",
    "SearchResponse",
    "ServiceInfo",
]

#: Most metrics one request may ask for.
MAX_METRICS: Final = 50
#: Most systems one comparison may include (190 pairs).
MAX_SYSTEMS: Final = 20
#: Upper bound on resamples a client may request for one test.
MAX_RESAMPLES: Final = 100_000


def _qrels(value: Any) -> Any:
    try:
        return qrels_from_mapping(value, source="qrels")
    except FormatError as exc:
        raise ValueError(str(exc)) from exc


def _run(value: Any) -> Any:
    try:
        return run_from_mapping(value, source="run")
    except FormatError as exc:
        raise ValueError(str(exc)) from exc


QrelsField = Annotated[
    dict[str, dict[str, int]],
    BeforeValidator(_qrels),
    Field(
        description="Relevance judgments: {query_id: {doc_id: integer grade}}.",
        examples=[{"q1": {"d1": 1, "d2": 0}}],
    ),
]
RunField = Annotated[
    dict[str, dict[str, float]],
    BeforeValidator(_run),
    Field(
        description="Retrieval scores: {query_id: {doc_id: score}}; higher ranks first.",
        examples=[{"q1": {"d1": 2.5, "d2": 1.0}}],
    ),
]
MetadataField = Annotated[
    dict[str, dict[str, Any]] | None,
    Field(
        description=(
            "Optional metadata keyed by id, as produced by groundtruth.legal "
            "(documents: status, jurisdiction, citations; queries: jurisdiction, "
            "binding_jurisdictions, expected_citations). Required by legal metrics."
        ),
    ),
]
MetricsField = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=64)]],
    Field(
        min_length=1,
        max_length=MAX_METRICS,
        description="Metric specifications such as nDCG@10, P@5, MAP or BadLaw@10.",
    ),
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EvaluationOptions(_Request):
    metrics: MetricsField = Field(default_factory=lambda: list(DEFAULT_METRICS))
    doc_metadata: MetadataField = None
    query_metadata: MetadataField = None
    missing: MissingPolicy = Field(
        default="zero",
        description="Judged queries absent from a run score 0 ('zero') or are left out ('skip').",
    )
    depth: int | None = Field(
        default=None, ge=1, description="Keep only the top `depth` documents per query."
    )
    rel_level: int = Field(
        default=1, ge=1, description="Minimum grade counted as relevant by binary metrics."
    )


class EvaluateRequest(_EvaluationOptions):
    """Body of ``POST /v1/evaluate``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"qrels": {"q1": {"d1": 1}}, "run": {"q1": {"d1": 1.0}}, "metrics": ["P@1"]}
            ]
        },
    )

    qrels: QrelsField
    run: RunField
    include_per_query: bool = Field(
        default=True, description="Return per-query scores (set false for large runs)."
    )


class CompareRequest(_EvaluationOptions):
    """Body of ``POST /v1/compare``: two or more named runs over the same qrels."""

    qrels: QrelsField
    runs: dict[str, dict[str, dict[str, float]]] = Field(
        min_length=2,
        max_length=MAX_SYSTEMS,
        description="Named runs, compared pairwise in the given order: {system: run}.",
    )
    test: SignificanceTest = "permutation"
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    n_resamples: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RESAMPLES,
        description="Resamples for permutation/bootstrap tests (default: service setting).",
    )
    seed: int | None = Field(default=0, description="Random seed; null for a random one.")

    @field_validator("runs", mode="before")
    @classmethod
    def _validate_runs(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        runs: dict[str, Any] = {}
        for name, run in value.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("system names must be non-empty strings")
            try:
                runs[name] = run_from_mapping(run, source=f"runs[{name!r}]")
            except FormatError as exc:
                raise ValueError(str(exc)) from exc
        return runs


class CompareResponse(BaseModel):
    """Per-system aggregate scores and pairwise comparisons per metric."""

    systems: list[str]
    metrics: list[str]
    aggregate: dict[str, dict[str, float]] = Field(
        description="Mean score per system and metric: {system: {metric: score}}."
    )
    num_queries: dict[str, int]
    comparisons: list[PairedComparison] = Field(
        description="One entry per metric and system pair; p-values Holm-corrected per metric."
    )
    warnings: dict[str, list[str]] = Field(description="Evaluation warnings per system.")


class MetricDescription(BaseModel):
    """A registered metric family."""

    name: str
    aliases: list[str]
    description: str
    cutoff: CutoffPolicy = Field(description="Whether the metric takes an @k cutoff.")
    higher_is_better: bool
    requires_metadata: bool = Field(description="Whether doc_metadata must be supplied.")


class MetricsResponse(BaseModel):
    metrics: list[MetricDescription]


class SearchRequest(_Request):
    """Body of ``POST /v1/search``."""

    query: str = Field(min_length=1, max_length=10_000)
    k: int = Field(default=10, ge=1, le=1000)
    jurisdictions: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        max_length=100,
        description="Only return documents from these jurisdictions (e.g. US-FED).",
    )


class SearchHitModel(BaseModel):
    rank: int
    doc_id: str
    score: float
    title: str
    jurisdiction: str | None
    court: str | None
    decision_date: date | None
    status: str
    citations: list[str]


class SearchResponse(BaseModel):
    retriever: str
    query: str
    hits: list[SearchHitModel]


class CorpusInfo(BaseModel):
    documents: int
    retriever: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    corpus: CorpusInfo | None = None


class ServiceInfo(BaseModel):
    name: str
    version: str
    docs: str
    openapi: str
    health: str
    readiness: str
    metrics: str
