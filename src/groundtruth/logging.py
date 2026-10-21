"""Structured logging with request correlation.

:func:`configure_logging` installs one handler on the root logger that writes
either JSON objects (one per line) or human-readable lines to standard error.
Every record carries the id of the HTTP request being served, taken from a
context variable that the API's request middleware sets
(:func:`bind_request_id`), so all log lines of one request can be correlated
with the ``X-Request-ID`` response header.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final, TextIO

__all__ = [
    "JsonFormatter",
    "RequestIdFilter",
    "bind_request_id",
    "configure_logging",
    "get_request_id",
]

_REQUEST_ID: ContextVar[str | None] = ContextVar("groundtruth_request_id", default=None)

#: Attributes every LogRecord has; anything else was passed through ``extra``.
_RECORD_ATTRIBUTES: Final = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None))
) | {"message", "asctime", "request_id", "taskName", "color_message"}

_TEXT_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s"

#: Loggers of the ASGI server whose output is routed through our handler.
_SERVER_LOGGERS: Final = ("uvicorn", "uvicorn.error", "gunicorn.error")
#: Server access loggers silenced because the API middleware logs each request.
_ACCESS_LOGGERS: Final = ("uvicorn.access",)

_installed_handler: logging.Handler | None = None


def get_request_id() -> str | None:
    """Id of the request being served in the current context, if any."""
    return _REQUEST_ID.get()


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    """Make ``request_id`` the current request id for the duration of the block."""
    token = _REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _REQUEST_ID.reset(token)


class RequestIdFilter(logging.Filter):
    """Attach the current request id (or ``-``) to every record as ``request_id``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        return True


class _StandardErrorHandler(logging.StreamHandler[TextIO]):
    """Write to whatever ``sys.stderr`` is when a record is emitted.

    Resolving the stream late keeps logging working when ``sys.stderr`` is
    replaced after configuration (test runners, CLI test harnesses).
    """

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        """Ignore assignments: the stream is always the current ``sys.stderr``."""


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON objects.

    Keys: ``timestamp`` (UTC, ISO 8601), ``level``, ``logger``, ``message``,
    ``request_id`` (when serving a request), ``exception`` (formatted traceback,
    when logged with ``exc_info``) and any fields passed through ``extra``.
    Values that are not JSON-serializable are rendered with ``str``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id and request_id != "-":
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _RECORD_ATTRIBUTES and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: str | int = "INFO",
    *,
    json_format: bool = True,
    stream: TextIO | None = None,
) -> logging.Handler:
    """Install the Ground Truth log handler on the root logger.

    Idempotent: a handler installed by an earlier call is replaced, while
    handlers installed by others (for example pytest's log capture) are kept.
    Server loggers (uvicorn, gunicorn) propagate to the root so their lines use
    the same format; the server access log is silenced because the API
    middleware writes one structured access line per request.

    Args:
        level: Log level name or number applied to the root logger.
        json_format: JSON lines when true, human-readable text otherwise.
        stream: Destination; standard error by default.

    Returns:
        The installed handler.
    """
    global _installed_handler

    handler: logging.Handler = (
        logging.StreamHandler(stream) if stream is not None else _StandardErrorHandler()
    )
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if json_format else logging.Formatter(_TEXT_FORMAT))

    root = logging.getLogger()
    if _installed_handler is not None:
        root.removeHandler(_installed_handler)
    root.addHandler(handler)
    root.setLevel(level.upper() if isinstance(level, str) else level)
    _installed_handler = handler

    for name in _SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    for name in _ACCESS_LOGGERS:
        access_logger = logging.getLogger(name)
        access_logger.handlers.clear()
        access_logger.propagate = False
    return handler
