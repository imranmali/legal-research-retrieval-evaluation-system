"""Reading and writing relevance judgments (qrels) and runs.

TREC text and JSON formats are supported, each optionally gzip-compressed
(``.gz``). :func:`load_qrels_any` and :func:`load_run_any` pick the format
from the file name: ``*.json`` / ``*.json.gz`` are JSON, anything else is TREC.
"""

from __future__ import annotations

from pathlib import Path

from groundtruth.io.jsonio import (
    dump_json,
    load_qrels_json,
    load_run_json,
    qrels_from_mapping,
    run_from_mapping,
)
from groundtruth.io.trec import (
    PathLike,
    PathOrFile,
    dump_qrels,
    dump_run,
    load_qrels,
    load_run,
    open_output,
    open_text,
    parse_qrels,
    parse_run,
)
from groundtruth.types import Qrels, Run

__all__ = [
    "PathLike",
    "PathOrFile",
    "dump_json",
    "dump_qrels",
    "dump_run",
    "is_json_path",
    "load_qrels",
    "load_qrels_any",
    "load_qrels_json",
    "load_run",
    "load_run_any",
    "load_run_json",
    "open_output",
    "open_text",
    "parse_qrels",
    "parse_run",
    "qrels_from_mapping",
    "run_from_mapping",
]


def is_json_path(path: PathLike) -> bool:
    """Whether ``path`` names a JSON file (``.json`` or ``.json.gz``, case-insensitive)."""
    return Path(path).name.lower().endswith((".json", ".json.gz"))


def load_qrels_any(path: PathLike) -> Qrels:
    """Load qrels from a TREC or JSON file, chosen by the file name suffix."""
    return load_qrels_json(path) if is_json_path(path) else load_qrels(path)


def load_run_any(path: PathLike) -> Run:
    """Load a run from a TREC or JSON file, chosen by the file name suffix."""
    return load_run_json(path) if is_json_path(path) else load_run(path)
