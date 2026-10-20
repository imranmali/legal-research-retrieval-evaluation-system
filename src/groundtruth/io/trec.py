"""TREC-format relevance judgments (qrels) and runs.

Qrels lines have the form ``query_id iteration doc_id relevance`` and run lines
``query_id Q0 doc_id rank score tag``; columns are separated by any whitespace.
Blank lines and lines starting with ``#`` are ignored. Parsing is streaming and
all-or-nothing: the first malformed line raises :class:`~groundtruth.errors.FormatError`
naming the source and the 1-based line number, and no partial data is returned.

Files whose name ends in ``.gz`` are transparently (de)compressed with gzip.
"""

from __future__ import annotations

import gzip
import math
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, TextIO, TypeAlias

from groundtruth.errors import FormatError
from groundtruth.ranking import rank_documents
from groundtruth.types import Qrels, Run

#: A filesystem path accepted by the loaders and writers.
PathLike: TypeAlias = str | os.PathLike[str]

#: Destination accepted by the writers: a path or an already open text stream.
PathOrFile: TypeAlias = str | os.PathLike[str] | TextIO

_INT_RE = re.compile(r"[+-]?\d+")
_WHITESPACE_RE = re.compile(r"\s")

__all__ = [
    "PathLike",
    "PathOrFile",
    "dump_qrels",
    "dump_run",
    "load_qrels",
    "load_run",
    "open_output",
    "open_text",
    "parse_qrels",
    "parse_run",
]


def _open(path: Path, mode: Literal["r", "w"]) -> TextIO:
    encoding = "utf-8-sig" if mode == "r" else "utf-8"
    if path.name.lower().endswith(".gz"):
        if mode == "r":
            return gzip.open(path, "rt", encoding=encoding, newline="")
        return gzip.open(path, "wt", encoding=encoding, newline="")
    return path.open(mode, encoding=encoding, newline="")


@contextmanager
def open_text(path: PathLike, mode: Literal["r", "w"]) -> Iterator[TextIO]:
    """Open ``path`` as UTF-8 text, using gzip when the name ends in ``.gz``.

    Reading strips a leading byte-order mark. Decoding failures and corrupt
    gzip streams surface as :class:`FormatError` naming the file.
    """
    p = Path(path)
    try:
        with _open(p, mode) as handle:
            yield handle
    except (UnicodeDecodeError, gzip.BadGzipFile, EOFError) as exc:
        raise FormatError(f"{p}: cannot read file: {exc}") from exc


@contextmanager
def open_output(path_or_file: PathOrFile) -> Iterator[TextIO]:
    """Yield a writable text stream: open (and later close) a path, or pass a stream through."""
    if isinstance(path_or_file, str | os.PathLike):
        with open_text(path_or_file, "w") as handle:
            yield handle
    else:
        yield path_or_file


def _as_lines(lines: Iterable[str] | str) -> Iterable[str]:
    return lines.splitlines() if isinstance(lines, str) else lines


