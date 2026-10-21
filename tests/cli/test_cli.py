"""``groundtruth evaluate``, ``compare``, ``validate``, ``metrics`` and ``version``."""

import csv
import gzip
import io
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from groundtruth import __version__
from groundtruth.cli import app
from groundtruth.metrics import available_metrics

# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def test_evaluate_json_output(runner: CliRunner, qrels_file: Path, perfect_run: Path) -> None:
    """Scenario: JSON output."""
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(perfect_run), "--metric", "P@5", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["metrics"] == ["P@5"]
    assert data["aggregate"]["P@5"] == pytest.approx((2 / 5 + 1 / 5) / 2)
    assert "per_query" not in data
    assert data["num_queries"] == 2


def test_evaluate_json_per_query(runner: CliRunner, qrels_file: Path, perfect_run: Path) -> None:
    result = runner.invoke(
        app,
        ["evaluate", str(qrels_file), str(perfect_run), "-m", "P@1", "-f", "json", "--per-query"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["per_query"] == {"q1": {"P@1": 1.0}, "q2": {"P@1": 1.0}}


def test_evaluate_default_metrics_table(
    runner: CliRunner, qrels_file: Path, perfect_run: Path
) -> None:
    result = runner.invoke(app, ["evaluate", str(qrels_file), str(perfect_run)])
    assert result.exit_code == 0, result.output
    for label in ("nDCG@10", "P@10", "R@100", "AP", "RR"):
        assert label in result.stdout
    assert "Scores (2 queries)" in result.stdout
    assert "1.0000" in result.stdout


def test_evaluate_table_per_query(runner: CliRunner, qrels_file: Path, half_run: Path) -> None:
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(half_run), "-m", "nDCG@10", "--per-query"]
    )
    assert result.exit_code == 0, result.output
    assert "Per query" in result.stdout
    assert "q2" in result.stdout
    assert "0.5000" in result.stdout


def test_evaluate_metrics_may_be_comma_separated(
    runner: CliRunner, qrels_file: Path, perfect_run: Path
) -> None:
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(perfect_run), "-m", "P@1, MAP", "-f", "json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["metrics"] == ["P@1", "AP"]


def test_evaluate_markdown_output(runner: CliRunner, qrels_file: Path, perfect_run: Path) -> None:
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(perfect_run), "-m", "P@1", "-f", "markdown"]
    )
    assert result.exit_code == 0, result.output
    assert "| Metric | Score |" in result.stdout
    assert "| P@1 | 1.0000 |" in result.stdout


def test_evaluate_csv_output(runner: CliRunner, qrels_file: Path, perfect_run: Path) -> None:
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(perfect_run), "-m", "P@1", "-f", "csv"]
    )
    assert result.exit_code == 0, result.output
    rows = list(csv.reader(io.StringIO(result.stdout)))
    assert rows == [["query_id", "P@1"], ["q1", "1.0"], ["q2", "1.0"], ["all", "1.0"]]


def test_evaluate_writes_output_file(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, tmp_path: Path
) -> None:
    target = tmp_path / "report.json.gz"
    result = runner.invoke(
        app,
        [
            "evaluate",
            str(qrels_file),
            str(perfect_run),
            "-m",
            "P@1",
            "-f",
            "json",
            "-o",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    with gzip.open(target, "rt", encoding="utf-8") as handle:
        assert json.load(handle)["aggregate"] == {"P@1": 1.0}


def test_evaluate_writes_table_to_file(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, tmp_path: Path
) -> None:
    target = tmp_path / "report.txt"
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(perfect_run), "-m", "P@1", "-o", str(target)]
    )
    assert result.exit_code == 0, result.output
    text = target.read_text(encoding="utf-8")
    assert "P@1" in text
    assert "1.0000" in text
    assert "\x1b[" not in text


