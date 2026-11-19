"""Approval-control test: segregation of duties and approval limits."""
from __future__ import annotations

from .anomalies import split_groups
from .common import APPROVAL_LIMIT_INR, read_employees, read_ledger, result, safe_tool

CAN_APPROVE_UP_TO_LIMIT = {"Manager", "Finance Head"}


@safe_tool
def check_approval_limits() -> dict:
    """Check every ledger entry against the approval rules in data/policy.md.

    Tests: (1) self-approval, posted_by equals approved_by (clause 2.1); (2) payments above Rs 50,000 not approved
    by a Finance Head (clause 4.2); (3) payments up to Rs 50,000 not approved by a Manager or Finance Head
    (clause 4.1); (4) split-payment clusters that avoid the limit (clause 4.3); (5) approver missing or unknown.

    Returns {"test", "flagged_ids", "stats", "notes"}. stats lists self_approved_ids, over_limit_ids,
    under_authorised_ids, split_suspect_ids and missing_or_unknown_approver_ids. Use retrieve_policy to find the
    clause text before citing it.
    """
    led, emp = read_ledger(), read_employees()
    role = dict(zip(emp.employee_id, emp.role))
    self_ids, over_ids, under_ids, bad_ids = [], [], [], []
    for r in led.itertuples(index=False):
        if not r.approved_by or r.approved_by not in role:
            bad_ids.append(r.entry_id)
            continue
        if r.posted_by == r.approved_by:
            self_ids.append(r.entry_id)
        if r.amount_inr > APPROVAL_LIMIT_INR and role[r.approved_by] != "Finance Head":
            over_ids.append(r.entry_id)
        elif r.amount_inr <= APPROVAL_LIMIT_INR and role[r.approved_by] not in CAN_APPROVE_UP_TO_LIMIT:
            under_ids.append(r.entry_id)
    splits = split_groups(led)
    split_ids = [i for g in splits for i in g["entry_ids"]]
    flagged = self_ids + over_ids + under_ids + split_ids + bad_ids
    amt = led.set_index("entry_id").amount_inr
    stats = {"limit_inr": APPROVAL_LIMIT_INR, "self_approved_ids": sorted(self_ids), "over_limit_ids": sorted(over_ids),
             "under_authorised_ids": sorted(under_ids), "split_suspect_ids": sorted(split_ids),
             "missing_or_unknown_approver_ids": sorted(bad_ids),
             "self_approved_amount_inr": round(float(amt.reindex(self_ids).sum()), 2),
             "split_suspect_amount_inr": round(float(amt.reindex(split_ids).sum()), 2),
             "clause_hints": {"self_approved": "2.1", "over_limit": "4.2", "under_authorised": "4.1",
                              "split": "4.3"}}
    return result("check_approval_limits", flagged, stats,
                  f"{len(self_ids)} self-approved, {len(over_ids)} over-limit, {len(under_ids)} under-authorised, "
                  f"{len(split_ids)} split-payment suspects, {len(bad_ids)} with missing/unknown approver.")
