"""Spec: retrieval-baselines (retrievers, filtering, runs)."""

import math
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from groundtruth.errors import ConfigurationError
from groundtruth.legal import LegalAnalyzer, LegalDocument, LegalQuery, load_documents
from groundtruth.ranking import rank_documents
from groundtruth.retrieval import (
    BM25Retriever,
    CitationBoostedBM25,
    Retriever,
    SearchHit,
    TfidfRetriever,
    available_retrievers,
    get_retriever,
    register_retriever,
    retriever_class,
)

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
ALL_RETRIEVERS = ["bm25", "bm25-citation", "tfidf"]


def _doc(doc_id: str, text: str, jurisdiction: str | None = None, **extra: object) -> LegalDocument:
    return LegalDocument.model_validate(
        {"doc_id": doc_id, "text": text, "jurisdiction": jurisdiction, **extra}
    )


@pytest.fixture(scope="module")
def sample_docs() -> list[LegalDocument]:
    return load_documents(SAMPLE / "corpus.jsonl")


@pytest.fixture
def small_corpus() -> list[LegalDocument]:
    return [
        _doc("cal-1", "Employer failed the interactive process for disability.", "US-CA"),
        _doc("cal-2", "Wage and hour claim for unpaid overtime.", "US-CA"),
        _doc("fed-1", "Disability accommodation under federal law.", "US-FED"),
        _doc("ny-1", "Disability discrimination in New York employment.", "US-NY"),
        _doc("none-1", "Disability benefits appeal.", None),
    ]


# -- Requirement: Citation-preserving analysis --------------------------------


def test_citation_match_across_variants() -> None:
    docs = [
        _doc("with-cite", "The plaintiff brought a claim under 42 U.S.C. § 1983 against officers."),
        _doc("claim-1", "A breach of contract claim and a second claim for fraud."),
        _doc("claim-2", "The claim was dismissed; the claim lacked merit."),
    ]
    hits = BM25Retriever().fit(docs).search("42 USC 1983 claim", k=3)
    assert hits[0].doc_id == "with-cite"
    assert all(hit.score < hits[0].score for hit in hits[1:])


def test_documents_are_found_by_their_own_citation() -> None:
    docs = [
        _doc("roe", "Opinion text without its own reporter cite.", citations=["410 U.S. 113"]),
        _doc("other", "Opinion text."),
    ]
    hits = BM25Retriever().fit(docs).search("410 US 113")
    assert [hit.doc_id for hit in hits] == ["roe"]


def test_cited_authorities_are_indexed_once() -> None:
    doc = _doc("d", "Relying on 42 U.S.C. § 1983.", cites=["42 USC 1983", "17 U.S.C. § 107"])
    retriever = BM25Retriever().fit([doc])
    postings = retriever.index.postings
    assert postings["§cite:42 U.S.C. § 1983"] == {0: 1}
    assert postings["§cite:17 U.S.C. § 107"] == {0: 1}


# -- Requirement: Baseline retrievers -----------------------------------------


def test_unknown_retriever() -> None:
    with pytest.raises(
        ConfigurationError, match=r"unknown retriever 'magic'.*bm25, bm25-citation, tfidf"
    ):
        get_retriever("magic")


def test_available_retrievers() -> None:
    assert available_retrievers() == ALL_RETRIEVERS


@pytest.mark.parametrize(
    ("name", "cls"),
    [("bm25", BM25Retriever), ("BM25-Citation", CitationBoostedBM25), (" tfidf ", TfidfRetriever)],
)
def test_get_retriever_by_name(name: str, cls: type[Retriever]) -> None:
    assert type(get_retriever(name)) is cls
    assert retriever_class(name) is cls


