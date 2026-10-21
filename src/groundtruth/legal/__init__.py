"""Legal-domain building blocks: citations, analysis, corpus model and metrics.

Importing this package registers the legal metrics (``BadLaw``,
``JurisdictionMatch``, ``KeyAuthorityRecall``/``KAR`` and ``CitationRecall``)
in the shared metric registry.
"""

from groundtruth.legal.analysis import CITATION_TOKEN_PREFIX, LegalAnalyzer
from groundtruth.legal.citations import Citation, extract_citations, normalize_citation
from groundtruth.legal.corpus import (
    LegalDocument,
    LegalQuery,
    PrecedentialStatus,
    document_metadata,
    load_documents,
    load_queries,
    query_metadata,
)
from groundtruth.legal.metrics import (
    KEY_AUTHORITY_GRADE,
    BadLaw,
    CitationRecall,
    JurisdictionMatch,
    KeyAuthorityRecall,
)

__all__ = [
    "CITATION_TOKEN_PREFIX",
    "KEY_AUTHORITY_GRADE",
    "BadLaw",
    "Citation",
    "CitationRecall",
    "JurisdictionMatch",
    "KeyAuthorityRecall",
    "LegalAnalyzer",
    "LegalDocument",
    "LegalQuery",
    "PrecedentialStatus",
    "document_metadata",
    "extract_citations",
    "load_documents",
    "load_queries",
    "normalize_citation",
    "query_metadata",
]