def _records(lines: Iterable[str] | str) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(line_number, columns)`` for every non-blank, non-comment line."""
    for lineno, raw in enumerate(_as_lines(lines), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield lineno, line.split()


def _parse_grade(token: str, source: str, lineno: int) -> int:
    if _INT_RE.fullmatch(token) is None:
        raise FormatError(f"{source}, line {lineno}: relevance must be an integer, got {token!r}")
    return max(int(token), 0)


def _parse_score(token: str, source: str, lineno: int) -> float:
    try:
        score = float(token) if "_" not in token else math.nan
    except ValueError:
        score = math.nan
    if not math.isfinite(score):
        raise FormatError(f"{source}, line {lineno}: score must be a finite number, got {token!r}")
    return score


def parse_qrels(lines: Iterable[str] | str, source: str = "<string>") -> Qrels:
    """Parse TREC qrels lines into ``{query_id: {doc_id: grade}}``.

    Negative grades (e.g. ``-1`` for "unjudgeable") are stored as 0. Repeating
    a judgment with the same grade is accepted; repeating it with a different
    grade is ambiguous and rejected. ``lines`` may be any iterable of lines
    (such as an open file) or a single string holding the whole content.

    Raises:
        FormatError: on the first malformed line, naming ``source`` and the line number.
    """
    qrels: Qrels = {}
    for lineno, cols in _records(lines):
        if len(cols) != 4:
            raise FormatError(
                f"{source}, line {lineno}: expected 4 columns "
                f"(query_id iteration doc_id relevance), found {len(cols)}"
            )
        query_id, _, doc_id, token = cols
        grade = _parse_grade(token, source, lineno)
        judgments = qrels.setdefault(query_id, {})
        previous = judgments.get(doc_id)
        if previous is not None and previous != grade:
            raise FormatError(
                f"{source}, line {lineno}: conflicting judgment for query {query_id!r}, "
                f"document {doc_id!r}: grade {grade} after earlier grade {previous}"
            )
        judgments[doc_id] = grade
    return qrels


def parse_run(lines: Iterable[str] | str, source: str = "<string>") -> Run:
    """Parse TREC run lines into ``{query_id: {doc_id: score}}``.

    The rank column is ignored: ranking order is always derived from the score
    (see :func:`groundtruth.ranking.rank_documents`). When a document is listed
    more than once for a query, the highest score is kept.

    Raises:
        FormatError: on the first malformed line, naming ``source`` and the line number.
    """
    run: Run = {}
    for lineno, cols in _records(lines):
        if len(cols) != 6:
            raise FormatError(
                f"{source}, line {lineno}: expected 6 columns "
                f"(query_id Q0 doc_id rank score tag), found {len(cols)}"
            )
        query_id, _, doc_id, _, token, _ = cols
        score = _parse_score(token, source, lineno)
        scores = run.setdefault(query_id, {})
        previous = scores.get(doc_id)
        if previous is None or score > previous:
            scores[doc_id] = score
    return run


def load_qrels(path: PathLike) -> Qrels:
    """Read a TREC qrels file (optionally ``.gz``); see :func:`parse_qrels`."""
    with open_text(path, "r") as handle:
        return parse_qrels(handle, source=str(path))


def load_run(path: PathLike) -> Run:
    """Read a TREC run file (optionally ``.gz``); see :func:`parse_run`."""
    with open_text(path, "r") as handle:
        return parse_run(handle, source=str(path))


def _check_token(value: str, what: str) -> None:
    if not value or _WHITESPACE_RE.search(value) is not None:
        raise FormatError(
            f"cannot write {what} {value!r} in TREC format: it is empty or contains whitespace"
        )


def dump_run(
    run: Mapping[str, Mapping[str, float]],
    path_or_file: PathOrFile,
    tag: str = "groundtruth",
) -> None:
    """Write ``run`` in TREC format.

    Queries are written in sorted order; within a query documents are ordered by
    descending score with the trec_eval tie-break and ranked from 1. Scores are
    written with full precision so that re-reading reproduces them exactly.

    Raises:
        FormatError: if an id or the tag cannot be represented (empty or containing
            whitespace), or a score is not finite.
    """
    _check_token(tag, "run tag")
    with open_output(path_or_file) as out:
        for query_id in sorted(run):
            _check_token(query_id, "query id")
            scores = run[query_id]
            for rank, doc_id in enumerate(rank_documents(scores), start=1):
                _check_token(doc_id, "document id")
                score = float(scores[doc_id])
                if not math.isfinite(score):
                    raise FormatError(
                        f"cannot write non-finite score {score!r} for query {query_id!r}, "
                        f"document {doc_id!r}"
                    )
                out.write(f"{query_id} Q0 {doc_id} {rank} {score!r} {tag}\n")


def dump_qrels(qrels: Mapping[str, Mapping[str, int]], path_or_file: PathOrFile) -> None:
    """Write ``qrels`` in TREC format (iteration column ``0``), sorted by query and document.

    Raises:
        FormatError: if an id is empty or contains whitespace.
    """
    with open_output(path_or_file) as out:
        for query_id in sorted(qrels):
            _check_token(query_id, "query id")
            judgments = qrels[query_id]
            for doc_id in sorted(judgments):
                _check_token(doc_id, "document id")
                out.write(f"{query_id} 0 {doc_id} {int(judgments[doc_id])}\n")
