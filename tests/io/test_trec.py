"""Tests for TREC qrels/run parsing and writing (spec: relevance-data)."""

import gzip
import io
import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from groundtruth.errors import FormatError
from groundtruth.io import (
    dump_qrels,
    dump_run,
    load_qrels,
    load_run,
    open_text,
    parse_qrels,
    parse_run,
)
from groundtruth.ranking import rank_documents

# --- Requirement: Parse TREC qrels -------------------------------------------------


def test_valid_qrels_file(tmp_path: Path) -> None:
    path = tmp_path / "qrels.txt"
    path.write_text("q1 0 d1 2\nq1 0 d2 0\n", encoding="utf-8")
    assert load_qrels(path) == {"q1": {"d1": 2, "d2": 0}}


def test_negative_grade() -> None:
    assert parse_qrels(["q1 0 d1 -1"]) == {"q1": {"d1": 0}}


def test_qrels_accepts_any_whitespace_comments_and_blank_lines() -> None:
    text = "# header comment\n\nq1\t0  d1\t3\r\n   \nq2 Q0 d7 1\n"
    assert parse_qrels(text) == {"q1": {"d1": 3}, "q2": {"d7": 1}}


def test_qrels_identical_duplicate_is_accepted() -> None:
    assert parse_qrels(["q1 0 d1 2", "q1 0 d1 2"]) == {"q1": {"d1": 2}}


def test_qrels_conflicting_duplicate_is_rejected_with_line() -> None:
    with pytest.raises(FormatError, match=r"line 2: conflicting judgment.*'q1'.*'d1'"):
        parse_qrels(["q1 0 d1 2", "q1 0 d1 1"], source="qrels.txt")


@pytest.mark.parametrize("token", ["1.5", "high", "1_0", "", "0x1"])
def test_qrels_non_integer_relevance_is_rejected(token: str) -> None:
    line = f"q1 0 d1 {token}".strip()
    with pytest.raises(FormatError, match="line 1"):
        parse_qrels([line])


def test_qrels_wrong_column_count() -> None:
    with pytest.raises(FormatError, match=r"qrels\.txt, line 2: expected 4 columns.*found 3"):
        parse_qrels(["q1 0 d1 1", "q1 d2 1"], source="qrels.txt")


# --- Requirement: Parse TREC runs --------------------------------------------------


def test_score_defines_order() -> None:
    run = parse_run(["q1 Q0 d1 1 1.0 tag", "q1 Q0 d2 2 5.0 tag"])
    assert rank_documents(run["q1"]) == ["d2", "d1"]


def test_duplicate_document() -> None:
    run = parse_run(["q1 Q0 d1 1 1.0 t", "q1 Q0 d1 2 3.0 t", "q1 Q0 d1 3 2.0 t"])
    assert run == {"q1": {"d1": 3.0}}


def test_run_parses_scientific_and_negative_scores() -> None:
    run = parse_run("q1 Q0 a 1 -1.5e-3 t\nq1 Q0 b 2 7 t\n")
    assert run == {"q1": {"a": -0.0015, "b": 7.0}}


# --- Requirement: Report malformed input precisely ---------------------------------


def test_wrong_column_count(tmp_path: Path) -> None:
    path = tmp_path / "run.txt"
    path.write_text("q1 Q0 d1 1 2.0 t\nq1 Q0 d2 2 1.0 t\nq1 Q0 d3 3 0.5\n", encoding="utf-8")
    with pytest.raises(FormatError, match=r"run\.txt, line 3: expected 6 columns.*found 5"):
        load_run(path)


@pytest.mark.parametrize("token", ["high", "nan", "inf", "-inf", "1_000"])
def test_non_numeric_score(token: str) -> None:
    with pytest.raises(FormatError, match=r"run, line 2: score must be a finite number"):
        parse_run(["q1 Q0 d1 1 1.0 t", f"q1 Q0 d2 2 {token} t"], source="run")


def test_line_numbers_count_comments_and_blank_lines() -> None:
    with pytest.raises(FormatError, match="line 4"):
        parse_qrels(["# comment", "", "q1 0 d1 1", "q1 0 d2"])


def test_malformed_input_returns_no_partial_data() -> None:
    parsed = None
    with pytest.raises(FormatError):
        parsed = parse_run(["q1 Q0 d1 1 1.0 t", "broken"])
    assert parsed is None


def test_invalid_utf8_is_a_format_error(tmp_path: Path) -> None:
    path = tmp_path / "run.txt"
    path.write_bytes(b"q1 Q0 d\xff 1 1.0 t\n")
    with pytest.raises(FormatError, match=r"run\.txt: cannot read file"):
        load_run(path)


