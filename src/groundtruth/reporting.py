"""Rendering evaluation and comparison results as JSON, Markdown and CSV.

Markdown is meant for people and rounds scores to 4 decimals; JSON and CSV are
meant for machines and keep full float precision.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence

from groundtruth.evaluation import EvaluationResult
from groundtruth.stats import PairedComparison

__all__ = [
    "AGGREGATE_ROW_ID",
    "comparisons_to_markdown",
    "to_csv",
    "to_json",
    "to_markdown",
]

#: Query id of the aggregate row in CSV output.
AGGREGATE_ROW_ID = "all"


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def _fmt_p(value: float) -> str:
    return "<0.0001" if value < 0.0001 else _fmt(value)


def _cell(text: str) -> str:
    """Escape text for a Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _table(
    header: Sequence[str], rows: Iterable[Sequence[str]], text_columns: int = 1
) -> list[str]:
    """A Markdown table whose first ``text_columns`` columns are left-aligned, the rest right."""
    lines = [
        "| " + " | ".join(_cell(h) for h in header) + " |",
        "|" + "|".join(" --- " if i < text_columns else " ---: " for i in range(len(header))) + "|",
    ]
    lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    return lines


def to_json(result: EvaluationResult, per_query: bool = True, *, indent: int | None = 2) -> str:
    """Render ``result`` as JSON: metrics, aggregate, query count, warnings and per-query scores.

    With ``per_query=False`` the (possibly large) per-query section is omitted.
    """
    data = result.model_dump(mode="json", exclude=None if per_query else {"per_query"})
    return json.dumps(data, indent=indent, allow_nan=False)


def to_markdown(result: EvaluationResult, per_query: bool = False) -> str:
    """Render ``result`` as Markdown: an aggregate table, optional per-query table and warnings."""
    lines = [
        f"**Queries evaluated:** {result.num_queries}",
        "",
        *_table(
            ["Metric", "Score"],
            ([label, _fmt(result.aggregate[label])] for label in result.metrics),
        ),
    ]
    if per_query:
        lines += [
            "",
            *_table(
                ["Query", *result.metrics],
                (
                    [query_id, *(_fmt(result.per_query[query_id][m]) for m in result.metrics)]
                    for query_id in sorted(result.per_query)
                ),
            ),
        ]
    if result.warnings:
        lines += ["", "**Warnings:**", "", *(f"- {_cell(w)}" for w in result.warnings)]
    return "\n".join(lines) + "\n"


def to_csv(result: EvaluationResult) -> str:
    """Render ``result`` as CSV: one row per query (sorted by id), then the ``all`` aggregate row.

    The header is ``query_id`` followed by the metric labels; scores keep full precision.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["query_id", *result.metrics])
    for query_id in sorted(result.per_query):
        row = result.per_query[query_id]
        writer.writerow([query_id, *(repr(row[m]) for m in result.metrics)])
    writer.writerow([AGGREGATE_ROW_ID, *(repr(result.aggregate[m]) for m in result.metrics)])
    return buffer.getvalue()


def comparisons_to_markdown(comparisons: Sequence[PairedComparison]) -> str:
    """Render paired comparisons as a Markdown table, one row per system pair.

    Significant differences are marked ``yes``; the corrected p-value column
    shows ``-`` for comparisons that were not corrected for multiple testing.
    """
    if not comparisons:
        return "_No comparisons._\n"
    rows = (
        [
            c.system_a,
            c.system_b,
            c.metric,
            c.test,
            str(c.num_queries),
            _fmt(c.mean_a),
            _fmt(c.mean_b),
            f"{c.delta:+.4f}",
            f"[{_fmt(c.ci_low)}, {_fmt(c.ci_high)}]",
            _fmt_p(c.p_value),
            "-" if c.p_value_corrected is None else _fmt_p(c.p_value_corrected),
            f"{c.alpha:g}",
            "yes" if c.significant else "no",
        ]
        for c in comparisons
    )
    header = [
        "System A",
        "System B",
        "Metric",
        "Test",
        "Queries",
        "Mean A",
        "Mean B",
        "Delta (B-A)",
        "CI",
        "p",
        "p (Holm)",
        "alpha",
        "Significant",
    ]
    return "\n".join(_table(header, rows, text_columns=4)) + "\n"
