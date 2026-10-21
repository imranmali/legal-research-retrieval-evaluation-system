"""Spec: legal-metrics."""

import subprocess
import sys
from collections.abc import Mapping
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

import groundtruth.legal  # noqa: F401  (registers the legal metrics)
from groundtruth.errors import ConfigurationError
from groundtruth.legal import (
    BadLaw,
    CitationRecall,
    JurisdictionMatch,
    KeyAuthorityRecall,
    LegalDocument,
    LegalQuery,
    PrecedentialStatus,
    document_metadata,
    query_metadata,
)
from groundtruth.metrics.base import MetricContext, available_metrics, get_metric


def _ctx(
    documents: Mapping[str, Mapping[str, Any]] | None = None,
    query: Mapping[str, Any] | None = None,
) -> MetricContext:
    return MetricContext(query=query or {}, documents=documents or {})


# -- Registration -------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "cls"),
    [
        ("BadLaw@10", BadLaw),
        ("badlaw@3", BadLaw),
        ("JurisdictionMatch@5", JurisdictionMatch),
        ("KeyAuthorityRecall@10", KeyAuthorityRecall),
        ("KAR@10", KeyAuthorityRecall),
        ("CitationRecall@20", CitationRecall),
    ],
)
def test_legal_metrics_are_registered(spec: str, cls: type) -> None:
    metric = get_metric(spec)
    assert isinstance(metric, cls)


@pytest.mark.parametrize("name", ["BadLaw", "JurisdictionMatch", "KAR", "CitationRecall"])
def test_legal_metrics_require_a_cutoff(name: str) -> None:
    with pytest.raises(ConfigurationError, match="requires a rank cutoff"):
        get_metric(name)


def test_metric_info_flags() -> None:
    info = {i.name: i for i in available_metrics()}
    assert info["BadLaw"].higher_is_better is False
    assert info["BadLaw"].requires_context is True
    assert info["JurisdictionMatch"].requires_context is True
    assert info["CitationRecall"].requires_context is True
    assert info["KeyAuthorityRecall"].requires_context is False
    assert info["KeyAuthorityRecall"].aliases == ("KAR",)
    assert all(info[name].description for name in info)


