"""Tests for JSON interchange and format dispatch (spec: relevance-data)."""

import gzip
import io
import json
import math
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from groundtruth.errors import FormatError
from groundtruth.io import (
    dump_json,
    dump_qrels,
    dump_run,
    is_json_path,
    load_qrels_any,
    load_qrels_json,
    load_run_any,
    load_run_json,
    qrels_from_mapping,
    run_from_mapping,
)

# --- Requirement: JSON interchange -------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    run = {"q1": {"d1": 0.1 + 0.2, "d2": -4.0}, "q2": {"d3": 1e-300}}
    path = tmp_path / "run.json"
    dump_json(run, path)
    assert load_run_json(path) == run


def test_round_trip_gzip(tmp_path: Path) -> None:
    qrels = {"q1": {"d1": 3, "d2": 0}}
    path = tmp_path / "qrels.json.gz"
    dump_json(qrels, path)
    assert json.loads(gzip.decompress(path.read_bytes())) == qrels
    assert load_qrels_json(path) == qrels


def test_json_qrels_negative_grade_becomes_zero() -> None:
    assert qrels_from_mapping({"q1": {"d1": -1, "d2": 2}}) == {"q1": {"d1": 0, "d2": 2}}


def test_json_run_integer_scores_become_floats() -> None:
    run = run_from_mapping({"q1": {"d1": 3}})
    assert run == {"q1": {"d1": 3.0}}
    assert isinstance(run["q1"]["d1"], float)


@pytest.mark.parametrize("grade", [1.5, "2", True, None, [1]])
def test_json_qrels_reject_non_integer_grades(grade: Any) -> None:
    with pytest.raises(FormatError, match=r"src: query 'q1', document 'd1': relevance"):
        qrels_from_mapping({"q1": {"d1": grade}}, source="src")


@pytest.mark.parametrize("score", [math.nan, math.inf, "1.0", False, None, 10**400])
def test_json_run_reject_invalid_scores(score: Any) -> None:
    with pytest.raises(FormatError, match=r"query 'q1', document 'd1': score must be"):
        run_from_mapping({"q1": {"d1": score}})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "expected a JSON object"),
        ({"q1": [1, 2]}, "query 'q1': expected an object"),
        ({"": {"d1": 1}}, "query ids must be non-empty strings"),
        ({1: {"d1": 1}}, "query ids must be non-empty strings"),
        ({"q1": {"": 1}}, "doc ids must be non-empty strings"),
    ],
)
def test_json_structure_validation(data: Any, message: str) -> None:
    with pytest.raises(FormatError, match=message):
        qrels_from_mapping(data)
    with pytest.raises(FormatError, match=message):
        run_from_mapping(data)


def test_invalid_json_reports_line(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text('{\n  "q1": {"d1": 1.0,}\n}\n', encoding="utf-8")
    with pytest.raises(FormatError, match=r"run\.json, line 2, column \d+: invalid JSON"):
        load_run_json(path)


def test_dump_json_to_stream_is_sorted_and_newline_terminated() -> None:
    out = io.StringIO()
    dump_json({"b": 1, "a": {"y": 2, "x": 1}}, out, indent=None)
    assert out.getvalue() == '{"a": {"x": 1, "y": 2}, "b": 1}\n'


def test_dump_json_accepts_pydantic_models() -> None:
    class Point(BaseModel):
        x: float
        label: str

    out = io.StringIO()
    dump_json(Point(x=1.5, label="p"), out)
    assert json.loads(out.getvalue()) == {"label": "p", "x": 1.5}


@pytest.mark.parametrize("data", [{"x": math.nan}, {"x": object()}])
def test_dump_json_rejects_unserializable_data(data: Any) -> None:
    with pytest.raises(FormatError, match="cannot serialize"):
        dump_json(data, io.StringIO())


# --- Format dispatch ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("run.json", True),
        ("RUN.JSON", True),
        ("run.json.gz", True),
        ("run.txt", False),
        ("run.txt.gz", False),
        ("run", False),
        ("json", False),
    ],
)
def test_is_json_path(name: str, expected: bool) -> None:
    assert is_json_path(name) is expected


def test_load_any_dispatches_on_suffix(tmp_path: Path) -> None:
    qrels = {"q1": {"d1": 1}}
    run = {"q1": {"d1": 2.5, "d2": 1.0}}
    dump_json(qrels, tmp_path / "qrels.json")
    dump_json(run, tmp_path / "run.json.gz")
    dump_qrels(qrels, tmp_path / "qrels.txt")
    dump_run(run, tmp_path / "run.trec.gz")
    assert load_qrels_any(tmp_path / "qrels.json") == qrels
    assert load_qrels_any(tmp_path / "qrels.txt") == qrels
    assert load_run_any(tmp_path / "run.json.gz") == run
    assert load_run_any(str(tmp_path / "run.trec.gz")) == run


_ids = st.text(min_size=1, max_size=6)


@given(
    st.dictionaries(
        _ids,
        st.dictionaries(_ids, st.floats(allow_nan=False, allow_infinity=False), max_size=6),
        max_size=4,
    )
)
def test_property_json_run_round_trip(run: dict[str, dict[str, float]]) -> None:
    out = io.StringIO()
    dump_json(run, out)
    assert run_from_mapping(json.loads(out.getvalue())) == run
