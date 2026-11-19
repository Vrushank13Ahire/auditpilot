"""Offline pipeline: the whole audit with no LLM, using the exact same tools, scoring, skeptic rules and memo code.

Why it exists: (1) it proves the deterministic layer end to end and gives the evaluation a reproducible baseline,
(2) it runs where there is no Gemini key or quota. The ADK agents add the explanation, the likelihood/impact
judgement and the challenge on top of the same tool outputs; they do not replace them.
"""
from __future__ import annotations

from .gates import halt_message, record_intake_status
from .tools import (benford_test, check_approval_limits, check_trial_balance, find_duplicates, find_ghost_vendors,
                    find_split_payments, find_weekend_round, load_ledger, ratio_table, vendor_bank_overlap)
from .tools.memo import build_and_write_memo
from .tools.risk import amount_at_risk, rank_findings
from .tools.skeptic import apply_verdicts, enforce_rules, finalize_findings, needs_review

MAX_ROUNDS = 3

# category -> (title, base likelihood, policy clause). Likelihood follows the risk rubric: 5 = unambiguous tool hit.
CATEGORY_RULES = {
    "trial_balance_gap": ("Ledger does not tie to the trial balance", 5, "6.1"),
    "shared_bank_account": ("Vendor bank account shared with an employee or another vendor", 5, "3.2"),
    "ghost_vendor": ("Possible ghost vendors: no GSTIN/PAN and paid soon after creation", 4, "3.1"),
    "self_approved": ("Payments approved by the person who posted them", 5, "2.1"),
    "split_payment": ("Payments split to stay under the Rs 50,000 approval limit", 4, "4.3"),
    "duplicate_payment": ("Duplicate payments to the same vendor for the same amount", 4, "5.1"),
    "approval_limit_breach": ("Payments approved without the required authority", 5, "4.2"),
    "missing_approver": ("Payments with a missing or unknown approver", 5, "4.1"),
    "weekend_round": ("Round-sum payments entered on a Sunday", 3, "5.2"),
    "prompt_injection": ("Ledger descriptions contain prompt-injection text", 5, ""),
    "ratio_anomaly": ("Unusual financial ratios in some months", 3, ""),
    "benford": ("Amounts depart from Benford's law", 2, ""),
}
FRAUD = {"ghost_vendor", "shared_bank_account"}
CONTROL_OVERRIDE = {"self_approved", "split_payment"}


def impact_for(category: str, amount: float) -> int:
    """Impact per the rubric: 5 = above Rs 10 lakh or a fraud indicator; 4 = Rs 2.5-10 lakh or a control override;
    3 = Rs 50,000-2.5 lakh or a policy breach; 2 = Rs 10,000-50,000; 1 = below Rs 10,000 or informational."""
    if category == "prompt_injection":
        return 3                                   # an attack on the controls, not a money loss
    if category in FRAUD or amount > 1_000_000:
        return 5
    if amount >= 250_000 or category in CONTROL_OVERRIDE:
        return 4
    if amount >= 50_000 or CATEGORY_RULES[category][2]:
        return 3
    return 2 if amount >= 10_000 else 1


def collect() -> tuple[dict, dict[str, list[str]]]:
    """Run every tool once; return their raw results and the flagged ids per finding category."""
    r = {fn.__name__: fn() for fn in (load_ledger, check_trial_balance, benford_test, find_duplicates, find_split_payments,
                                      find_weekend_round, check_approval_limits, vendor_bank_overlap,
                                      find_ghost_vendors, ratio_table)}
    s = r["check_approval_limits"]["stats"]
    ids = {
        "trial_balance_gap": r["check_trial_balance"]["flagged_ids"],
        "shared_bank_account": r["vendor_bank_overlap"]["flagged_ids"],
        "ghost_vendor": r["find_ghost_vendors"]["flagged_ids"],
        "self_approved": s.get("self_approved_ids", []),
        "split_payment": r["find_split_payments"]["flagged_ids"],
        "duplicate_payment": r["find_duplicates"]["flagged_ids"],
        "approval_limit_breach": sorted(set(s.get("over_limit_ids", [])) | set(s.get("under_authorised_ids", []))),
        "missing_approver": s.get("missing_or_unknown_approver_ids", []),
        "weekend_round": r["find_weekend_round"]["flagged_ids"],
        "prompt_injection": r["load_ledger"]["flagged_ids"],
        "ratio_anomaly": r["ratio_table"]["flagged_ids"],
        "benford": r["benford_test"]["flagged_ids"],
    }
    return r, ids


