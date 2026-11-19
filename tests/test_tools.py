"""Phase 2: one test per tool; each seeded anomaly type reaches recall >= 90% against ground truth."""
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from auditpilot import tools
from conftest import precision, recall

TOOLS_DIR = Path(tools.__file__).parent
CONTRACT_KEYS = {"test", "flagged_ids", "stats", "notes"}


def _check_contract(res: dict):
    assert set(res) == CONTRACT_KEYS
    assert isinstance(res["flagged_ids"], list) and isinstance(res["stats"], dict) and isinstance(res["notes"], str)
    json.dumps(res)  # must be JSON-serialisable for the agent


# ---- one test per tool -------------------------------------------------------------------------------------

def test_load_ledger(truth_ids):
    res = tools.load_ledger()
    _check_contract(res)
    assert res["stats"]["status"] == "OK" and res["stats"]["rows"] == 6000
    assert res["stats"]["date_min"] >= "2025-04-01" and res["stats"]["date_max"] <= "2026-03-31"
    inj = truth_ids("prompt_injection")
    assert recall(res["flagged_ids"], inj) >= 0.9 and precision(res["flagged_ids"], inj) >= 0.9


def test_load_ledger_fails_on_missing_column(data_copy):
    df = pd.read_csv(data_copy / "ledger.csv", dtype=str)
    df.drop(columns=["approved_by"]).to_csv(data_copy / "ledger.csv", index=False)
    res = tools.load_ledger()
    assert res["stats"]["status"] == "FAILED"
    assert any("approved_by" in r for r in res["stats"]["reasons"])


def test_load_ledger_fails_on_bad_dates_and_dup_ids(data_copy):
    df = pd.read_csv(data_copy / "ledger.csv", dtype=str)
    df.loc[0, "date"] = "2024-01-01"
    df.loc[1, "entry_id"] = df.loc[2, "entry_id"]
    df.to_csv(data_copy / "ledger.csv", index=False)
    res = tools.load_ledger()
    assert res["stats"]["status"] == "FAILED"
    text = " ".join(res["stats"]["reasons"])
    assert "outside FY" in text and "duplicate entry_ids" in text


def test_check_trial_balance(truth_ids):
    res = tools.check_trial_balance()
    _check_contract(res)
    assert res["stats"]["status"] == "EXCEPTIONS"           # reconciliation difference is a finding, not a failure
    assert res["stats"]["debits_equal_credits"] is False
    assert res["stats"]["debit_credit_difference_inr"] == 185000.0
    assert set(res["flagged_ids"]) == truth_ids("trial_balance_gap")


def test_check_trial_balance_ok_when_it_ties(data_copy):
    tb = pd.read_csv(data_copy / "trial_balance.csv")
    tb.loc[tb.account_code == 5300, "debit_inr"] -= 185000.0
    tb.to_csv(data_copy / "trial_balance.csv", index=False)
    res = tools.check_trial_balance()
    assert res["stats"]["status"] == "OK" and res["flagged_ids"] == []


def test_benford_test():
    res = tools.benford_test()
    _check_contract(res)
    digits = res["stats"]["digits"]
    assert [d["digit"] for d in digits] == list(range(1, 10))
    assert digits[0]["expected_pct"] == pytest.approx(30.1, abs=0.01)
    assert res["stats"]["conformity"] in {"close conformity", "acceptable conformity"}
    assert res["flagged_ids"] == []                          # population screen: no entry-level flags when conforming


def test_benford_flags_when_nonconforming(data_copy):
    df = pd.read_csv(data_copy / "ledger.csv")
    df["amount_inr"] = 9000.0 + df.index % 900               # every amount starts with 9
    df.to_csv(data_copy / "ledger.csv", index=False)
    res = tools.benford_test()
    assert res["stats"]["conformity"] == "nonconformity" and len(res["flagged_ids"]) > 0


def test_find_duplicates(truth_ids):
    res = tools.find_duplicates()
    _check_contract(res)
    t = truth_ids("duplicate_payment")
    assert recall(res["flagged_ids"], t) >= 0.9 and precision(res["flagged_ids"], t) >= 0.9
    assert res["stats"]["group_count"] == 10


def test_find_split_payments(truth_ids):
    res = tools.find_split_payments()
    _check_contract(res)
    t = truth_ids("split_payment")
    assert recall(res["flagged_ids"], t) >= 0.9 and precision(res["flagged_ids"], t) >= 0.9
    assert res["stats"]["group_count"] == 6
    assert all(g["combined_amount_inr"] > 50_000 for g in res["stats"]["groups"])


