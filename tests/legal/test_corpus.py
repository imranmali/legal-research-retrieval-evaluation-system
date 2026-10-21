"""Spec: legal-corpus."""

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from groundtruth.errors import FormatError
from groundtruth.legal.corpus import (
    LegalDocument,
    LegalQuery,
    PrecedentialStatus,
    document_metadata,
    load_documents,
    load_queries,
    normalize_citation_list,
    query_metadata,
)


def _write_jsonl(path: Path, records: list[Any]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


# -- Requirement: Legal documents ---------------------------------------------


def test_default_status(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "docs.jsonl", [{"doc_id": "d1", "text": "x"}])
    (doc,) = load_documents(path)
    assert doc.status is PrecedentialStatus.UNKNOWN


def test_document_defaults() -> None:
    doc = LegalDocument(doc_id="d1", text="body")
    assert doc.title == ""
    assert doc.jurisdiction is None
    assert doc.court is None
    assert doc.decision_date is None
    assert doc.citations == []
    assert doc.cites == []


def test_document_full_record() -> None:
    doc = LegalDocument.model_validate(
        {
            "doc_id": " d1 ",
            "text": "body",
            "title": "Roe v. Wade",
            "jurisdiction": " US-FED ",
            "court": "Supreme Court",
            "decision_date": "1973-01-22",
            "citations": ["410 U.S. 113", "93 S.Ct. 705"],
            "cites": ["123 F. 3d 456", "Restatement (Second) of Torts", "123 F.3d 456"],
            "status": "Good Law",
        }
    )
    assert doc.doc_id == "d1"
    assert doc.jurisdiction == "US-FED"
    assert doc.decision_date == date(1973, 1, 22)
    assert doc.citations == ["410 U.S. 113", "93 S. Ct. 705"]
    assert doc.cites == ["123 F.3d 456", "Restatement (Second) of Torts"]
    assert doc.status is PrecedentialStatus.GOOD_LAW


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("overruled", PrecedentialStatus.OVERRULED),
        ("OVERRULED", PrecedentialStatus.OVERRULED),
        ("good-law", PrecedentialStatus.GOOD_LAW),
        (" superseded ", PrecedentialStatus.SUPERSEDED),
        ("questioned", PrecedentialStatus.QUESTIONED),
        (None, PrecedentialStatus.UNKNOWN),
        (PrecedentialStatus.OVERRULED, PrecedentialStatus.OVERRULED),
    ],
)
def test_status_parsing(raw: Any, status: PrecedentialStatus) -> None:
    assert LegalDocument(doc_id="d", text="t", status=raw).status is status


def test_invalid_status_rejected() -> None:
    with pytest.raises(ValidationError):
        LegalDocument(doc_id="d", text="t", status="vacated")  # type: ignore[arg-type]


@pytest.mark.parametrize("doc_id", ["", "   "])
def test_blank_doc_id_rejected(doc_id: str) -> None:
    with pytest.raises(ValidationError):
        LegalDocument(doc_id=doc_id, text="t")


def test_blank_optional_text_becomes_none() -> None:
    doc = LegalDocument(doc_id="d", text="t", jurisdiction="  ", court="")
    assert doc.jurisdiction is None
    assert doc.court is None


def test_documents_are_immutable() -> None:
    doc = LegalDocument(doc_id="d", text="t")
    with pytest.raises(ValidationError):
        doc.text = "changed"  # type: ignore[misc]


def test_normalize_citation_list() -> None:
    assert normalize_citation_list(["42 USC 1983", " ", "42 U.S.C. § 1983", "Some Act s. 4"]) == [
        "42 U.S.C. § 1983",
        "Some Act s. 4",
    ]


# -- Requirement: Research queries --------------------------------------------


def test_query_with_jurisdiction() -> None:
    query = LegalQuery(query_id="q1", text="interactive process", jurisdiction="US-CA")
    assert query.jurisdiction == "US-CA"
    assert query.jurisdictions == frozenset({"US-CA"})
    assert query_metadata([query])["q1"]["jurisdiction"] == "US-CA"


def test_query_binding_jurisdictions_and_expected_citations() -> None:
    query = LegalQuery(
        query_id="q1",
        text="t",
        jurisdiction="US-CA",
        binding_jurisdictions=["US-FED", " US-FED ", ""],
        expected_citations=["410 US 113"],
    )
    assert query.binding_jurisdictions == ["US-FED"]
    assert query.jurisdictions == frozenset({"US-CA", "US-FED"})
    assert query.expected_citations == ["410 U.S. 113"]


def test_query_without_jurisdiction_has_no_scope() -> None:
    query = LegalQuery(query_id="q1", text="t", binding_jurisdictions=["US-FED"])
    assert query.jurisdiction is None
    assert query.jurisdictions is None


