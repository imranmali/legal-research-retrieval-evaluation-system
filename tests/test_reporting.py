"""Tests for report rendering (spec: evaluation-engine, Report rendering)."""

import csv
import io
import json

import pytest

from groundtruth.evaluation import EvaluationResult, evaluate
from groundtruth.reporting import comparisons_to_markdown, to_csv, to_json, to_markdown
from groundtruth.stats import PairedComparison


@pytest.fixture
def result() -> EvaluationResult:
    qrels = {"q2": {"d1": 1}, "q1": {"d1": 2, "d2": 1}, "q|3": {"d9": 1}}
    run = {"q1": {"d1": 3.0, "x": 2.0, "d2": 1.0}, "q2": {"x": 1.0, "d1": 0.5}, "q9": {"d": 1.0}}
    return evaluate(qrels, run, ["nDCG@10", "P@2"])


def test_json_report_contains_everything(result: EvaluationResult) -> None:
    data = json.loads(to_json(result))
    assert data["metrics"] == ["nDCG@10", "P@2"]
    assert data["num_queries"] == 3
    assert data["aggregate"] == result.aggregate
    assert data["per_query"] == result.per_query
    assert len(data["warnings"]) == 2
    assert EvaluationResult.model_validate(data) == result


def test_json_report_keeps_full_precision(result: EvaluationResult) -> None:
    data = json.loads(to_json(result, indent=None))
    assert data["aggregate"]["nDCG@10"] == result.aggregate["nDCG@10"]


def test_json_report_without_per_query(result: EvaluationResult) -> None:
    data = json.loads(to_json(result, per_query=False))
    assert "per_query" not in data
    assert data["num_queries"] == 3


def test_csv_aggregate_row(result: EvaluationResult) -> None:
    rows = list(csv.reader(io.StringIO(to_csv(result))))
    assert rows[0] == ["query_id", "nDCG@10", "P@2"]
    assert [row[0] for row in rows[1:]] == ["q1", "q2", "q|3", "all"]
    last = rows[-1]
    assert last[0] == "all"
    assert float(last[1]) == result.aggregate["nDCG@10"]
    assert float(last[2]) == result.aggregate["P@2"]
    assert float(rows[1][1]) == result.per_query["q1"]["nDCG@10"]


def test_markdown_aggregate_table(result: EvaluationResult) -> None:
    text = to_markdown(result)
    assert "**Queries evaluated:** 3" in text
    assert "| Metric | Score |" in text
    assert f"| P@2 | {result.aggregate['P@2']:.4f} |" in text
    assert "| Query |" not in text
    assert "**Warnings:**" in text
    assert "- 1 run query has no relevance judgments and was ignored: q9" in text


def test_markdown_per_query_table_escapes_pipes(result: EvaluationResult) -> None:
    text = to_markdown(result, per_query=True)
    assert "| Query | nDCG@10 | P@2 |" in text
    assert "| q\\|3 | 0.0000 | 0.0000 |" in text
    q1 = result.per_query["q1"]
    assert f"| q1 | {q1['nDCG@10']:.4f} | 0.5000 |" in text


def test_markdown_without_warnings() -> None:
    plain = evaluate({"q1": {"d1": 1}}, {"q1": {"d1": 1.0}}, ["RR"])
    assert "Warnings" not in to_markdown(plain)
    assert to_markdown(plain).endswith("| RR | 1.0000 |\n")


def _comparison(**overrides: object) -> PairedComparison:
    fields: dict[str, object] = {
        "system_a": "bm25",
        "system_b": "dense",
        "metric": "nDCG@10",
        "test": "permutation",
        "mean_a": 0.41234,
        "mean_b": 0.5,
        "delta": 0.08766,
        "p_value": 0.00004,
        "ci_low": 0.01,
        "ci_high": 0.15,
        "num_queries": 30,
        "alpha": 0.05,
        "significant": True,
    }
    fields.update(overrides)
    return PairedComparison.model_validate(fields)


def test_comparisons_to_markdown() -> None:
    text = comparisons_to_markdown(
        [
            _comparison(),
            _comparison(system_b="hybrid", delta=-0.0123, p_value=0.2, significant=False),
        ]
    )
    lines = text.strip().splitlines()
    assert lines[0].startswith("| System A | System B | Metric | Test | Queries |")
    assert lines[1].startswith("| --- | --- | --- | --- | ---: |")
    assert lines[2] == (
        "| bm25 | dense | nDCG@10 | permutation | 30 | 0.4123 | 0.5000 | +0.0877 "
        "| [0.0100, 0.1500] | <0.0001 | - | 0.05 | yes |"
    )
    assert "| -0.0123 |" in lines[3]
    assert lines[3].endswith("| 0.2000 | - | 0.05 | no |")


def test_comparisons_to_markdown_with_corrected_p_values() -> None:
    text = comparisons_to_markdown([_comparison(p_value_corrected=0.12, significant=False)])
    assert "| <0.0001 | 0.1200 | 0.05 | no |" in text


def test_comparisons_to_markdown_empty() -> None:
    assert comparisons_to_markdown([]) == "_No comparisons._\n"