def test_corrupt_gzip_is_a_format_error(tmp_path: Path) -> None:
    path = tmp_path / "qrels.txt.gz"
    path.write_bytes(b"this is not gzip data")
    with pytest.raises(FormatError, match="cannot read file"):
        load_qrels(path)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_run(tmp_path / "absent.txt")


# --- gzip and byte-order marks -----------------------------------------------------


def test_gzip_files_are_read_transparently(tmp_path: Path) -> None:
    path = tmp_path / "qrels.txt.GZ"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("q1 0 d1 1\n")
    assert load_qrels(path) == {"q1": {"d1": 1}}


def test_utf8_byte_order_mark_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "run.txt"
    path.write_bytes("﻿q1 Q0 d1 1 1.0 t\n".encode())
    assert load_run(path) == {"q1": {"d1": 1.0}}


def test_open_text_writes_gzip(tmp_path: Path) -> None:
    path = tmp_path / "out.gz"
    with open_text(path, "w") as handle:
        handle.write("hello\n")
    assert gzip.decompress(path.read_bytes()) == b"hello\n"


# --- Requirement: Write TREC runs --------------------------------------------------


def test_written_run_re_reads_identically(tmp_path: Path) -> None:
    run = {"q2": {"a": 1.0, "c": 1.0, "b": 0.1 + 0.2}, "q1": {"x": -3.25e-7}}
    path = tmp_path / "run.txt.gz"
    dump_run(run, path, tag="bm25")
    reread = load_run(path)
    assert reread == run
    for query_id, scores in run.items():
        assert rank_documents(reread[query_id]) == rank_documents(scores)


def test_dump_run_format_ranks_from_one_with_tie_break() -> None:
    out = io.StringIO()
    dump_run({"q1": {"a": 1.0, "c": 1.0, "b": 2.0}}, out, tag="mytag")
    assert out.getvalue().splitlines() == [
        "q1 Q0 b 1 2.0 mytag",
        "q1 Q0 c 2 1.0 mytag",
        "q1 Q0 a 3 1.0 mytag",
    ]


def test_dump_run_default_tag() -> None:
    out = io.StringIO()
    dump_run({"q1": {"d": 1}}, out)
    assert out.getvalue() == "q1 Q0 d 1 1.0 groundtruth\n"


@pytest.mark.parametrize(
    ("run", "tag", "message"),
    [
        ({"q1": {"d1": 1.0}}, "bad tag", "run tag"),
        ({"q 1": {"d1": 1.0}}, "t", "query id"),
        ({"q1": {"": 1.0}}, "t", "document id"),
        ({"q1": {"d1": math.nan}}, "t", "non-finite score"),
    ],
)
def test_dump_run_rejects_unrepresentable_values(
    run: dict[str, dict[str, float]], tag: str, message: str
) -> None:
    with pytest.raises(FormatError, match=message):
        dump_run(run, io.StringIO(), tag=tag)


def test_qrels_round_trip(tmp_path: Path) -> None:
    qrels = {"q2": {"b": 0, "a": 3}, "q1": {"z": 1}}
    path = tmp_path / "qrels.txt"
    dump_qrels(qrels, path)
    assert path.read_text(encoding="utf-8") == "q1 0 z 1\nq2 0 a 3\nq2 0 b 0\n"
    assert load_qrels(path) == qrels


def test_dump_qrels_rejects_whitespace_ids() -> None:
    with pytest.raises(FormatError, match="document id"):
        dump_qrels({"q1": {"d 1": 1}}, io.StringIO())


_ids = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.:/", min_size=1, max_size=8)
_scores = st.floats(allow_nan=False, allow_infinity=False, width=64)


@given(st.dictionaries(_ids, st.dictionaries(_ids, _scores, max_size=8), max_size=5))
def test_property_run_round_trip_preserves_scores_and_rankings(
    run: dict[str, dict[str, float]],
) -> None:
    out = io.StringIO()
    dump_run(run, out)
    reread = parse_run(out.getvalue())
    expected = {q: docs for q, docs in run.items() if docs}
    assert reread == expected
    for query_id, scores in expected.items():
        assert rank_documents(reread[query_id]) == rank_documents(scores)


@given(
    st.dictionaries(
        _ids, st.dictionaries(_ids, st.integers(min_value=0, max_value=10), max_size=8), max_size=5
    )
)
def test_property_qrels_round_trip(qrels: dict[str, dict[str, int]]) -> None:
    out = io.StringIO()
    dump_qrels(qrels, out)
    assert parse_qrels(out.getvalue()) == {q: docs for q, docs in qrels.items() if docs}
