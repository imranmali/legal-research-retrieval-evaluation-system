"""FastAPI application factory.

Production runs the factory, never a module-level app::

    gunicorn --worker-class uvicorn_worker.UvicornWorker "groundtruth.api.app:create_app()"
    uvicorn --factory groundtruth.api.app:create_app

Tests call ``create_app(Settings(...))`` to inject configuration.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from groundtruth import __version__
from groundtruth.api.errors import install_error_handlers
from groundtruth.api.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    PrometheusMiddleware,
    RequestContextMiddleware,
)
from groundtruth.api.routes import API_KEY_HEADER, probes_router, v1_router
from groundtruth.api.state import ServiceState
from groundtruth.config import Settings
from groundtruth.logging import configure_logging

__all__ = ["create_app"]

logger = logging.getLogger("groundtruth.api")

_DESCRIPTION = """
Evaluate, compare and benchmark legal research retrieval systems.

* `POST /v1/evaluate` scores a run against relevance judgments.
* `POST /v1/compare` tests whether systems differ significantly.
* `GET /v1/metrics` lists the available metrics.
* `POST /v1/search` searches the corpus configured at startup.

When API keys are configured, `/v1` endpoints require an `X-API-Key` header.
Errors are returned as `{"error": {"code", "message", "request_id"}}`.
"""


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    state: ServiceState = app.state.service
    try:
        await anyio.to_thread.run_sync(state.load_corpus)
    except Exception:
        logger.exception("startup failed: cannot load corpus %s", state.settings.corpus_path)
        raise
    state.ready = True
    logger.info("service ready", extra={"version": __version__})
    try:
        yield
    finally:
        state.ready = False
        logger.info("service shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Ground Truth API.

    Args:
        settings: Configuration; read from ``GROUNDTRUTH_*`` environment
            variables when omitted.

    The corpus (if configured) is loaded and indexed in the lifespan startup,
    so ``/readyz`` answers 200 only once the service can serve every endpoint.
    A corpus that cannot be loaded aborts startup.
    """
    settings = settings if settings is not None else Settings()
    configure_logging(settings.log_level, json_format=settings.log_json)

    app = FastAPI(
        title="Ground Truth",
        summary="Legal research retrieval evaluation service",
        description=_DESCRIPTION,
        version=__version__,
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    state = ServiceState(settings=settings)
    app.state.service = state

    install_error_handlers(app)
    app.include_router(probes_router)
    app.include_router(v1_router)

    # Middleware added last runs first: the request context wraps everything.
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", API_KEY_HEADER, REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(PrometheusMiddleware, metrics=state.metrics)
    app.add_middleware(RequestContextMiddleware)
    return app
