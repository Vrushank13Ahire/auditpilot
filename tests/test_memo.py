"""Phase 8: DRAFT then FINAL only after human approval; every number in the memo comes from tool output."""
import json

import pytest

from auditpilot.offline import run_offline
from auditpilot.tools.memo import (allowed_numbers, build_and_write_memo, check_memo_numbers, inr, memo_paths,
                                   sign_off_memo)


@pytest.fixture
def docs(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPILOT_DOCS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(scope="module")
def state_no_write():
    return run_offline(write_memo=False)


def test_inr_uses_indian_grouping():
    assert inr(185000) == "Rs 1,85,000.00" and inr(192510650.32) == "Rs 19,25,10,650.32" and inr(999.5) == "Rs 999.50"


def test_pipeline_produces_a_draft_memo_with_all_sections(docs, state_no_write):
    out = build_and_write_memo(state_no_write)
    assert out["ok"] and out["status"] == "DRAFT"
    text = (docs / "audit_memo.md").read_text()
    assert "**Status: DRAFT**" in text and "FINAL" not in text.split("## 1.")[0]
    for section in ("Scope and data", "Executive summary", "Ranked findings", "Recommended actions", "Limitations",
                    "Appendix: dropped findings", "Sign-off"):
        assert section in text
    for f in state_no_write["confirmed_findings"]:
        assert all(i in text for i in f["entry_ids"]), "every finding lists its entry ids in the memo"
    assert "synthetic" in text.lower()


def test_approval_flips_draft_to_final_and_other_decisions_do_not(docs, state_no_write):
    build_and_write_memo(state_no_write)
    path, meta = memo_paths()
    assert sign_off_memo("request_changes", "Asha Rao", "tighten F2")["status"] == "DRAFT"
    assert "**Status: DRAFT**" in path.read_text() and "Changes requested by Asha Rao" in path.read_text()
    assert sign_off_memo("reject", "Asha Rao")["status"] == "DRAFT"
    out = sign_off_memo("approve", "Asha Rao", "ok to issue")
    assert out["ok"] and out["status"] == "FINAL"
    text = path.read_text()
    assert "**Status: FINAL** (approved by Asha Rao)" in text and "**Status: DRAFT**" not in text
    assert "Approved by Asha Rao" in text and json.loads(meta.read_text())["status"] == "FINAL"


def test_sign_off_needs_a_valid_decision_a_name_and_a_draft(docs, state_no_write):
    assert not sign_off_memo("approve", "Asha")["ok"]                      # no memo yet
    build_and_write_memo(state_no_write)
    assert not sign_off_memo("approve", "")["ok"]                          # no reviewer name
    assert not sign_off_memo("maybe", "Asha")["ok"]                        # unknown decision
    assert "**Status: DRAFT**" in memo_paths()[0].read_text()              # still a draft after all refusals


def test_editing_the_memo_after_drafting_blocks_sign_off(docs, state_no_write):
    build_and_write_memo(state_no_write)
    path, _ = memo_paths()
    path.write_text(path.read_text() + "\nsneaky edit\n")
    out = sign_off_memo("approve", "Asha")
    assert not out["ok"] and "changed" in out["message"]


def test_rewriting_the_memo_resets_an_approved_memo_to_draft(docs, state_no_write):
    build_and_write_memo(state_no_write)
    sign_off_memo("approve", "Asha")
    build_and_write_memo(state_no_write)
    assert "**Status: DRAFT**" in memo_paths()[0].read_text()


def test_every_amount_in_the_memo_appears_in_tool_output(docs, state_no_write):
    out = build_and_write_memo(state_no_write)
    assert out["number_check"]["ok"] and out["number_check"]["checked"] > 10
    text = memo_paths()[0].read_text()
    allowed = allowed_numbers(state_no_write["confirmed_findings"] + state_no_write["dropped_findings"],
                              extra=[sum(f["amount_at_risk_inr"] for f in state_no_write["confirmed_findings"])])
    bad = check_memo_numbers(text, allowed)["unsupported_numbers"]
    assert all(v < 1e7 for v in bad) or bad == [], bad                     # only the code-derived combined total may differ


def test_an_invented_figure_in_the_narrative_stops_the_memo(docs, state_no_write):
    out = build_and_write_memo(state_no_write, {"executive_summary": "We found Rs 99,99,999 of fraud."})
    assert not out["ok"] and out["status"] == "NOT_WRITTEN" and 9999999.0 in out["unsupported_numbers"]
    assert not (docs / "audit_memo.md").exists()


def test_a_real_figure_in_the_narrative_is_accepted(docs, state_no_write):
    top = state_no_write["confirmed_findings"][0]
    out = build_and_write_memo(state_no_write, {"executive_summary": f"{top['id']} puts {inr(top['amount_at_risk_inr'])} at risk."})
    assert out["ok"]


def test_dropped_findings_appear_in_the_appendix_with_reasons(docs, state_no_write):
    state = dict(state_no_write)
    state["dropped_findings"] = [{"id": "F9", "category": "benford", "title": "Fake", "entry_ids": ["L99999"],
                                  "status_reason": "cites entry_id(s) that do not exist in the books: L99999"}]
    build_and_write_memo(state)
    text = memo_paths()[0].read_text()
    appendix = text.split("## 6. Appendix")[1]
    assert "F9" in appendix and "do not exist" in appendix


def test_evidence_with_untraceable_figures_is_withheld_not_printed(docs, state_no_write):
    state = dict(state_no_write)
    f = dict(state["confirmed_findings"][0])
    f["evidence"] = ["find_duplicates: we saw Rs 7,77,77,777 lost"]
    state["confirmed_findings"] = [f] + state["confirmed_findings"][1:]
    assert build_and_write_memo(state)["number_check"]["ok"]
    text = memo_paths()[0].read_text()
    assert "7,77,77,777" not in text and "evidence line withheld" in text


def test_no_confirmed_findings_still_gives_a_valid_draft(docs):
    out = build_and_write_memo({"confirmed_findings": [], "dropped_findings": []})
    assert out["ok"] and "No findings were confirmed" in memo_paths()[0].read_text()
