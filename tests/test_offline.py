"""The offline pipeline: same tools, scoring, skeptic rules and memo as the agents, with no LLM."""
from auditpilot.offline import impact_for, predictions, run_offline
from auditpilot.tools.memo import memo_paths
from conftest import precision, recall


def test_offline_pipeline_end_to_end(tmp_path, monkeypatch, truth_ids):
    monkeypatch.setenv("AUDITPILOT_DOCS_DIR", str(tmp_path))
    state = run_offline()
    confirmed = state["confirmed_findings"]
    assert state["memo"]["status"] == "DRAFT" and memo_paths()[0].exists()
    assert [f["score"] for f in confirmed] == sorted((f["score"] for f in confirmed), reverse=True)
    assert all(f["entry_ids"] and f["status"] == "confirmed" for f in confirmed)
    assert state["dropped_findings"] == []
    pred = predictions(state)
    for kind in ("duplicate_payment", "split_payment", "ghost_vendor", "shared_bank_account", "self_approved",
                 "sunday_round", "trial_balance_gap", "prompt_injection"):
        assert recall(pred[kind], truth_ids(kind)) >= 0.9, kind
        assert precision(pred[kind], truth_ids(kind)) >= 0.9, kind


def test_offline_pipeline_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPILOT_DOCS_DIR", str(tmp_path))
    a, b = run_offline(), run_offline()
    assert a["confirmed_findings"] == b["confirmed_findings"]


def test_broken_books_stop_the_offline_audit_from_inventing_findings(data_copy):
    (data_copy / "ledger.csv").unlink()
    state = run_offline(write_memo=False)
    assert state["confirmed_findings"] == []


def test_impact_rubric():
    assert impact_for("ghost_vendor", 100) == 5 and impact_for("duplicate_payment", 2_000_000) == 5
    assert impact_for("self_approved", 100) == 4 and impact_for("duplicate_payment", 300_000) == 4
    assert impact_for("duplicate_payment", 60_000) == 3 and impact_for("weekend_round", 1) == 3   # policy breach
    assert impact_for("benford", 20_000) == 2 and impact_for("benford", 100) == 1
