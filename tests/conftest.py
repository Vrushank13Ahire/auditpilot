import shutil
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.fixture(scope="session")
def truth() -> pd.DataFrame:
    return pd.read_csv(DATA / "ground_truth.csv", dtype=str)


@pytest.fixture
def truth_ids(truth):
    def _get(kind: str) -> set[str]:
        return set(truth[truth.anomaly_type == kind].entry_id)
    return _get


@pytest.fixture
def data_copy(tmp_path, monkeypatch):
    """A private copy of the books that tests can break, wired in via AUDITPILOT_DATA_DIR."""
    dst = tmp_path / "data"
    shutil.copytree(DATA, dst)
    monkeypatch.setenv("AUDITPILOT_DATA_DIR", str(dst))
    return dst


def recall(pred, truth_set) -> float:
    return len(set(pred) & truth_set) / len(truth_set)


def precision(pred, truth_set) -> float:
    return len(set(pred) & truth_set) / max(len(set(pred)), 1)
