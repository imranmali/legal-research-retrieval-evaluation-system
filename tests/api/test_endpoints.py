"""/v1 endpoints, probes and the OpenAPI document."""

import math
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from groundtruth import __version__
from groundtruth.evaluation import evaluate
from groundtruth.legal import document_metadata, load_documents
from groundtruth.metrics import available_metrics

from .conftest import SAMPLE_CORPUS, SMOKE_BODY, ClientFactory

QRELS = {"q1": {"d1": 2, "d2": 1, "d3": 0}, "q2": {"d4": 1, "d5": 0}}
PERFECT = {"q1": {"d1": 3.0, "d2": 2.0, "d3": 1.0}, "q2": {"d4": 2.0, "d5": 1.0}}
HALF = {"q1": {"d1": 3.0, "d2": 2.0, "d3": 1.0}, "q2": {"d5": 1.0}}


def _error(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    error: dict[str, Any] = body["error"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


# ---------------------------------------------------------------------------
# POST /v1/evaluate
# ---------------------------------------------------------------------------


def test_successful_evaluation(client: TestClient) -> None:
    """Scenario: Successful evaluation (the CI smoke-test body)."""
    response = client.post("/v1/evaluate", json=SMOKE_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["aggregate"]["P@1"] == 1.0
    assert body["per_query"] == {"q1": {"P@1": 1.0}}
    assert body["num_queries"] == 1
    assert body["warnings"] == []
    assert body["metrics"] == ["P@1"]


def test_evaluation_matches_the_library(client: TestClient) -> None:
    metrics = ["nDCG@10", "P@1", "MAP"]
    response = client.post("/v1/evaluate", json={"qrels": QRELS, "run": HALF, "metrics": metrics})
    assert response.status_code == 200
    expected = evaluate(QRELS, HALF, metrics)
    assert response.json() == expected.model_dump(mode="json")


def test_evaluation_defaults_to_the_standard_metrics(client: TestClient) -> None:
    response = client.post("/v1/evaluate", json={"qrels": QRELS, "run": PERFECT})
    assert response.status_code == 200
    assert response.json()["metrics"] == ["nDCG@10", "P@10", "R@100", "AP", "RR"]


def test_evaluation_options(client: TestClient) -> None:
    response = client.post(
        "/v1/evaluate",
        json={
            "qrels": QRELS,
            "run": {"q1": PERFECT["q1"], "q9": {"d1": 1.0}},
            "metrics": ["P@2"],
            "missing": "skip",
            "depth": 1,
            "rel_level": 2,
            "include_per_query": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["num_queries"] == 1
    assert body["aggregate"]["P@2"] == pytest.approx(0.5)
    assert body["per_query"] == {}
    assert len(body["warnings"]) == 2


def test_evaluation_with_legal_metadata(client: TestClient) -> None:
    documents = document_metadata(load_documents(SAMPLE_CORPUS))
    run = {"Q03": {"FED-4A-01": 2.0, "FED-4A-02": 1.0}}
    qrels = {"Q03": {"FED-4A-01": 3}}
    response = client.post(
        "/v1/evaluate",
        json={
            "qrels": qrels,
            "run": run,
            "metrics": ["BadLaw@10", "JurisdictionMatch@10"],
            "doc_metadata": documents,
            "query_metadata": {"Q03": {"jurisdiction": "US-FED"}},
        },
    )
    assert response.status_code == 200, response.text
    aggregate = response.json()["aggregate"]
    assert aggregate["BadLaw@10"] == pytest.approx(0.5)  # FED-4A-02 is overruled
    assert aggregate["JurisdictionMatch@10"] == pytest.approx(1.0)


def test_legal_metric_without_metadata_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/evaluate", json={"qrels": QRELS, "run": PERFECT, "metrics": ["BadLaw@10"]}
    )
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "invalid_request"
    assert "BadLaw@10" in error["message"]


def test_unknown_metric(client: TestClient) -> None:
    """Scenario: Unknown metric."""
    response = client.post(
        "/v1/evaluate", json={"qrels": QRELS, "run": PERFECT, "metrics": ["foo"]}
    )
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "unknown_metric"
    assert "foo" in error["message"]


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        (
            {"qrels": {"q1": {"d1": 1.5}}, "run": {"q1": {"d1": 1.0}}},
            "relevance must be an integer",
        ),
        (
            {"qrels": {"q1": {"d1": True}}, "run": {"q1": {"d1": 1.0}}},
            "relevance must be an integer",
        ),
        ({"qrels": {"q1": {"d1": 1}}, "run": {"q1": {"d1": "1.0"}}}, "score must be a finite"),
        ({"qrels": {"q1": {"d1": 1}}, "run": {"q1": {"d1": True}}}, "score must be a finite"),
        ({"qrels": {"q1": {"d1": 1}}, "run": {"": {"d1": 1.0}}}, "non-empty strings"),
        ({"qrels": {"q1": []}, "run": {"q1": {"d1": 1.0}}}, "expected an object"),
        ({"qrels": [], "run": {"q1": {"d1": 1.0}}}, "expected a JSON object"),
        ({"run": {"q1": {"d1": 1.0}}}, "qrels"),
        ({"qrels": {}, "run": {}, "metrics": []}, "metrics"),
        ({"qrels": {}, "run": {}, "unknown": 1}, "unknown"),
        ({"qrels": {}, "run": {}, "missing": "drop"}, "missing"),
        ({"qrels": {}, "run": {}, "depth": 0}, "depth"),
    ],
)
def test_invalid_evaluation_input(client: TestClient, body: dict[str, Any], fragment: str) -> None:
    response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "validation_error"
    assert fragment in error["message"]
    assert error["details"]
    assert "Value error" not in error["message"]


def test_non_finite_score_is_rejected(client: TestClient) -> None:
    body = '{"qrels": {"q1": {"d1": 1}}, "run": {"q1": {"d1": NaN}}, "metrics": ["P@1"]}'
    response = client.post(
        "/v1/evaluate", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "finite" in _error(response)["message"]


def test_malformed_json_is_a_validation_error(client: TestClient) -> None:
    response = client.post(
        "/v1/evaluate", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert _error(response)["code"] == "validation_error"


def test_nothing_to_evaluate_is_a_domain_error(client: TestClient) -> None:
    response = client.post(
        "/v1/evaluate", json={"qrels": {}, "run": {"q1": {"d1": 1.0}}, "metrics": ["P@1"]}
    )
    assert response.status_code == 422
    assert "nothing to evaluate" in _error(response)["message"]


def test_too_many_run_entries(make_client: ClientFactory) -> None:
    with make_client(max_run_entries=4) as client:
        assert client.post("/v1/evaluate", json={"qrels": QRELS, "run": HALF}).status_code == 200
        response = client.post("/v1/evaluate", json={"qrels": QRELS, "run": PERFECT})
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "too_many_run_entries"
    assert "5 run entries" in error["message"]


# ---------------------------------------------------------------------------
# POST /v1/compare
# ---------------------------------------------------------------------------


def test_two_systems(client: TestClient) -> None:
    """Scenario: Two systems."""
    response = client.post(
        "/v1/compare",
        json={"qrels": QRELS, "runs": {"half": HALF, "perfect": PERFECT}, "metrics": ["nDCG@10"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["systems"] == ["half", "perfect"]
    assert body["metrics"] == ["nDCG@10"]
    assert len(body["comparisons"]) == 1
    comparison = body["comparisons"][0]
    assert comparison["system_a"] == "half"
    assert comparison["system_b"] == "perfect"
    assert comparison["delta"] == pytest.approx(0.5)
    assert 0.0 < comparison["p_value"] <= 1.0
    assert comparison["p_value_corrected"] == comparison["p_value"]
    assert comparison["test"] == "permutation"
    assert body["aggregate"] == {"half": {"nDCG@10": 0.5}, "perfect": {"nDCG@10": 1.0}}
    assert body["num_queries"] == {"half": 2, "perfect": 2}


def test_compare_many_systems_and_metrics(client: TestClient) -> None:
    worst = {"q1": {"d3": 1.0}, "q2": {"d5": 1.0}}
    response = client.post(
        "/v1/compare",
        json={
            "qrels": QRELS,
            "runs": {"a": PERFECT, "b": HALF, "c": worst},
            "metrics": ["nDCG@10", "P@1"],
            "test": "bootstrap",
            "alpha": 0.1,
            "n_resamples": 300,
            "seed": 3,
        },
    )
    assert response.status_code == 200, response.text
    comparisons = response.json()["comparisons"]
    assert [(c["metric"], c["system_a"], c["system_b"]) for c in comparisons] == [
        (metric, a, b)
        for metric in ("nDCG@10", "P@1")
        for a, b in (("a", "b"), ("a", "c"), ("b", "c"))
    ]
    assert all(c["test"] == "bootstrap" and c["alpha"] == 0.1 for c in comparisons)
    assert all(c["p_value_corrected"] >= c["p_value"] for c in comparisons)


def test_compare_uses_the_default_resamples_setting(make_client: ClientFactory) -> None:
    body = {"qrels": QRELS, "runs": {"a": HALF, "b": PERFECT}, "metrics": ["nDCG@10"]}
    with make_client(default_resamples=9) as client:
        p_value = client.post("/v1/compare", json=body).json()["comparisons"][0]["p_value"]
    # Permutation p-values are multiples of 1 / (n_resamples + 1).
    assert math.isclose(p_value * 10, round(p_value * 10))


def test_compare_ttest_with_random_seed(client: TestClient) -> None:
    response = client.post(
        "/v1/compare",
        json={
            "qrels": QRELS,
            "runs": {"a": HALF, "b": PERFECT},
            "metrics": ["P@1"],
            "test": "ttest",
            "seed": None,
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"qrels": QRELS, "runs": {"only": PERFECT}}, "runs"),
        ({"qrels": QRELS, "runs": {"a": PERFECT, "b": {"q1": {"d1": "x"}}}}, "runs['b']"),
        ({"qrels": QRELS, "runs": {"a": PERFECT, " ": HALF}}, "system names"),
        ({"qrels": QRELS, "runs": {"a": PERFECT, "b": HALF}, "alpha": 1.0}, "alpha"),
        ({"qrels": QRELS, "runs": {"a": PERFECT, "b": HALF}, "test": "wilcoxon"}, "test"),
        ({"qrels": QRELS, "runs": {"a": PERFECT, "b": HALF}, "n_resamples": 0}, "n_resamples"),
        ({"qrels": QRELS, "runs": []}, "runs"),
    ],
)
def test_invalid_compare_input(client: TestClient, body: dict[str, Any], fragment: str) -> None:
    response = client.post("/v1/compare", json=body)
    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "validation_error"
    assert fragment in error["message"]


def test_compare_unknown_metric(client: TestClient) -> None:
    response = client.post(
        "/v1/compare", json={"qrels": QRELS, "runs": {"a": PERFECT, "b": HALF}, "metrics": ["foo"]}
    )
    assert response.status_code == 422
    assert "foo" in _error(response)["message"]


def test_compare_counts_entries_of_every_run(make_client: ClientFactory) -> None:
    with make_client(max_run_entries=9) as client:
        response = client.post(
            "/v1/compare", json={"qrels": QRELS, "runs": {"a": PERFECT, "b": PERFECT}}
        )
    assert response.status_code == 422
    assert _error(response)["code"] == "too_many_run_entries"


# ---------------------------------------------------------------------------
# GET /v1/metrics and POST /v1/search
# ---------------------------------------------------------------------------


def test_list_metrics(client: TestClient) -> None:
    response = client.get("/v1/metrics")
    assert response.status_code == 200
    metrics = {entry["name"]: entry for entry in response.json()["metrics"]}
    assert set(metrics) == {info.name for info in available_metrics()}
    assert metrics["BadLaw"] == {
        "name": "BadLaw",
        "aliases": [],
        "description": metrics["BadLaw"]["description"],
        "cutoff": "required",
        "higher_is_better": False,
        "requires_metadata": True,
    }
    assert "MAP" in metrics["AP"]["aliases"]


def test_search_without_corpus(client: TestClient) -> None:
    """Scenario: Search without corpus."""
    response = client.post("/v1/search", json={"query": "pretext"})
    assert response.status_code == 503
    error = _error(response)
    assert error["code"] == "corpus_unavailable"
    assert "GROUNDTRUTH_CORPUS_PATH" in error["message"]


def test_search_with_corpus(corpus_client: TestClient) -> None:
    response = corpus_client.post(
        "/v1/search", json={"query": "cell phone search incident to arrest", "k": 2}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["retriever"] == "bm25"
    assert body["query"] == "cell phone search incident to arrest"
    hits = body["hits"]
    assert [hit["rank"] for hit in hits] == [1, 2]
    assert hits[0]["doc_id"] == "FED-4A-01"
    assert hits[0]["score"] >= hits[1]["score"]
    assert hits[0]["citations"] == ["731 U.S. 204"]
    assert hits[0]["status"] == "good_law"
    assert hits[0]["decision_date"] == "2019-06-24"


def test_search_jurisdiction_filter(corpus_client: TestClient) -> None:
    response = corpus_client.post(
        "/v1/search",
        json={"query": "cell phone search incident to arrest", "k": 10, "jurisdictions": ["US-NY"]},
    )
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert hits
    assert {hit["jurisdiction"] for hit in hits} == {"US-NY"}


def test_search_with_configured_retriever(make_client: ClientFactory) -> None:
    with make_client(corpus_path=SAMPLE_CORPUS, retriever="tfidf") as client:
        body = client.post("/v1/search", json={"query": "Title VII pretext"}).json()
    assert body["retriever"] == "tfidf"
    assert len(body["hits"]) <= 10


@pytest.mark.parametrize(
    "body",
    [{"query": ""}, {"query": "x", "k": 0}, {"query": "x", "k": 1001}, {"k": 3}],
)
def test_invalid_search_input(corpus_client: TestClient, body: dict[str, Any]) -> None:
    response = corpus_client.post("/v1/search", json=body)
    assert response.status_code == 422
    assert _error(response)["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Probes, service info and documentation
# ---------------------------------------------------------------------------


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_after_startup(client: TestClient, corpus_client: TestClient) -> None:
    assert client.get("/readyz").json() == {"status": "ready", "corpus": None}
    assert corpus_client.get("/readyz").json() == {
        "status": "ready",
        "corpus": {"documents": 24, "retriever": "bm25"},
    }


def test_readyz_before_startup() -> None:
    from groundtruth.api.app import create_app
    from groundtruth.config import Settings

    # Without entering the client context the lifespan never runs.
    client = TestClient(create_app(Settings()))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert _error(response)["code"] == "not_ready"
    assert client.get("/healthz").status_code == 200


def test_service_info(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["name"] == "groundtruth"
    assert body["version"] == __version__
    assert body["docs"] == "/docs"


def test_openapi_documents_every_endpoint(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == __version__
    paths = schema["paths"]
    for path in ("/v1/evaluate", "/v1/compare", "/v1/metrics", "/v1/search", "/healthz"):
        assert path in paths
    assert "APIKeyHeader" in schema["components"]["securitySchemes"]
    assert client.get("/docs").status_code == 200


def test_unknown_route(client: TestClient) -> None:
    response = client.get("/v2/evaluate")
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


def test_wrong_method(client: TestClient) -> None:
    response = client.get("/v1/evaluate")
    assert response.status_code == 405
    assert _error(response)["code"] == "method_not_allowed"


def test_corpus_load_failure_aborts_startup(make_client: ClientFactory, tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{oops}\n", encoding="utf-8")
    with pytest.raises(Exception, match="invalid JSON"), make_client(corpus_path=broken):
        pass  # pragma: no cover - startup fails before the body runs
