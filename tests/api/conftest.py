"""TestClient factories for the API with injected settings."""

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from groundtruth.api.app import create_app
from groundtruth.config import Settings

SAMPLE_CORPUS = Path(__file__).resolve().parents[2] / "data" / "sample" / "corpus.jsonl"

#: The body the CI container smoke test posts to /v1/evaluate.
SMOKE_BODY = {"qrels": {"q1": {"d1": 1}}, "run": {"q1": {"d1": 1.0}}, "metrics": ["P@1"]}

ClientFactory = Callable[..., AbstractContextManager[TestClient]]


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """create_app configures the root logger; undo it after each test."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def make_client() -> ClientFactory:
    """Build an app from keyword settings and run its lifespan around a TestClient."""

    @contextmanager
    def factory(**settings: Any) -> Iterator[TestClient]:
        app = create_app(Settings(**{"log_json": True, **settings}))
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    return factory


@pytest.fixture
def client(make_client: ClientFactory) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def corpus_client(make_client: ClientFactory) -> Iterator[TestClient]:
    with make_client(corpus_path=SAMPLE_CORPUS) as test_client:
        yield test_client
