"""Spec: retrieval-baselines / Citation-preserving analysis (analyzer level)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from groundtruth.legal.analysis import (
    CITATION_TOKEN_PREFIX,
    DEFAULT_STOPWORDS,
    LegalAnalyzer,
    citation_token,
    light_stem,
)


def test_citation_kept_as_single_canonical_token() -> None:
    tokens = LegalAnalyzer().analyze("A claim under 42 USC 1983 for damages")
    assert tokens == ["claim", "§cite:42 U.S.C. § 1983", "damag"]


def test_citation_variants_produce_the_same_token() -> None:
    analyzer = LegalAnalyzer()
    a = analyzer.analyze("relief under 42 U.S.C. § 1983")
    b = analyzer.analyze("relief under 42 USC 1983")
    assert a == b
    assert citation_token("42 U.S.C. § 1983") in a


def test_lowercases_and_drops_punctuation() -> None:
    assert LegalAnalyzer(stem=False).analyze("Negligence, DUTY; Breach!") == [
        "negligence",
        "duty",
        "breach",
    ]


def test_default_stopwords_removed() -> None:
    tokens = LegalAnalyzer(stem=False).analyze("The duty of the court in Roe v. Wade")
    assert tokens == ["duty", "court", "roe", "wade"]
    assert {"the", "of", "in", "v"} <= DEFAULT_STOPWORDS


def test_custom_and_empty_stopwords() -> None:
    assert LegalAnalyzer(stopwords=frozenset({"Court"}), stem=False).analyze("the court") == ["the"]
    assert LegalAnalyzer(stopwords=frozenset(), stem=False).analyze("the court") == [
        "the",
        "court",
    ]


def test_possessive_suffix_removed() -> None:
    analyzer = LegalAnalyzer(stem=False)
    assert analyzer.analyze("the employer's reason") == ["employer", "reason"]
    assert analyzer.analyze("the employer\u2019s reason") == ["employer", "reason"]


def test_unicode_words_are_kept() -> None:
    assert LegalAnalyzer(stem=False).analyze("Café société") == ["café", "société"]


def test_stemming_conflates_inflections() -> None:
    analyzer = LegalAnalyzer()
    forms = ["discriminate", "discriminated", "discriminating", "discrimination", "discriminations"]
    assert len({tuple(analyzer.analyze(form)) for form in forms}) == 1
    assert analyzer.analyze("searches searched searching") == ["search"] * 3


def test_stemming_can_be_disabled() -> None:
    assert LegalAnalyzer(stem=False).analyze("searches") == ["searches"]


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("parties", "party"),
        ("ties", "tie"),
        ("classes", "class"),
        ("searches", "search"),
        ("boxes", "box"),
        ("cases", "case"),
        ("status", "status"),
        ("analysis", "analysis"),
        ("witness", "witness"),
        ("stopped", "stop"),
        ("committed", "commit"),
        ("filled", "fill"),
        ("employed", "employ"),
        ("employees", "employee"),
        ("relational", "relat"),
        ("nation", "nation"),
        ("accommodation", "accommodat"),
        ("bring", "bring"),
        ("spring", "spring"),
        ("need", "need"),
        ("law", "law"),
        ("1983", "1983"),
        ("f3d", "f3d"),
    ],
)
def test_light_stem(word: str, stem: str) -> None:
    assert light_stem(word) == stem


def test_analyzer_equality_hash_and_repr() -> None:
    assert LegalAnalyzer() == LegalAnalyzer(stopwords=DEFAULT_STOPWORDS, stem=True)
    assert hash(LegalAnalyzer()) == hash(LegalAnalyzer())
    assert LegalAnalyzer() != LegalAnalyzer(stem=False)
    assert LegalAnalyzer() != "analyzer"
    assert "stem=True" in repr(LegalAnalyzer())


@given(st.text(max_size=300))
def test_word_tokens_never_collide_with_citation_tokens(text: str) -> None:
    for token in LegalAnalyzer(stem=False).analyze(text):
        assert token
        if token.startswith(CITATION_TOKEN_PREFIX):
            assert len(token) > len(CITATION_TOKEN_PREFIX)
        else:
            assert "§" not in token
            assert token not in DEFAULT_STOPWORDS


@given(st.text(max_size=300))
def test_analysis_is_deterministic(text: str) -> None:
    analyzer = LegalAnalyzer()
    assert analyzer.analyze(text) == analyzer.analyze(text)
