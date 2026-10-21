"""Spec: legal-citations."""

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from groundtruth.legal.citations import (
    CASE_REPORTERS,
    Citation,
    extract_citations,
    normalize_citation,
)

# -- Requirement: Case reporter citations -----------------------------------


def test_supreme_court_citation() -> None:
    text = "see Roe v. Wade, 410 U.S. 113 (1973)"
    citations = extract_citations(text)
    assert citations == [Citation(kind="case", canonical="410 U.S. 113", start=17, end=29)]
    assert text[citations[0].start : citations[0].end] == "410 U.S. 113"


@pytest.mark.parametrize("text", ["123 F. 3d 456", "123 F.3d 456", "123 F 3d 456", "123 F.3rd 456"])
def test_spacing_variants_normalize(text: str) -> None:
    assert normalize_citation(text) == "123 F.3d 456"
    assert [c.canonical for c in extract_citations(f"See {text}.")] == ["123 F.3d 456"]


@pytest.mark.parametrize("reporter", CASE_REPORTERS)
def test_every_supported_reporter_is_recognized_in_canonical_form(reporter: str) -> None:
    citation = f"12 {reporter} 345"
    assert normalize_citation(citation) == citation
    (found,) = extract_citations(f"as held in {citation}, the rule applies")
    assert found.kind == "case"
    assert found.canonical == citation


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("93 S.Ct. 705", "93 S. Ct. 705"),
        ("93 S. Ct. 705", "93 S. Ct. 705"),
        ("35 L.Ed.2d 147", "35 L. Ed. 2d 147"),
        ("35 L. Ed. 147", "35 L. Ed. 147"),
        ("5 F.Supp.3d 6", "5 F. Supp. 3d 6"),
        ("5 F. Supp. 2nd 6", "5 F. Supp. 2d 6"),
        ("5 F. Supp. 6", "5 F. Supp. 6"),
        ("3 F.App'x 4", "3 F. App'x 4"),
        ("3 F. Appx 4", "3 F. App'x 4"),
        ("3 F. App\u2019x 4", "3 F. App'x 4"),
        ("7 F.4th 8", "7 F.4th 8"),
        ("12 N.E. 2d 4", "12 N.E.2d 4"),
        ("12 NE2d 4", "12 N.E.2d 4"),
        ("88 N.W.2d 101", "88 N.W.2d 101"),
        ("9 So.3d 1", "9 So. 3d 1"),
        ("9 So. 1", "9 So. 1"),
        ("410 US 113", "410 U.S. 113"),
        ("0410 U.S. 0113", "410 U.S. 113"),
        ("200 S.W.3d 9", "200 S.W.3d 9"),
        ("4 P. 5", "4 P. 5"),
    ],
)
def test_loose_reporter_spellings_normalize(text: str, canonical: str) -> None:
    assert normalize_citation(text) == canonical


@pytest.mark.parametrize(
    "text",
    [
        "5 A 6",  # single-letter reporters need their period
        "12 P 4",
        "in 2019 the court ruled",
        "F.3d alone",
        "123 F.3d",  # no page
        "123 F.3d456",  # page glued to the series
        "1x F.3d 4",
        "page 12 of the U.S. report",
    ],
)
def test_prose_is_not_mistaken_for_a_case_citation(text: str) -> None:
    assert [c for c in extract_citations(text) if c.kind == "case"] == []


# -- Requirement: Statutory and regulatory citations --------------------------


@pytest.mark.parametrize(
    "text",
    [
        "42 USC 1983",
        "42 U.S.C. § 1983",
        "42 U.S.C. §1983",
        "42 U.S.C. sec. 1983",
        "42 U.S.C. Sec. 1983",
        "42 U.S.C. section 1983",
        "42 U.S.C.A. § 1983",
        "42 U. S. C. § 1983",
    ],
)
def test_statute_variants(text: str) -> None:
    assert normalize_citation(text) == "42 U.S.C. § 1983"
    (citation,) = extract_citations(f"a claim under {text} for damages")
    assert citation.kind == "usc"
    assert citation.canonical == "42 U.S.C. § 1983"


def test_statute_with_hyphenated_section_and_subsection() -> None:
    text = "Title VII, 42 U.S.C. § 2000e-2(a), prohibits discrimination"
    (citation,) = extract_citations(text)
    assert citation.canonical == "42 U.S.C. § 2000e-2"
    assert text[citation.start : citation.end] == "42 U.S.C. § 2000e-2"


def test_usc_is_not_read_as_us_reporter() -> None:
    assert [c.kind for c in extract_citations("42 U.S.C. § 1983 and 42 USC 1981")] == [
        "usc",
        "usc",
    ]


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("29 C.F.R. § 1630.2", "29 C.F.R. § 1630.2"),
        ("29 CFR 1630.2", "29 C.F.R. § 1630.2"),
        ("29 C.F.R. sec. 1630", "29 C.F.R. § 1630"),
        ("16 C.F.R. § 312.5a", "16 C.F.R. § 312.5a"),
    ],
)
def test_cfr_citations(text: str, canonical: str) -> None:
    assert normalize_citation(text) == canonical
    (citation,) = extract_citations(f"see {text}.")
    assert citation.kind == "cfr"


