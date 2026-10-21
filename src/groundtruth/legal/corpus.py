"""Legal documents, research queries and their conversion to evaluation metadata.

Documents and queries are read from JSONL files (one JSON object per line,
optionally gzip-compressed). Citation fields are normalized to canonical form
where the citation is recognized; unrecognized strings are kept verbatim so
no information is lost.
"""

from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Iterable, Iterator
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from groundtruth.errors import FormatError
from groundtruth.legal.citations import normalize_citation

__all__ = [
    "LegalDocument",
    "LegalQuery",
    "PrecedentialStatus",
    "document_metadata",
    "load_documents",
    "load_queries",
    "normalize_citation_list",
    "query_metadata",
]


class PrecedentialStatus(StrEnum):
    """Whether a document is still good law."""

    GOOD_LAW = "good_law"
    QUESTIONED = "questioned"
    OVERRULED = "overruled"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


def normalize_citation_list(values: Iterable[str]) -> list[str]:
    """Canonicalize citations, keep unrecognized ones verbatim, drop blanks and duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text:
            continue
        canonical = normalize_citation(text) or text
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _optional_text(value: Any) -> Any:
    """Strip strings and map blank strings to ``None``."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


_Id = Annotated[str, Field(min_length=1)]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class LegalDocument(_Record):
    """A judicial opinion, statute or other authority in a retrieval corpus.

    ``citations`` are the document's own citations (how it is cited);
    ``cites`` are the authorities it relies on. Both are stored canonically.
    """

    doc_id: _Id
    text: str
    title: str = ""
    jurisdiction: str | None = None
    court: str | None = None
    decision_date: date | None = None
    citations: list[str] = Field(default_factory=list)
    cites: list[str] = Field(default_factory=list)
    status: PrecedentialStatus = PrecedentialStatus.UNKNOWN

    @field_validator("doc_id", mode="before")
    @classmethod
    def _strip_id(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("jurisdiction", "court", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _optional_text(value)

    @field_validator("citations", "cites")
    @classmethod
    def _normalize_citations(cls, value: list[str]) -> list[str]:
        return normalize_citation_list(value)

    @field_validator("status", mode="before")
    @classmethod
    def _parse_status(cls, value: Any) -> Any:
        if value is None:
            return PrecedentialStatus.UNKNOWN
        if isinstance(value, str):
            return value.strip().lower().replace(" ", "_").replace("-", "_")
        return value


class LegalQuery(_Record):
    """A legal research question with its jurisdictional scope.

    ``binding_jurisdictions`` lists jurisdictions besides ``jurisdiction``
    whose authority binds the research (e.g. ``US-FED`` for a California
    question); ``expected_citations`` are citations a good answer should surface.
    """

    query_id: _Id
    text: str
    jurisdiction: str | None = None
    binding_jurisdictions: list[str] = Field(default_factory=list)
    expected_citations: list[str] = Field(default_factory=list)

    @field_validator("query_id", mode="before")
    @classmethod
    def _strip_id(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("jurisdiction", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _optional_text(value)

    @field_validator("binding_jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(j.strip() for j in value if j.strip()))

    @field_validator("expected_citations")
    @classmethod
    def _normalize_citations(cls, value: list[str]) -> list[str]:
        return normalize_citation_list(value)

    @property
    def jurisdictions(self) -> frozenset[str] | None:
        """Target plus binding jurisdictions, or ``None`` without a target."""
        if self.jurisdiction is None:
            return None
        return frozenset({self.jurisdiction, *self.binding_jurisdictions})


_GZIP_MAGIC: Final = b"\x1f\x8b"
R = TypeVar("R", bound=_Record)


def _iter_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open("rb") as probe:
        compressed = probe.read(2) == _GZIP_MAGIC
    if compressed:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            yield from enumerate(handle, start=1)
    else:
        with path.open(encoding="utf-8") as handle:
            yield from enumerate(handle, start=1)


def _describe(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        location = ".".join(str(p) for p in item["loc"]) or "record"
        parts.append(f"{location}: {item['msg']}")
    return "; ".join(parts)


def _load(path: str | Path, model: type[R], id_field: str) -> list[R]:
    source = Path(path)
    records: list[R] = []
    first_seen: dict[str, int] = {}
    try:
        for lineno, line in _iter_lines(source):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FormatError(f"{source}:{lineno}: invalid JSON: {exc.msg}") from exc
            if not isinstance(raw, dict):
                raise FormatError(
                    f"{source}:{lineno}: expected a JSON object, got {type(raw).__name__}"
                )
            try:
                record = model.model_validate(raw)
            except ValidationError as exc:
                raise FormatError(f"{source}:{lineno}: invalid record: {_describe(exc)}") from exc
            record_id: str = getattr(record, id_field)
            if record_id in first_seen:
                raise FormatError(
                    f"{source}:{lineno}: duplicate {id_field} {record_id!r} "
                    f"(first defined on line {first_seen[record_id]})"
                )
            first_seen[record_id] = lineno
            records.append(record)
    except (OSError, UnicodeDecodeError, EOFError, zlib.error) as exc:
        raise FormatError(f"{source}: cannot read file: {exc}") from exc
    return records


def load_documents(path: str | Path) -> list[LegalDocument]:
    """Load documents from a JSONL (or gzip-compressed JSONL) file.

    Blank lines are skipped. Raises :class:`~groundtruth.errors.FormatError`
    naming the file and 1-based line for invalid JSON, invalid records and
    duplicate ``doc_id`` values, and for unreadable files.
    """
    return _load(path, LegalDocument, "doc_id")


def load_queries(path: str | Path) -> list[LegalQuery]:
    """Load research queries from a JSONL (or gzip-compressed JSONL) file.

    Same format rules and errors as :func:`load_documents`, keyed on ``query_id``.
    """
    return _load(path, LegalQuery, "query_id")


def document_metadata(documents: Iterable[LegalDocument]) -> dict[str, dict[str, Any]]:
    """Document metadata for the evaluation engine.

    Keys per document: ``status`` (string value), ``jurisdiction`` and
    ``citations`` (canonical forms).
    """
    return {
        doc.doc_id: {
            "status": doc.status.value,
            "jurisdiction": doc.jurisdiction,
            "citations": list(doc.citations),
        }
        for doc in documents
    }


def query_metadata(queries: Iterable[LegalQuery]) -> dict[str, dict[str, Any]]:
    """Query metadata for the evaluation engine.

    Keys per query: ``jurisdiction``, ``binding_jurisdictions`` and
    ``expected_citations`` (canonical forms).
    """
    return {
        query.query_id: {
            "jurisdiction": query.jurisdiction,
            "binding_jurisdictions": list(query.binding_jurisdictions),
            "expected_citations": list(query.expected_citations),
        }
        for query in queries
    }
