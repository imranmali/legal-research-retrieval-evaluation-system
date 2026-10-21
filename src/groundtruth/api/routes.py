"""HTTP endpoints: probes and observability at the root, the versioned API under ``/v1``.

Handlers are plain ``def`` functions: FastAPI runs them in its threadpool, so
CPU-bound evaluation never blocks the event loop.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response, Security
from fastapi.security import APIKeyHeader
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import SecretStr

from groundtruth import __version__
from groundtruth.api.errors import APIError, error_body
from groundtruth.api.schemas import (
    CompareRequest,
    CompareResponse,
    CorpusInfo,
    EvaluateRequest,
    EvaluationResult,
    HealthResponse,
    MetricDescription,
    MetricsResponse,
    ReadinessResponse,
    SearchHitModel,
    SearchRequest,
    SearchResponse,
    ServiceInfo,
)
from groundtruth.api.state import ServiceState
from groundtruth.config import Settings
from groundtruth.evaluation import evaluate
from groundtruth.metrics import available_metrics
from groundtruth.stats import compare_many

__all__ = ["API_KEY_HEADER", "probes_router", "require_api_key", "v1_router"]

#: Header carrying the client's API key.
API_KEY_HEADER: Final = "X-API-Key"

_api_key_scheme = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="Required on /v1 endpoints when the service is configured with API keys.",
)


def _error_responses(*statuses: int) -> dict[int | str, dict[str, object]]:
    example = error_body("validation_error", "metrics.0: ...", request_id="5f0c...")
    return {
        status: {
            "description": "Error",
            "content": {"application/json": {"example": example}},
        }
        for status in statuses
    }


def get_state(request: Request) -> ServiceState:
    """The :class:`~groundtruth.api.app.ServiceState` of the serving application."""
    state: ServiceState = request.app.state.service
    return state


StateDep = Annotated[ServiceState, Depends(get_state)]


def _key_matches(candidate: str, keys: Iterable[SecretStr]) -> bool:
    """Constant-time comparison against every configured key (no early exit)."""
    supplied = candidate.encode("utf-8")
    matched = False
    for key in keys:
        matched |= secrets.compare_digest(supplied, key.get_secret_value().encode("utf-8"))
    return matched


def require_api_key(
    request: Request,
    api_key: Annotated[str | None, Security(_api_key_scheme)] = None,
) -> None:
    """Reject the request with 401 unless it carries a configured API key.

    Does nothing when no API keys are configured.
    """
    settings: Settings = get_state(request).settings
    if not settings.api_keys:
        return
    if api_key is None or not _key_matches(api_key, settings.api_keys):
        raise APIError(401, "unauthorized", f"missing or invalid {API_KEY_HEADER} header")


def _run_entries(run: Mapping[str, Mapping[str, float]]) -> int:
    return sum(len(docs) for docs in run.values())


def _check_run_entries(entries: int, settings: Settings) -> None:
    if entries > settings.max_run_entries:
        raise APIError(
            422,
            "too_many_run_entries",
            f"the request holds {entries} run entries; the limit is "
            f"{settings.max_run_entries}. Evaluate larger runs with the groundtruth CLI.",
        )


# ---------------------------------------------------------------------------
# Probes and observability (never authenticated)
# ---------------------------------------------------------------------------

probes_router = APIRouter(tags=["operations"])


@probes_router.get("/", response_model=ServiceInfo, summary="Service information")
def service_info() -> ServiceInfo:
    return ServiceInfo(
        name="groundtruth",
        version=__version__,
        docs="/docs",
        openapi="/openapi.json",
        health="/healthz",
        readiness="/readyz",
        metrics="/metrics",
    )


@probes_router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
def healthz() -> HealthResponse:
    """Answers 200 while the process is able to serve requests."""
    return HealthResponse()


@probes_router.get(
    "/readyz",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses=_error_responses(503),
)
def readyz(state: StateDep) -> ReadinessResponse:
    """Answers 200 once startup (including corpus indexing) has finished, 503 before."""
    if not state.ready:
        raise APIError(503, "not_ready", "the service is starting up or shutting down")
    corpus = None
    if state.retriever is not None:
        corpus = CorpusInfo(documents=len(state.documents), retriever=state.retriever.name)
    return ReadinessResponse(corpus=corpus)


@probes_router.get(
    "/metrics",
    summary="Prometheus metrics",
    response_class=Response,
    responses={200: {"content": {CONTENT_TYPE_LATEST: {}}}},
)
def prometheus_metrics(state: StateDep) -> Response:
    """Request counts and latencies by route template and status, in Prometheus text format."""
    return Response(generate_latest(state.metrics.registry), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Versioned API
# ---------------------------------------------------------------------------

v1_router = APIRouter(
    prefix="/v1",
    tags=["v1"],
    dependencies=[Depends(require_api_key)],
    responses=_error_responses(401, 413, 422, 500),
)


@v1_router.post(
    "/evaluate",
    response_model=EvaluationResult,
    summary="Evaluate a run",
)
def evaluate_run(body: EvaluateRequest, state: StateDep) -> EvaluationResult:
    """Score a run against relevance judgments: aggregate and per-query scores."""
    _check_run_entries(_run_entries(body.run), state.settings)
    result = evaluate(
        body.qrels,
        body.run,
        body.metrics,
        doc_metadata=body.doc_metadata,
        query_metadata=body.query_metadata,
        missing=body.missing,
        depth=body.depth,
        rel_level=body.rel_level,
    )
    if not body.include_per_query:
        result = result.model_copy(update={"per_query": {}})
    return result


@v1_router.post(
    "/compare",
    response_model=CompareResponse,
    summary="Compare systems with paired significance tests",
)
def compare_runs(body: CompareRequest, state: StateDep) -> CompareResponse:
    """Evaluate every run and compare each pair of systems on each metric.

    Pairs follow the order of ``runs`` (earlier system as A). P-values are
    Holm-Bonferroni corrected across the pairs of each metric.
    """
    settings = state.settings
    _check_run_entries(sum(_run_entries(run) for run in body.runs.values()), settings)
    results = {
        name: evaluate(
            body.qrels,
            run,
            body.metrics,
            doc_metadata=body.doc_metadata,
            query_metadata=body.query_metadata,
            missing=body.missing,
            depth=body.depth,
            rel_level=body.rel_level,
        )
        for name, run in body.runs.items()
    }
    labels = next(iter(results.values())).metrics
    n_resamples = body.n_resamples if body.n_resamples is not None else settings.default_resamples
    comparisons = [
        comparison
        for label in labels
        for comparison in compare_many(
            results,
            label,
            test=body.test,
            alpha=body.alpha,
            n_resamples=n_resamples,
            seed=body.seed,
        )
    ]
    return CompareResponse(
        systems=list(results),
        metrics=labels,
        aggregate={name: dict(result.aggregate) for name, result in results.items()},
        num_queries={name: result.num_queries for name, result in results.items()},
        comparisons=comparisons,
        warnings={name: list(result.warnings) for name, result in results.items()},
    )


@v1_router.get("/metrics", response_model=MetricsResponse, summary="List available metrics")
def list_metrics() -> MetricsResponse:
    """Registered metric families; request them as NAME or NAME@K."""
    return MetricsResponse(
        metrics=[
            MetricDescription(
                name=info.name,
                aliases=list(info.aliases),
                description=info.description,
                cutoff=info.cutoff_policy,
                higher_is_better=info.higher_is_better,
                requires_metadata=info.requires_context,
            )
            for info in available_metrics()
        ]
    )


@v1_router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search the configured corpus",
    responses=_error_responses(503),
)
def search_corpus(body: SearchRequest, state: StateDep) -> SearchResponse:
    """Search the corpus loaded at startup; 503 when the service has no corpus."""
    retriever = state.retriever
    if retriever is None:
        raise APIError(
            503,
            "corpus_unavailable",
            "no search corpus is configured; set GROUNDTRUTH_CORPUS_PATH",
        )
    hits = retriever.search(body.query, k=body.k, jurisdictions=body.jurisdictions)
    models = []
    for rank, hit in enumerate(hits, start=1):
        doc = state.documents[hit.doc_id]
        models.append(
            SearchHitModel(
                rank=rank,
                doc_id=hit.doc_id,
                score=hit.score,
                title=doc.title,
                jurisdiction=doc.jurisdiction,
                court=doc.court,
                decision_date=doc.decision_date,
                status=doc.status.value,
                citations=list(doc.citations),
            )
        )
    return SearchResponse(retriever=retriever.name, query=body.query, hits=models)
