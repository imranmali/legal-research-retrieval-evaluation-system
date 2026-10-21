"""Okapi BM25 and a citation-boosted variant."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from groundtruth.errors import ConfigurationError
from groundtruth.legal.analysis import CITATION_TOKEN_PREFIX, LegalAnalyzer
from groundtruth.retrieval.base import Retriever
from groundtruth.retrieval.index import InvertedIndex

__all__ = ["BM25Retriever", "CitationBoostedBM25"]


class BM25Retriever(Retriever):
    """Okapi BM25 with the Lucene idf ``ln(1 + (N - df + 0.5) / (df + 0.5))``.

    ``k1`` (>= 0) controls term-frequency saturation and ``b`` (in [0, 1])
    length normalization. The defaults (0.9, 0.4) are the Anserini baseline values.
    """

    name = "bm25"

    def __init__(
        self,
        k1: float = 0.9,
        b: float = 0.4,
        *,
        analyzer: LegalAnalyzer | None = None,
    ) -> None:
        super().__init__(analyzer=analyzer)
        if not (math.isfinite(k1) and k1 >= 0):
            raise ConfigurationError(f"bm25: k1 must be a finite number >= 0, got {k1!r}")
        if not 0 <= b <= 1:
            raise ConfigurationError(f"bm25: b must be in [0, 1], got {b!r}")
        self.k1 = float(k1)
        self.b = float(b)
        self._idf: dict[str, float] = {}
        self._length_norms: list[float] = []

    def get_params(self) -> dict[str, Any]:
        """``{"k1": ..., "b": ...}``."""
        return {"k1": self.k1, "b": self.b}

    def term_weight(self, term: str) -> float:  # noqa: ARG002 - hook for subclasses
        """Multiplier applied to a query term's contribution (1.0 here)."""
        return 1.0

    def _prepare(self, index: InvertedIndex) -> None:
        n = index.num_docs
        self._idf = {
            term: math.log(1.0 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for term, plist in index.postings.items()
        }
        avgdl = index.avg_doc_length or 1.0
        self._length_norms = [
            self.k1 * (1.0 - self.b + self.b * length / avgdl) for length in index.doc_lengths
        ]

    def _score(self, index: InvertedIndex, terms: Counter[str]) -> dict[int, float]:
        scores: dict[int, float] = {}
        norms = self._length_norms
        saturation = self.k1 + 1.0
        for term, query_tf in terms.items():
            plist = index.postings.get(term)
            if not plist:
                continue
            weight = self._idf[term] * query_tf * self.term_weight(term) * saturation
            for doc_index, tf in plist.items():
                scores[doc_index] = scores.get(doc_index, 0.0) + weight * tf / (
                    tf + norms[doc_index]
                )
        return scores


class CitationBoostedBM25(BM25Retriever):
    """BM25 whose citation query terms count ``citation_boost`` times as much.

    Citations are precise signals in legal research: a query citing
    ``42 U.S.C. § 1983`` is very likely after documents that cite it.
    """

    name = "bm25-citation"

    def __init__(
        self,
        k1: float = 0.9,
        b: float = 0.4,
        citation_boost: float = 2.0,
        *,
        analyzer: LegalAnalyzer | None = None,
    ) -> None:
        super().__init__(k1=k1, b=b, analyzer=analyzer)
        if not (math.isfinite(citation_boost) and citation_boost > 0):
            raise ConfigurationError(
                f"bm25-citation: citation_boost must be a finite number > 0, got {citation_boost!r}"
            )
        self.citation_boost = float(citation_boost)

    def get_params(self) -> dict[str, Any]:
        """``{"k1": ..., "b": ..., "citation_boost": ...}``."""
        return {**super().get_params(), "citation_boost": self.citation_boost}

    def term_weight(self, term: str) -> float:
        """``citation_boost`` for citation tokens, 1.0 otherwise."""
        return self.citation_boost if term.startswith(CITATION_TOKEN_PREFIX) else 1.0
