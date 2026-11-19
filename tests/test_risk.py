"""Phase 6: schema validated, ranked by score, score and amount come from code, every finding has an entry_id."""
import json

import pandas as pd
import pytest
from pydantic import ValidationError

from auditpilot import tools
from auditpilot.schemas import Finding, FindingDraft, RiskAssessment
from auditpilot.tools.risk import amount_at_risk, parse_risk_draft, rank_findings, risk_score


def _draft(fid, ids, likelihood=4, impact=4, category="duplicate_payment", **extra):
    d = {"id": fid, "category": category, "title": f"title {fid}", "entry_ids": ids, "evidence": ["tool: numbers"],
         "likelihood": likelihood, "impact": impact, "rationale": "because", "policy_clause": ""}
    d.update(extra)
    return d


def test_finding_score_is_likelihood_times_impact_always():
    f = Finding(id="F1", category="benford", title="t", entry_ids=["L1"], evidence=[], likelihood=3, impact=5,
                rationale="r", score=999)                      # a supplied score is overwritten by code
    assert f.score == 15 and risk_score(3, 5) == 15


def test_schema_rejects_bad_values():
    with pytest.raises(ValidationError):
        Finding(id="F1", category="duplicate_payment", title="t", entry_ids=[], evidence=[], likelihood=3,
                impact=3, rationale="r")                       # needs >= 1 entry_id
    with pytest.raises(ValidationError):
        Finding(id="F1", category="duplicate_payment", title="t", entry_ids=["L1"], evidence=[], likelihood=6,
                impact=3, rationale="r")
    with pytest.raises(ValidationError):
        Finding(id="F1", category="made_up", title="t", entry_ids=["L1"], evidence=[], likelihood=1, impact=1,
                rationale="r")


def test_llm_facing_schema_has_no_amount_or_score_and_no_defaults():
    fields = set(FindingDraft.model_fields)
    assert "score" not in fields and "amount_at_risk_inr" not in fields
    assert all(f.is_required() for f in FindingDraft.model_fields.values())
    assert "findings" in RiskAssessment.model_json_schema()["properties"]


def test_amount_at_risk_comes_from_the_ledger():
    dup = tools.find_duplicates()
    led = pd.read_csv("data/ledger.csv").set_index("entry_id")
    expected = round(float(led.loc[dup["flagged_ids"], "amount_inr"].sum()), 2)
    assert amount_at_risk(dup["flagged_ids"]) == expected == dup["stats"]["excess_amount_inr"]
    assert amount_at_risk(["TB:5300"]) == 185000.0
    assert amount_at_risk(["FIN:2025-07"]) == 0.0


def test_ranked_sorted_by_score_and_code_computes_everything():
    dup_ids = tools.find_duplicates()["flagged_ids"]
    drafts = [
        _draft("F1", dup_ids, 2, 2),
        _draft("F2", ["TB:5300"], 5, 4, category="trial_balance_gap"),
        _draft("F3", tools.find_ghost_vendors()["flagged_ids"], 5, 5, category="ghost_vendor",
               score=1, amount_at_risk_inr=1.0, status="confirmed"),   # model-supplied extras must be ignored
    ]
    out = rank_findings(drafts)
    ranked = out["ranked"]
    assert [f["id"] for f in ranked] == ["F3", "F2", "F1"]
    assert [f["score"] for f in ranked] == sorted([f["score"] for f in ranked], reverse=True) == [25, 20, 4]
    f3 = ranked[0]
    assert f3["status"] == "proposed" and f3["amount_at_risk_inr"] > 1.0
    assert all(len(f["entry_ids"]) >= 1 for f in ranked)
    assert out["rejected"] == []


def test_findings_without_entry_ids_are_rejected_with_a_reason_not_dropped_silently():
    out = rank_findings([_draft("F1", []), _draft("F2", ["L00001"])])
    assert [f["id"] for f in out["ranked"]] == ["F2"]
    assert out["rejected"] == [{"id": "F1", "title": "title F1", "reason": "finding has no entry_ids"}]


def test_duplicate_ids_are_made_unique():
    out = rank_findings([_draft("F1", ["L00001"]), _draft("F1", ["L00002"])])
    assert len({f["id"] for f in out["ranked"]}) == 2


def test_parse_risk_draft_accepts_json_string_fenced_json_dict_and_junk():
    payload = {"findings": [_draft("F1", ["L00001"])]}
    assert len(parse_risk_draft(json.dumps(payload))) == 1
    assert len(parse_risk_draft("```json\n" + json.dumps(payload) + "\n```")) == 1
    assert len(parse_risk_draft(payload)) == 1
    assert len(parse_risk_draft(RiskAssessment(**payload))) == 1
    assert parse_risk_draft("not json") == [] and parse_risk_draft(None) == []
