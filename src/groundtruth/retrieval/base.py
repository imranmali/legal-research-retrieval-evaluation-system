"""Retriever contract: fitting, searching, batch retrieval and persistence.

Ranking order
    Hits are ordered by descending score; equal scores are broken by
    **descending doc id**, the same order :func:`groundtruth.ranking.rank_documents`
    (and trec_eval) uses, so a run produced here ranks identically when evaluated.

Persistence format
    A gzip-compressed JSON object ``{"format": "groundtruth-index", "version": 1,
    "retriever": <name>, "params": {...}, "analyzer": {...}, "index": {...}}``.
    JSON is used instead of pickle so that loading an index never executes code.
"""

from __future__ import annotations

import gzip
import heapq
import json
import zlib
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final, Self

from groundtruth.errors import ConfigurationError, FormatError
from groundtruth.legal.analysis import LegalAnalyzer
from groundtruth.legal.corpus import LegalDocument, LegalQuery
from groundtruth.retrieval.index import InvertedIndex
from groundtruth.types import Run

__all__ = ["INDEX_FORMAT", "INDEX_VERSION", "Retriever", "SearchHit"]

#: ``format`` marker written into saved indexes.
INDEX_FORMAT: Final = "groundtruth-index"
#: Index file version written by this release; other versions are rejected on load.
INDEX_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One retrieved document and its score (higher is better)."""

    doc_id: str
    score: float


class Retriever(ABC):
    """Base class of the lexical baseline retrievers.

    Subclasses set :attr:`name`, accept their parameters as keyword arguments
    (plus ``analyzer``), report them from :meth:`get_params`, precompute
    collection statistics in :meth:`_prepare` and score in :meth:`_score`.
    """

    name: ClassVar[str]

    def __init__(self, *, analyzer: LegalAnalyzer | None = None) -> None:
        self.analyzer = analyzer if analyzer is not None else LegalAnalyzer()
        self._index: InvertedIndex | None = None

    # -- extension points -------------------------------------------------

    @abstractmethod
    def get_params(self) -> dict[str, Any]:
        """Constructor parameters (excluding ``analyzer``) as JSON-compatible values."""

    @abstractmethod
    def _prepare(self, index: InvertedIndex) -> None:
        """Precompute statistics (idf, length norms) for ``index``."""

    @abstractmethod
    def _score(self, index: InvertedIndex, terms: Counter[str]) -> dict[int, float]:
        """Accumulate scores term-at-a-time for analyzed query ``terms``.

        Returns ``doc_index -> score`` for documents matching at least one term.
        """

    # -- fitting and searching --------------------------------------------

    @property
    def is_fitted(self) -> bool:
        """Whether :meth:`fit` (or :meth:`load`) has provided an index."""
        return self._index is not None

    @property
    def index(self) -> InvertedIndex:
        """The fitted index; raises ConfigurationError before fitting."""
        if self._index is None:
            raise ConfigurationError(
                f"{type(self).__name__} is not fitted; call fit(documents) or load(path) first"
            )
        return self._index

    def _install(self, index: InvertedIndex) -> None:
        self._prepare(index)
        self._index = index

    def fit(self, documents: Iterable[LegalDocument]) -> Self:
        """Index ``documents`` (replacing any previous index) and return ``self``."""
        self._install(InvertedIndex.build(documents, self.analyzer))
        return self

    def search(
        self,
        query: str,
        k: int = 10,
        jurisdictions: Collection[str] | None = None,
    ) -> list[SearchHit]:
        """Return at most ``k`` hits for ``query``, best first.

        With ``jurisdictions``, only documents whose jurisdiction is in that
        collection are returned (documents without a jurisdiction never are).
        Ties are broken by descending doc id.
        """
        index = self.index
        if k < 1:
            raise ConfigurationError(f"k must be >= 1, got {k}")
        scores = self._score(index, Counter(self.analyzer.analyze(query)))
        candidates: Iterable[tuple[int, float]] = scores.items()
        if jurisdictions is not None:
            allowed = {jurisdictions} if isinstance(jurisdictions, str) else set(jurisdictions)
            doc_jurisdictions = index.jurisdictions
            candidates = [(i, s) for i, s in candidates if doc_jurisdictions[i] in allowed]
        doc_ids = index.doc_ids
        top = heapq.nlargest(k, candidates, key=lambda item: (item[1], doc_ids[item[0]]))
        return [SearchHit(doc_ids[i], score) for i, score in top]

    def retrieve(
        self,
        queries: Iterable[LegalQuery],
        k: int = 100,
        use_query_jurisdiction: bool = False,
    ) -> Run:
        """Search every query and return a run ``query_id -> {doc_id: score}``.

        Every query gets an entry (possibly empty). With
        ``use_query_jurisdiction``, a query that names a jurisdiction is
        restricted to it plus its binding jurisdictions.
        """
        run: Run = {}
        for query in queries:
            if query.query_id in run:
                raise ConfigurationError(f"duplicate query_id {query.query_id!r}")
            jurisdictions = query.jurisdictions if use_query_jurisdiction else None
            hits = self.search(query.text, k=k, jurisdictions=jurisdictions)
            run[query.query_id] = {hit.doc_id: hit.score for hit in hits}
        return run

    # -- persistence ------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Write the fitted index and configuration to ``path`` (gzip JSON)."""
        payload = {
            "format": INDEX_FORMAT,
            "version": INDEX_VERSION,
            "retriever": self.name,
            "params": self.get_params(),
            "analyzer": {
                "stopwords": sorted(self.analyzer.stopwords),
                "stem": self.analyzer.stem,
            },
            "index": self.index.to_dict(),
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        Path(path).write_bytes(gzip.compress(data, mtime=0))

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Restore a retriever saved with :meth:`save`.

        Called on :class:`Retriever` it returns whichever retriever the file
        holds; called on a subclass it also checks the stored retriever is of
        that class. Raises FormatError for unreadable files, foreign formats and
        unsupported versions.
        """
        from groundtruth.retrieval.registry import retriever_class  # avoid import cycle

        source = Path(path)
        try:
            payload = json.loads(gzip.decompress(source.read_bytes()).decode("utf-8"))
        except (OSError, EOFError, zlib.error, UnicodeDecodeError, ValueError) as exc:
            raise FormatError(f"{source}: not a readable index file: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("format") != INDEX_FORMAT:
            raise FormatError(f"{source}: not a {INDEX_FORMAT} file")
        version = payload.get("version")
        if version != INDEX_VERSION:
            raise FormatError(
                f"{source}: unsupported index version {version!r}; expected {INDEX_VERSION}"
            )
        try:
            target = retriever_class(str(payload.get("retriever")))
        except ConfigurationError as exc:
            raise FormatError(f"{source}: {exc}") from exc
        if not issubclass(target, cls):
            raise FormatError(
                f"{source}: index holds a {target.name!r} retriever, not {cls.__name__}"
            )
        try:
            analyzer_cfg = payload["analyzer"]
            analyzer = LegalAnalyzer(
                stopwords=frozenset(str(w) for w in analyzer_cfg["stopwords"]),
                stem=bool(analyzer_cfg["stem"]),
            )
            retriever = target(**payload.get("params", {}), analyzer=analyzer)
            index = InvertedIndex.from_dict(payload.get("index"))
        except (KeyError, TypeError, ConfigurationError, FormatError) as exc:
            raise FormatError(f"{source}: invalid index contents: {exc}") from exc
        retriever._install(index)
        return retriever

    def __repr__(self) -> str:
        params = ", ".join(f"{key}={value!r}" for key, value in self.get_params().items())
        state = "fitted" if self.is_fitted else "unfitted"
        return f"<{type(self).__name__}({params}) {state}>"