def test_evaluate_accepts_json_inputs(runner: CliRunner, tmp_path: Path) -> None:
    qrels = tmp_path / "qrels.json"
    run = tmp_path / "run.json"
    qrels.write_text(json.dumps({"q1": {"d1": 1}}), encoding="utf-8")
    run.write_text(json.dumps({"q1": {"d1": 1.0, "d2": 2.0}}), encoding="utf-8")
    result = runner.invoke(app, ["evaluate", str(qrels), str(run), "-m", "P@1", "-f", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["aggregate"]["P@1"] == 0.0


def test_evaluate_options_depth_missing_and_rel_level(
    runner: CliRunner, qrels_file: Path, half_run: Path
) -> None:
    base = ["evaluate", str(qrels_file), str(half_run), "-f", "json"]
    skip = runner.invoke(app, [*base, "-m", "P@1", "--missing", "skip"])
    assert json.loads(skip.stdout)["num_queries"] == 2
    graded = runner.invoke(app, [*base, "-m", "P@2", "--rel-level", "2", "--depth", "1"])
    assert graded.exit_code == 0, graded.output
    # Only d1 (grade 2) counts as relevant and only the top document is kept.
    assert json.loads(graded.stdout)["aggregate"]["P@2"] == pytest.approx(0.25)


def test_evaluate_legal_metrics_with_metadata(
    runner: CliRunner,
    qrels_file: Path,
    perfect_run: Path,
    corpus_file: Path,
    queries_file: Path,
) -> None:
    """Scenario: Legal metrics with metadata."""
    result = runner.invoke(
        app,
        [
            "evaluate",
            str(qrels_file),
            str(perfect_run),
            "--metric",
            "BadLaw@10",
            "--metric",
            "JurisdictionMatch@10",
            "--corpus",
            str(corpus_file),
            "--queries",
            str(queries_file),
            "--format",
            "json",
            "--per-query",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["per_query"]["q1"]["BadLaw@10"] == pytest.approx(1 / 3)
    assert data["per_query"]["q2"]["BadLaw@10"] == pytest.approx(1 / 2)
    assert data["aggregate"]["BadLaw@10"] == pytest.approx((1 / 3 + 1 / 2) / 2)
    # q1 targets US-FED: d1, d2 match; q2 targets US-CA: d4 matches.
    assert data["aggregate"]["JurisdictionMatch@10"] == pytest.approx((2 / 3 + 1 / 2) / 2)


def test_evaluate_legal_metric_without_corpus_is_an_input_error(
    runner: CliRunner, qrels_file: Path, perfect_run: Path
) -> None:
    result = runner.invoke(app, ["evaluate", str(qrels_file), str(perfect_run), "-m", "BadLaw@10"])
    assert result.exit_code == 2
    assert "BadLaw@10" in result.stderr
    assert "--corpus" in result.stderr


def test_evaluate_prints_warnings_to_stderr(runner: CliRunner, tmp_path: Path) -> None:
    qrels = tmp_path / "qrels.txt"
    qrels.write_text("q1 0 d1 1\nq2 0 d2 1\n", encoding="utf-8")
    run = tmp_path / "run.txt"
    run.write_text("q1 Q0 d1 1 1.0 t\nq9 Q0 d1 1 1.0 t\n", encoding="utf-8")
    result = runner.invoke(app, ["evaluate", str(qrels), str(run), "-m", "P@1"])
    assert result.exit_code == 0, result.output
    assert "warning:" in result.stderr
    assert "q9" in result.stderr
    assert "q2" in result.stderr
    as_csv = runner.invoke(app, ["evaluate", str(qrels), str(run), "-m", "P@1", "-f", "csv"])
    assert "warning:" in as_csv.stderr
    as_json = runner.invoke(app, ["evaluate", str(qrels), str(run), "-m", "P@1", "-f", "json"])
    assert as_json.stderr == ""
    assert len(json.loads(as_json.stdout)["warnings"]) == 2


# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------


def test_gate_fails(runner: CliRunner, qrels_file: Path, half_run: Path) -> None:
    """Scenario: Gate fails."""
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(half_run), "--fail-under", "nDCG@10=0.99"]
    )
    assert result.exit_code == 1
    assert "nDCG@10" in result.stderr
    assert "0.5000 is below the threshold 0.99" in result.stderr
    # The report is still printed.
    assert "Scores" in result.stdout


def test_gate_passes(runner: CliRunner, qrels_file: Path, half_run: Path) -> None:
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(half_run), "--fail-under", "nDCG@10=0.5"]
    )
    assert result.exit_code == 0, result.output
    assert "quality gate failed" not in result.stderr


