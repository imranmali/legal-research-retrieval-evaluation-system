"""Test-suite wide isolation from the developer's environment."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_groundtruth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove GROUNDTRUTH_* variables so service settings start from their defaults."""
    for name in list(os.environ):
        if name.upper().startswith("GROUNDTRUTH_"):
            monkeypatch.delenv(name)
