"""``groundtruth retrieve``, ``benchmark`` and ``serve``."""

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from groundtruth.cli import app
from groundtruth.io import load_run, load_run_json

from .conftest import SAMPLE

CORPUS = SAMPLE / "corpus.jsonl"
QUERIES = SAMPLE / "queries.jsonl"
QRELS = SAMPLE / "qrels.txt"


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


def test_retrieve_writes_trec_run_to_stdout(runner: CliRunner) -> None:
    result = runner.invoke(app, ["retrieve", str(CORPUS), str(QUERIES), "--depth", "3"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert len(lines) == 8 * 3
    first = lines[0].split()
    assert first[0] == "Q01"
    assert first[1] == "Q0"
    assert first[3] == "1"
    assert first[5] == "bm25"


def test_retrieve_writes_run_file(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "tfidf.run"
    result = runner.invoke(
        app,
        [
            "retrieve",
            str(CORPUS),
            str(QUERIES),
            "-r",
            "tfidf",
            "-k",
            "5",
            "-o",
            str(target),
            "--tag",
            "exp1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    run = load_run(target)
    assert len(run) == 8
    assert all(len(docs) <= 5 for docs in run.values())
    assert target.read_text(encoding="utf-8").split("\n", 1)[0].endswith(" exp1")


def test_retrieve_json_output_and_jurisdiction_filter(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "run.json"
    result = runner.invoke(
        app,
        ["retrieve", str(CORPUS), str(QUERIES), "-o", str(target), "--jurisdiction-filter"],
    )
    assert result.exit_code == 0, result.output
    run = load_run_json(target)
    corpus = {
        doc["doc_id"]: doc["jurisdiction"]
        for doc in map(json.loads, CORPUS.read_text(encoding="utf-8").splitlines())
    }
    queries = {
        q["query_id"]: {q["jurisdiction"], *q.get("binding_jurisdictions", [])}
        for q in map(json.loads, QUERIES.read_text(encoding="utf-8").splitlines())
    }
    for query_id, docs in run.items():
        assert docs, query_id
        assert {corpus[doc_id] for doc_id in docs} <= queries[query_id]


def test_retrieve_unknown_retriever(runner: CliRunner) -> None:
    result = runner.invoke(app, ["retrieve", str(CORPUS), str(QUERIES), "-r", "nope"])
    assert result.exit_code == 2
    assert "unknown retriever 'nope'" in result.stderr


def test_retrieve_malformed_corpus(runner: CliRunner, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"doc_id": "a", "text": "x"}\n{not json}\n', encoding="utf-8")
    result = runner.invoke(app, ["retrieve", str(corpus), str(QUERIES)])
    assert result.exit_code == 2
    assert ":2:" in result.stderr


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------


def test_benchmark_sample_data(runner: CliRunner) -> None:
    """Scenario: Benchmark sample data (end to end on data/sample)."""
    result = runner.invoke(
        app,
        [
            "benchmark",
            str(CORPUS),
            str(QUERIES),
            str(QRELS),
            "--retriever",
            "bm25",
            "--retriever",
            "tfidf",
        ],
    )
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "Scores" in out
    score_rows = [line for line in out.splitlines() if line.startswith(("│ bm25", "│ tfidf"))]
    assert len(score_rows) == 2
    assert "Significance against bm25" in out
    assert "│ nDCG@10" in out


def test_benchmark_json_reports_scores_and_significance(runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        [
            "benchmark",
            str(CORPUS),
            str(QUERIES),
            str(QRELS),
            "-r",
            "bm25",
            "-r",
            "tfidf",
            "-r",
            "bm25-citation",
            "-m",
            "nDCG@10",
            "-m",
            "BadLaw@10",
            "-m",
            "JurisdictionMatch@10",
            "--resamples",
            "500",
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["systems"] == ["bm25", "tfidf", "bm25-citation"]
    assert data["baseline"] == "bm25"
    assert data["metrics"] == ["nDCG@10", "BadLaw@10", "JurisdictionMatch@10"]
    for scores in data["aggregate"].values():
        assert 0.0 <= scores["nDCG@10"] <= 1.0
        assert 0.0 <= scores["BadLaw@10"] <= 1.0
    assert data["num_queries"] == {"bm25": 8, "tfidf": 8, "bm25-citation": 8}
    pairs = [(c["metric"], c["system_a"], c["system_b"]) for c in data["comparisons"]]
    assert pairs == [
        (metric, "bm25", other)
        for metric in data["metrics"]
        for other in ("tfidf", "bm25-citation")
    ]
    assert all(c["p_value_corrected"] >= c["p_value"] for c in data["comparisons"])


def test_benchmark_single_retriever_has_no_comparisons(runner: CliRunner, tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    result = runner.invoke(
        app,
        [
            "benchmark",
            str(CORPUS),
            str(QUERIES),
            str(QRELS),
            "-m",
            "P@5",
            "--depth",
            "20",
            "--jurisdiction-filter",
            "--runs-dir",
            str(runs_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Significance" not in result.stdout
    run = load_run(runs_dir / "bm25.run")
    assert len(run) == 8
    assert all(len(docs) <= 20 for docs in run.values())


def test_benchmark_markdown_and_csv(runner: CliRunner) -> None:
    base = ["benchmark", str(CORPUS), str(QUERIES), str(QRELS), "-r", "bm25", "-r", "tfidf"]
    markdown = runner.invoke(app, [*base, "-m", "P@5", "-f", "markdown", "--resamples", "100"])
    assert markdown.exit_code == 0, markdown.output
    assert "| System | P@5 |" in markdown.stdout
    assert "| bm25 | tfidf | P@5 |" in markdown.stdout
    as_csv = runner.invoke(app, [*base, "-m", "P@5", "-f", "csv", "--resamples", "100"])
    assert as_csv.exit_code == 0, as_csv.output
    rows = list(csv.DictReader(io.StringIO(as_csv.stdout)))
    assert [(row["system_a"], row["system_b"]) for row in rows] == [("bm25", "tfidf")]


def test_benchmark_duplicate_retriever(runner: CliRunner) -> None:
    result = runner.invoke(
        app, ["benchmark", str(CORPUS), str(QUERIES), str(QRELS), "-r", "bm25", "-r", "BM25"]
    )
    assert result.exit_code == 2
    assert "only once" in result.stderr


def test_benchmark_missing_qrels(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(app, ["benchmark", str(CORPUS), str(QUERIES), str(tmp_path / "q")])
    assert result.exit_code == 2
    assert "No such file" in result.stderr


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    import uvicorn

    calls: list[dict[str, Any]] = []

    def fake_run(app: str, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(uvicorn, "run", fake_run)
    # serve exports settings for its workers via os.environ. Setting every
    # variable here (empty means unset) makes monkeypatch restore them afterwards.
    for name in ("CORPUS_PATH", "RETRIEVER", "LOG_LEVEL"):
        monkeypatch.setenv(f"GROUNDTRUTH_{name}", "")
    monkeypatch.setenv("GROUNDTRUTH_LOG_JSON", "false")
    return calls


def test_serve_runs_the_app_factory(runner: CliRunner, uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert uvicorn_calls == [
        {
            "app": "groundtruth.api.app:create_app",
            "factory": True,
            "host": "127.0.0.1",
            "port": 8000,
            "workers": 1,
            "reload": False,
            "log_config": None,
        }
    ]


def test_serve_options_and_corpus(runner: CliRunner, uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(
        app,
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--workers",
            "3",
            "--corpus",
            str(CORPUS),
            "--retriever",
            "tfidf",
        ],
    )
    assert result.exit_code == 0, result.output
    call = uvicorn_calls[0]
    assert (call["host"], call["port"], call["workers"]) == ("0.0.0.0", 9000, 3)
    assert os.environ["GROUNDTRUTH_CORPUS_PATH"] == str(CORPUS.resolve())
    assert os.environ["GROUNDTRUTH_RETRIEVER"] == "tfidf"


def test_serve_reload_with_workers_is_rejected(
    runner: CliRunner, uvicorn_calls: list[dict[str, Any]]
) -> None:
    result = runner.invoke(app, ["serve", "--reload", "--workers", "2"])
    assert result.exit_code == 2
    assert "--reload" in result.stderr
    assert uvicorn_calls == []


def test_serve_reload(runner: CliRunner, uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ["serve", "--reload"])
    assert result.exit_code == 0, result.output
    assert uvicorn_calls[0]["reload"] is True


def test_serve_missing_corpus(
    runner: CliRunner, uvicorn_calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    result = runner.invoke(app, ["serve", "--corpus", str(tmp_path / "missing.jsonl")])
    assert result.exit_code == 2
    assert "corpus file not found" in result.stderr
    assert uvicorn_calls == []


def test_serve_invalid_settings(
    runner: CliRunner, uvicorn_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROUNDTRUTH_RETRIEVER", "nope")
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 2
    assert "invalid setting retriever" in result.stderr
    assert uvicorn_calls == []


def test_benchmark_single_retriever_markdown(runner: CliRunner) -> None:
    result = runner.invoke(
        app, ["benchmark", str(CORPUS), str(QUERIES), str(QRELS), "-m", "P@5", "-f", "markdown"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("| System | P@5 |")
    assert "System A" not in result.stdout


def test_p_value_formatting() -> None:
    from groundtruth.cli import _fmt_p

    assert _fmt_p(None) == "-"
    assert _fmt_p(0.00001) == "<0.0001"
    assert _fmt_p(0.25) == "0.2500"