def test_get_retriever_passes_parameters() -> None:
    retriever = get_retriever("bm25-citation", k1=1.2, b=0.75, citation_boost=3.0)
    assert retriever.get_params() == {"k1": 1.2, "b": 0.75, "citation_boost": 3.0}
    assert get_retriever("tfidf").get_params() == {}


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("bm25", {"k1": -1.0}),
        ("bm25", {"k1": math.inf}),
        ("bm25", {"b": 1.5}),
        ("bm25", {"b": math.nan}),
        ("bm25-citation", {"citation_boost": 0.0}),
        ("bm25", {"unknown": 1}),
        ("tfidf", {"k1": 1.0}),
    ],
)
def test_invalid_parameters_raise_configuration_error(name: str, params: dict[str, float]) -> None:
    with pytest.raises(ConfigurationError):
        get_retriever(name, **params)


def test_register_retriever_rejects_name_clash() -> None:
    class Impostor(BM25Retriever):
        name = "bm25"

    with pytest.raises(ConfigurationError, match="already registered"):
        register_retriever(Impostor)
    assert register_retriever(BM25Retriever) is BM25Retriever


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_deterministic_results(name: str, sample_docs: list[LegalDocument]) -> None:
    query = "duty of care negligence public authority"
    first = get_retriever(name).fit(sample_docs).search(query, k=10)
    second = get_retriever(name).fit(sample_docs).search(query, k=10)
    assert first == second


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_ties_broken_by_descending_doc_id(name: str) -> None:
    docs = [_doc(doc_id, "identical negligence text") for doc_id in ["b", "d", "a", "c"]]
    docs.append(_doc("z", "unrelated words"))
    hits = get_retriever(name).fit(docs).search("negligence", k=10)
    assert [hit.doc_id for hit in hits] == ["d", "c", "b", "a"]
    assert len({hit.score for hit in hits}) == 1
    assert [hit.doc_id for hit in hits] == rank_documents({h.doc_id: h.score for h in hits})


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_at_most_k_hits_in_descending_score_order(
    name: str, sample_docs: list[LegalDocument]
) -> None:
    hits = get_retriever(name).fit(sample_docs).search("search warrant arrest phone", k=4)
    assert len(hits) == 4
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_bm25_score_matches_formula() -> None:
    docs = [_doc("a", "alpha alpha beta"), _doc("b", "beta gamma"), _doc("c", "delta")]
    k1, b = 1.2, 0.75
    hits = BM25Retriever(k1=k1, b=b).fit(docs).search("alpha", k=3)
    n, df, tf, dl, avgdl = 3, 1, 2, 3, 2.0
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    expected = idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
    assert hits == [SearchHit("a", pytest.approx(expected))]  # type: ignore[arg-type]


def test_bm25_counts_repeated_query_terms() -> None:
    docs = [_doc("a", "alpha beta"), _doc("b", "gamma")]
    retriever = BM25Retriever().fit(docs)
    once = retriever.search("alpha")[0].score
    twice = retriever.search("alpha alpha")[0].score
    assert twice == pytest.approx(2 * once)


def test_bm25_with_zero_k1_is_binary() -> None:
    docs = [_doc("a", "alpha alpha alpha"), _doc("b", "alpha beta gamma")]
    hits = BM25Retriever(k1=0.0, b=0.0).fit(docs).search("alpha", k=2)
    assert hits[0].score == pytest.approx(hits[1].score)


def test_citation_boost_multiplies_citation_terms_only() -> None:
    docs = [
        _doc("a", "Claim under 42 U.S.C. § 1983 for excessive force."),
        _doc("b", "Excessive force in an arrest."),
        _doc("c", "Contract dispute."),
    ]
    plain = BM25Retriever().fit(docs)
    boosted = CitationBoostedBM25(citation_boost=3.0).fit(docs)
    cite_plain = plain.search("42 USC 1983")[0].score
    cite_boosted = boosted.search("42 USC 1983")[0].score
    assert cite_boosted == pytest.approx(3.0 * cite_plain)
    assert boosted.search("excessive force") == plain.search("excessive force")


def test_tfidf_scores_are_cosine_similarities() -> None:
    docs = [_doc("same", "fair use transformative"), _doc("other", "fair dealing parody")]
    hits = TfidfRetriever().fit(docs).search("transformative fair use", k=2)
    assert hits[0].doc_id == "same"
    assert hits[0].score == pytest.approx(1.0)
    assert 0.0 < hits[1].score < 1.0


