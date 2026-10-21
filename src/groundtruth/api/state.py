"""Per-process service state created by the app factory."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from groundtruth.api.middleware import HttpMetrics
from groundtruth.config import Settings
from groundtruth.legal import LegalDocument, load_documents
from groundtruth.retrieval import Retriever, get_retriever

__all__ = ["ServiceState"]

logger = logging.getLogger("groundtruth.api")


@dataclass
class ServiceState:
    """Configuration, metrics and the optional search corpus of one worker process.

    Populated during startup and shared read-only by requests afterwards.
    """

    settings: Settings
    metrics: HttpMetrics = field(default_factory=HttpMetrics)
    ready: bool = False
    retriever: Retriever | None = None
    documents: dict[str, LegalDocument] = field(default_factory=dict)

    def load_corpus(self) -> None:
        """Load ``settings.corpus_path`` (if set) and fit the configured retriever on it."""
        path = self.settings.corpus_path
        if path is None:
            return
        started = time.perf_counter()
        documents = load_documents(path)
        retriever = get_retriever(self.settings.retriever).fit(documents)
        self.documents = {doc.doc_id: doc for doc in documents}
        self.retriever = retriever
        self.metrics.corpus_documents.set(len(documents))
        logger.info(
            "corpus indexed",
            extra={
                "corpus": {
                    "path": str(path),
                    "documents": len(documents),
                    "retriever": retriever.name,
                    "seconds": round(time.perf_counter() - started, 3),
                }
            },
        )
