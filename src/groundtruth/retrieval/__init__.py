"""Reproducible lexical retrieval baselines producing evaluation runs.

Available retrievers: ``bm25`` (:class:`BM25Retriever`), ``bm25-citation``
(:class:`CitationBoostedBM25`) and ``tfidf`` (:class:`TfidfRetriever`).
Hits are ordered by descending score, ties broken by descending doc id
(the order of :func:`groundtruth.ranking.rank_documents`).
"""

from groundtruth.retrieval.base import INDEX_FORMAT, INDEX_VERSION, Retriever, SearchHit
from groundtruth.retrieval.bm25 import BM25Retriever, CitationBoostedBM25
from groundtruth.retrieval.index import InvertedIndex
from groundtruth.retrieval.registry import (
    available_retrievers,
    get_retriever,
    register_retriever,
    retriever_class,
)
from groundtruth.retrieval.tfidf import TfidfRetriever

__all__ = [
    "INDEX_FORMAT",
    "INDEX_VERSION",
    "BM25Retriever",
    "CitationBoostedBM25",
    "InvertedIndex",
    "Retriever",
    "SearchHit",
    "TfidfRetriever",
    "available_retrievers",
    "get_retriever",
    "register_retriever",
    "retriever_class",
]
