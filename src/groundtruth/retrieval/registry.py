"""Name-based lookup of retriever implementations."""

from __future__ import annotations

from typing import Any, TypeVar

from groundtruth.errors import ConfigurationError
from groundtruth.retrieval.base import Retriever
from groundtruth.retrieval.bm25 import BM25Retriever, CitationBoostedBM25
from groundtruth.retrieval.tfidf import TfidfRetriever

__all__ = [
    "available_retrievers",
    "get_retriever",
    "register_retriever",
    "retriever_class",
]

_RETRIEVERS: dict[str, type[Retriever]] = {}

R = TypeVar("R", bound=type[Retriever])


def register_retriever(cls: R) -> R:
    """Make ``cls`` selectable by its (case-insensitive) ``name``."""
    key = cls.name.lower()
    existing = _RETRIEVERS.get(key)
    if existing is not None and existing is not cls:
        raise ConfigurationError(f"retriever name {cls.name!r} already registered")
    _RETRIEVERS[key] = cls
    return cls


for _builtin in (BM25Retriever, CitationBoostedBM25, TfidfRetriever):
    register_retriever(_builtin)


def available_retrievers() -> list[str]:
    """Registered retriever names, sorted."""
    return sorted(cls.name for cls in _RETRIEVERS.values())


def retriever_class(name: str) -> type[Retriever]:
    """Resolve a retriever name to its class; unknown names raise ConfigurationError."""
    cls = _RETRIEVERS.get(name.strip().lower())
    if cls is None:
        available = ", ".join(available_retrievers())
        raise ConfigurationError(f"unknown retriever {name!r}; available: {available}")
    return cls


def get_retriever(name: str, **params: Any) -> Retriever:
    """Instantiate the retriever called ``name`` with keyword ``params``.

    Unknown names and invalid parameters raise ConfigurationError.
    """
    cls = retriever_class(name)
    try:
        return cls(**params)
    except TypeError as exc:
        raise ConfigurationError(f"invalid parameters for retriever {cls.name!r}: {exc}") from exc
