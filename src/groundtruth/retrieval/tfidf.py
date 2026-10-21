"""TF-IDF vector-space retrieval with cosine similarity."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from groundtruth.legal.analysis import LegalAnalyzer
from groundtruth.retrieval.base import Retriever
from groundtruth.retrieval.index import InvertedIndex

__all__ = ["TfidfRetriever"]


class TfidfRetriever(Retriever):
    """Cosine similarity of log-tf x idf vectors.

    Term weights are ``(1 + ln tf) * idf`` with the smoothed idf
    ``ln((1 + N) / (1 + df)) + 1``; document and query vectors are
    L2-normalized, so scores lie in [0, 1].
    """

    name = "tfidf"

    def __init__(self, *, analyzer: LegalAnalyzer | None = None) -> None:
        super().__init__(analyzer=analyzer)
        self._idf: dict[str, float] = {}
        self._doc_norms: list[float] = []

    def get_params(self) -> dict[str, Any]:
        """TF-IDF has no tunable parameters; returns ``{}``."""
        return {}

    def _prepare(self, index: InvertedIndex) -> None:
        n = index.num_docs
        self._idf = {
            term: math.log((1.0 + n) / (1.0 + len(plist))) + 1.0
            for term, plist in index.postings.items()
        }
        squares = [0.0] * n
        for term, plist in index.postings.items():
            idf = self._idf[term]
            for doc_index, tf in plist.items():
                weight = (1.0 + math.log(tf)) * idf
                squares[doc_index] += weight * weight
        self._doc_norms = [math.sqrt(s) for s in squares]

    def _score(self, index: InvertedIndex, terms: Counter[str]) -> dict[int, float]:
        query_weights = {
            term: (1.0 + math.log(query_tf)) * self._idf[term]
            for term, query_tf in terms.items()
            if term in self._idf
        }
        if not query_weights:
            return {}
        query_norm = math.sqrt(sum(w * w for w in query_weights.values()))
        dots: dict[int, float] = {}
        for term, query_weight in query_weights.items():
            idf = self._idf[term]
            for doc_index, tf in index.postings[term].items():
                dots[doc_index] = (
                    dots.get(doc_index, 0.0) + query_weight * (1.0 + math.log(tf)) * idf
                )
        norms = self._doc_norms
        return {i: dot / (query_norm * norms[i]) for i, dot in dots.items()}
