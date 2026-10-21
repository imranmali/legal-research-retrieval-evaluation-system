"""Service configuration read from ``GROUNDTRUTH_*`` environment variables.

Every setting has a production-safe default, so the API starts without any
configuration. Lists (``GROUNDTRUTH_API_KEYS``, ``GROUNDTRUTH_CORS_ORIGINS``)
are comma-separated; an empty or unset variable means an empty list. Empty
variables are treated as unset for every setting. See ``docs/deployment.md``
for the operator-facing reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from groundtruth.retrieval import available_retrievers

__all__ = ["DEFAULT_METRICS", "LOG_LEVELS", "Settings"]

#: Metrics evaluated when a CLI or API caller does not name any.
DEFAULT_METRICS: Final[tuple[str, ...]] = ("nDCG@10", "P@10", "R@100", "MAP", "MRR")

#: Accepted values of ``GROUNDTRUTH_LOG_LEVEL`` (case-insensitive).
LOG_LEVELS: Final[tuple[str, ...]] = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")

_MIB: Final = 1024 * 1024


def _split_csv(value: Any) -> Any:
    """Split a comma-separated string into stripped, non-empty, de-duplicated items."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if isinstance(value, list | tuple | set | frozenset):
        items = (item.get_secret_value() if isinstance(item, SecretStr) else item for item in value)
        cleaned = (item.strip() if isinstance(item, str) else item for item in items)
        return list(dict.fromkeys(item for item in cleaned if item != ""))
    return value


class Settings(BaseSettings):
    """Runtime settings of the HTTP service (and ``groundtruth serve``).

    Attributes:
        api_keys: Accepted ``X-API-Key`` values; empty disables authentication.
        max_body_bytes: Largest accepted request body in bytes (413 above it).
        max_run_entries: Most (query, document) run entries per request (422 above it).
        corpus_path: JSONL corpus indexed at startup to enable ``/v1/search``.
        retriever: Retriever fitted on the corpus (see ``groundtruth.retrieval``).
        log_level: Application log level.
        log_json: Emit structured JSON logs (``False`` for human-readable lines).
        cors_origins: Origins allowed for browser clients; empty disables CORS.
        default_resamples: Default resamples for permutation/bootstrap tests.
    """

    model_config = SettingsConfigDict(
        env_prefix="GROUNDTRUTH_",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    api_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    max_body_bytes: int = Field(default=50 * _MIB, ge=1)
    max_run_entries: int = Field(default=5_000_000, ge=1)
    corpus_path: Path | None = None
    retriever: str = "bm25"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    default_resamples: int = Field(default=10_000, ge=1, le=1_000_000)

    @field_validator("api_keys", "cors_origins", mode="before")
    @classmethod
    def _parse_list(cls, value: Any) -> Any:
        return _split_csv(value)

    @field_validator("corpus_path", mode="before")
    @classmethod
    def _blank_path_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("retriever")
    @classmethod
    def _known_retriever(cls, value: str) -> str:
        name = value.strip().lower()
        known = available_retrievers()
        if name not in known:
            raise ValueError(f"unknown retriever {value!r}; available: {', '.join(known)}")
        return name

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"log_level must be one of {', '.join(LOG_LEVELS)}, got {value!r}")
        return level

    @property
    def auth_enabled(self) -> bool:
        """Whether ``/v1`` endpoints require an ``X-API-Key`` header."""
        return bool(self.api_keys)