def test_importing_legal_metrics_first_has_no_import_cycle() -> None:
    code = (
        "import groundtruth.legal.metrics\n"
        "from groundtruth.metrics.base import get_metric\n"
        "assert get_metric('KAR@5').label == 'KeyAuthorityRecall@5'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# -- Requirement: Bad law exposure --------------------------------------------


def test_one_overruled_in_top_4() -> None:
    docs = {
        "a": {"status": "good_law"},
        "b": {"status": "overruled"},
        "c": {"status": "questioned"},
        "d": {"status": "unknown"},
        "e": {"status": "overruled"},
    }
    metric = get_metric("BadLaw@4")
    assert metric.compute(["a", "b", "c", "d", "e"], {}, _ctx(docs)) == 0.25


def test_bad_law_counts_superseded_and_enum_values() -> None:
    docs = {"a": {"status": PrecedentialStatus.SUPERSEDED}, "b": {"status": "OVERRULED"}}
    assert BadLaw(cutoff=10).compute(["a", "b"], {}, _ctx(docs)) == 1.0


def test_bad_law_empty_ranking_is_zero() -> None:
    assert BadLaw(cutoff=10).compute([], {}, _ctx()) == 0.0


def test_bad_law_tolerates_documents_missing_from_metadata() -> None:
    docs = {"a": {"status": "overruled"}, "b": {}}
    assert BadLaw(cutoff=10).compute(["a", "b", "c", "d"], {}, _ctx(docs)) == 0.25


def test_bad_law_ignores_documents_below_cutoff() -> None:
    docs = {"e": {"status": "overruled"}}
    assert BadLaw(cutoff=4).compute(["a", "b", "c", "d", "e"], {}, _ctx(docs)) == 0.0


# -- Requirement: Jurisdictional fit ------------------------------------------


def test_mixed_jurisdictions() -> None:
    docs = {
        "a": {"jurisdiction": "US-CA"},
        "b": {"jurisdiction": "US-NY"},
        "c": {"jurisdiction": "US-CA"},
        "d": {"jurisdiction": "US-CA"},
    }
    metric = get_metric("JurisdictionMatch@4")
    assert metric.compute(["a", "b", "c", "d"], {}, _ctx(docs, {"jurisdiction": "US-CA"})) == 0.75


def test_binding_jurisdictions_count_as_matches() -> None:
    docs = {"a": {"jurisdiction": "US-FED"}, "b": {"jurisdiction": "UK"}}
    query = {"jurisdiction": "US-CA", "binding_jurisdictions": ["US-FED"]}
    assert JurisdictionMatch(cutoff=2).compute(["a", "b"], {}, _ctx(docs, query)) == 0.5


@pytest.mark.parametrize("query", [{}, {"jurisdiction": None}, {"jurisdiction": ""}])
def test_query_without_target_jurisdiction_scores_one(query: dict[str, Any]) -> None:
    docs = {"a": {"jurisdiction": "UK"}}
    metric = JurisdictionMatch(cutoff=5)
    assert metric.compute(["a"], {}, _ctx(docs, query)) == 1.0
    assert metric.compute([], {}, _ctx(docs, query)) == 1.0


def test_jurisdiction_match_nothing_retrieved_is_zero() -> None:
    assert JurisdictionMatch(cutoff=5).compute([], {}, _ctx(query={"jurisdiction": "UK"})) == 0.0


def test_jurisdiction_match_tolerates_missing_metadata() -> None:
    query = {"jurisdiction": "UK", "binding_jurisdictions": None}
    docs = {"a": {"jurisdiction": "UK"}}
    assert JurisdictionMatch(cutoff=5).compute(["a", "x"], {}, _ctx(docs, query)) == 0.5


# -- Requirement: Key authority recall ----------------------------------------


def test_missing_the_controlling_case() -> None:
    judgments = {"key1": 3, "key2": 3, "rel": 2, "tangent": 1}
    ranking = ["rel", "key1", *[f"x{i}" for i in range(8)], "key2"]
    assert get_metric("KeyAuthorityRecall@10").compute(ranking, judgments) == 0.5


def test_key_authority_recall_without_key_authorities_is_zero() -> None:
    assert KeyAuthorityRecall(cutoff=10).compute(["a"], {"a": 2}) == 0.0


def test_key_authority_recall_all_found() -> None:
    assert KeyAuthorityRecall(cutoff=2).compute(["b", "a"], {"a": 3, "b": 4}) == 1.0


# -- Requirement: Citation recall ---------------------------------------------


def test_citation_found() -> None:
    docs = {
        "a": {"citations": ["999 F.3d 1"]},
        "b": {"citations": []},
        "c": {"citations": ["410 U.S. 113", "93 S. Ct. 705"]},
    }
    query = {"expected_citations": ["410 U.S. 113"]}
    assert get_metric("CitationRecall@3").compute(["a", "b", "c"], {}, _ctx(docs, query)) == 1.0
    assert get_metric("CitationRecall@2").compute(["a", "b", "c"], {}, _ctx(docs, query)) == 0.0


def test_citation_recall_without_expected_citations_is_zero() -> None:
    docs = {"a": {"citations": ["410 U.S. 113"]}}
    assert CitationRecall(cutoff=5).compute(["a"], {}, _ctx(docs, {})) == 0.0
    query = {"expected_citations": []}
    assert CitationRecall(cutoff=5).compute(["a"], {}, _ctx(docs, query)) == 0.0


def test_citation_recall_normalizes_both_sides() -> None:
    docs = {"a": {"citations": ["123 F. 3d 456"]}, "b": {"citations": "42 USC 1983"}}
    query = {"expected_citations": ["123 F.3d 456", "42 U.S.C. § 1983", "Unknown Act s. 2", "  "]}
    assert CitationRecall(cutoff=5).compute(["a", "b", "c"], {}, _ctx(docs, query)) == 2 / 3


def test_citation_recall_matches_unrecognized_strings_verbatim() -> None:
    docs = {"a": {"citations": ["Unknown Act s. 2", None]}}
    query = {"expected_citations": ["Unknown Act s. 2"]}
    assert CitationRecall(cutoff=1).compute(["a"], {}, _ctx(docs, query)) == 1.0


def test_citation_recall_tolerates_odd_metadata_values() -> None:
    docs = {"a": {"citations": 410}, "b": {"citations": None}}
    query = {"expected_citations": ["410"]}
    assert CitationRecall(cutoff=5).compute(["a", "b", "missing"], {}, _ctx(docs, query)) == 1.0


# -- Integration with corpus metadata -----------------------------------------


def test_metrics_consume_corpus_metadata() -> None:
    docs = [
        LegalDocument(
            doc_id="new",
            text="t",
            jurisdiction="US-NY",
            citations=["861 N.E. 3d 455"],
            status=PrecedentialStatus.GOOD_LAW,
        ),
        LegalDocument(
            doc_id="old", text="t", jurisdiction="US-NY", status=PrecedentialStatus.OVERRULED
        ),
        LegalDocument(doc_id="fed", text="t", jurisdiction="US-FED"),
    ]
    query = LegalQuery(
        query_id="q",
        text="t",
        jurisdiction="US-NY",
        expected_citations=["861 N.E.3d 455"],
    )
    context = MetricContext(query=query_metadata([query])["q"], documents=document_metadata(docs))
    ranking = ["old", "new", "fed"]
    assert BadLaw(cutoff=3).compute(ranking, {}, context) == pytest.approx(1 / 3)
    assert JurisdictionMatch(cutoff=3).compute(ranking, {}, context) == pytest.approx(2 / 3)
    assert CitationRecall(cutoff=2).compute(ranking, {}, context) == 1.0
    assert KeyAuthorityRecall(cutoff=1).compute(ranking, {"new": 3}, context) == 0.0


# -- Properties ---------------------------------------------------------------

_ids = st.sampled_from([f"d{i}" for i in range(8)])
_statuses = st.sampled_from(["good_law", "questioned", "overruled", "superseded", "unknown"])
_juris = st.sampled_from(["US-FED", "US-CA", "UK", None])


@given(
    ranking=st.lists(_ids, unique=True, max_size=8),
    meta=st.dictionaries(
        _ids,
        st.fixed_dictionaries(
            {"status": _statuses, "jurisdiction": _juris, "citations": st.just(["1 U.S. 1"])}
        ),
    ),
    judgments=st.dictionaries(_ids, st.integers(0, 3)),
    target=_juris,
    cutoff=st.integers(1, 10),
)
def test_legal_metrics_are_bounded(
    ranking: list[str],
    meta: dict[str, dict[str, Any]],
    judgments: dict[str, int],
    target: str | None,
    cutoff: int,
) -> None:
    context = MetricContext(
        query={"jurisdiction": target, "expected_citations": ["1 U.S. 1", "2 U.S. 2"]},
        documents=meta,
    )
    for cls in (BadLaw, JurisdictionMatch, KeyAuthorityRecall, CitationRecall):
        value = cls(cutoff=cutoff).compute(ranking, judgments, context)
        assert 0.0 <= value <= 1.0
