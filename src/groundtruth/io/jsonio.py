"""JSON interchange for qrels and runs.

Both use the shape ``{query_id: {doc_id: value}}`` (the pytrec_eval convention)
and are validated with the same rules as the TREC readers: relevance grades are
integers (negative grades become 0) and scores are finite numbers.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from groundtruth.errors import FormatError
from groundtruth.io.trec import PathLike, PathOrFile, open_output, open_text
from groundtruth.types import Qrels, Run

__all__ = [
    "dump_json",
    "load_qrels_json",
    "load_run_json",
    "qrels_from_mapping",
    "run_from_mapping",
]


def _entries(data: Any, source: str) -> list[tuple[str, Mapping[Any, Any]]]:
    if not isinstance(data, Mapping):
        raise FormatError(
            f"{source}: expected a JSON object mapping query ids to "
            f"{{doc_id: value}} objects, got {type(data).__name__}"
        )
    entries: list[tuple[str, Mapping[Any, Any]]] = []
    for query_id, docs in data.items():
        if not isinstance(query_id, str) or not query_id:
            raise FormatError(f"{source}: query ids must be non-empty strings, got {query_id!r}")
        if not isinstance(docs, Mapping):
            raise FormatError(
                f"{source}: query {query_id!r}: expected an object mapping doc ids to values, "
                f"got {type(docs).__name__}"
            )
        for doc_id in docs:
            if not isinstance(doc_id, str) or not doc_id:
                raise FormatError(
                    f"{source}: query {query_id!r}: doc ids must be non-empty strings, "
                    f"got {doc_id!r}"
                )
        entries.append((query_id, docs))
    return entries


def qrels_from_mapping(data: Any, source: str = "<data>") -> Qrels:
    """Validate a decoded ``{query_id: {doc_id: grade}}`` object and return qrels.

    Grades must be integers (booleans are rejected); negative grades become 0.

    Raises:
        FormatError: naming ``source``, the query and the document at fault.
    """
    qrels: Qrels = {}
    for query_id, docs in _entries(data, source):
        judgments: dict[str, int] = {}
        for doc_id, grade in docs.items():
            if isinstance(grade, bool) or not isinstance(grade, int):
                raise FormatError(
                    f"{source}: query {query_id!r}, document {doc_id!r}: "
                    f"relevance must be an integer, got {grade!r}"
                )
            judgments[doc_id] = max(grade, 0)
        qrels[query_id] = judgments
    return qrels


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def run_from_mapping(data: Any, source: str = "<data>") -> Run:
    """Validate a decoded ``{query_id: {doc_id: score}}`` object and return a run.

    Scores must be finite numbers (booleans are rejected).

    Raises:
        FormatError: naming ``source``, the query and the document at fault.
    """
    run: Run = {}
    for query_id, docs in _entries(data, source):
        scores: dict[str, float] = {}
        for doc_id, score in docs.items():
            value = _finite_float(score)
            if value is None:
                raise FormatError(
                    f"{source}: query {query_id!r}, document {doc_id!r}: "
                    f"score must be a finite number, got {score!r}"
                )
            scores[doc_id] = value
        run[query_id] = scores
    return run


def _load(path: PathLike) -> Any:
    with open_text(path, "r") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError as exc:
            raise FormatError(
                f"{path}, line {exc.lineno}, column {exc.colno}: invalid JSON: {exc.msg}"
            ) from exc


def load_qrels_json(path: PathLike) -> Qrels:
    """Read qrels from a JSON file (optionally ``.gz``); see :func:`qrels_from_mapping`."""
    return qrels_from_mapping(_load(path), source=str(path))


def load_run_json(path: PathLike) -> Run:
    """Read a run from a JSON file (optionally ``.gz``); see :func:`run_from_mapping`."""
    return run_from_mapping(_load(path), source=str(path))


def dump_json(data: Any, path_or_file: PathOrFile, *, indent: int | None = 2) -> None:
    """Write JSON-serializable ``data`` (or a pydantic model) to a path or text stream.

    Keys are written in sorted order for reproducible output; a path ending in
    ``.gz`` is gzip-compressed. Non-finite floats are rejected, since they are
    not valid JSON.

    Raises:
        FormatError: if ``data`` cannot be represented as standard JSON.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    try:
        text = json.dumps(data, indent=indent, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise FormatError(f"cannot serialize data as JSON: {exc}") from exc
    with open_output(path_or_file) as out:
        out.write(text)
        out.write("\n")
