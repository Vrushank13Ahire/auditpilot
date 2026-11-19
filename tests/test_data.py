"""Phase 1: the generated books contain exactly the planted anomalies and are reproducible."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _load_make_data():
    spec = importlib.util.spec_from_file_location("make_data", ROOT / "scripts" / "make_data.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["make_data"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def truth():
    return pd.read_csv(DATA / "ground_truth.csv", dtype=str)


@pytest.fixture(scope="module")
def ledger():
    return pd.read_csv(DATA / "ledger.csv", dtype={"entry_id": str, "vendor_id": str})


def test_file_shapes(ledger):
    assert len(ledger) == 6000
    assert len(pd.read_csv(DATA / "vendors.csv")) == 120
    assert len(pd.read_csv(DATA / "employees.csv")) == 40
    assert len(pd.read_csv(DATA / "financials.csv")) == 12
    assert list(ledger.columns) == ["entry_id", "date", "posted_by", "approved_by", "account_code",
                                    "account_name", "vendor_id", "amount_inr", "description"]


def test_ground_truth_counts(truth, ledger):
    counts = truth.anomaly_type.value_counts().to_dict()
    assert counts["duplicate_payment"] == 10
    assert counts["split_payment"] == 18           # 6 groups of 3
    assert counts["self_approved"] == 8
    assert counts["sunday_round"] == 12
    assert counts["trial_balance_gap"] == 1
    assert counts["prompt_injection"] == 4
    by_vendor = ledger.merge(truth, on="entry_id")
    assert by_vendor[by_vendor.anomaly_type == "ghost_vendor"].vendor_id.nunique() == 5
    assert by_vendor[by_vendor.anomaly_type == "shared_bank_account"].vendor_id.nunique() == 3
    split = by_vendor[by_vendor.anomaly_type == "split_payment"]
    assert split.groupby("vendor_id").size().eq(3).all() and split.vendor_id.nunique() == 6
    assert split.amount_inr.between(45_000, 49_999.99).all()


def test_truth_ids_exist(truth, ledger):
    ids = set(ledger.entry_id)
    assert all(e in ids for e in truth.entry_id if not e.startswith("TB:"))
    assert len(truth) == len(truth.drop_duplicates())


def test_reproducible(tmp_path):
    mod = _load_make_data()
    a, b = tmp_path / "a", tmp_path / "b"
    mod.build(a)
    mod.build(b)
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f
    # and it matches the committed files
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (DATA / f).read_bytes(), f


def test_everything_is_fictional():
    assert "fictional" in (DATA / "policy.md").read_text().lower()
