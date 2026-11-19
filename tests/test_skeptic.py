"""Phase 7: the skeptic drops fake findings, keeps real ones, never loses anything, and the loop is bounded."""
from auditpilot import tools
from auditpilot.tools.risk import rank_findings
from auditpilot.tools.skeptic import (apply_verdicts, enforce_rules, finalize_findings, needs_review, parse_verdicts,
                                      verify_entry_ids)


def _draft(fid, ids, category, likelihood=4, impact=4):
    return {"id": fid, "category": category, "title": f"t {fid}", "entry_ids": ids, "evidence": ["x"],
            "likelihood": likelihood, "impact": impact, "rationale": "r", "policy_clause": ""}


def _real_drafts():
    return [
        _draft("F1", tools.find_duplicates()["flagged_ids"], "duplicate_payment"),
        _draft("F2", tools.check_approval_limits()["stats"]["self_approved_ids"], "self_approved"),
        _draft("F3", tools.find_ghost_vendors()["flagged_ids"], "ghost_vendor", 5, 5),
        _draft("F4", ["TB:5300"], "trial_balance_gap", 5, 4),
    ]


def test_verify_entry_ids_flags_only_missing_ids():
    out = verify_entry_ids(["L00001", "L99999", "TB:5300", "TB:0000", "FIN:2025-07", "FIN:1999-01"])
    assert out["test"] == "verify_entry_ids"
    assert out["flagged_ids"] == ["FIN:1999-01", "L99999", "TB:0000"]
    assert out["stats"]["found_count"] == 3
    assert verify_entry_ids(["L00001"])["flagged_ids"] == []


def test_verify_entry_ids_returns_facts_and_redacts_injection_text(truth_ids):
    inj = sorted(truth_ids("prompt_injection"))
    out = verify_entry_ids(inj)
    assert out["flagged_ids"] == []
    assert all("[REDACTED" in e["description"] for e in out["stats"]["entries"])
    one = verify_entry_ids(["L00001"])["stats"]
    assert one["total_amount_inr"] == 20619.8 and one["entries"][0]["vendor_id"] == "V104"


def test_verify_entry_ids_never_raises_on_odd_input():
    assert verify_entry_ids([])["flagged_ids"] == []
    assert verify_entry_ids("L00001, L99999")["flagged_ids"] == ["L99999"]


def test_fake_finding_with_nonexistent_entry_id_is_dropped_and_real_ones_stay_confirmed():
    drafts = _real_drafts() + [_draft("F9", ["L99999", "L88888"], "duplicate_payment", 5, 5)]
    ranked = rank_findings(drafts)["ranked"]
    # the "model" confirms everything, including the fake one
    verdicts = [{"id": f["id"], "status": "confirmed", "reason": "looks fine"} for f in ranked]
    reviewed = enforce_rules(apply_verdicts(ranked, verdicts))
    status = {f["id"]: f["status"] for f in reviewed}
    assert status["F9"] == "dropped"
    assert all(status[i] == "confirmed" for i in ("F1", "F2", "F3", "F4"))
    reason = next(f["status_reason"] for f in reviewed if f["id"] == "F9")
    assert "L99999" in reason and "do not exist" in reason


def test_a_dropped_finding_can_not_be_revived_by_the_model():
    ranked = rank_findings([_draft("F9", ["L99999"], "duplicate_payment")])["ranked"]
    first = enforce_rules(ranked)
    revived = enforce_rules(apply_verdicts(first, [{"id": "F9", "status": "confirmed", "reason": "trust me"}]))
    assert revived[0]["status"] == "dropped"


def test_real_ids_under_the_wrong_category_do_not_survive():
    # genuine ledger ids, but none is a duplicate: the duplicates test does not back this claim
    ranked = rank_findings([_draft("F1", ["L00001", "L00002"], "duplicate_payment")])["ranked"]
    out = enforce_rules(apply_verdicts(ranked, [{"id": "F1", "status": "confirmed", "reason": "x"}]))
    assert out[0]["status"] == "dropped" and "find_duplicates" in out[0]["status_reason"]


def test_partly_supported_finding_needs_evidence_and_is_never_confirmed():
    ids = tools.find_duplicates()["flagged_ids"][:3] + ["L00001"]
    ranked = rank_findings([_draft("F1", ids, "duplicate_payment")])["ranked"]
    out = enforce_rules(apply_verdicts(ranked, [{"id": "F1", "status": "confirmed", "reason": "x"}]))
    assert out[0]["status"] == "needs_evidence" and needs_review(out)


def test_unreviewed_findings_need_evidence_so_the_loop_goes_again():
    ranked = rank_findings(_real_drafts())["ranked"]
    out = enforce_rules(ranked)                      # model said nothing
    assert {f["status"] for f in out} == {"needs_evidence"} and needs_review(out)
    done = enforce_rules(apply_verdicts(out, [{"id": f["id"], "status": "confirmed", "reason": "ok"} for f in out]))
    assert not needs_review(done)


def test_model_can_drop_a_real_finding_with_an_innocent_explanation():
    ranked = rank_findings(_real_drafts())["ranked"]
    out = enforce_rules(apply_verdicts(ranked, [{"id": "F1", "status": "dropped", "reason": "recurring rent"}]))
    f1 = next(f for f in out if f["id"] == "F1")
    assert f1["status"] == "dropped" and f1["status_reason"] == "recurring rent"


def test_loop_is_bounded_and_nothing_is_deleted_silently():
    """Simulate 3 rounds in which the model never settles a finding: it ends up dropped, with a reason, in the appendix."""
    drafts = _real_drafts() + [_draft("F8", ["L00001", "L00002"], "weekend_round"),    # real ids, wrong test
                               {**_draft("F7", [], "benford")}]                        # no ids: rejected by risk scorer
    scored = rank_findings(drafts)
    findings = scored["ranked"]
    for _ in range(3):                               # max_iterations=3
        findings = enforce_rules(apply_verdicts(findings, [{"id": f["id"], "status": "confirmed", "reason": "ok"}
                                                           for f in findings if f["status"] != "dropped"]))
        if not needs_review(findings):
            break
    final = finalize_findings(findings, scored["rejected"])
    assert len(final["confirmed"]) + len(final["dropped"]) == len(drafts)          # every finding accounted for
    assert {f["id"] for f in final["confirmed"]} == {"F1", "F2", "F3", "F4"}
    assert {f["id"] for f in final["dropped"]} == {"F8", "F7"}
    assert all(f["status_reason"] for f in final["dropped"])
    assert [f["score"] for f in final["confirmed"]] == sorted([f["score"] for f in final["confirmed"]], reverse=True)


def test_leftover_needs_evidence_is_dropped_with_the_reason_at_the_end():
    ranked = rank_findings(_real_drafts())["ranked"]
    final = finalize_findings(enforce_rules(ranked))
    assert final["confirmed"] == [] and len(final["dropped"]) == 4
    assert all("final skeptic round" in f["status_reason"] for f in final["dropped"])


def test_parse_verdicts_is_forgiving_but_strict_about_status():
    good = '[{"id": "F1", "status": "Confirmed", "reason": "ok"}, {"id": "F2", "status": "maybe"}, {"status": "dropped"}]'
    assert parse_verdicts(good) == [{"id": "F1", "status": "confirmed", "reason": "ok"}]
    assert parse_verdicts('```json\n{"verdicts": [{"id": "F1", "status": "dropped"}]}\n```')[0]["reason"] == "no reason given"
    assert parse_verdicts("garbage") == [] and parse_verdicts(None) == []
