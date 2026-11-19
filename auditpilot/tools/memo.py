"""Audit memo: rendered by code from confirmed findings; a human partner signs it off. No LLM inside.

The report agent supplies only prose (executive summary, recommended actions, limitations). Every figure in the memo
comes from state or from tool outputs, and check_memo_numbers() proves it: any amount that no tool returned is rejected.
The memo is DRAFT until sign_off_memo(decision="approve") is called by a human; rewriting the memo resets it to DRAFT.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .anomalies import find_duplicates, find_split_payments, find_weekend_round
from .approvals import check_approval_limits
from .benford import benford_test
from .common import REPO_ROOT
from .ledger import check_trial_balance, load_ledger
from .ratios import ratio_table
from .risk import amount_at_risk
from .vendors import find_ghost_vendors, vendor_bank_overlap

COMPANY = "Kaveri Precision Components Pvt Ltd (fictional)"
DECISIONS = {"approve", "request_changes", "reject"}
MEMO_NAME = "audit_memo.md"
META_NAME = "audit_memo.meta.json"
MAX_IDS_SHOWN = 60
WITHHELD = "[evidence line withheld: it contains figures that no tool returned]"
STATUS_RE = re.compile(r"^\*\*Status: (DRAFT|FINAL)\*\*.*$", re.MULTILINE)
SIGNOFF_RE = re.compile(r"(## Sign-off\n\n).*\Z", re.DOTALL)

STANDARD_LIMITATIONS = [
    "All data in this audit is synthetic and fictional; this is a prototype, not an audit opinion.",
    "The tests find suspects. They do not prove fraud: an innocent explanation may exist for any finding.",
    "Only the files provided were tested (ledger, vendors, employees, trial balance, financials, policy).",
    "Likelihood and impact ratings are judgements applied to a fixed rubric; amounts and scores are computed by code.",
]
DEFAULT_ACTIONS = {
    "duplicate_payment": "Recover the excess amount from the vendor and add a duplicate-invoice check before payment.",
    "split_payment": "Review the grouped payments as one purchase and enforce approval at the combined value.",
    "ghost_vendor": "Freeze payments and verify the vendors' registration, address and deliverables with the Finance Head.",
    "shared_bank_account": "Escalate to the Finance Head for a conflict-of-interest review before any further payment.",
    "self_approved": "Re-approve the payments by an independent approver and block self-approval in the system.",
    "approval_limit_breach": "Obtain Finance Head approval for the payments and review approver authority settings.",
    "missing_approver": "Locate the approval evidence for each entry or reverse the payment.",
    "weekend_round": "Obtain the Finance Head's written justification for each Sunday round-sum payment.",
    "trial_balance_gap": "Investigate and clear the reconciliation difference before the books are closed.",
    "prompt_injection": "Treat the entries' text as hostile data, review who entered it, and keep it out of AI instructions.",
    "ratio_anomaly": "Ask management to explain the flagged months.",
    "benford": "Extend testing to the amounts that drive the digit-distribution departure.",
}


# ------------------------------------------------------------------------------------------------- helpers

def docs_dir() -> Path:
    return Path(os.environ.get("AUDITPILOT_DOCS_DIR", REPO_ROOT / "docs"))


def inr(x: float) -> str:
    """Rupees with Indian digit grouping, for example Rs 1,85,000.00."""
    s = f"{abs(float(x)):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{'-' if x < 0 else ''}Rs {whole}.{frac}"


def _walk_numbers(obj: Any, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            _walk_numbers(v, out)
    elif isinstance(obj, str):
        for m in _strip_ids(obj, keep_small=True):
            out.add(m)


_ID_PATTERNS = [r"FIN:\d{4}-\d{2}", r"TB:\d+", r"\b[A-Z]{1,4}-?\d{2,}\b", r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{4}-\d{2}\b",
                r"(?i)clauses?\s+\d+\.\d+", r"(?m)^\s*(?:\d+\.|[-*])\s+"]
_NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _strip_ids(text: str, keep_small: bool = False) -> list[float]:
    """All numbers in a text once ids, dates, months, clause references and list markers are removed."""
    for p in _ID_PATTERNS:
        text = re.sub(p, " ", text)
    vals = []
    for m in _NUM_RE.findall(text):
        try:
            v = round(float(m.replace(",", "").rstrip(".")), 2)
        except ValueError:
            continue
        if keep_small or v >= 100:
            vals.append(v)
    return vals


def tool_outputs() -> list[dict]:
    """Run every deterministic tool once. These outputs are the only legitimate source of figures."""
    fns = (load_ledger, check_trial_balance, benford_test, find_duplicates, find_split_payments, find_weekend_round,
           check_approval_limits, vendor_bank_overlap, find_ghost_vendors, ratio_table)
    return [fn() for fn in fns]


def allowed_numbers(findings: list[dict], extra: list[float] | None = None) -> set[float]:
    out: set[float] = {2025.0, 2026.0}
    for r in tool_outputs():
        _walk_numbers({k: v for k, v in r.items() if k != "flagged_ids"}, out)
    for f in findings:
        _walk_numbers({k: f.get(k) for k in ("amount_at_risk_inr", "score", "likelihood", "impact")}, out)
    out.update(round(float(x), 2) for x in (extra or []))
    return out


def check_memo_numbers(text: str, allowed: set[float]) -> dict:
    """Every number of 100 or more in the memo must appear in tool output (ids, dates and clause numbers excluded)."""
    found = _strip_ids(text)
    bad = sorted({v for v in found if v not in allowed})
    return {"ok": not bad, "checked": len(found), "unsupported_numbers": bad}


# --------------------------------------------------------------------------------------------- rendering

def _ids(ids: list[str]) -> str:
    shown = ", ".join(ids[:MAX_IDS_SHOWN])
    return shown + (f" ... and {len(ids) - MAX_IDS_SHOWN} more" if len(ids) > MAX_IDS_SHOWN else "")


def default_narrative(findings: list[dict]) -> dict:
    """Template prose used by the offline pipeline and as a fallback. Figures come from code only."""
    ids = sorted({i for f in findings for i in f["entry_ids"]})
    cats = sorted({f["category"] for f in findings})
    top = findings[0] if findings else None
    summary = (f"The audit tested every ledger entry with deterministic tests. {len(findings)} findings were confirmed "
               f"across {len(cats)} categories; together they involve {len(ids)} entries or reconciliation items and "
               f"{inr(amount_at_risk(ids))} at risk (each entry counted once)."
               + (f" The highest-ranked finding is {top['id']}: {top['title']} (score {top['score']})." if top else ""))
    actions = [f"{f['id']} ({f['category'].replace('_', ' ')}): {DEFAULT_ACTIONS.get(f['category'], 'Review with management.')}"
               for f in findings]
    return {"executive_summary": summary, "recommended_actions": actions, "limitations": []}


def render_memo(state: dict, narrative: dict) -> str:
    confirmed = list(state.get("confirmed_findings") or [])
    dropped = list(state.get("dropped_findings") or [])
    ledger, tb = load_ledger()["stats"], check_trial_balance()["stats"]
    allowed = allowed_numbers(confirmed + dropped)
    all_ids = sorted({i for f in confirmed for i in f["entry_ids"]})
    L: list[str] = [f"# Audit Memo: {COMPANY}", "", "**Status: DRAFT** (not final until a partner approves)", "",
                    "## 1. Scope and data", "",
                    f"- Period: FY 2025-26 ({ledger.get('date_min')} to {ledger.get('date_max')}).",
                    f"- Ledger: {ledger.get('rows')} entries, total {inr(ledger.get('total_amount_inr', 0))}, "
                    f"{ledger.get('distinct_vendors')} vendors. Every entry was tested (no sampling).",
                    f"- Trial balance: debits {inr(tb.get('total_debit_inr', 0))}, credits {inr(tb.get('total_credit_inr', 0))}; "
                    f"status {tb.get('status')}.",
                    "- Method: deterministic Python tests produce every number; AI agents explain, rate and challenge.", "",
                    "## 2. Executive summary", "", narrative.get("executive_summary", "").strip() or "(none)", "",
                    "## 3. Ranked findings", ""]
    if confirmed:
        L += ["| Rank | ID | Category | Title | Amount at risk | Likelihood | Impact | Score | Policy clause |",
              "|---|---|---|---|---|---|---|---|---|"]
        for n, f in enumerate(confirmed, 1):
            L.append(f"| {n} | {f['id']} | {f['category']} | {f['title']} | {inr(f['amount_at_risk_inr'])} | "
                     f"{f['likelihood']} | {f['impact']} | {f['score']} | {f.get('policy_clause') or '-'} |")
        L += ["", f"Combined amount at risk, each entry counted once: {inr(amount_at_risk(all_ids))}.", "",
              "### Evidence by finding", ""]
        for f in confirmed:
            ev = [e if not check_memo_numbers(e, allowed)["unsupported_numbers"] else WITHHELD for e in f.get("evidence", [])]
            L += [f"**{f['id']}: {f['title']}**", f"- Entry IDs: {_ids(f['entry_ids'])}"]
            L += [f"- Evidence: {e}" for e in ev]
            L += [f"- Rationale: {f.get('rationale', '')}", f"- Skeptic: {f.get('status_reason') or 'confirmed'}", ""]
    else:
        L += ["No findings were confirmed.", ""]
    L += ["## 4. Recommended actions", ""] + [f"- {a}" for a in narrative.get("recommended_actions", [])] + [""]
    L += ["## 5. Limitations", ""] + [f"- {x}" for x in STANDARD_LIMITATIONS + list(narrative.get("limitations", []))] + [""]
    L += ["## 6. Appendix: dropped findings", ""]
    if dropped:
        L += ["| ID | Category | Title | Entry IDs | Why it was dropped |", "|---|---|---|---|---|"]
        for f in dropped:
            L.append(f"| {f['id']} | {f.get('category') or '-'} | {f.get('title', '')} | {_ids(f.get('entry_ids') or []) or '-'} "
                     f"| {f.get('status_reason', '')} |")
    else:
        L.append("No findings were dropped.")
    L += ["", "## Sign-off", "", "Pending partner review. This memo is DRAFT until approved.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------------------- write + sign-off

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def memo_paths() -> tuple[Path, Path]:
    return docs_dir() / MEMO_NAME, docs_dir() / META_NAME


def build_and_write_memo(state: dict, narrative: dict | None = None) -> dict:
    """Render the memo, prove its numbers, write docs/audit_memo.md as DRAFT. Returns {"ok", ...}.

    If the narrative contains a figure that no tool returned, nothing is written and the offending numbers are returned
    so the report agent can rewrite its text.
    """
    confirmed = list(state.get("confirmed_findings") or [])
    base = default_narrative(confirmed)
    narrative = {**base, **{k: v for k, v in (narrative or {}).items() if v}}
    narrative["recommended_actions"] = [str(a) for a in narrative["recommended_actions"]]
    prose = " ".join([narrative["executive_summary"], *narrative["recommended_actions"], *map(str, narrative.get("limitations", []))])
    allowed = allowed_numbers(confirmed + list(state.get("dropped_findings") or []),
                              extra=[amount_at_risk(sorted({i for f in confirmed for i in f["entry_ids"]}))])
    prose_check = check_memo_numbers(prose, allowed)
    if not prose_check["ok"]:
        return {"ok": False, "status": "NOT_WRITTEN", "unsupported_numbers": prose_check["unsupported_numbers"],
                "message": "These figures were not returned by any tool. Rewrite using only exact figures from the "
                           "findings, or remove them."}
    text = render_memo(state, narrative)
    full_check = check_memo_numbers(text, allowed)
    path, meta = memo_paths()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    meta.write_text(json.dumps({"status": "DRAFT", "sha": _sha(text), "decision": None, "reviewer": None}, indent=2))
    return {"ok": True, "status": "DRAFT", "path": str(path), "findings": len(confirmed),
            "dropped": len(state.get("dropped_findings") or []), "number_check": full_check}


def sign_off_memo(decision: str, reviewer: str, comments: str = "") -> dict:
    """Human gate. approve flips DRAFT to FINAL; request_changes and reject leave it DRAFT and record why."""
    decision = str(decision).strip().lower().replace(" ", "_")
    reviewer, comments = str(reviewer).strip(), str(comments).strip()
    path, meta_path = memo_paths()
    if decision not in DECISIONS:
        return {"ok": False, "status": "UNCHANGED", "message": f"decision must be one of {sorted(DECISIONS)}"}
    if not reviewer:
        return {"ok": False, "status": "UNCHANGED", "message": "a reviewer name is required to sign off"}
    if not path.exists() or not meta_path.exists():
        return {"ok": False, "status": "UNCHANGED", "message": "there is no DRAFT memo to sign off; run the audit first"}
    text, meta = path.read_text(encoding="utf-8"), json.loads(meta_path.read_text())
    if meta.get("sha") != _sha(text):
        return {"ok": False, "status": "UNCHANGED", "message": "the memo changed after it was drafted; re-run the audit"}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if decision == "approve":
        status, line = "FINAL", f"Approved by {reviewer} on {stamp}." + (f" Comment: {comments}" if comments else "")
        text = STATUS_RE.sub(f"**Status: FINAL** (approved by {reviewer})", text, count=1)
    else:
        status = "DRAFT"
        line = (f"{'Changes requested' if decision == 'request_changes' else 'Rejected'} by {reviewer} on {stamp}."
                + (f" Comment: {comments}" if comments else "") + " The memo stays DRAFT.")
    text = SIGNOFF_RE.sub(lambda m: m.group(1) + line + "\n", text, count=1)
    path.write_text(text, encoding="utf-8")
    meta_path.write_text(json.dumps({"status": status, "sha": _sha(text), "decision": decision, "reviewer": reviewer,
                                     "comments": comments, "signed_at": stamp}, indent=2))
    return {"ok": True, "status": status, "decision": decision, "reviewer": reviewer, "path": str(path)}