def test_gate_metric_is_added_to_the_evaluation(
    runner: CliRunner, qrels_file: Path, perfect_run: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "evaluate",
            str(qrels_file),
            str(perfect_run),
            "-m",
            "P@1",
            "--fail-under",
            "ndcg@5=0.9",
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["metrics"] == ["P@1", "nDCG@5"]


def test_gate_respects_lower_is_better_metrics(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, corpus_file: Path
) -> None:
    args = ["evaluate", str(qrels_file), str(perfect_run), "--corpus", str(corpus_file)]
    failing = runner.invoke(app, [*args, "--fail-under", "BadLaw@10=0.1"])
    assert failing.exit_code == 1
    assert "BadLaw@10" in failing.stderr
    assert "above the threshold 0.1" in failing.stderr
    passing = runner.invoke(app, [*args, "--fail-under", "BadLaw@10=0.5"])
    assert passing.exit_code == 0, passing.output


def test_several_gates_report_every_failure(
    runner: CliRunner, qrels_file: Path, half_run: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "evaluate",
            str(qrels_file),
            str(half_run),
            "--fail-under",
            "nDCG@10=0.9",
            "--fail-under",
            "P@1=0.9",
            "--fail-under",
            "R@100=0.1",
        ],
    )
    assert result.exit_code == 1
    assert result.stderr.count("quality gate failed") == 2


@pytest.mark.parametrize(
    ("gate", "message"),
    [
        ("nDCG@10", "METRIC=VALUE"),
        ("=0.5", "METRIC=VALUE"),
        ("nDCG@10=", "METRIC=VALUE"),
        ("nDCG@10=high", "finite number"),
        ("nDCG@10=nan", "finite number"),
        ("foo=0.5", "unknown metric 'foo'"),
    ],
)
def test_invalid_gate_is_an_input_error(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, gate: str, message: str
) -> None:
    result = runner.invoke(
        app, ["evaluate", str(qrels_file), str(perfect_run), "--fail-under", gate]
    )
    assert result.exit_code == 2
    assert message in result.stderr


# ---------------------------------------------------------------------------
# Input errors
# ---------------------------------------------------------------------------


def test_malformed_run(runner: CliRunner, qrels_file: Path, tmp_path: Path) -> None:
    """Scenario: Malformed run."""
    run = tmp_path / "broken.run"
    run.write_text("q1 Q0 d1 1 1.0 tag\nq1 Q0 d2 2 not-a-score tag\n", encoding="utf-8")
    result = runner.invoke(app, ["evaluate", str(qrels_file), str(run)])
    assert result.exit_code == 2
    assert "line 2" in result.stderr
    assert result.stderr.startswith("error: ")
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.output


def test_missing_file_is_an_input_error(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(tmp_path / "nope.txt"), str(tmp_path / "x")])
    assert result.exit_code == 2
    assert "nope.txt" in result.stderr
    assert "No such file" in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1


def test_directory_is_an_input_error(runner: CliRunner, tmp_path: Path, perfect_run: Path) -> None:
    result = runner.invoke(app, ["evaluate", str(tmp_path), str(perfect_run)])
    assert result.exit_code == 2
    assert result.stderr.startswith("error: ")


def test_unknown_metric_is_an_input_error(
    runner: CliRunner, qrels_file: Path, perfect_run: Path
) -> None:
    result = runner.invoke(app, ["evaluate", str(qrels_file), str(perfect_run), "-m", "foo"])
    assert result.exit_code == 2
    assert "unknown metric 'foo'" in result.stderr


def test_empty_metric_list_is_an_input_error(
    runner: CliRunner, qrels_file: Path, perfect_run: Path
) -> None:
    result = runner.invoke(app, ["evaluate", str(qrels_file), str(perfect_run), "-m", " , "])
    assert result.exit_code == 2
    assert "at least one metric" in result.stderr


def test_usage_error_exits_2(runner: CliRunner) -> None:
    result = runner.invoke(app, ["evaluate"])
    assert result.exit_code == 2


def test_no_arguments_shows_help(runner: CliRunner) -> None:
    result = runner.invoke(app, [])
    assert "evaluate" in result.output
    assert "benchmark" in result.output


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def test_two_runs(runner: CliRunner, qrels_file: Path, perfect_run: Path, half_run: Path) -> None:
    """Scenario: Two runs."""
    result = runner.invoke(
        app,
        ["compare", str(qrels_file), str(half_run), str(perfect_run), "--metric", "nDCG@10"],
    )
    assert result.exit_code == 0, result.output
    rows = [line for line in result.stdout.splitlines() if "half" in line and "perfect" in line]
    assert len(rows) == 1
    row = rows[0]
    assert "nDCG@10" in row
    assert "+0.5000" in row
    assert "no" in row.split()[-2:] or row.rstrip(" │").endswith("no")