def test_tfidf_query_with_only_unknown_terms_returns_nothing() -> None:
    assert TfidfRetriever().fit([_doc("a", "alpha")]).search("zeta omega") == []


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_query_without_indexed_terms_returns_no_hits(name: str) -> None:
    retriever = get_retriever(name).fit([_doc("a", "alpha")])
    assert retriever.search("zeta") == []
    assert retriever.search("the of and") == []


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_empty_corpus_returns_no_hits(name: str) -> None:
    assert get_retriever(name).fit([]).search("anything") == []


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_documents_without_terms_are_harmless(name: str) -> None:
    retriever = get_retriever(name).fit([_doc("empty", ""), _doc("stop", "the of"), _doc("a", "x")])
    assert [hit.doc_id for hit in retriever.search("x")] == ["a"]


def test_search_before_fit_raises() -> None:
    with pytest.raises(ConfigurationError, match="not fitted"):
        BM25Retriever().search("query")
    assert not BM25Retriever().is_fitted


@pytest.mark.parametrize("k", [0, -1])
def test_invalid_k_rejected(k: int, small_corpus: list[LegalDocument]) -> None:
    with pytest.raises(ConfigurationError, match="k must be >= 1"):
        BM25Retriever().fit(small_corpus).search("disability", k=k)


def test_duplicate_doc_ids_rejected() -> None:
    with pytest.raises(ConfigurationError, match="duplicate doc_id 'a'"):
        BM25Retriever().fit([_doc("a", "x"), _doc("a", "y")])


def test_fit_returns_self_and_refit_replaces_index(small_corpus: list[LegalDocument]) -> None:
    retriever = BM25Retriever()
    assert retriever.fit(small_corpus) is retriever
    assert retriever.is_fitted
    retriever.fit([_doc("only", "overtime")])
    assert [hit.doc_id for hit in retriever.search("overtime")] == ["only"]


def test_custom_analyzer_is_used() -> None:
    retriever = BM25Retriever(analyzer=LegalAnalyzer(stem=False)).fit([_doc("a", "searches")])
    assert retriever.search("search") == []
    assert [hit.doc_id for hit in retriever.search("searches")] == ["a"]


def test_repr_mentions_parameters_and_state() -> None:
    retriever = BM25Retriever(k1=1.5)
    assert repr(retriever) == "<BM25Retriever(k1=1.5, b=0.4) unfitted>"
    retriever.fit([])
    assert repr(retriever).endswith("fitted>")


# -- Requirement: Jurisdiction filtering --------------------------------------


@pytest.mark.parametrize("name", ALL_RETRIEVERS)
def test_filter_applied(name: str, small_corpus: list[LegalDocument]) -> None:
    retriever = get_retriever(name).fit(small_corpus)
    by_id = {doc.doc_id: doc for doc in small_corpus}
    unfiltered = retriever.search("disability", k=10)
    assert len(unfiltered) == 4
    hits = retriever.search("disability", k=10, jurisdictions={"US-CA"})
    assert [hit.doc_id for hit in hits] == ["cal-1"]
    assert all(by_id[hit.doc_id].jurisdiction == "US-CA" for hit in hits)


def test_filter_with_several_jurisdictions_and_strings(small_corpus: list[LegalDocument]) -> None:
    retriever = BM25Retriever().fit(small_corpus)
    hits = retriever.search("disability", jurisdictions=["US-FED", "US-NY"])
    assert {hit.doc_id for hit in hits} == {"fed-1", "ny-1"}
    assert [h.doc_id for h in retriever.search("disability", jurisdictions="US-NY")] == ["ny-1"]
    assert retriever.search("disability", jurisdictions=set()) == []


def test_filter_respects_k_after_filtering(small_corpus: list[LegalDocument]) -> None:
    hits = BM25Retriever().fit(small_corpus).search("disability", k=1, jurisdictions={"US-NY"})
    assert [hit.doc_id for hit in hits] == ["ny-1"]


