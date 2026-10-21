"""Structured logging and request-id correlation."""

import io
import json
import logging
from collections.abc import Iterator

import pytest

from groundtruth.logging import (
    JsonFormatter,
    RequestIdFilter,
    bind_request_id,
    configure_logging,
    get_request_id,
)


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _record(message: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("groundtruth.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_request_id_is_bound_for_the_block() -> None:
    assert get_request_id() is None
    with bind_request_id("abc"):
        assert get_request_id() == "abc"
        with bind_request_id("inner"):
            assert get_request_id() == "inner"
        assert get_request_id() == "abc"
    assert get_request_id() is None


def test_json_formatter_renders_core_fields_and_extras() -> None:
    line = JsonFormatter().format(_record("served %s", http={"status": 200}, _private=1))
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "groundtruth.test"
    assert payload["message"] == "served %s"
    assert payload["http"] == {"status": 200}
    assert payload["timestamp"].endswith("+00:00")
    assert "_private" not in payload
    assert "request_id" not in payload


def test_json_formatter_includes_request_id_from_context() -> None:
    with bind_request_id("req-1"):
        payload = json.loads(JsonFormatter().format(_record()))
    assert payload["request_id"] == "req-1"


def test_json_formatter_renders_exceptions_and_unserializable_values() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info(), sinfo="stack here"
        )
    record.obj = object()
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]
    assert payload["stack"] == "stack here"
    assert payload["obj"].startswith("<object object")


def test_request_id_filter_defaults_to_dash() -> None:
    record = _record()
    assert RequestIdFilter().filter(record)
    assert record.request_id == "-"
    with bind_request_id("r2"):
        other = _record()
        RequestIdFilter().filter(other)
    assert other.request_id == "r2"


@pytest.mark.usefixtures("restore_logging")
def test_configure_logging_json_output() -> None:
    stream = io.StringIO()
    configure_logging("debug", json_format=True, stream=stream)
    with bind_request_id("abc"):
        logging.getLogger("groundtruth.test").debug("hello", extra={"answer": 42})
    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["message"] == "hello"
    assert payload["request_id"] == "abc"
    assert payload["answer"] == 42
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.usefixtures("restore_logging")
def test_configure_logging_text_output() -> None:
    stream = io.StringIO()
    configure_logging(logging.WARNING, json_format=False, stream=stream)
    logging.getLogger("groundtruth.test").info("hidden")
    logging.getLogger("groundtruth.test").warning("shown")
    output = stream.getvalue()
    assert "hidden" not in output
    assert "WARNING" in output
    assert "groundtruth.test [-] shown" in output


@pytest.mark.usefixtures("restore_logging")
def test_configure_logging_is_idempotent_and_keeps_foreign_handlers() -> None:
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    first = configure_logging()
    second = configure_logging()
    assert first not in root.handlers
    assert second in root.handlers
    assert foreign in root.handlers


@pytest.mark.usefixtures("restore_logging")
def test_configure_logging_routes_server_loggers_through_root() -> None:
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.addHandler(logging.NullHandler())
    uvicorn_error.propagate = False
    configure_logging()
    assert uvicorn_error.handlers == []
    assert uvicorn_error.propagate
    assert logging.getLogger("uvicorn.access").propagate is False