def test_compare_json_matches_the_api_shape(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, half_run: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "compare",
            str(qrels_file),
            str(half_run),
            str(perfect_run),
            "-m",
            "nDCG@10",
            "-m",
            "P@1",
            "--test",
            "ttest",
            "--alpha",
            "0.1",
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert set(data) == {
        "systems",
        "metrics",
        "aggregate",
        "num_queries",
        "comparisons",
        "warnings",
    }
    assert data["systems"] == ["half", "perfect"]
    assert data["aggregate"]["perfect"]["nDCG@10"] == 1.0
    assert [c["metric"] for c in data["comparisons"]] == ["nDCG@10", "P@1"]
    first = data["comparisons"][0]
    assert first["test"] == "ttest"
    assert first["alpha"] == 0.1
    assert first["delta"] == pytest.approx(0.5)
    assert first["p_value_corrected"] == first["p_value"]


def test_compare_three_runs_is_holm_corrected(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, half_run: Path, tmp_path: Path
) -> None:
    third = tmp_path / "third.run"
    third.write_text("q1 Q0 d3 1 1.0 t\nq2 Q0 d5 1 1.0 t\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "compare",
            str(qrels_file),
            str(perfect_run),
            str(half_run),
            str(third),
            "-m",
            "nDCG@10",
            "--resamples",
            "200",
            "--seed",
            "7",
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    comparisons = json.loads(result.stdout)["comparisons"]
    assert [(c["system_a"], c["system_b"]) for c in comparisons] == [
        ("perfect", "half"),
        ("perfect", "third"),
        ("half", "third"),
    ]
    assert all(c["p_value_corrected"] >= c["p_value"] for c in comparisons)


def test_compare_names_markdown_and_csv(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, half_run: Path
) -> None:
    base = ["compare", str(qrels_file), str(half_run), str(perfect_run), "-m", "P@1"]
    names = ["--name", "baseline", "--name", "candidate"]
    markdown = runner.invoke(app, [*base, *names, "-f", "markdown"])
    assert markdown.exit_code == 0, markdown.output
    assert "| System | P@1 |" in markdown.stdout
    assert "| baseline | candidate | P@1 |" in markdown.stdout
    as_csv = runner.invoke(app, [*base, *names, "-f", "csv"])
    rows = list(csv.DictReader(io.StringIO(as_csv.stdout)))
    assert len(rows) == 1
    assert rows[0]["system_a"] == "baseline"
    assert rows[0]["system_b"] == "candidate"
    assert rows[0]["significant"] in {"True", "False"}


def test_compare_default_names_are_unique(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, tmp_path: Path
) -> None:
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    twin = other_dir / perfect_run.name
    twin.write_text(perfect_run.read_text(encoding="utf-8"), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "compare",
            str(qrels_file),
            str(perfect_run),
            str(twin),
            str(perfect_run),
            str(perfect_run),
            "-m",
            "P@1",
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["systems"] == [
        "perfect",
        str(twin),
        str(perfect_run),
        f"{perfect_run}#2",
    ]


def test_compare_warnings_name_the_system(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, tmp_path: Path
) -> None:
    partial = tmp_path / "partial.run"
    partial.write_text("q1 Q0 d1 1 1.0 t\n", encoding="utf-8")
    result = runner.invoke(
        app, ["compare", str(qrels_file), str(perfect_run), str(partial), "-m", "P@1"]
    )
    assert result.exit_code == 0, result.output
    assert "warning: partial: 1 judged query is missing from the run" in result.stderr


def test_compare_writes_output_file(
    runner: CliRunner, qrels_file: Path, perfect_run: Path, half_run: Path, tmp_path: Path
) -> None:
    target = tmp_path / "compare.txt"
    result = runner.invoke(
        app,
        [
            "compare",
            str(qrels_file),
            str(perfect_run),
            str(half_run),
            "-m",
            "P@1",
            "-o",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Significance" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--name", "only-one"], "one per run"),
        (["--name", "x", "--name", "x"], "unique"),
        (["--alpha", "1.5"], "alpha"),
        (["-m", "BadLaw@10"], "--corpus"),
    ],
)
def test_compare_invalid_options(
    runner: CliRunner,
    qrels_file: Path,
    perfect_run: Path,
    half_run: Path,
    extra: list[str],
    message: str,
) -> None:
    result = runner.invoke(
        app, ["compare", str(qrels_file), str(perfect_run), str(half_run), *extra]
    )
    assert result.exit_code == 2
    assert message in result.stderr


def test_compare_needs_two_runs(runner: CliRunner, qrels_file: Path, perfect_run: Path) -> None:
    result = runner.invoke(app, ["compare", str(qrels_file), str(perfect_run)])
    assert result.exit_code == 2
    assert "at least two runs" in result.stderr


def test_compare_legal_metrics(
    runner: CliRunner,
    qrels_file: Path,
    perfect_run: Path,
    half_run: Path,
    corpus_file: Path,
    queries_file: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "compare",
            str(qrels_file),
            str(perfect_run),
            str(half_run),
            "-m",
            "BadLaw@10",
            "--corpus",
            str(corpus_file),
            "--queries",
            str(queries_file),
            "--missing",
            "skip",
            "--depth",
            "10",
            "--rel-level",
            "1",
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    aggregate = json.loads(result.stdout)["aggregate"]
    assert aggregate["half"]["BadLaw@10"] == pytest.approx((1 / 3 + 0.0) / 2)


# ---------------------------------------------------------------------------
# validate, metrics, version
# ---------------------------------------------------------------------------


def test_validate_files(runner: CliRunner, qrels_file: Path, half_run: Path) -> None:
    """Scenario: Validate files."""
    result = runner.invoke(app, ["validate", str(qrels_file), str(half_run)])
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "queries" in out
    assert "judgments" in out
    lines = {" ".join(line.replace("│", " ").split()) for line in out.splitlines()}
    assert "qrels queries 2" in lines
    assert "qrels judgments 5" in lines
    assert "qrels relevant 3" in lines
    assert "run entries 4" in lines


def test_validate_json_with_corpus_and_queries(
    runner: CliRunner, qrels_file: Path, tmp_path: Path, corpus_file: Path, queries_file: Path
) -> None:
    run = tmp_path / "partial.run"
    run.write_text("q1 Q0 d1 1 1.0 t\nq7 Q0 d1 1 1.0 t\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "validate",
            str(qrels_file),
            str(run),
            "--corpus",
            str(corpus_file),
            "--queries",
            str(queries_file),
            "-f",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert data["summary"]["run"] == {
        "queries": 2,
        "entries": 2,
        "judged_queries": 1,
        "unjudged_queries": 1,
        "missing_queries": 1,
    }
    assert data["summary"]["corpus"] == {"documents": 5}
    assert data["summary"]["queries"] == {"queries": 2}
    assert len(data["notes"]) == 2


def test_validate_table_prints_notes(runner: CliRunner, qrels_file: Path, tmp_path: Path) -> None:
    run = tmp_path / "partial.run"
    run.write_text("q1 Q0 d1 1 1.0 t\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(qrels_file), str(run)])
    assert result.exit_code == 0, result.output
    assert "missing from the run" in result.stderr


def test_validate_qrels_only(runner: CliRunner, qrels_file: Path) -> None:
    result = runner.invoke(app, ["validate", str(qrels_file), "-f", "json"])
    assert result.exit_code == 0, result.output
    assert set(json.loads(result.stdout)["summary"]) == {"qrels"}


def test_validate_rejects_malformed_qrels(runner: CliRunner, tmp_path: Path) -> None:
    qrels = tmp_path / "bad.qrels"
    qrels.write_text("q1 0 d1\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(qrels)])
    assert result.exit_code == 2
    assert "line 1" in result.stderr


def test_metrics_lists_every_family(runner: CliRunner) -> None:
    result = runner.invoke(app, ["metrics"])
    assert result.exit_code == 0, result.output
    for info in available_metrics():
        assert info.name in result.stdout


def test_metrics_json(runner: CliRunner) -> None:
    result = runner.invoke(app, ["metrics", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = {entry["name"]: entry for entry in json.loads(result.stdout)}
    assert data["BadLaw"]["higher_is_better"] is False
    assert data["BadLaw"]["requires_metadata"] is True
    assert data["BadLaw"]["cutoff"] == "required"
    assert "MAP" in data["AP"]["aliases"]


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"groundtruth {__version__}"
