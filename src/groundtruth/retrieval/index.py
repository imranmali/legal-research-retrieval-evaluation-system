"""In-memory inverted index shared by the lexical retrievers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from groundtruth.errors import ConfigurationError, FormatError
from groundtruth.legal.analysis import LegalAnalyzer, citation_token
from groundtruth.legal.corpus import LegalDocument

__all__ = ["InvertedIndex", "document_terms"]


def document_terms(document: LegalDocument, analyzer: LegalAnalyzer) -> list[str]:
    """Index terms of a document.

    The title and text are analyzed; the document's own ``citations`` are
    added as citation tokens (so a query citing a case finds that case), as
    are entries of ``cites`` that do not already occur in the text.
    """
    terms = analyzer.analyze(document.title) if document.title else []
    terms.extend(analyzer.analyze(document.text))
    present = set(terms)
    for canonical in (*document.citations, *document.cites):
        token = citation_token(canonical)
        if token not in present:
            present.add(token)
            terms.append(token)
    return terms


@dataclass
class InvertedIndex:
    """Postings ``term -> {doc_index: term_frequency}`` plus per-document data.

    Documents are addressed by their position (``doc_index``) in ``doc_ids``.
    """

    doc_ids: list[str] = field(default_factory=list)
    doc_lengths: list[int] = field(default_factory=list)
    jurisdictions: list[str | None] = field(default_factory=list)
    postings: dict[str, dict[int, int]] = field(default_factory=dict)

    @classmethod
    def build(cls, documents: Iterable[LegalDocument], analyzer: LegalAnalyzer) -> InvertedIndex:
        """Analyze and index ``documents``; duplicate doc ids raise ConfigurationError."""
        index = cls()
        seen: set[str] = set()
        for document in documents:
            if document.doc_id in seen:
                raise ConfigurationError(f"duplicate doc_id {document.doc_id!r} in corpus")
            seen.add(document.doc_id)
            doc_index = len(index.doc_ids)
            counts = Counter(document_terms(document, analyzer))
            index.doc_ids.append(document.doc_id)
            index.doc_lengths.append(sum(counts.values()))
            index.jurisdictions.append(document.jurisdiction)
            for term, tf in counts.items():
                index.postings.setdefault(term, {})[doc_index] = tf
        return index

    @property
    def num_docs(self) -> int:
        """Number of indexed documents."""
        return len(self.doc_ids)

    @property
    def avg_doc_length(self) -> float:
        """Mean document length in terms (0.0 for an empty index)."""
        return sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0

    def doc_freq(self, term: str) -> int:
        """Number of documents containing ``term``."""
        return len(self.postings.get(term, ()))

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation (postings keys become strings)."""
        return {
            "doc_ids": list(self.doc_ids),
            "doc_lengths": list(self.doc_lengths),
            "jurisdictions": list(self.jurisdictions),
            "postings": {
                term: [[doc_index, tf] for doc_index, tf in plist.items()]
                for term, plist in self.postings.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Any) -> InvertedIndex:
        """Rebuild an index from :meth:`to_dict` output, validating its structure."""
        try:
            doc_ids = [str(d) for d in data["doc_ids"]]
            doc_lengths = [int(n) for n in data["doc_lengths"]]
            jurisdictions = [None if j is None else str(j) for j in data["jurisdictions"]]
            postings = {
                str(term): {int(doc_index): int(tf) for doc_index, tf in plist}
                for term, plist in data["postings"].items()
            }
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise FormatError(f"malformed index data: {exc!r}") from exc
        size = len(doc_ids)
        if len(doc_lengths) != size or len(jurisdictions) != size:
            raise FormatError("malformed index data: per-document arrays differ in length")
        if any(not 0 <= i < size for plist in postings.values() for i in plist):
            raise FormatError("malformed index data: posting refers to an unknown document")
        return cls(doc_ids, doc_lengths, jurisdictions, postings)
