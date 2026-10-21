"""Authentication, request limits, request ids, error format and Prometheus metrics."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from groundtruth.api.app import create_app
from groundtruth.api.middleware import (
    UNMATCHED_ROUTE,
    BodySizeLimitMiddleware,
    HttpMetrics,
    PrometheusMiddleware,
    RequestBodyTooLarge,
    RequestContextMiddleware,
    route_template,
)
from groundtruth.config import Settings

from .conftest import SMOKE_BODY, ClientFactory


def _error(response: Any) -> dict[str, Any]:
    error: dict[str, Any] = response.json()["error"]
    assert set(error) >= {"code", "message", "request_id"}
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@pytest.fixture
def secured(make_client: ClientFactory) -> Iterator[TestClient]:
    with make_client(api_keys=["key-one", "key-two"]) as client:
        yield client


def test_missing_key(secured: TestClient) -> None:
    """Scenario: Missing key."""
    response = secured.post("/v1/evaluate", json=SMOKE_BODY)
    assert response.status_code == 401
    error = _error(response)
    assert error["code"] == "unauthorized"
    assert "X-API-Key" in error["message"]


@pytest.mark.parametrize(
    "key", ["wrong", "key-one ", "", "key-one,key-two", "kéy".encode("latin-1")]
)
def test_wrong_key(secured: TestClient, key: str | bytes) -> None:
    response = secured.post("/v1/evaluate", json=SMOKE_BODY, headers={"X-API-Key": key})
    assert response.status_code == 401


@pytest.mark.parametrize("key", ["key-one", "key-two"])
def test_any_configured_key_is_accepted(secured: TestClient, key: str) -> None:
    response = secured.post("/v1/evaluate", json=SMOKE_BODY, headers={"X-API-Key": key})
    assert response.status_code == 200
    assert response.json()["aggregate"]["P@1"] == 1.0


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/v1/metrics"), ("post", "/v1/compare"), ("post", "/v1/search")],
)
def test_every_v1_endpoint_requires_the_key(secured: TestClient, method: str, path: str) -> None:
    response = getattr(secured, method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics", "/", "/openapi.json"])
def test_operational_endpoints_stay_open(secured: TestClient, path: str) -> None:
    assert secured.get(path).status_code == 200


def test_auth_is_checked_before_body_validation(secured: TestClient) -> None:
    response = secured.post("/v1/evaluate", json={"not": "valid"})
    assert response.status_code == 401


def test_no_keys_means_no_auth(client: TestClient) -> None:
    assert client.post("/v1/evaluate", json=SMOKE_BODY).status_code == 200


def test_api_keys_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDTRUTH_API_KEYS", "env-key")
    with TestClient(create_app()) as client:
        assert client.get("/v1/metrics").status_code == 401
        assert client.get("/v1/metrics", headers={"X-API-Key": "env-key"}).status_code == 200


# ---------------------------------------------------------------------------
# Request limits
# ---------------------------------------------------------------------------


def test_oversized_body(make_client: ClientFactory) -> None:
    """Scenario: Oversized body."""
    with make_client(max_body_bytes=100) as client:
        small = client.post("/v1/evaluate", json=SMOKE_BODY)
        large = client.post(
            "/v1/evaluate",
            json={**SMOKE_BODY, "run": {"q1": {f"doc-{i}": 1.0 for i in range(50)}}},
        )
    assert small.status_code == 200
    assert large.status_code == 413
    error = _error(large)
    assert error["code"] == "payload_too_large"
    assert "100 bytes" in error["message"]


def test_oversized_streamed_body_without_content_length(make_client: ClientFactory) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"qrels": {"q1": {"d1": 1}}, '
        yield b'"run": {"q1": {"d1": 1.0}}, "metrics": ["P@1"]' + b" " * 200 + b"}"

    with make_client(max_body_bytes=100) as client:
        response = client.post(
            "/v1/evaluate", content=chunks(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 413
    assert _error(response)["code"] == "payload_too_large"


def test_streamed_body_within_the_limit(make_client: ClientFactory) -> None:
    def chunks() -> Iterator[bytes]:
        yield json.dumps(SMOKE_BODY).encode()

    with make_client(max_body_bytes=1000) as client:
        response = client.post(
            "/v1/evaluate", content=chunks(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 200


def test_invalid_content_length(client: TestClient) -> None:
    response = client.post(
        "/v1/evaluate",
        content=json.dumps(SMOKE_BODY).encode(),
        headers={"Content-Type": "application/json", "Content-Length": "lots"},
    )
    assert response.status_code == 400
    assert _error(response)["code"] == "bad_request"


async def _noop_receive() -> Message:  # pragma: no cover - never awaited
    return {"type": "http.disconnect"}


def _http_scope(**headers: str) -> Scope:
    return {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }


async def _run_asgi(app: Any, scope: Scope, body_chunks: list[bytes]) -> list[Message]:
    sent: list[Message] = []
    pending = [
        {"type": "http.request", "body": chunk, "more_body": i < len(body_chunks) - 1}
        for i, chunk in enumerate(body_chunks)
    ]

    async def receive() -> Message:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


async def _read_body_app(scope: Scope, receive: Receive, send: Send) -> None:
    """A bare ASGI app that reads the whole body, then answers 200."""
    while True:
        message = await receive()
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.anyio
async def test_body_limit_answers_413_when_the_app_does_not() -> None:
    middleware = BodySizeLimitMiddleware(_read_body_app, max_body_bytes=5)
    sent = await _run_asgi(middleware, _http_scope(), [b"abc", b"defgh"])
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["error"]["code"] == "payload_too_large"


@pytest.mark.anyio
async def test_body_limit_rejects_declared_length_on_first_read() -> None:
    middleware = BodySizeLimitMiddleware(_read_body_app, max_body_bytes=5)
    sent = await _run_asgi(middleware, _http_scope(**{"Content-Length": "6"}), [b"abcdef"])
    assert sent[0]["status"] == 413
    assert (b"connection", b"close") in sent[0]["headers"]
    invalid = await _run_asgi(middleware, _http_scope(**{"Content-Length": "-1"}), [b"a"])
    assert invalid[0]["status"] == 400
    assert json.loads(invalid[1]["body"])["error"]["code"] == "bad_request"


@pytest.mark.anyio
async def test_body_limit_ignores_unread_bodies() -> None:
    async def ignores_body(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = BodySizeLimitMiddleware(ignores_body, max_body_bytes=5)
    sent = await _run_asgi(middleware, _http_scope(**{"Content-Length": "600"}), [b"x" * 600])
    assert sent[0]["status"] == 204


@pytest.mark.anyio
async def test_body_limit_after_response_started_reraises() -> None:
    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()
        await receive()

    middleware = BodySizeLimitMiddleware(streaming_app, max_body_bytes=2)
    with pytest.raises(RequestBodyTooLarge):
        await _run_asgi(middleware, _http_scope(), [b"ab", b"cd"])


@pytest.mark.anyio
async def test_middleware_passes_non_http_scopes_through() -> None:
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    scope: Scope = {"type": "lifespan"}
    await BodySizeLimitMiddleware(app, 1)(scope, _noop_receive, _noop_send)
    await RequestContextMiddleware(app)(scope, _noop_receive, _noop_send)
    await PrometheusMiddleware(app, HttpMetrics())(scope, _noop_receive, _noop_send)
    assert seen == ["lifespan"] * 3


async def _noop_send(message: Message) -> None:  # pragma: no cover - never awaited
    return None


def test_body_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_body_bytes"):
        BodySizeLimitMiddleware(_read_body_app, 0)


# ---------------------------------------------------------------------------
# Request ids
# ---------------------------------------------------------------------------


def test_request_id_echo(client: TestClient) -> None:
    """Scenario: Request id echo."""
    response = client.get("/healthz", headers={"X-Request-ID": "abc"})
    assert response.headers["X-Request-ID"] == "abc"


def test_request_id_is_generated(client: TestClient) -> None:
    first = client.get("/healthz").headers["X-Request-ID"]
    second = client.get("/healthz").headers["X-Request-ID"]
    assert len(first) == 32
    assert first != second


@pytest.mark.parametrize("value", ["x" * 129, "has space", "new\nline", 'quote"'])
def test_unsafe_request_ids_are_replaced(client: TestClient, value: str) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": value})
    assert response.headers["X-Request-ID"] != value
    assert len(response.headers["X-Request-ID"]) == 32


def test_error_responses_carry_the_request_id(client: TestClient) -> None:
    response = client.post(
        "/v1/evaluate",
        json={"qrels": {}, "run": {}, "metrics": ["foo"]},
        headers={"X-Request-ID": "trace-1"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["request_id"] == "trace-1"
    assert response.headers["X-Request-ID"] == "trace-1"


def test_access_log_line(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="groundtruth.access"):
        client.post("/v1/evaluate", json=SMOKE_BODY, headers={"X-Request-ID": "log-1"})
    records = [r for r in caplog.records if r.name == "groundtruth.access"]
    assert records
    record = records[-1]
    assert record.http["route"] == "/v1/evaluate"  # type: ignore[attr-defined]
    assert record.http["status"] == 200  # type: ignore[attr-defined]
    assert record.http["method"] == "POST"  # type: ignore[attr-defined]
    assert record.request_id == "log-1"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Error format
# ---------------------------------------------------------------------------


def _app_with_failing_routes() -> FastAPI:
    app = create_app(Settings())

    def explode() -> None:
        raise RuntimeError("secret internal detail")

    app.add_api_route("/boom", explode, methods=["GET"])
    return app


def test_internal_error(caplog: pytest.LogCaptureFixture) -> None:
    """Scenario: Internal error."""
    with (
        caplog.at_level(logging.ERROR, logger="groundtruth.api"),
        TestClient(_app_with_failing_routes(), raise_server_exceptions=False) as client,
    ):
        response = client.get("/boom", headers={"X-Request-ID": "err-1"})
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "internal server error",
            "request_id": "err-1",
        }
    }
    assert "Traceback" not in response.text
    assert "secret internal detail" not in response.text
    assert response.headers["X-Request-ID"] == "err-1"
    # The traceback is logged server-side instead.
    assert any(r.exc_info for r in caplog.records if r.name == "groundtruth.api")


@pytest.mark.anyio
async def test_exception_after_response_started_is_reraised() -> None:
    async def half_sent(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("late failure")

    scope = _http_scope()
    with pytest.raises(RuntimeError, match="late failure"):
        await _run_asgi(RequestContextMiddleware(half_sent), scope, [b""])


def test_unexpected_status_code_name() -> None:
    from groundtruth.api.errors import status_code_name

    assert status_code_name(404) == "not_found"
    assert status_code_name(418) == "i_m_a_teapot"
    assert status_code_name(499) == "client_error"
    assert status_code_name(599) == "server_error"


def test_http_exception_without_string_detail() -> None:
    from fastapi import HTTPException

    app = create_app(Settings())

    def conflict() -> None:
        raise HTTPException(status_code=409, detail={"reason": "x"})

    app.add_api_route("/conflict", conflict, methods=["GET"])
    with TestClient(app) as client:
        response = client.get("/conflict")
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "conflict",
        "message": "Conflict",
        "request_id": response.headers["X-Request-ID"],
    }


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


def test_metrics_content(client: TestClient) -> None:
    client.post("/v1/evaluate", json=SMOKE_BODY)
    client.post("/v1/evaluate", json={"metrics": ["foo"]})
    client.get("/no/such/path/12345")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert (
        'groundtruth_http_requests_total{method="POST",route="/v1/evaluate",status="200"} 1.0'
        in text
    )
    assert (
        'groundtruth_http_requests_total{method="POST",route="/v1/evaluate",status="422"} 1.0'
        in text
    )
    assert f'route="{UNMATCHED_ROUTE}",status="404"' in text
    assert "/no/such/path" not in text
    assert 'groundtruth_http_request_duration_seconds_bucket{le="0.005",method="POST"' in text
    assert 'groundtruth_build_info{version="' in text
    assert "groundtruth_corpus_documents 0.0" in text


def test_metrics_label_route_templates_for_rejected_requests(make_client: ClientFactory) -> None:
    with make_client(max_body_bytes=10) as client:
        client.post("/v1/evaluate", json=SMOKE_BODY)
        text = client.get("/metrics").text
    assert 'route="/v1/evaluate",status="413"' in text


def test_metrics_registries_are_per_app(make_client: ClientFactory) -> None:
    with make_client() as first, make_client() as second:
        first.get("/healthz")
        assert 'route="/healthz"' in first.get("/metrics").text
        assert 'route="/healthz"' not in second.get("/metrics").text


def test_metrics_report_corpus_size(corpus_client: TestClient) -> None:
    assert "groundtruth_corpus_documents 24.0" in corpus_client.get("/metrics").text


def test_internal_errors_are_counted_as_500() -> None:
    with TestClient(_app_with_failing_routes(), raise_server_exceptions=False) as client:
        client.get("/boom")
        text = client.get("/metrics").text
    assert 'groundtruth_http_requests_total{method="GET",route="/boom",status="500"} 1.0' in text


def test_unusual_methods_share_one_label(client: TestClient) -> None:
    client.request("PROPFIND", "/healthz")
    assert 'method="OTHER"' in client.get("/metrics").text


def test_route_template_labels() -> None:
    class FakeRoute:
        path = "/v1/items/{item_id}"

    scope: Scope = {"type": "http", "path": "/v1/items/42", "route": FakeRoute()}
    assert route_template(scope) == "/v1/items/{item_id}"
    assert route_template({"type": "http", "path": "/v1/items/42"}) == UNMATCHED_ROUTE
    assert route_template({"type": "http", "route": object()}) == UNMATCHED_ROUTE


def test_path_parameters_do_not_leak_into_labels() -> None:
    app = create_app(Settings())

    def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    app.add_api_route("/items/{item_id}", item, methods=["GET"])
    with TestClient(app) as client:
        client.get("/items/1")
        client.get("/items/2")
        text = client.get("/metrics").text
    assert 'route="/items/{item_id}",status="200"} 2.0' in text


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_disabled_by_default(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Origin": "https://app.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_origins(make_client: ClientFactory) -> None:
    with make_client(cors_origins=["https://app.example"]) as client:
        simple = client.get("/healthz", headers={"Origin": "https://app.example"})
        preflight = client.options(
            "/v1/evaluate",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key, Content-Type",
            },
        )
        other = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert simple.headers["access-control-allow-origin"] == "https://app.example"
    assert "x-request-id" in simple.headers["access-control-expose-headers"].lower()
    assert preflight.status_code == 200
    assert "X-Request-ID" in preflight.headers
    assert "access-control-allow-origin" not in other.headers


@pytest.mark.anyio
async def test_body_limit_passes_disconnects_through() -> None:
    received: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        received.append(await receive())
        received.append(await receive())

    middleware = BodySizeLimitMiddleware(app, max_body_bytes=5)
    await _run_asgi(middleware, _http_scope(), [b"abc"])
    assert [m["type"] for m in received] == ["http.request", "http.disconnect"]


def test_error_codes_for_domain_errors() -> None:
    from groundtruth.api.errors import _domain_code, _validation_message
    from groundtruth.errors import ConfigurationError, FormatError, UnknownMetricError

    assert _domain_code(UnknownMetricError("x")) == "unknown_metric"
    assert _domain_code(FormatError("x")) == "invalid_input"
    assert _domain_code(ConfigurationError("x")) == "invalid_request"
    assert _validation_message([], 0) == "request validation failed"
