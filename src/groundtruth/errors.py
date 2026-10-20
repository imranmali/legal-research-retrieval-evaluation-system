"""Exception hierarchy shared by every Ground Truth module."""


class GroundTruthError(Exception):
    """Base class for all errors raised by Ground Truth."""


class FormatError(GroundTruthError):
    """Input data (qrels, runs, corpora, queries) is malformed.

    The message names the source and, where known, the 1-based line number.
    """


class UnknownMetricError(GroundTruthError):
    """A metric specification does not resolve to a registered metric."""


class ConfigurationError(GroundTruthError):
    """A component was configured with invalid or inconsistent parameters."""
