"""The fictional sample collection in data/sample loads and is fit for demos."""

from collections import Counter
from pathlib import Path

import pytest

from groundtruth.legal import (
    KEY_AUTHORITY_GRADE,
    LegalDocument,
    LegalQuery,
    PrecedentialStatus,
    load_documents,
    load_queries,
    normalize_citation,
)
from groundtruth.retrieval import BM25Retriever

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"


def _load_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        query_id, iteration, doc_id, grade = line.split()
        assert iteration == "0"
        qrels.setdefault(query_id, {})[doc_id] = int(grade)
    return qrels


@pytest.fixture(scope="module")
def documents() -> list[LegalDocument]:
    return load_documents(SAMPLE / "corpus.jsonl")


@pytest.fixture(scope="module")
def queries() -> list[LegalQuery]:
    return load_queries(SAMPLE / "queries.jsonl")


@pytest.fixture(scope="module")
def qrels() -> dict[str, dict[str, int]]:
    return _load_qrels(SAMPLE / "qrels.txt")


def test_sample_collection_loads(documents: list[LegalDocument], queries: list[LegalQuery]) -> None:
    assert len(documents) == 24
    assert len(queries) == 8
    assert {d.jurisdiction for d in documents} == {"US-FED", "US-CA", "US-NY", "UK"}
    assert all(q.jurisdiction for q in queries)
    assert all(q.expected_citations for q in queries)


def test_sample_has_bad_law_and_questioned_authority(documents: list[LegalDocument]) -> None:
    statuses = Counter(d.status for d in documents)
    assert statuses[PrecedentialStatus.OVERRULED] >= 3
    assert statuses[PrecedentialStatus.SUPERSEDED] >= 1
    assert statuses[PrecedentialStatus.QUESTIONED] >= 1
    assert statuses[PrecedentialStatus.UNKNOWN] == 0


def test_sample_documents_are_well_formed(documents: list[LegalDocument]) -> None:
    for doc in documents:
        assert doc.text.count(". ") >= 2, doc.doc_id  # at least three sentences
        assert 200 <= len(doc.text) <= 1200, doc.doc_id
        assert doc.title
        assert doc.court
        assert doc.decision_date
        for citation in (*doc.citations, *doc.cites):
            assert normalize_citation(citation) == citation, (doc.doc_id, citation)


def test_qrels_reference_known_ids_and_valid_grades(
    documents: list[LegalDocument], queries: list[LegalQuery], qrels: dict[str, dict[str, int]]
) -> None:
    doc_ids = {d.doc_id for d in documents}
    assert set(qrels) == {q.query_id for q in queries}
    for judged in qrels.values():
        assert set(judged) <= doc_ids
        assert set(judged.values()) <= {0, 1, 2, 3}
        assert KEY_AUTHORITY_GRADE in judged.values()
        assert any(grade < KEY_AUTHORITY_GRADE for grade in judged.values())


def test_overruled_documents_are_judged_relevant_somewhere(
    documents: list[LegalDocument], qrels: dict[str, dict[str, int]]
) -> None:
    bad = {
        d.doc_id
        for d in documents
        if d.status in {PrecedentialStatus.OVERRULED, PrecedentialStatus.SUPERSEDED}
    }
    relevant_bad = {d for judged in qrels.values() for d, g in judged.items() if d in bad and g > 0}
    assert len(relevant_bad) >= 3


def test_expected_citations_point_at_key_authorities(
    documents: list[LegalDocument], queries: list[LegalQuery], qrels: dict[str, dict[str, int]]
) -> None:
    by_citation = {c: d.doc_id for d in documents for c in d.citations}
    for query in queries:
        for citation in query.expected_citations:
            assert qrels[query.query_id][by_citation[citation]] == KEY_AUTHORITY_GRADE


def test_bm25_is_reasonable_but_imperfect_on_sample(
    documents: list[LegalDocument], queries: list[LegalQuery], qrels: dict[str, dict[str, int]]
) -> None:
    bm25 = BM25Retriever().fit(documents)
    top1 = {q.query_id: bm25.search(q.text, k=1)[0].doc_id for q in queries}
    relevant_top1 = sum(qrels[qid].get(doc_id, 0) > 0 for qid, doc_id in top1.items())
    key_top1 = sum(qrels[qid].get(doc_id, 0) == KEY_AUTHORITY_GRADE for qid, doc_id in top1.items())
    assert relevant_top1 >= 6
    assert key_top1 < len(queries)  # not a solved collection


def test_readme_states_data_is_fictional() -> None:
    readme = (SAMPLE / "README.md").read_text(encoding="utf-8")
    assert "FICTIONAL" in readme
    assert "Do not cite" in readme
    for grade in ("0", "1", "2", "3"):
        assert f"| {grade}     |" in readme
