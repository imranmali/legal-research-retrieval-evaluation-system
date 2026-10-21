"""Recognizing and normalizing legal citations.

Four citation families are recognized:

* ``case`` — US case reporters (``410 U.S. 113``, ``123 F.3d 456``, ``5 So. 3d 77``),
* ``usc`` — the United States Code (``42 U.S.C. § 1983``),
* ``cfr`` — the Code of Federal Regulations (``29 C.F.R. § 1630.2``),
* ``neutral`` — UK neutral citations (``[2019] EWCA Civ 123``, ``[2018] EWHC 456 (Ch)``).

Every citation is reduced to one canonical spelling so that variants such as
``123 F. 3d 456`` / ``123 F.3d 456`` or ``42 USC 1983`` / ``42 U.S.C. § 1983``
compare equal. Pin cites and short forms (``id.``, ``supra``) are out of scope.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

__all__ = [
    "CASE_REPORTERS",
    "Citation",
    "CitationKind",
    "extract_citations",
    "normalize_citation",
]

#: The citation families recognized by :func:`extract_citations`.
CitationKind: TypeAlias = Literal["case", "usc", "cfr", "neutral"]


@dataclass(frozen=True, slots=True)
class Citation:
    """A citation found in text.

    ``canonical`` is the normalized spelling; ``start`` / ``end`` are the
    character offsets of the matched span in the source text (``end`` exclusive).
    """

    kind: CitationKind
    canonical: str
    start: int
    end: int


#: Canonical abbreviations of the supported US case reporters.
CASE_REPORTERS: Final[tuple[str, ...]] = (
    "U.S.",
    "S. Ct.",
    "L. Ed.",
    "L. Ed. 2d",
    "F.",
    "F.2d",
    "F.3d",
    "F.4th",
    "F. Supp.",
    "F. Supp. 2d",
    "F. Supp. 3d",
    "F. App'x",
    "A.",
    "A.2d",
    "A.3d",
    "N.E.",
    "N.E.2d",
    "N.E.3d",
    "N.W.",
    "N.W.2d",
    "P.",
    "P.2d",
    "P.3d",
    "S.E.",
    "S.E.2d",
    "S.W.",
    "S.W.2d",
    "S.W.3d",
    "So.",
    "So. 2d",
    "So. 3d",
)

_SERIES_PATTERNS: Final[dict[str, str]] = {
    "2d": "(?:2d|2nd)",
    "3d": "(?:3d|3rd)",
    "4th": "4th",
}
_PIECE_RE: Final = re.compile(r"[A-Za-z0-9']+")


def _reporter_key(text: str) -> str:
    """Spelling-insensitive lookup key for a reporter abbreviation."""
    key = re.sub("[\\s.'\u2019]", "", text).lower()
    return key.replace("2nd", "2d").replace("3rd", "3d")


def _reporter_pattern(canonical: str) -> str:
    """Regex accepting loose spellings of ``canonical`` (optional dots and spaces)."""
    pieces = _PIECE_RE.findall(canonical)
    parts: list[str] = []
    for piece in pieces:
        if piece in _SERIES_PATTERNS:
            parts.append(_SERIES_PATTERNS[piece])
        elif piece == "App'x":
            parts.append("App(?:['\u2019]x|x)\\.?")
        else:
            # A lone single-word reporter (``F.``, ``A.``, ``P.``, ``So.``) must keep its
            # period, otherwise ordinary prose such as ``5 A 6`` would match.
            dot = r"\." if len(pieces) == 1 else r"\.?"
            parts.append(re.escape(piece) + dot)
    return r"\s*".join(parts)


_REPORTER_CANONICAL: Final[dict[str, str]] = {_reporter_key(r): r for r in CASE_REPORTERS}

_CASE_RE: Final = re.compile(
    r"(?<![\w.])(?P<volume>\d{1,4})\s+(?P<reporter>"
    + "|".join(_reporter_pattern(r) for r in sorted(CASE_REPORTERS, key=lambda r: (-len(r), r)))
    + r")\s+(?P<page>\d{1,5})(?![\w])"
)

_SECTION_WORD: Final = r"(?:§§?|(?i:sec(?:tion)?s?)\.?)"

_USC_RE: Final = re.compile(
    r"(?<![\w.])(?P<title>\d{1,3})\s+U\.?\s*S\.?\s*C\.?(?:\s*A\.?)?\s*"
    + _SECTION_WORD
    + r"?\s*(?P<section>\d+[A-Za-z]*(?:-\d+[A-Za-z]*)*)(?![\w])"
)

_CFR_RE: Final = re.compile(
    r"(?<![\w.])(?P<title>\d{1,3})\s+C\.?\s*F\.?\s*R\.?\s*"
    + _SECTION_WORD
    + r"?\s*(?P<section>\d+(?:\.\d+)?[a-z]?)(?![\w])"
)

_NEUTRAL_COURTS: Final[tuple[str, ...]] = (
    "UKSC",
    "UKPC",
    "UKHL",
    "EWCA Civ",
    "EWCA Crim",
    "EWHC",
    "EWCOP",
    "EWFC",
    "UKUT",
    "UKFTT",
    "UKEAT",
    "CSIH",
    "CSOH",
    "NICA",
    "NIQB",
)
_NEUTRAL_DIVISIONS: Final[tuple[str, ...]] = (
    "Admin",
    "Admlty",
    "Ch",
    "Comm",
    "Costs",
    "Fam",
    "IPEC",
    "KB",
    "Pat",
    "QB",
    "TCC",
)
_COURT_CANONICAL: Final[dict[str, str]] = {
    re.sub(r"\s+", " ", c).upper(): c for c in _NEUTRAL_COURTS
}
_DIVISION_CANONICAL: Final[dict[str, str]] = {d.upper(): d for d in _NEUTRAL_DIVISIONS}

_NEUTRAL_RE: Final = re.compile(
    r"\[(?P<year>\d{4})\]\s*(?P<court>"
    + "|".join(c.replace(" ", r"\s+") for c in _NEUTRAL_COURTS)
    + r")\s+(?P<number>\d{1,5})(?:\s*\((?P<division>"
    + "|".join(_NEUTRAL_DIVISIONS)
    + r")\))?(?![\w])",
    re.IGNORECASE,
)


def _canonical_case(match: re.Match[str]) -> str:
    reporter = _REPORTER_CANONICAL[_reporter_key(match["reporter"])]
    return f"{int(match['volume'])} {reporter} {int(match['page'])}"


def _canonical_usc(match: re.Match[str]) -> str:
    return f"{int(match['title'])} U.S.C. § {match['section']}"


def _canonical_cfr(match: re.Match[str]) -> str:
    return f"{int(match['title'])} C.F.R. § {match['section']}"


def _canonical_neutral(match: re.Match[str]) -> str:
    court = _COURT_CANONICAL[re.sub(r"\s+", " ", match["court"]).upper()]
    canonical = f"[{match['year']}] {court} {int(match['number'])}"
    if match["division"]:
        canonical += f" ({_DIVISION_CANONICAL[match['division'].upper()]})"
    return canonical


_Extractor: TypeAlias = tuple[CitationKind, re.Pattern[str], Callable[[re.Match[str]], str]]

_EXTRACTORS: Final[tuple[_Extractor, ...]] = (
    ("usc", _USC_RE, _canonical_usc),
    ("cfr", _CFR_RE, _canonical_cfr),
    ("neutral", _NEUTRAL_RE, _canonical_neutral),
    ("case", _CASE_RE, _canonical_case),
)


#: Every citation form contains a digit followed by whitespace and a capital letter
#: (volume/title before the reporter or code) or opens with ``[`` and a digit (neutral
#: citations); text without either is skipped without running the full patterns.
_TRIGGER_RE: Final = re.compile(r"\d\s+[A-Z]|\[\d")


def extract_citations(text: str) -> list[Citation]:
    """Find every recognized citation in ``text``.

    Results are ordered by position and never overlap; where two patterns
    match overlapping spans the earlier, then longer, match wins.
    """
    if _TRIGGER_RE.search(text) is None:
        return []
    candidates: list[Citation] = []
    for kind, pattern, canonicalize in _EXTRACTORS:
        candidates.extend(
            Citation(kind=kind, canonical=canonicalize(m), start=m.start(), end=m.end())
            for m in pattern.finditer(text)
        )
    candidates.sort(key=lambda c: (c.start, -(c.end - c.start)))
    selected: list[Citation] = []
    for citation in candidates:
        if not selected or citation.start >= selected[-1].end:
            selected.append(citation)
    return selected


_LEFTOVER_RE: Final = re.compile(r"[\s,.;:]*(?:\([^()]*\))?[\s,.;:]*")


def normalize_citation(text: str) -> str | None:
    """Return the canonical form of a standalone citation, or ``None``.

    The string must hold exactly one recognized citation; surrounding
    whitespace, punctuation and one trailing parenthetical (``(1973)``,
    ``(2d Cir. 2001)``) are tolerated. Anything else, e.g. ``"hello world"``
    or a sentence quoting a citation, yields ``None``.
    """
    stripped = text.strip()
    citations = extract_citations(stripped)
    if len(citations) != 1:
        return None
    (citation,) = citations
    if stripped[: citation.start].strip(" \t\n,.;:"):
        return None
    if _LEFTOVER_RE.fullmatch(stripped[citation.end :]) is None:
        return None
    return citation.canonical
