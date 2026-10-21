"""Uniform JSON error responses.

Every error the service returns has the shape::

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

with an optional ``details`` list for request validation failures. Messages
never contain stack traces; unexpected exceptions are logged server-side and
answered with a generic ``internal_error``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from groundtruth.errors import FormatError, GroundTruthError, UnknownMetricError
from groundtruth.logging import get_request_id

__all__ = [
    "APIError",
    "error_body",
    "error_response",
    "install_error_handlers",
]

#: Error codes for HTTP statuses raised by the framework (routing, auth, limits).
_STATUS_CODES: Final[Mapping[int, str]] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}

#: Limits on validation details echoed back to the client.
_MAX_DETAILS: Final = 20
_MAX_DETAIL_CHARS: Final = 500
_VALUE_ERROR_PREFIX: Final = "Value error, "


class APIError(Exception):
    """An error with a fixed HTTP status and machine-readable code.

    Raise it from endpoints and dependencies; :func:`install_error_handlers`
    renders it in the standard error format.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers) if headers else None


def error_body(
    code: str,
    message: str,
    request_id: str | None = None,
    details: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The JSON body of an error response."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id if request_id is not None else get_request_id(),
    }
    if details:
        error["details"] = list(details)
    return {"error": error}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Sequence[Mapping[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """A :class:`JSONResponse` in the standard error format."""
    return JSONResponse(
        error_body(code, message, details=details),
        status_code=status_code,
        headers=dict(headers) if headers else None,
    )


def status_code_name(status_code: int) -> str:
    """Error code used for a bare HTTP status (``404`` -> ``not_found``)."""
    known = _STATUS_CODES.get(status_code)
    if known is not None:
        return known
    try:
        return re.sub(r"[^a-z0-9]+", "_", HTTPStatus(status_code).phrase.lower()).strip("_")
    except ValueError:
        return "client_error" if status_code < 500 else "server_error"


def _domain_code(exc: GroundTruthError) -> str:
    if isinstance(exc, UnknownMetricError):
        return "unknown_metric"
    if isinstance(exc, FormatError):
        return "invalid_input"
    return "invalid_request"


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_DETAIL_CHARS else text[: _MAX_DETAIL_CHARS - 3] + "..."


def _clean_message(message: str) -> str:
    """Drop pydantic's ``Value error, `` prefix from messages raised by our validators."""
    return message.removeprefix(_VALUE_ERROR_PREFIX)


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Location, message and type of each validation error, without echoing input values."""
    return [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": _truncate(_clean_message(str(error.get("msg", "")))),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()[:_MAX_DETAILS]
    ]


def _validation_message(details: Sequence[Mapping[str, Any]], total: int) -> str:
    if not details:
        return "request validation failed"
    first = details[0]
    location = ".".join(part for part in first["loc"] if part != "body") or "body"
    text = str(first["msg"])
    message = text if text.startswith(f"{location}:") else f"{location}: {text}"
    if total > 1:
        message += f" (and {total - 1} more error{'s' if total > 2 else ''})"
    return message


async def _handle_api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, APIError)
    return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def _handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(
        exc.status_code, status_code_name(exc.status_code), message, headers=exc.headers
    )


async def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = _validation_details(exc)
    message = _validation_message(details, len(exc.errors()))
    return error_response(422, "validation_error", message, details=details)


async def _handle_domain_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GroundTruthError)
    return error_response(422, _domain_code(exc), str(exc))


def install_error_handlers(app: FastAPI) -> None:
    """Register the standard error rendering on ``app``.

    Unexpected exceptions are not handled here: they propagate to
    :class:`groundtruth.api.middleware.RequestContextMiddleware`, which logs
    them and answers ``500 internal_error`` with the request id attached.
    """
    app.add_exception_handler(APIError, _handle_api_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(GroundTruthError, _handle_domain_error)
