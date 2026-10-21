"""Citation-preserving text analysis for legal retrieval.

:class:`LegalAnalyzer` turns text into index terms: recognized citations
become single canonical tokens (``§cite:42 U.S.C. § 1983``) and the remaining
prose is lowercased, split on non-word characters, filtered for stopwords and
lightly stemmed. Because ``§`` is never part of a word token, citation tokens
cannot collide with ordinary terms.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Final

from groundtruth.legal.citations import extract_citations

__all__ = [
    "CITATION_TOKEN_PREFIX",
    "DEFAULT_STOPWORDS",
    "LegalAnalyzer",
    "citation_token",
    "light_stem",
]

#: Prefix marking a canonical citation token produced by :class:`LegalAnalyzer`.
CITATION_TOKEN_PREFIX: Final = "§cite:"

#: English function words plus the case-name connective ``v``/``vs``.
_STOPWORD_TEXT: Final = """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself his how
    i if in into is it its itself just may me might more most must my myself no nor not
    now of off on once only or other our ours ourselves out over own same shall she should
    so some such than that the their theirs them themselves then there these they this
    those through to too under until up upon very was we were what when where which while
    who whom why will with would you your yours yourself yourselves s v vs
"""
DEFAULT_STOPWORDS: Final[frozenset[str]] = frozenset(_STOPWORD_TEXT.split())

_WORD_RE: Final = re.compile(r"[^\W_]+")
_POSSESSIVE_RE: Final = re.compile("['\u2019]s\\b", re.IGNORECASE)
_VOWELS: Final = frozenset("aeiouy")
_NO_UNDOUBLE: Final = frozenset("lsz")


def citation_token(canonical: str) -> str:
    """Index term for a canonical citation."""
    return CITATION_TOKEN_PREFIX + canonical


def _has_vowel(stem: str) -> bool:
    return any(ch in _VOWELS for ch in stem)


@lru_cache(maxsize=1 << 17)
def light_stem(token: str) -> str:
    """Conservative English suffix stripping.

    Handles plurals (``searches`` → ``search``, ``parties`` → ``party``),
    ``-ing`` / ``-ed`` (``searching`` → ``search``), ``-ation`` and a trailing
    ``e`` so that ``discriminate``, ``discriminated``, ``discriminating`` and
    ``discrimination`` share one stem. Tokens of three characters or fewer
    and tokens containing digits are returned unchanged.
    """
    if len(token) <= 3 or not token.isalpha():
        return token
    word = token
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("sses") or word.endswith(("ches", "shes", "xes", "zes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]

    if word.endswith("ational"):
        word = word[:-7] + "ate"
    elif word.endswith("ation") and len(word) > 7:
        word = word[:-5] + "ate"
    else:
        for suffix in ("ing", "ed"):
            stem = word[: -len(suffix)]
            if word.endswith(suffix) and len(stem) >= 3 and _has_vowel(stem):
                word = stem
                if len(word) > 3 and word[-1] == word[-2] and word[-1] not in _NO_UNDOUBLE:
                    word = word[:-1]
                break

    if len(word) > 4 and word.endswith("e") and not word.endswith("ee"):
        word = word[:-1]
    return word


class LegalAnalyzer:
    """Tokenizer that keeps legal citations intact.

    ``stopwords`` defaults to :data:`DEFAULT_STOPWORDS`; pass an empty set to
    keep every word. ``stem`` toggles :func:`light_stem`. Stopwords are
    matched before stemming, against the lowercased word.
    """

    def __init__(self, stopwords: frozenset[str] | None = None, stem: bool = True) -> None:
        self.stopwords: frozenset[str] = (
            DEFAULT_STOPWORDS if stopwords is None else frozenset(w.lower() for w in stopwords)
        )
        self.stem = stem

    def _words(self, segment: str) -> list[str]:
        words = _WORD_RE.findall(_POSSESSIVE_RE.sub("", segment).lower())
        kept = [w for w in words if w not in self.stopwords]
        return [light_stem(w) for w in kept] if self.stem else kept

    def analyze(self, text: str) -> list[str]:
        """Convert ``text`` into an ordered list of index terms."""
        tokens: list[str] = []
        position = 0
        for citation in extract_citations(text):
            tokens.extend(self._words(text[position : citation.start]))
            tokens.append(citation_token(citation.canonical))
            position = citation.end
        tokens.extend(self._words(text[position:]))
        return tokens

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LegalAnalyzer):
            return NotImplemented
        return self.stopwords == other.stopwords and self.stem == other.stem

    def __hash__(self) -> int:
        return hash((self.stopwords, self.stem))

    def __repr__(self) -> str:
        return f"LegalAnalyzer(stopwords=<{len(self.stopwords)} words>, stem={self.stem})"
