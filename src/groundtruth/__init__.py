"""Ground Truth: evaluation toolkit and service for legal research retrieval systems."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("groundtruth-legal")
except PackageNotFoundError:  # pragma: no cover - only when running from a source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
