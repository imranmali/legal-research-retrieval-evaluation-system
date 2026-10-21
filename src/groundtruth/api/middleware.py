"""Pure ASGI middleware: request context, body-size limit and Prometheus metrics.

Pure ASGI (instead of ``BaseHTTPMiddleware``) keeps streaming intact, adds no
per-request task and lets the body limit count bytes as they arrive.

Order, outermost first, as installed by :func:`groundtruth.api.app.create_app`:

1. :class:`RequestContextMiddleware` assigns the request id, writes the access
   log line and turns unexpected exceptions into ``500 internal_error``.
2. :class:`PrometheusMiddleware` counts requests and observes latencies.
3. (optional CORS)
4. :class:`BodySizeLimitMiddleware` rejects oversized bodies with 413.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from groundtruth import __version__
from groundtruth.api.errors import error_response, status_code_name
from groundtruth.logging import bind_request_id

__all__ = [
    "REQUEST_ID_HEADER",
    "UNMATCHED_ROUTE",
    "BodySizeLimitMiddleware",
    "HttpMetrics",
    "InvalidContentLength",
    "PrometheusMiddleware",
    "RequestBodyRejected",
    "RequestBodyTooLarge",
    "RequestContextMiddleware",
    "route_template",
]

#: Header carrying the request id, read from clients and echoed on every response.
REQUEST_ID_HEADER: Final = "X-Request-ID"

#: Route label for requests matching no route (keeps metric cardinality bounded).
UNMATCHED_ROUTE: Final = "<unmatched>"

#: Client-supplied request ids are echoed only if they match this pattern,
#: which keeps them safe to log and to send back as a header.
_VALID_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9._:/+=@-]{1,128}")

#: Latency buckets (seconds); evaluations of large runs can take tens of seconds.
_LATENCY_BUCKETS: Final = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
)

#: Methods reported as-is in metrics; anything else is labelled ``OTHER``.
_KNOWN_METHODS: Final = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)

access_logger = logging.getLogger("groundtruth.access")
error_logger = logging.getLogger("groundtruth.api")


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _client_request_id(scope: Scope) -> str | None:
    value = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if value is not None and _VALID_REQUEST_ID.fullmatch(value):
        return value
    return None


def route_template(scope: Scope) -> str:
    """Path template of the route serving ``scope`` (``/v1/evaluate``), never the raw path.

    Requests that matched no route are labelled :data:`UNMATCHED_ROUTE`, which
    keeps the label set bounded whatever paths clients request.
    """
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class RequestContextMiddleware:
    """Request id, structured access log and last-resort error handling.

    The request id is the client's ``X-Request-ID`` when it is well formed
    (at most 128 characters of ``[A-Za-z0-9._:/+=@-]``), otherwise a new UUID.
    It is bound for logging, stored in ``scope["state"]["request_id"]`` and
    returned in the ``X-Request-ID`` response header. An exception escaping
    the application is logged with its traceback and answered with
    ``500 internal_error`` (no traceback in the body) if no response has
    started yet.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _client_request_id(scope) or _new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        with bind_request_id(request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                error_logger.exception(
                    "unhandled exception while serving %s %s", scope["method"], scope["path"]
                )
                if response_started:
                    raise
                response = error_response(500, "internal_error", "internal server error")
                await response(scope, receive, send_with_request_id)
            finally:
                access_logger.info(
                    "%s %s %d",
                    scope["method"],
                    scope["path"],
                    status_code,
                    extra={
                        "http": {
                            "method": scope["method"],
                            "path": scope["path"],
                            "route": route_template(scope),
                            "status": status_code,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                            "client": _client_address(scope),
                        }
                    },
                )


def _client_address(scope: Scope) -> str | None:
    client = scope.get("client")
    return None if client is None else str(client[0])


class RequestBodyRejected(HTTPException):
    """Raised from ``receive`` when a request body must not be read."""


class RequestBodyTooLarge(RequestBodyRejected):
    """The request body exceeds the configured limit (413)."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            status_code=413,
            detail=f"request body exceeds the limit of {limit} bytes",
            # Unread body bytes may remain on the connection; do not reuse it.
            headers={"Connection": "close"},
        )


class InvalidContentLength(RequestBodyRejected):
    """The ``Content-Length`` header is not a non-negative integer (400)."""

    def __init__(self) -> None:
        super().__init__(status_code=400, detail="invalid Content-Length header")


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ``max_body_bytes`` with 413.

    The check happens when the application first reads the body, so the
    request has been routed (metrics and logs carry its route) and nothing of
    an oversized body is consumed: a declared ``Content-Length`` above the
    limit fails immediately, and bodies without a (truthful) length are
    counted while they stream. Either way :class:`RequestBodyTooLarge` is
    raised from ``receive``; FastAPI renders it as a 413 error, and this
    middleware does so itself for an application that lets it escape before
    responding.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError(f"max_body_bytes must be >= 1, got {max_body_bytes}")
        self.app = app
        self.max_body_bytes = max_body_bytes

    def _declared_problem(self, scope: Scope) -> RequestBodyRejected | None:
        declared = Headers(scope=scope).get("content-length")
        if declared is None:
            return None
        if not declared.strip().isdigit():
            return InvalidContentLength()
        if int(declared) > self.max_body_bytes:
            return RequestBodyTooLarge(self.max_body_bytes)
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        problem = self._declared_problem(scope)
        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            if problem is not None:
                raise problem
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise RequestBodyTooLarge(self.max_body_bytes)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestBodyRejected as exc:
            if response_started:
                raise
            response = error_response(
                exc.status_code,
                status_code_name(exc.status_code),
                exc.detail,
                headers=exc.headers,
            )
            await response(scope, receive, send)


class HttpMetrics:
    """Prometheus collectors of one application, in their own registry.

    A per-application :class:`CollectorRegistry` (instead of the global default)
    lets several apps coexist in one process, e.g. in tests.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        self.requests = Counter(
            "groundtruth_http_requests_total",
            "HTTP requests served, by method, route template and status code.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.latency = Histogram(
            "groundtruth_http_request_duration_seconds",
            "HTTP request latency in seconds, by method and route template.",
            ("method", "route"),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.in_progress = Gauge(
            "groundtruth_http_requests_in_progress",
            "HTTP requests currently being served.",
            registry=self.registry,
        )
        self.build_info = Gauge(
            "groundtruth_build_info",
            "Ground Truth version serving the requests (value is always 1).",
            ("version",),
            registry=self.registry,
        )
        self.build_info.labels(version=__version__).set(1)
        self.corpus_documents = Gauge(
            "groundtruth_corpus_documents",
            "Documents in the search corpus loaded at startup (0 without a corpus).",
            registry=self.registry,
        )


class PrometheusMiddleware:
    """Record request counts and latencies labelled by route template and status."""

    def __init__(self, app: ASGIApp, metrics: HttpMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500
        started = time.perf_counter()

        async def recording_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        self.metrics.in_progress.inc()
        try:
            await self.app(scope, receive, recording_send)
        finally:
            self.metrics.in_progress.dec()
            route = route_template(scope)
            method = scope["method"] if scope["method"] in _KNOWN_METHODS else "OTHER"
            self.metrics.requests.labels(method=method, route=route, status=str(status_code)).inc()
            self.metrics.latency.labels(method=method, route=route).observe(
                time.perf_counter() - started
            )
