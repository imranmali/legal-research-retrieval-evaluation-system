"""Core data aliases.

Relevance judgments and runs use plain nested dicts (the same convention as
trec_eval / pytrec_eval) so that large files stay cheap to hold and iterate.
"""

from collections.abc import Mapping
from typing import Any, TypeAlias

#: query_id -> doc_id -> graded relevance (0 = not relevant, higher = more relevant).
Qrels: TypeAlias = dict[str, dict[str, int]]

#: query_id -> doc_id -> retrieval score (higher = ranked earlier).
Run: TypeAlias = dict[str, dict[str, float]]

#: doc_id -> arbitrary metadata (e.g. jurisdiction, court, precedential status).
DocMetadata: TypeAlias = Mapping[str, Mapping[str, Any]]

#: query_id -> arbitrary metadata (e.g. the jurisdiction the research targets).
QueryMetadata: TypeAlias = Mapping[str, Mapping[str, Any]]
