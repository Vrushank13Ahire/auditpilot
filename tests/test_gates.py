"""Phase 3: a failed intake must stop the pipeline, enforced in code (no ADK needed)."""
import pandas as pd

from auditpilot import tools
from auditpilot.gates import halt_message, record_intake_status


def test_failed_tool_result_sets_flag_and_halts():
    state = {}
    failed = {"test": "load_ledger", "flagged_ids": [], "stats": {"status": "FAILED", "reasons": ["missing x"]},
              "notes": ""}
    assert record_intake_status("load_ledger", failed, state) is True
    assert state["intake_failed"] is True
    msg = halt_message(state)
    assert msg and "FAILED" in msg and "missing x" in msg


def test_ok_and_exceptions_do_not_halt():
    state = {}
    ok = {"stats": {"status": "OK"}}
    exc = {"stats": {"status": "EXCEPTIONS"}}      # a reconciliation difference is a finding, not a stop
    assert record_intake_status("load_ledger", ok, state) is False
    assert record_intake_status("check_trial_balance", exc, state) is False
    assert halt_message(state) is None


def test_other_tools_cannot_trigger_the_gate():
    state = {}
    assert record_intake_status("find_duplicates", {"stats": {"status": "FAILED"}}, state) is False
    assert halt_message(state) is None


def test_deleting_a_column_makes_the_real_tool_fail_and_halt(data_copy):
    df = pd.read_csv(data_copy / "ledger.csv", dtype=str)
    df.drop(columns=["amount_inr"]).to_csv(data_copy / "ledger.csv", index=False)
    state = {}
    res = tools.load_ledger()
    assert res["stats"]["status"] == "FAILED"
    assert record_intake_status("load_ledger", res, state)
    assert "amount_inr" in halt_message(state)
