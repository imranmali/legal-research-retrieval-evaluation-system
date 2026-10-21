"""Turning scored runs into rankings."""

from collections.abc import Mapping


def rank_documents(scores: Mapping[str, float], depth: int | None = None) -> list[str]:
    """Order doc ids by descending score, breaking ties by descending doc id.

    The tie-break matches trec_eval, so results are reproducible and comparable
    with established tooling. ``depth`` truncates the ranking when given.
    """
    ordered = sorted(scores.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    ranking = [doc_id for doc_id, _ in ordered]
    return ranking if depth is None else ranking[:depth]