# -- Requirement: JSONL loading -----------------------------------------------


def test_load_documents_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    path.write_text(
        '{"doc_id": "d1", "text": "a"}\n\n   \n{"doc_id": "d2", "text": "b", "extra": 1}\n',
        encoding="utf-8",
    )
    assert [d.doc_id for d in load_documents(path)] == ["d1", "d2"]


def test_load_gzip_compressed(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl.gz"
    path.write_bytes(gzip.compress(b'{"doc_id": "d1", "text": "a", "status": "overruled"}\n'))
    (doc,) = load_documents(str(path))
    assert doc.status is PrecedentialStatus.OVERRULED


def test_gzip_detected_by_content_not_name(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_bytes(gzip.compress(b'{"query_id": "q1", "text": "a"}\n'))
    assert [q.query_id for q in load_queries(path)] == ["q1"]


def test_duplicate_id(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "docs.jsonl",
        [
            {"doc_id": "d1", "text": "a"},
            {"doc_id": "d2", "text": "b"},
            {"doc_id": "d1", "text": "c"},
        ],
    )
    with pytest.raises(FormatError, match=r"docs\.jsonl:3: duplicate doc_id 'd1'.*line 1"):
        load_documents(path)


def test_duplicate_query_id(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "q.jsonl", [{"query_id": "q1", "text": "a"}, {"query_id": "q1", "text": "b"}]
    )
    with pytest.raises(FormatError, match=r"q\.jsonl:2: duplicate query_id 'q1'"):
        load_queries(path)


def test_invalid_json_names_line(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    path.write_text('{"doc_id": "d1", "text": "a"}\n{not json}\n', encoding="utf-8")
    with pytest.raises(FormatError, match=r"docs\.jsonl:2: invalid JSON"):
        load_documents(path)


def test_non_object_record_rejected(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "docs.jsonl", [["d1", "text"]])
    with pytest.raises(FormatError, match=r":1: expected a JSON object, got list"):
        load_documents(path)


def test_invalid_record_names_line_and_field(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "docs.jsonl", [{"doc_id": "d1", "text": "a"}, {"doc_id": "d2"}])
    with pytest.raises(FormatError, match=r"docs\.jsonl:2: invalid record: text: Field required"):
        load_documents(path)


def test_invalid_date_rejected(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "docs.jsonl", [{"doc_id": "d1", "text": "a", "decision_date": "yesterday"}]
    )
    with pytest.raises(FormatError, match="decision_date"):
        load_documents(path)


def test_missing_file_is_a_format_error(tmp_path: Path) -> None:
    with pytest.raises(FormatError, match="cannot read file"):
        load_documents(tmp_path / "absent.jsonl")


def test_corrupt_gzip_is_a_format_error(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl.gz"
    path.write_bytes(gzip.compress(b'{"doc_id": "d1", "text": "a"}\n' * 50)[:40])
    with pytest.raises(FormatError, match="cannot read file"):
        load_documents(path)


def test_invalid_utf8_is_a_format_error(tmp_path: Path) -> None:
    path = tmp_path / "docs.jsonl"
    path.write_bytes(b'{"doc_id": "d1", "text": "\xff"}\n')
    with pytest.raises(FormatError, match="cannot read file"):
        load_documents(path)


# -- Requirement: Evaluation metadata -----------------------------------------


def test_metadata_from_corpus() -> None:
    docs = [
        LegalDocument(
            doc_id="d1",
            text="t",
            status="overruled",  # type: ignore[arg-type]
            jurisdiction="US-NY",
            citations=["702 N.E. 2d 1189"],
        ),
        LegalDocument(doc_id="d2", text="t"),
    ]
    meta = document_metadata(docs)
    assert meta == {
        "d1": {"status": "overruled", "jurisdiction": "US-NY", "citations": ["702 N.E.2d 1189"]},
        "d2": {"status": "unknown", "jurisdiction": None, "citations": []},
    }
    assert type(meta["d1"]["status"]) is str


def test_query_metadata() -> None:
    queries = [
        LegalQuery(
            query_id="q1",
            text="t",
            jurisdiction="UK",
            binding_jurisdictions=["EU"],
            expected_citations=["[2019] ukSC 87"],
        )
    ]
    assert query_metadata(queries) == {
        "q1": {
            "jurisdiction": "UK",
            "binding_jurisdictions": ["EU"],
            "expected_citations": ["[2019] UKSC 87"],
        }
    }


def test_non_string_status_rejected() -> None:
    with pytest.raises(ValidationError):
        LegalDocument(doc_id="d", text="t", status=3)  # type: ignore[arg-type]
