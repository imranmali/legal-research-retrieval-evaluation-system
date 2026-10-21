"""Small qrels, runs and a legal corpus written to temporary files for CLI tests."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"

QRELS = """\
q1 0 d1 2
q1 0 d2 1
q1 0 d3 0
q2 0 d4 1
q2 0 d5 0
"""

#: Ranks every relevant document first: nDCG@10 = P@1 = 1.0.
PERFECT_RUN = """\
q1 Q0 d1 1 3.0 perfect
q1 Q0 d2 2 2.0 perfect
q1 Q0 d3 3 1.0 perfect
q2 Q0 d4 1 2.0 perfect
q2 Q0 d5 2 1.0 perfect
"""

#: Perfect on q1, retrieves nothing relevant for q2: nDCG@10 = 0.5.
HALF_RUN = """\
q1 Q0 d1 1 3.0 half
q1 Q0 d2 2 2.0 half
q1 Q0 d3 3 1.0 half
q2 Q0 d5 1 1.0 half
"""

#: Precedential statuses: q1's top 3 hold one overruled case (1/3),
#: q2's top 2 one superseded statute (1/2), so BadLaw@10 = (1/3 + 1/2) / 2.
CORPUS = [
    {"doc_id": "d1", "text": "a", "status": "overruled", "jurisdiction": "US-FED"},
    {"doc_id": "d2", "text": "b", "status": "good_law", "jurisdiction": "US-FED"},
    {"doc_id": "d3", "text": "c", "status": "good_law", "jurisdiction": "US-CA"},
    {"doc_id": "d4", "text": "d", "status": "superseded", "jurisdiction": "US-CA"},
    {"doc_id": "d5", "text": "e", "status": "good_law", "jurisdiction": "US-NY"},
]
QUERIES = [
    {"query_id": "q1", "text": "first", "jurisdiction": "US-FED"},
    {"query_id": "q2", "text": "second", "jurisdiction": "US-CA"},
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture
def qrels_file(tmp_path: Path) -> Path:
    path = tmp_path / "qrels.txt"
    path.write_text(QRELS, encoding="utf-8")
    return path


@pytest.fixture
def perfect_run(tmp_path: Path) -> Path:
    path = tmp_path / "perfect.run"
    path.write_text(PERFECT_RUN, encoding="utf-8")
    return path


@pytest.fixture
def half_run(tmp_path: Path) -> Path:
    path = tmp_path / "half.run"
    path.write_text(HALF_RUN, encoding="utf-8")
    return path


@pytest.fixture
def corpus_file(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.jsonl"
    path.write_text("".join(json.dumps(doc) + "\n" for doc in CORPUS), encoding="utf-8")
    return path


@pytest.fixture
def queries_file(tmp_path: Path) -> Path:
    path = tmp_path / "queries.jsonl"
    path.write_text("".join(json.dumps(q) + "\n" for q in QUERIES), encoding="utf-8")
    return path