def test_find_weekend_round(truth_ids):
    res = tools.find_weekend_round()
    _check_contract(res)
    t = truth_ids("sunday_round")
    assert recall(res["flagged_ids"], t) >= 0.9 and precision(res["flagged_ids"], t) >= 0.9


def test_check_approval_limits(truth_ids):
    res = tools.check_approval_limits()
    _check_contract(res)
    s = res["stats"]
    assert recall(s["self_approved_ids"], truth_ids("self_approved")) >= 0.9
    assert precision(s["self_approved_ids"], truth_ids("self_approved")) >= 0.9
    assert recall(s["split_suspect_ids"], truth_ids("split_payment")) >= 0.9
    assert s["over_limit_ids"] == [] and s["under_authorised_ids"] == []


def test_check_approval_limits_catches_over_limit(data_copy):
    emp = pd.read_csv(data_copy / "employees.csv")
    manager = emp[emp.role == "Manager"].employee_id.iloc[0]
    led = pd.read_csv(data_copy / "ledger.csv")
    idx = led.index[(led.amount_inr > 60_000) & (led.posted_by != manager)][0]
    led.loc[idx, "approved_by"] = manager                    # a manager approves > Rs 50,000
    led.to_csv(data_copy / "ledger.csv", index=False)
    res = tools.check_approval_limits()
    assert led.loc[idx, "entry_id"] in res["stats"]["over_limit_ids"]


def test_vendor_bank_overlap(truth_ids):
    res = tools.vendor_bank_overlap()
    _check_contract(res)
    t = truth_ids("shared_bank_account")
    assert recall(res["flagged_ids"], t) >= 0.9 and precision(res["flagged_ids"], t) >= 0.9
    assert len(res["stats"]["vendor_employee_matches"]) == 3
    raw = pd.read_csv(Path(__file__).resolve().parents[1] / "data" / "employees.csv", dtype=str).bank_account
    assert not any(acct in json.dumps(res) for acct in raw)  # account numbers never appear in full


def test_find_ghost_vendors(truth_ids):
    res = tools.find_ghost_vendors()
    _check_contract(res)
    t = truth_ids("ghost_vendor")
    assert recall(res["flagged_ids"], t) >= 0.9 and precision(res["flagged_ids"], t) >= 0.9
    assert res["stats"]["vendor_count"] == 5


def test_ratio_table():
    res = tools.ratio_table()
    _check_contract(res)
    assert res["stats"]["months"] == 12 and len(res["stats"]["table"]) == 12
    assert res["stats"]["table"][0]["gross_margin_pct"] == pytest.approx(
        (22_000_000 - 22_000_000 * 0.61) / 22_000_000 * 100, abs=6)


def test_ratio_table_flags_a_bad_month(data_copy):
    fin = pd.read_csv(data_copy / "financials.csv")
    fin.loc[5, "current_liabilities"] = fin.loc[5, "current_assets"] * 2   # current ratio 0.5
    fin.to_csv(data_copy / "financials.csv", index=False)
    res = tools.ratio_table()
    assert "FIN:2025-09" in res["flagged_ids"]


# ---- cross-cutting guarantees ------------------------------------------------------------------------------

def test_tools_are_deterministic():
    a = [getattr(tools, n)() for n in tools.__all__]
    b = [getattr(tools, n)() for n in tools.__all__]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_tools_have_type_hints_and_docstrings():
    for name in tools.__all__:
        fn = getattr(tools, name)
        assert fn.__doc__ and len(fn.__doc__) > 80, name      # the agent reads the docstring
        assert fn.__annotations__.get("return") is not None, name


def test_no_llm_no_randomness_no_printing_no_ground_truth_in_tools():
    for path in TOOLS_DIR.glob("*.py"):
        src = path.read_text()
        assert not re.search(r"google|genai|openai|anthropic", src, re.I), path.name
        assert not re.search(r"^\s*import random|numpy\.random|np\.random|\brandom\.", src, re.M), path.name
        assert not re.search(r"^\s*print\(", src, re.M), path.name
        assert "ground_truth" not in src, path.name


def test_tools_never_raise_on_missing_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPILOT_DATA_DIR", str(tmp_path))   # empty folder
    for name in tools.__all__:
        res = getattr(tools, name)()
        assert set(res) == CONTRACT_KEYS and res["stats"]["status"] in {"FAILED", "ERROR"}, name