# -- Requirement: Batch retrieval to runs -------------------------------------


def test_run_for_queries(sample_docs: list[LegalDocument]) -> None:
    queries = [
        LegalQuery(query_id="q1", text="court held employer search contract duty data claim"),
        LegalQuery(query_id="q2", text="fair use"),
        LegalQuery(query_id="q3", text="xyzzy"),
    ]
    run = BM25Retriever().fit(sample_docs).retrieve(queries, k=10)
    assert list(run) == ["q1", "q2", "q3"]
    assert all(len(docs) <= 10 for docs in run.values())
    assert len(run["q1"]) == 10
    assert 0 < len(run["q2"]) < 10
    assert run["q3"] == {}


def test_run_ranking_matches_search_order(sample_docs: list[LegalDocument]) -> None:
    retriever = TfidfRetriever().fit(sample_docs)
    query = LegalQuery(query_id="q", text="search incident to arrest")
    run = retriever.retrieve([query], k=5)
    assert rank_documents(run["q"]) == [hit.doc_id for hit in retriever.search(query.text, k=5)]


def test_run_uses_query_jurisdictions(small_corpus: list[LegalDocument]) -> None:
    queries = [
        LegalQuery(
            query_id="ca",
            text="disability",
            jurisdiction="US-CA",
            binding_jurisdictions=["US-FED"],
        ),
        LegalQuery(query_id="any", text="disability"),
    ]
    retriever = BM25Retriever().fit(small_corpus)
    filtered = retriever.retrieve(queries, k=10, use_query_jurisdiction=True)
    assert set(filtered["ca"]) == {"cal-1", "fed-1"}
    assert len(filtered["any"]) == 4
    unfiltered = retriever.retrieve(queries, k=10)
    assert len(unfiltered["ca"]) == 4


def test_run_rejects_duplicate_query_ids(small_corpus: list[LegalDocument]) -> None:
    queries = [LegalQuery(query_id="q", text="a"), LegalQuery(query_id="q", text="b")]
    with pytest.raises(ConfigurationError, match="duplicate query_id 'q'"):
        BM25Retriever().fit(small_corpus).retrieve(queries)


# -- Properties ---------------------------------------------------------------

_QUERY_WORDS = [
    *("search", "warrant", "phone", "arrest", "duty", "care", "negligence", "contract"),
    *("offer", "acceptance", "privacy", "data", "fair", "use", "copyright", "disability"),
    *("employer", "42", "USC", "1983", "410", "U.S.", "113"),
]


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=50)
@given(
    words=st.lists(
        st.sampled_from(_QUERY_WORDS),
        min_size=1,
        max_size=8,
    ),
    k=st.integers(1, 30),
    name=st.sampled_from(ALL_RETRIEVERS),
    jurisdictions=st.one_of(
        st.none(), st.sets(st.sampled_from(["US-FED", "US-CA", "US-NY", "UK"]))
    ),
)
def test_search_invariants(
    sample_docs: list[LegalDocument],
    words: list[str],
    k: int,
    name: str,
    jurisdictions: set[str] | None,
) -> None:
    retriever = _fitted(name, sample_docs)
    hits = retriever.search(" ".join(words), k=k, jurisdictions=jurisdictions)
    assert len(hits) <= k
    assert len({hit.doc_id for hit in hits}) == len(hits)
    keys = [(hit.score, hit.doc_id) for hit in hits]
    assert keys == sorted(keys, reverse=True)
    assert all(math.isfinite(hit.score) and hit.score > 0 for hit in hits)
    if jurisdictions is not None:
        by_id = {doc.doc_id: doc.jurisdiction for doc in sample_docs}
        assert all(by_id[hit.doc_id] in jurisdictions for hit in hits)


_FITTED: dict[str, Retriever] = {}


def _fitted(name: str, docs: list[LegalDocument]) -> Retriever:
    if name not in _FITTED:
        _FITTED[name] = get_retriever(name).fit(docs)
    return _FITTED[name]
