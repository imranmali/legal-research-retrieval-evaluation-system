"""Service settings from GROUNDTRUTH_* environment variables."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from groundtruth.config import DEFAULT_METRICS, Settings
from groundtruth.metrics import get_metric

_ENV_VARS = (
    "API_KEYS",
    "MAX_BODY_BYTES",
    "MAX_RUN_ENTRIES",
    "CORPUS_PATH",
    "RETRIEVER",
    "LOG_LEVEL",
    "LOG_JSON",
    "CORS_ORIGINS",
    "DEFAULT_RESAMPLES",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(f"GROUNDTRUTH_{name}", raising=False)


def _keys(settings: Settings) -> list[str]:
    return [key.get_secret_value() for key in settings.api_keys]


def test_defaults_match_the_deployment_guide() -> None:
    settings = Settings()
    assert settings.api_keys == []
    assert not settings.auth_enabled
    assert settings.max_body_bytes == 50 * 1024 * 1024
    assert settings.max_run_entries == 5_000_000
    assert settings.corpus_path is None
    assert settings.retriever == "bm25"
    assert settings.log_level == "INFO"
    assert settings.log_json is True
    assert settings.cors_origins == []
    assert settings.default_resamples == 10_000


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDTRUTH_MAX_BODY_BYTES", "1024")
    monkeypatch.setenv("GROUNDTRUTH_MAX_RUN_ENTRIES", "10")
    monkeypatch.setenv("GROUNDTRUTH_CORPUS_PATH", "/data/corpus.jsonl")
    monkeypatch.setenv("GROUNDTRUTH_RETRIEVER", " TFIDF ")
    monkeypatch.setenv("groundtruth_log_level", "debug")
    monkeypatch.setenv("GROUNDTRUTH_LOG_JSON", "false")
    monkeypatch.setenv("GROUNDTRUTH_DEFAULT_RESAMPLES", "500")
    settings = Settings()
    assert settings.max_body_bytes == 1024
    assert settings.max_run_entries == 10
    assert settings.corpus_path == Path("/data/corpus.jsonl")
    assert settings.retriever == "tfidf"
    assert settings.log_level == "DEBUG"
    assert settings.log_json is False
    assert settings.default_resamples == 500


def test_api_keys_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDTRUTH_API_KEYS", " key-one, key-two ,,key-one ")
    settings = Settings()
    assert _keys(settings) == ["key-one", "key-two"]
    assert settings.auth_enabled


@pytest.mark.parametrize("value", ["", " ", ",", " , "])
def test_empty_api_keys_disable_auth(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("GROUNDTRUTH_API_KEYS", value)
    settings = Settings()
    assert settings.api_keys == []
    assert not settings.auth_enabled


def test_api_keys_are_secret_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDTRUTH_API_KEYS", "s3cret-value")
    settings = Settings()
    assert "s3cret-value" not in repr(settings)
    assert "s3cret-value" not in str(settings.model_dump())


def test_api_keys_accept_python_lists() -> None:
    assert _keys(Settings(api_keys=["a", " b ", "a"])) == ["a", "b"]
    assert _keys(Settings(api_keys=[SecretStr("c")])) == ["c"]
    assert Settings(api_keys=None).api_keys == []


def test_cors_origins_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDTRUTH_CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]


def test_empty_variables_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.setenv(f"GROUNDTRUTH_{name}", "")
    assert Settings() == Settings.model_construct(**Settings().model_dump())
    assert Settings().corpus_path is None
    assert Settings().max_body_bytes == 50 * 1024 * 1024


def test_blank_corpus_path_is_none() -> None:
    assert Settings(corpus_path="  ").corpus_path is None


def test_unknown_retriever_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown retriever 'nope'"):
        Settings(retriever="nope")


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError, match="log_level must be one of"):
        Settings(log_level="loud")


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_body_bytes", 0), ("max_run_entries", 0), ("default_resamples", 0)],
)
def test_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_invalid_number_in_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUNDTRUTH_MAX_BODY_BYTES", "lots")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_immutable() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.retriever = "tfidf"


def test_default_metrics_resolve_to_distinct_metrics() -> None:
    labels = [get_metric(spec).label for spec in DEFAULT_METRICS]
    assert labels == ["nDCG@10", "P@10", "R@100", "AP", "RR"]


def test_list_settings_reject_other_types() -> None:
    with pytest.raises(ValidationError):
        Settings(api_keys=5)