def test_cfr_section_does_not_swallow_sentence_period() -> None:
    (citation,) = extract_citations("governed by 29 C.F.R. § 1630.2. The court")
    assert citation.canonical == "29 C.F.R. § 1630.2"


# -- Requirement: UK neutral citations ----------------------------------------


def test_court_of_appeal_citation() -> None:
    (citation,) = extract_citations("as decided in [2019] EWCA Civ 123, the duty")
    assert citation.kind == "neutral"
    assert citation.canonical == "[2019] EWCA Civ 123"


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("[2020] UKSC 5", "[2020] UKSC 5"),
        ("[2018] EWHC 456 (Ch)", "[2018] EWHC 456 (Ch)"),
        ("[2018] EWHC 456(ch)", "[2018] EWHC 456 (Ch)"),
        ("[2019] ewca  civ 0123", "[2019] EWCA Civ 123"),
        ("[2009] UKHL 12", "[2009] UKHL 12"),
        ("[2021] EWCA Crim 7", "[2021] EWCA Crim 7"),
        ("[2022] EWHC 99 (KB)", "[2022] EWHC 99 (KB)"),
    ],
)
def test_neutral_citation_variants(text: str, canonical: str) -> None:
    assert normalize_citation(text) == canonical


def test_unknown_uk_court_is_not_recognized() -> None:
    assert extract_citations("[2019] ABCD 12") == []


# -- Requirement: Normalization of single citations ---------------------------


def test_unrecognized_string() -> None:
    assert normalize_citation("hello world") is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "Roe v. Wade, 410 U.S. 113",  # leading prose
        "410 U.S. 113 and 42 U.S.C. § 1983",  # two citations
        "410 U.S. 113 is the leading case",  # trailing prose
    ],
)
def test_normalize_rejects_anything_but_a_single_citation(text: str) -> None:
    assert normalize_citation(text) is None


@pytest.mark.parametrize(
    "text",
    ["  410 U.S. 113  ", "410 U.S. 113 (1973)", "410 U.S. 113,", "410 U.S. 113 (2d Cir. 1990)."],
)
def test_normalize_tolerates_whitespace_punctuation_and_parenthetical(text: str) -> None:
    assert normalize_citation(text) == "410 U.S. 113"


def test_extract_orders_by_position_without_overlap() -> None:
    text = (
        "Compare [2019] UKSC 87 with 410 U.S. 113, 93 S. Ct. 705 (1973), "
        "42 USC 1983 and 29 C.F.R. § 1630.2."
    )
    citations = extract_citations(text)
    assert [c.canonical for c in citations] == [
        "[2019] UKSC 87",
        "410 U.S. 113",
        "93 S. Ct. 705",
        "42 U.S.C. § 1983",
        "29 C.F.R. § 1630.2",
    ]
    assert [c.kind for c in citations] == ["neutral", "case", "case", "usc", "cfr"]
    for earlier, later in itertools.pairwise(citations):
        assert earlier.end <= later.start


def test_citation_is_immutable() -> None:
    citation = Citation(kind="case", canonical="1 U.S. 1", start=0, end=8)
    with pytest.raises(AttributeError):
        citation.canonical = "2 U.S. 2"  # type: ignore[misc]


# -- Properties ---------------------------------------------------------------

_reporters = st.sampled_from(CASE_REPORTERS)
_numbers = st.integers(min_value=1, max_value=9999)
_prose = st.text(alphabet="abcdefghijklmnopqrstuvwxyz ,", max_size=30)


@given(volume=_numbers, reporter=_reporters, page=_numbers, before=_prose, after=_prose)
def test_case_citation_found_in_surrounding_prose(
    volume: int, reporter: str, page: int, before: str, after: str
) -> None:
    canonical = f"{volume} {reporter} {page}"
    text = f"{before} {canonical} {after}"
    (citation,) = extract_citations(text)
    assert citation.canonical == canonical
    assert text[citation.start : citation.end] == canonical


@given(title=st.integers(1, 99), section=st.integers(1, 99999), statute=st.booleans())
def test_statutory_normalization_is_idempotent(title: int, section: int, statute: bool) -> None:
    raw = f"{title} USC {section}" if statute else f"{title} CFR {section}"
    canonical = normalize_citation(raw)
    assert canonical is not None
    assert normalize_citation(canonical) == canonical


@given(st.text(max_size=200))
def test_extraction_is_total_ordered_and_non_overlapping(text: str) -> None:
    citations = extract_citations(text)
    for citation in citations:
        assert 0 <= citation.start < citation.end <= len(text)
        assert normalize_citation(citation.canonical) == citation.canonical
    for earlier, later in itertools.pairwise(citations):
        assert earlier.end <= later.start


def test_overlapping_matches_keep_the_earlier_citation() -> None:
    # "2 F.3d 4" would start inside the statute match "1 USC 2".
    assert [c.canonical for c in extract_citations("1 USC 2 F.3d 4")] == ["1 U.S.C. § 2"]