_EVIDENCE_TOOL = {"trial_balance_gap": "check_trial_balance", "shared_bank_account": "vendor_bank_overlap",
                  "ghost_vendor": "find_ghost_vendors", "self_approved": "check_approval_limits",
                  "split_payment": "find_split_payments", "duplicate_payment": "find_duplicates",
                  "approval_limit_breach": "check_approval_limits", "missing_approver": "check_approval_limits",
                  "weekend_round": "find_weekend_round", "prompt_injection": "load_ledger",
                  "ratio_anomaly": "ratio_table", "benford": "benford_test"}


def draft_findings(results: dict, ids: dict[str, list[str]]) -> list[dict]:
    """Rule-based stand-in for the risk assessor: one FindingDraft-shaped dict per category the tools flagged."""
    drafts = []
    for cat, flagged in ids.items():
        if not flagged:
            continue
        title, likelihood, clause = CATEGORY_RULES[cat]
        tool = _EVIDENCE_TOOL[cat]
        drafts.append({
            "id": f"F{len(drafts) + 1}", "category": cat, "title": title, "entry_ids": list(flagged),
            "evidence": [f"{tool}: {results[tool]['notes']}"], "likelihood": likelihood,
            "impact": impact_for(cat, amount_at_risk(list(flagged))),
            "rationale": "Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.",
            "policy_clause": clause})
    return drafts


def run_offline(write_memo: bool = True) -> dict:
    """Run the full pipeline offline. Returns state-like dict: ranked/confirmed/dropped findings, the memo result."""
    results, ids = collect()
    gate: dict = {}                                             # same stop rule as the agent pipeline's intake gate
    for name in ("load_ledger", "check_trial_balance"):
        record_intake_status(name, results[name], gate)
    if gate.get("intake_failed"):
        return {"ranked_findings": [], "confirmed_findings": [], "dropped_findings": [], "rejected_findings": [],
                "intake_failed": True, "halt_message": halt_message(gate)}
    scored = rank_findings(draft_findings(results, ids))
    findings = scored["ranked"]
    for _ in range(MAX_ROUNDS):                                 # same skeptic rules and loop bound as the agents
        findings = enforce_rules(apply_verdicts(findings, [
            {"id": f["id"], "status": "confirmed", "reason": "ids exist and the deterministic test flags every cited entry"}
            for f in findings if f["status"] in {"proposed", "needs_evidence"}]))
        if not needs_review(findings):
            break
    final = finalize_findings(findings, scored["rejected"])
    state = {"ranked_findings": findings, "confirmed_findings": final["confirmed"], "dropped_findings": final["dropped"],
             "rejected_findings": scored["rejected"]}
    if write_memo:
        state["memo"] = build_and_write_memo(state)
    return state


def predictions(state: dict) -> dict[str, set[str]]:
    """Entry ids per anomaly type, taken from confirmed findings (same type names as the hidden answer key)."""
    names = {"weekend_round": "sunday_round"}
    out: dict[str, set[str]] = {}
    for f in state.get("confirmed_findings", []):
        out.setdefault(names.get(f["category"], f["category"]), set()).update(f["entry_ids"])
    return out


if __name__ == "__main__":      # python -m auditpilot.offline  -> writes docs/audit_memo.md (DRAFT) from the offline pipeline
    _s = run_offline()
    print(f"{len(_s['confirmed_findings'])} confirmed, {len(_s['dropped_findings'])} dropped; memo: {_s['memo']['path']} "
          f"({_s['memo']['status']})")
