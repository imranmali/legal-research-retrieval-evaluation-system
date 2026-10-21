"""Spec: retrieval-baselines / Index persistence."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from groundtruth.errors import ConfigurationError, FormatError
from groundtruth.legal import LegalAnalyzer, LegalDocument, load_documents
from groundtruth.retrieval import (
    INDEX_FORMAT,
    INDEX_VERSION,
    BM25Retriever,
    CitationBoostedBM25,
    InvertedIndex,
    Retriever,
    TfidfRetriever,
    get_retriever,
)

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
QUERIES = [
    "warrantless search of a cell phone incident to arrest",
    "duty of care public authority negligence",
    "17 USC 107 transformative fair use",
    "[2019] UKSC 87",
]


@pytest.fixture(scope="module")
def sample_docs() -> list[LegalDocument]:
    return load_documents(SAMPLE / "corpus.jsonl")


def _payload(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(gzip.decompress(path.read_bytes()))
    return data


def _write_payload(path: Path, payload: Any) -> Path:
    path.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
    return path


@pytest.fixture
def saved_bm25(tmp_path: Path, sample_docs: list[LegalDocument]) -> Path:
    path = tmp_path / "bm25.idx.gz"
    BM25Retriever().fit(sample_docs).save(path)
    return path


def test_save_and_load(tmp_path: Path, sample_docs: list[LegalDocument]) -> None:
    original = BM25Retriever().fit(sample_docs)
    path = tmp_path / "bm25.idx.gz"
    original.save(path)
    restored = BM25Retriever.load(path)
    for query in QUERIES:
        assert restored.search(query, k=10) == original.search(query, k=10)


@pytest.mark.parametrize("name", ["bm25", "bm25-citation", "tfidf"])
def test_round_trip_through_base_class_dispatch(
    name: str, tmp_path: Path, sample_docs: list[LegalDocument]
) -> None:
    original = get_retriever(name).fit(sample_docs)
    path = tmp_path / f"{name}.idx.gz"
    original.save(str(path))
    restored = Retriever.load(path)
    assert type(restored) is type(original)
    assert restored.get_params() == original.get_params()
    for query in QUERIES:
        for jurisdictions in (None, {"US-FED"}):
            assert restored.search(query, k=24, jurisdictions=jurisdictions) == original.search(
                query, k=24, jurisdictions=jurisdictions
            )


def test_parameters_and_analyzer_are_persisted(
    tmp_path: Path, sample_docs: list[LegalDocument]
) -> None:
    analyzer = LegalAnalyzer(stopwords=frozenset({"court"}), stem=False)
    original = CitationBoostedBM25(k1=1.3, b=0.6, citation_boost=4.0, analyzer=analyzer)
    original.fit(sample_docs).save(tmp_path / "x.gz")
    restored = CitationBoostedBM25.load(tmp_path / "x.gz")
    assert restored.get_params() == {"k1": 1.3, "b": 0.6, "citation_boost": 4.0}
    assert restored.analyzer == analyzer


def test_file_is_versioned_gzip_json(saved_bm25: Path) -> None:
    payload = _payload(saved_bm25)
    assert payload["format"] == INDEX_FORMAT == "groundtruth-index"
    assert payload["version"] == INDEX_VERSION == 1
    assert payload["retriever"] == "bm25"
    assert payload["params"] == {"k1": 0.9, "b": 0.4}


def test_saving_is_byte_for_byte_reproducible(
    tmp_path: Path, sample_docs: list[LegalDocument]
) -> None:
    BM25Retriever().fit(sample_docs).save(tmp_path / "a.gz")
    BM25Retriever().fit(sample_docs).save(tmp_path / "b.gz")
    assert (tmp_path / "a.gz").read_bytes() == (tmp_path / "b.gz").read_bytes()


def test_subclass_load_accepts_its_own_subclasses(tmp_path: Path) -> None:
    CitationBoostedBM25().fit([]).save(tmp_path / "c.gz")
    assert type(BM25Retriever.load(tmp_path / "c.gz")) is CitationBoostedBM25


def test_subclass_load_rejects_other_retrievers(saved_bm25: Path) -> None:
    with pytest.raises(FormatError, match="holds a 'bm25' retriever, not TfidfRetriever"):
        TfidfRetriever.load(saved_bm25)


def test_unknown_version_rejected(saved_bm25: Path) -> None:
    payload = _payload(saved_bm25)
    payload["version"] = 2
    _write_payload(saved_bm25, payload)
    with pytest.raises(FormatError, match="unsupported index version 2; expected 1"):
        Retriever.load(saved_bm25)


@pytest.mark.parametrize("payload", [{"format": "other", "version": 1}, ["not", "a", "dict"]])
def test_foreign_format_rejected(tmp_path: Path, payload: Any) -> None:
    path = _write_payload(tmp_path / "f.gz", payload)
    with pytest.raises(FormatError, match="not a groundtruth-index file"):
        Retriever.load(path)


def test_unknown_retriever_name_rejected(saved_bm25: Path) -> None:
    payload = _payload(saved_bm25)
    payload["retriever"] = "magic"
    _write_payload(saved_bm25, payload)
    with pytest.raises(FormatError, match="unknown retriever 'magic'"):
        Retriever.load(saved_bm25)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("analyzer"),
        lambda p: p.update(params={"k1": -1}),
        lambda p: p.update(params={"bogus": 1}),
        lambda p: p.update(params=[1, 2]),
        lambda p: p.update(index=None),
        lambda p: p["index"].update(postings={"x": [[999, 1]]}),
        lambda p: p["index"].update(postings={"x": [["a", 1]]}),
        lambda p: p["index"].update(doc_lengths=[]),
    ],
)
def test_invalid_contents_rejected(saved_bm25: Path, mutate: Any) -> None:
    payload = _payload(saved_bm25)
    mutate(payload)
    _write_payload(saved_bm25, payload)
    with pytest.raises(FormatError, match="invalid index contents"):
        Retriever.load(saved_bm25)


@pytest.mark.parametrize(
    "content",
    [b"plain text, not gzip", gzip.compress(b"{not json"), gzip.compress(b"\xff\xfe")],
)
def test_unreadable_files_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "bad.gz"
    path.write_bytes(content)
    with pytest.raises(FormatError, match="not a readable index file"):
        Retriever.load(path)


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(FormatError, match="not a readable index file"):
        Retriever.load(tmp_path / "absent.gz")


def test_saving_unfitted_retriever_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not fitted"):
        BM25Retriever().save(tmp_path / "x.gz")


def test_inverted_index_dict_round_trip(sample_docs: list[LegalDocument]) -> None:
    index = InvertedIndex.build(sample_docs, LegalAnalyzer())
    restored = InvertedIndex.from_dict(json.loads(json.dumps(index.to_dict())))
    assert restored == index
    assert restored.num_docs == 24
    assert restored.doc_freq("negligenc") == index.doc_freq("negligenc") > 0
    assert restored.doc_freq("absent-term") == 0
    assert InvertedIndex().avg_doc_length == 0.0
