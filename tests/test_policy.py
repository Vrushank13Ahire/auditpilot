"""Phase 5: policy retrieval returns the right clause and every quote is verbatim."""
import re
from pathlib import Path

import pytest

from auditpilot.tools import check_approval_limits, retrieve_policy
from auditpilot.tools.policy import split_clauses

POLICY = (Path(__file__).resolve().parents[1] / "data" / "policy.md").read_text()

QUESTIONS = [
    ("Who must approve a payment above Rs 50,000?", "4.2"),
    ("Can an employee approve their own payment?", "2.1"),
    ("Is splitting a bill into smaller payments to stay under the limit allowed?", "4.3"),
    ("May a vendor bank account be the same as an employee bank account?", "3.2"),
    ("Do Sunday payments need written justification?", "5.2"),
]


@pytest.mark.parametrize("question,clause", QUESTIONS)
def test_right_clause_is_top_1(question, clause):
    res = retrieve_policy(question)
    assert res["stats"]["results"][0]["clause_id"] == clause


def test_extra_questions_duplicates_and_reconciliation():
    assert retrieve_policy("same invoice paid twice to the vendor")["stats"]["results"][0]["clause_id"] == "5.1"
    assert retrieve_policy("ledger does not agree with the trial balance")["stats"]["results"][0]["clause_id"] == "6.1"


def test_k_and_shape():
    res = retrieve_policy("approval limit", k=2)
    assert set(res) == {"test", "flagged_ids", "stats", "notes"}
    assert len(res["stats"]["results"]) == 2
    scores = [r["score"] for r in res["stats"]["results"]]
    assert scores == sorted(scores, reverse=True)
    assert len(retrieve_policy("approval", k=50)["stats"]["results"]) == len(split_clauses(POLICY))


def test_quotes_are_verbatim_and_short():
    for question, _ in QUESTIONS:
        for r in retrieve_policy(question)["stats"]["results"]:
            assert re.sub(r"\s+", " ", r["quote"]) in re.sub(r"\s+", " ", POLICY)
            assert 0 < len(r["quote"]) <= 240


def test_clause_ids_are_numbered_and_unique():
    clauses = split_clauses(POLICY)
    ids = [c.clause_id for c in clauses]
    assert len(ids) == len(set(ids)) == 10 and "4.2" in ids


def test_policy_agent_inputs_cover_self_approved_and_split_entries(truth_ids):
    s = check_approval_limits()["stats"]
    assert set(s["self_approved_ids"]) == truth_ids("self_approved")
    assert set(s["split_suspect_ids"]) == truth_ids("split_payment")
    # the clause the agent must cite for each group is retrievable
    assert retrieve_policy("approving your own payment")["stats"]["results"][0]["clause_id"] == s["clause_hints"]["self_approved"]
    assert retrieve_policy("splitting a payment to stay under the approval limit")["stats"]["results"][0]["clause_id"] == s["clause_hints"]["split"]
