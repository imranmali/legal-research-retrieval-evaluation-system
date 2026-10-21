"""The ``groundtruth`` command-line tool.

Commands: ``evaluate``, ``compare``, ``retrieve``, ``benchmark``, ``validate``,
``metrics``, ``serve`` and ``version``.

Exit codes:

* ``0`` success;
* ``1`` a ``--fail-under`` quality gate failed (the output is still printed);
* ``2`` invalid input or usage: a one-line ``error: ...`` message on standard
  error, never a stack trace.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from rich.text import Text

from groundtruth import __version__
from groundtruth.config import DEFAULT_METRICS, Settings
from groundtruth.errors import ConfigurationError, GroundTruthError
from groundtruth.evaluation import EvaluationResult, MissingPolicy, evaluate, resolve_metrics
from groundtruth.io import dump_json, dump_run, is_json_path, load_qrels_any, load_run_any
from groundtruth.io import open_output as _open_output
from groundtruth.legal import document_metadata, load_documents, load_queries, query_metadata
from groundtruth.metrics import available_metrics, get_metric
from groundtruth.reporting import comparisons_to_markdown, to_csv, to_json, to_markdown
from groundtruth.retrieval import available_retrievers, get_retriever
from groundtruth.stats import PairedComparison, compare_many, compare_systems, holm_bonferroni
from groundtruth.types import DocMetadata, Qrels, QueryMetadata

__all__ = ["app"]

app = typer.Typer(
    name="groundtruth",
    help="Evaluate, compare and benchmark legal research retrieval systems.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

#: Exit code of a failed quality gate.
EXIT_GATE_FAILED = 1
#: Exit code of invalid input or usage.
EXIT_INPUT_ERROR = 2

#: Width used when rendering tables into files (no terminal to measure).
_FILE_TABLE_WIDTH = 160


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    MARKDOWN = "markdown"
    CSV = "csv"


class SimpleFormat(StrEnum):
    TABLE = "table"
    JSON = "json"


class Missing(StrEnum):
    ZERO = "zero"
    SKIP = "skip"


class SignificanceTestChoice(StrEnum):
    PERMUTATION = "permutation"
    BOOTSTRAP = "bootstrap"
    TTEST = "ttest"


# ---------------------------------------------------------------------------
# Shared option types
# ---------------------------------------------------------------------------

MetricOption = Annotated[
    list[str] | None,
    typer.Option(
        "--metric",
        "-m",
        help=(
            "Metric such as nDCG@10, P@5, MAP or BadLaw@10; repeat or comma-separate. "
            f"Default: {', '.join(DEFAULT_METRICS)}."
        ),
        show_default=False,
    ),
]
FormatOption = Annotated[
    OutputFormat,
    typer.Option("--format", "-f", help="Output format.", case_sensitive=False),
]
SimpleFormatOption = Annotated[
    SimpleFormat,
    typer.Option("--format", "-f", help="Output format.", case_sensitive=False),
]
OutputOption = Annotated[
    Path | None,
    typer.Option(
        "--output",
        "-o",
        help="Write the report to this file instead of standard output.",
        dir_okay=False,
        show_default=False,
    ),
]
CorpusOption = Annotated[
    Path | None,
    typer.Option(
        "--corpus",
        help="Corpus JSONL supplying document metadata for legal metrics.",
        dir_okay=False,
        show_default=False,
    ),
]
QueriesOption = Annotated[
    Path | None,
    typer.Option(
        "--queries",
        help="Queries JSONL supplying query metadata for legal metrics.",
        dir_okay=False,
        show_default=False,
    ),
]
MissingOption = Annotated[
    Missing,
    typer.Option(
        "--missing",
        help="Judged queries absent from a run score 0 (zero) or are left out (skip).",
        case_sensitive=False,
    ),
]
DepthOption = Annotated[
    int | None,
    typer.Option("--depth", help="Evaluate only the top N documents per query.", min=1),
]
RelLevelOption = Annotated[
    int,
    typer.Option("--rel-level", help="Minimum grade counted as relevant.", min=1),
]
TestOption = Annotated[
    SignificanceTestChoice,
    typer.Option("--test", help="Paired significance test.", case_sensitive=False),
]
AlphaOption = Annotated[
    float,
    typer.Option("--alpha", help="Significance level, strictly between 0 and 1."),
]
ResamplesOption = Annotated[
    int,
    typer.Option("--resamples", help="Resamples for permutation and bootstrap tests.", min=1),
]
SeedOption = Annotated[int, typer.Option("--seed", help="Random seed for resampling tests.")]


# ---------------------------------------------------------------------------
# Error handling and output helpers
# ---------------------------------------------------------------------------


def _fail(message: str, code: int = EXIT_INPUT_ERROR) -> NoReturn:
    """Print a one-line error to standard error and exit."""
    one_line = " ".join(message.split())
    typer.echo(f"error: {one_line}", err=True)
    raise typer.Exit(code)


def _describe_os_error(exc: OSError) -> str:
    reason = exc.strerror or str(exc)
    return f"{exc.filename}: {reason}" if exc.filename else reason


@contextmanager
def _input_errors() -> Iterator[None]:
    """Turn domain, file-system and settings errors into exit code 2."""
    try:
        yield
    except GroundTruthError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(_describe_os_error(exc))
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        _fail(f"invalid setting {location}: {first['msg']}")


def _warn(message: str) -> None:
    typer.echo(f"warning: {message}", err=True)


def _stdout_console() -> Console:
    return Console(highlight=False)


def _emit_text(text: str, output: Path | None) -> None:
    if output is None:
        typer.echo(text, nl=not text.endswith("\n"))
        return
    with _open_output(output) as handle:
        handle.write(text if text.endswith("\n") else text + "\n")


def _emit_tables(tables: Sequence[Table], output: Path | None) -> None:
    if output is None:
        console = _stdout_console()
        for table in tables:
            console.print(table)
        return
    with _open_output(output) as handle:
        console = Console(file=handle, width=_FILE_TABLE_WIDTH, color_system=None, highlight=False)
        for table in tables:
            console.print(table)


def _table(
    title: str | None,
    columns: Sequence[str],
    numeric_from: int = 1,
    *,
    wrap_last: bool = False,
) -> Table:
    """A table whose columns from ``numeric_from`` on are right-aligned and never wrapped.

    With ``wrap_last`` only the last column wraps, so a long free-text column
    absorbs the width a narrow terminal lacks.
    """
    table = Table(title=title, title_justify="left")
    last = len(columns) - 1
    for index, column in enumerate(columns):
        numeric = index >= numeric_from
        table.add_column(
            column,
            justify="right" if numeric else "left",
            no_wrap=numeric or (wrap_last and index != last),
        )
    return table


def _add_row(table: Table, *cells: str) -> None:
    table.add_row(*(Text(cell) for cell in cells))


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "-"
    return "<0.0001" if value < 0.0001 else _fmt(value)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _metric_specs(values: Sequence[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_METRICS)
    specs = [part.strip() for value in values for part in value.split(",")]
    specs = [spec for spec in specs if spec]
    if not specs:
        raise ConfigurationError("at least one metric must be requested")
    return specs


def _metadata(
    corpus: Path | None, queries: Path | None, specs: Sequence[str], rel_level: int
) -> tuple[DocMetadata | None, QueryMetadata | None]:
    """Load legal metadata, after checking the metrics resolve and have what they need."""
    needs_corpus = [m.label for m in resolve_metrics(specs, rel_level) if m.requires_context]
    if needs_corpus and corpus is None:
        raise ConfigurationError(
            f"metric(s) {', '.join(needs_corpus)} need document metadata; "
            "pass --corpus CORPUS.jsonl (and --queries QUERIES.jsonl for query metadata)"
        )
    docs = document_metadata(load_documents(corpus)) if corpus is not None else None
    query_meta = query_metadata(load_queries(queries)) if queries is not None else None
    return docs, query_meta


def _system_names(paths: Sequence[Path], names: Sequence[str] | None) -> list[str]:
    """Names of compared systems: explicit ``--name`` values or unique file-based names."""
    if names:
        if len(names) != len(paths):
            raise ConfigurationError(
                f"got {len(names)} --name value(s) for {len(paths)} runs; give one per run"
            )
        if len(set(names)) != len(names):
            raise ConfigurationError("--name values must be unique")
        return list(names)
    result: list[str] = []
    for path in paths:
        stem = path.name.removesuffix(".gz")
        stem = stem.rsplit(".", 1)[0] if "." in stem.lstrip(".") else stem
        candidate = stem or str(path)
        if candidate in result:
            candidate = str(path)
        suffix = 2
        unique = candidate
        while unique in result:
            unique = f"{candidate}#{suffix}"
            suffix += 1
        result.append(unique)
    return result


@dataclass(frozen=True)
class _Gate:
    label: str
    threshold: float
    higher_is_better: bool

    def violation(self, value: float) -> str | None:
        if self.higher_is_better and value < self.threshold:
            return f"{self.label} = {_fmt(value)} is below the threshold {self.threshold:g}"
        if not self.higher_is_better and value > self.threshold:
            return (
                f"{self.label} = {_fmt(value)} is above the threshold {self.threshold:g} "
                "(lower is better)"
            )
        return None


def _parse_gates(values: Sequence[str] | None, rel_level: int) -> list[_Gate]:
    gates: list[_Gate] = []
    for value in values or ():
        spec, sep, raw = value.rpartition("=")
        if not sep or not spec.strip() or not raw.strip():
            raise ConfigurationError(f"--fail-under expects METRIC=VALUE, got {value!r}")
        try:
            threshold = float(raw)
        except ValueError:
            threshold = math.nan
        if not math.isfinite(threshold):
            raise ConfigurationError(f"--fail-under {value!r}: threshold must be a finite number")
        metric = get_metric(spec.strip(), rel_level=rel_level)
        gates.append(_Gate(metric.label, threshold, metric.higher_is_better))
    return gates


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_evaluation(
    result: EvaluationResult, fmt: OutputFormat, per_query: bool, output: Path | None
) -> None:
    if fmt is OutputFormat.JSON:
        _emit_text(to_json(result, per_query=per_query), output)
        return
    if fmt is OutputFormat.MARKDOWN:
        _emit_text(to_markdown(result, per_query=per_query), output)
        return
    for warning in result.warnings:
        _warn(warning)
    if fmt is OutputFormat.CSV:
        _emit_text(to_csv(result), output)
        return
    tables = [_table(f"Scores ({result.num_queries} queries)", ["Metric", "Score"])]
    for label in result.metrics:
        _add_row(tables[0], label, _fmt(result.aggregate[label]))
    if per_query:
        detail = _table("Per query", ["Query", *result.metrics])
        for query_id in sorted(result.per_query):
            row = result.per_query[query_id]
            _add_row(detail, query_id, *(_fmt(row[m]) for m in result.metrics))
        tables.append(detail)
    _emit_tables(tables, output)


@dataclass
class _SystemsReport:
    """Scores of several systems plus their pairwise comparisons."""

    results: dict[str, EvaluationResult]
    comparisons: list[PairedComparison]
    baseline: str | None = None
    metrics: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.metrics = list(next(iter(self.results.values())).metrics)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "systems": list(self.results),
            "metrics": self.metrics,
            "aggregate": {name: dict(r.aggregate) for name, r in self.results.items()},
            "num_queries": {name: r.num_queries for name, r in self.results.items()},
            "comparisons": [c.model_dump(mode="json") for c in self.comparisons],
            "warnings": {name: list(r.warnings) for name, r in self.results.items()},
        }
        if self.baseline is not None:
            data["baseline"] = self.baseline
        return data

    def scores_markdown(self) -> str:
        header = ["System", *self.metrics]
        lines = [
            "| " + " | ".join(header) + " |",
            "| --- |" + " ---: |" * len(self.metrics),
        ]
        for name, result in self.results.items():
            cells = [name.replace("|", "\\|"), *(_fmt(result.aggregate[m]) for m in self.metrics)]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines) + "\n"

    def comparisons_csv(self) -> str:
        buffer = io.StringIO()
        fields = list(PairedComparison.model_fields)
        writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for comparison in self.comparisons:
            row = comparison.model_dump(mode="json")
            writer.writerow({key: "" if row[key] is None else row[key] for key in fields})
        return buffer.getvalue()


def _render_systems(report: _SystemsReport, fmt: OutputFormat, output: Path | None) -> None:
    if fmt is OutputFormat.JSON:
        _emit_text(json.dumps(report.to_dict(), indent=2, allow_nan=False), output)
        return
    for name, result in report.results.items():
        for warning in result.warnings:
            _warn(f"{name}: {warning}")
    if fmt is OutputFormat.MARKDOWN:
        text = report.scores_markdown()
        if report.comparisons:
            text += "\n" + comparisons_to_markdown(report.comparisons)
        _emit_text(text, output)
        return
    if fmt is OutputFormat.CSV:
        _emit_text(report.comparisons_csv(), output)
        return
    scores = _table("Scores", ["System", *report.metrics])
    for name, result in report.results.items():
        _add_row(scores, name, *(_fmt(result.aggregate[m]) for m in report.metrics))
    tables = [scores]
    if report.comparisons:
        title = "Significance" + (f" against {report.baseline}" if report.baseline else "")
        first = report.comparisons[0]
        title += f" ({first.test}, alpha={first.alpha:g}, Holm-corrected)"
        comparisons = _table(
            title,
            ["Metric", "A", "B", "Delta (B-A)", "p", "p (Holm)", "Sig."],
            numeric_from=3,
        )
        for c in report.comparisons:
            _add_row(
                comparisons,
                c.metric,
                c.system_a,
                c.system_b,
                f"{c.delta:+.4f}",
                _fmt_p(c.p_value),
                _fmt_p(c.p_value_corrected),
                "yes" if c.significant else "no",
            )
        tables.append(comparisons)
    _emit_tables(tables, output)


def _compare_to_baseline(
    results: Mapping[str, EvaluationResult],
    *,
    test: SignificanceTestChoice,
    alpha: float,
    n_resamples: int,
    seed: int,
) -> list[PairedComparison]:
    """Compare every system against the first, Holm-correcting per metric."""
    names = list(results)
    baseline, others = names[0], names[1:]
    comparisons: list[PairedComparison] = []
    for label in results[baseline].metrics:
        raw = [
            compare_systems(
                results[baseline],
                results[other],
                label,
                test=test.value,
                alpha=alpha,
                n_resamples=n_resamples,
                seed=seed,
                name_a=baseline,
                name_b=other,
            )
            for other in others
        ]
        corrected = holm_bonferroni([c.p_value for c in raw])
        comparisons.extend(
            c.model_copy(update={"p_value_corrected": p, "significant": p < alpha})
            for c, p in zip(raw, corrected, strict=True)
        )
    return comparisons


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("evaluate")
def evaluate_command(
    qrels: Annotated[
        Path, typer.Argument(metavar="QRELS", help="Relevance judgments (TREC or JSON).")
    ],
    run: Annotated[Path, typer.Argument(metavar="RUN", help="Run to evaluate (TREC or JSON).")],
    metric: MetricOption = None,
    fmt: FormatOption = OutputFormat.TABLE,
    per_query: Annotated[
        bool, typer.Option("--per-query", help="Also report scores per query.")
    ] = False,
    output: OutputOption = None,
    corpus: CorpusOption = None,
    queries: QueriesOption = None,
    missing: MissingOption = Missing.ZERO,
    depth: DepthOption = None,
    rel_level: RelLevelOption = 1,
    fail_under: Annotated[
        list[str] | None,
        typer.Option(
            "--fail-under",
            help=(
                "Quality gate METRIC=VALUE (repeatable): exit 1 when the score is below "
                "VALUE, or above it for lower-is-better metrics such as BadLaw."
            ),
            show_default=False,
        ),
    ] = None,
) -> None:
    """Score a run against relevance judgments."""
    with _input_errors():
        gates = _parse_gates(fail_under, rel_level)
        specs = _metric_specs(metric)
        specs += [gate.label for gate in gates]
        doc_meta, query_meta = _metadata(corpus, queries, specs, rel_level)
        result = evaluate(
            load_qrels_any(qrels),
            load_run_any(run),
            specs,
            doc_metadata=doc_meta,
            query_metadata=query_meta,
            missing=_missing(missing),
            depth=depth,
            rel_level=rel_level,
        )
        _render_evaluation(result, fmt, per_query, output)
    failures = [
        message
        for gate in gates
        if (message := gate.violation(result.aggregate[gate.label])) is not None
    ]
    for message in failures:
        typer.echo(f"quality gate failed: {message}", err=True)
    if failures:
        raise typer.Exit(EXIT_GATE_FAILED)


def _missing(value: Missing) -> MissingPolicy:
    return "skip" if value is Missing.SKIP else "zero"


@app.command("compare")
def compare_command(
    qrels: Annotated[
        Path, typer.Argument(metavar="QRELS", help="Relevance judgments (TREC or JSON).")
    ],
    runs: Annotated[
        list[Path],
        typer.Argument(metavar="RUN...", help="Two or more runs to compare (TREC or JSON)."),
    ],
    metric: MetricOption = None,
    name: Annotated[
        list[str] | None,
        typer.Option(
            "--name",
            "-n",
            help="System name per run, in order (default: file names).",
            show_default=False,
        ),
    ] = None,
    test: TestOption = SignificanceTestChoice.PERMUTATION,
    alpha: AlphaOption = 0.05,
    resamples: ResamplesOption = 10_000,
    seed: SeedOption = 0,
    fmt: FormatOption = OutputFormat.TABLE,
    output: OutputOption = None,
    corpus: CorpusOption = None,
    queries: QueriesOption = None,
    missing: MissingOption = Missing.ZERO,
    depth: DepthOption = None,
    rel_level: RelLevelOption = 1,
) -> None:
    """Compare systems pairwise with paired significance tests.

    P-values are Holm-Bonferroni corrected across the system pairs of each
    metric when more than two runs are compared.
    """
    with _input_errors():
        if len(runs) < 2:
            raise ConfigurationError(f"compare needs at least two runs, got {len(runs)}")
        names = _system_names(runs, name)
        specs = _metric_specs(metric)
        judgments: Qrels = load_qrels_any(qrels)
        doc_meta, query_meta = _metadata(corpus, queries, specs, rel_level)
        results = {
            system: evaluate(
                judgments,
                load_run_any(path),
                specs,
                doc_metadata=doc_meta,
                query_metadata=query_meta,
                missing=_missing(missing),
                depth=depth,
                rel_level=rel_level,
            )
            for system, path in zip(names, runs, strict=True)
        }
        labels = next(iter(results.values())).metrics
        comparisons = [
            comparison
            for label in labels
            for comparison in compare_many(
                results, label, test=test.value, alpha=alpha, n_resamples=resamples, seed=seed
            )
        ]
        _render_systems(_SystemsReport(results, comparisons), fmt, output)


@app.command("retrieve")
def retrieve_command(
    corpus: Annotated[Path, typer.Argument(metavar="CORPUS", help="Corpus JSONL to index.")],
    queries: Annotated[Path, typer.Argument(metavar="QUERIES", help="Queries JSONL to search.")],
    retriever: Annotated[
        str,
        typer.Option(
            "--retriever",
            "-r",
            help=f"Retriever: {', '.join(available_retrievers())}.",
        ),
    ] = "bm25",
    depth: Annotated[
        int, typer.Option("--depth", "-k", help="Documents retrieved per query.", min=1)
    ] = 100,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write the run here (.json for JSON, otherwise TREC; .gz compresses).",
            dir_okay=False,
            show_default="standard output",
        ),
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option("--tag", help="Run tag in TREC output.", show_default="retriever name"),
    ] = None,
    jurisdiction_filter: Annotated[
        bool,
        typer.Option(
            "--jurisdiction-filter",
            help="Restrict each query to its jurisdiction plus binding jurisdictions.",
        ),
    ] = False,
) -> None:
    """Search every query with a baseline retriever and write a run."""
    with _input_errors():
        model = get_retriever(retriever).fit(load_documents(corpus))
        run = model.retrieve(
            load_queries(queries), k=depth, use_query_jurisdiction=jurisdiction_filter
        )
        destination = output if output is not None else sys.stdout
        if output is not None and is_json_path(output):
            dump_json(run, output)
        else:
            dump_run(run, destination, tag=tag if tag is not None else model.name)


@app.command("benchmark")
def benchmark_command(
    corpus: Annotated[Path, typer.Argument(metavar="CORPUS", help="Corpus JSONL to index.")],
    queries: Annotated[Path, typer.Argument(metavar="QUERIES", help="Queries JSONL to search.")],
    qrels: Annotated[
        Path, typer.Argument(metavar="QRELS", help="Relevance judgments (TREC or JSON).")
    ],
    retriever: Annotated[
        list[str] | None,
        typer.Option(
            "--retriever",
            "-r",
            help=(
                f"Retriever to benchmark (repeatable): {', '.join(available_retrievers())}. "
                "The first is the baseline for significance tests. Default: bm25."
            ),
            show_default=False,
        ),
    ] = None,
    metric: MetricOption = None,
    depth: Annotated[
        int, typer.Option("--depth", "-k", help="Documents retrieved per query.", min=1)
    ] = 100,
    jurisdiction_filter: Annotated[
        bool,
        typer.Option(
            "--jurisdiction-filter",
            help="Restrict each query to its jurisdiction plus binding jurisdictions.",
        ),
    ] = False,
    test: TestOption = SignificanceTestChoice.PERMUTATION,
    alpha: AlphaOption = 0.05,
    resamples: ResamplesOption = 10_000,
    seed: SeedOption = 0,
    fmt: FormatOption = OutputFormat.TABLE,
    output: OutputOption = None,
    runs_dir: Annotated[
        Path | None,
        typer.Option(
            "--runs-dir",
            help="Also write each retriever's TREC run to DIR/<retriever>.run.",
            file_okay=False,
            show_default=False,
        ),
    ] = None,
) -> None:
    """Run retrievers end to end on a collection, score them and test differences.

    Legal metrics (BadLaw, JurisdictionMatch, ...) use the corpus and query
    metadata automatically.
    """
    with _input_errors():
        names = [name.strip().lower() for name in (retriever or ["bm25"])]
        if len(set(names)) != len(names):
            raise ConfigurationError("each --retriever may be given only once")
        models = [get_retriever(name) for name in names]
        specs = _metric_specs(metric)
        documents = load_documents(corpus)
        research_queries = load_queries(queries)
        judgments = load_qrels_any(qrels)
        doc_meta = document_metadata(documents)
        query_meta = query_metadata(research_queries)
        if runs_dir is not None:
            runs_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, EvaluationResult] = {}
        for model in models:
            run = model.fit(documents).retrieve(
                research_queries, k=depth, use_query_jurisdiction=jurisdiction_filter
            )
            if runs_dir is not None:
                dump_run(run, runs_dir / f"{model.name}.run", tag=model.name)
            results[model.name] = evaluate(
                judgments, run, specs, doc_metadata=doc_meta, query_metadata=query_meta
            )
        comparisons = (
            _compare_to_baseline(results, test=test, alpha=alpha, n_resamples=resamples, seed=seed)
            if len(results) > 1
            else []
        )
        _render_systems(_SystemsReport(results, comparisons, baseline=models[0].name), fmt, output)


@app.command("validate")
def validate_command(
    qrels: Annotated[
        Path, typer.Argument(metavar="QRELS", help="Relevance judgments (TREC or JSON).")
    ],
    run: Annotated[
        Path | None,
        typer.Argument(metavar="[RUN]", help="Optional run to check against the qrels."),
    ] = None,
    corpus: Annotated[
        Path | None,
        typer.Option("--corpus", help="Also validate a corpus JSONL.", show_default=False),
    ] = None,
    queries: Annotated[
        Path | None,
        typer.Option("--queries", help="Also validate a queries JSONL.", show_default=False),
    ] = None,
    fmt: SimpleFormatOption = SimpleFormat.TABLE,
) -> None:
    """Check input files and print summary counts."""
    with _input_errors():
        judgments = load_qrels_any(qrels)
        summary: dict[str, dict[str, int]] = {
            "qrels": {
                "queries": len(judgments),
                "judgments": sum(len(docs) for docs in judgments.values()),
                "relevant": sum(
                    1 for docs in judgments.values() for grade in docs.values() if grade > 0
                ),
            }
        }
        notes: list[str] = []
        if run is not None:
            scores = load_run_any(run)
            unjudged = sorted(set(scores) - set(judgments))
            absent = sorted(set(judgments) - set(scores))
            summary["run"] = {
                "queries": len(scores),
                "entries": sum(len(docs) for docs in scores.values()),
                "judged_queries": len(set(scores) & set(judgments)),
                "unjudged_queries": len(unjudged),
                "missing_queries": len(absent),
            }
            if unjudged:
                notes.append(f"{len(unjudged)} run queries have no judgments")
            if absent:
                notes.append(f"{len(absent)} judged queries are missing from the run")
        if corpus is not None:
            summary["corpus"] = {"documents": len(load_documents(corpus))}
        if queries is not None:
            summary["queries"] = {"queries": len(load_queries(queries))}
    if fmt is SimpleFormat.JSON:
        _emit_text(json.dumps({"valid": True, "summary": summary, "notes": notes}, indent=2), None)
        return
    table = _table("Valid input", ["File", "Count", "Value"], numeric_from=2)
    for source, counts in summary.items():
        for key, value in counts.items():
            _add_row(table, source, key.replace("_", " "), str(value))
    _emit_tables([table], None)
    for note in notes:
        _warn(note)


@app.command("metrics")
def metrics_command(fmt: SimpleFormatOption = SimpleFormat.TABLE) -> None:
    """List the available metrics."""
    infos = available_metrics()
    if fmt is SimpleFormat.JSON:
        data = [
            {
                "name": info.name,
                "aliases": list(info.aliases),
                "description": info.description,
                "cutoff": info.cutoff_policy.value,
                "higher_is_better": info.higher_is_better,
                "requires_metadata": info.requires_context,
            }
            for info in infos
        ]
        _emit_text(json.dumps(data, indent=2), None)
        return
    table = _table(
        "Metrics (request as NAME or NAME@K)",
        ["Name", "Aliases", "Cutoff", "Better", "Metadata", "Description"],
        numeric_from=99,
        wrap_last=True,
    )
    for info in infos:
        _add_row(
            table,
            info.name,
            ", ".join(info.aliases),
            info.cutoff_policy.value,
            "higher" if info.higher_is_better else "lower",
            "yes" if info.requires_context else "no",
            info.description,
        )
    _emit_tables([table], None)


@app.command("serve")
def serve_command(
    host: Annotated[str, typer.Option("--host", help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[
        int, typer.Option("--port", help="Port to listen on.", min=1, max=65535)
    ] = 8000,
    workers: Annotated[int, typer.Option("--workers", help="Worker processes.", min=1)] = 1,
    reload: Annotated[
        bool, typer.Option("--reload", help="Restart on code changes (development only).")
    ] = False,
    corpus: Annotated[
        Path | None,
        typer.Option(
            "--corpus",
            help="Corpus JSONL to search (sets GROUNDTRUTH_CORPUS_PATH).",
            dir_okay=False,
            show_default=False,
        ),
    ] = None,
    retriever: Annotated[
        str | None,
        typer.Option(
            "--retriever",
            help="Retriever for /v1/search (sets GROUNDTRUTH_RETRIEVER).",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Run the HTTP API with uvicorn (use gunicorn in production; see docs/deployment.md)."""
    if reload and workers > 1:
        _fail("--reload cannot be combined with --workers > 1")
    if corpus is not None:
        os.environ["GROUNDTRUTH_CORPUS_PATH"] = str(corpus.resolve())
    if retriever is not None:
        os.environ["GROUNDTRUTH_RETRIEVER"] = retriever
    with _input_errors():
        settings = Settings()
        if settings.corpus_path is not None and not settings.corpus_path.is_file():
            raise ConfigurationError(f"{settings.corpus_path}: corpus file not found")

    import uvicorn  # imported lazily: only this command needs the server

    from groundtruth.logging import configure_logging

    configure_logging(settings.log_level, json_format=settings.log_json)
    uvicorn.run(
        "groundtruth.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        log_config=None,
    )


@app.command("version")
def version_command() -> None:
    """Print the Ground Truth version."""
    typer.echo(f"groundtruth {__version__}")
