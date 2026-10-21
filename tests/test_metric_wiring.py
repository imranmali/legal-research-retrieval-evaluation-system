import subprocess
import sys

from groundtruth.metrics import available_metrics, get_metric


def test_legal_metrics_available_from_metrics_package() -> None:
    names = {info.name for info in available_metrics()}
    assert {"BadLaw", "JurisdictionMatch", "KeyAuthorityRecall", "CitationRecall"} <= names
    assert {"P", "R", "nDCG", "AP", "RR"} <= names
    assert get_metric("kar@10").label == "KeyAuthorityRecall@10"


def test_fresh_interpreter_import_has_no_cycle() -> None:
    code = (
        "import groundtruth.metrics as m;"
        "assert any(i.name == 'BadLaw' for i in m.available_metrics())"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
