"""Risk scoring in code: amount at risk, score = likelihood x impact, and ranking. The model never does this math."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from auditpilot.schemas import Finding

from .common import read_ledger
from .ledger import check_trial_balance

FINDING_FIELDS = set(Finding.model_fields) - {"amount_at_risk_inr", "score", "status", "status_reason"}


def risk_score(likelihood: int, impact: int) -> int:
    """score = likelihood x impact (1..25)."""
    return int(likelihood) * int(impact)


def amount_at_risk(entry_ids: list[str]) -> float:
    """Rupees at risk for a finding: ledger payments summed, TB:<account> = the reconciliation gap, FIN:<month> = 0."""
    ids = list(dict.fromkeys(str(i).strip() for i in entry_ids if str(i).strip()))
    total = 0.0
    ledger_ids = [i for i in ids if not i.startswith(("TB:", "FIN:"))]
    if ledger_ids:
        led = read_ledger().set_index("entry_id")["amount_inr"]
        total += float(led.reindex(ledger_ids).fillna(0.0).sum())
    tb_ids = {i[3:] for i in ids if i.startswith("TB:")}
    if tb_ids:
        for m in check_trial_balance()["stats"].get("account_mismatches", []):
            if m["account_code"] in tb_ids:
                total += abs(float(m["difference_inr"]))
    return round(total, 2)


def parse_risk_draft(value: Any) -> list[dict]:
    """Turn the risk agent's saved output (JSON string, dict or pydantic object) into a list of draft dicts."""
    if value is None:
        return []
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, str):
        text = re.sub(r"^```(?:json)?|```$", "", value.strip(), flags=re.MULTILINE).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        value = value.get("findings", [])
    return [f for f in value if isinstance(f, dict)] if isinstance(value, list) else []


def rank_findings(drafts: list[dict]) -> dict:
    """Validate drafts, compute amount and score by code, and sort by score (then amount) descending.

    Returns {"ranked": [Finding dicts], "rejected": [{"id", "reason"}]}. A draft with no entry_ids, or that fails the
    schema, is rejected with a reason (never silently dropped).
    """
    ranked, rejected, seen = [], [], set()
    for n, d in enumerate(drafts, start=1):
        fid = str(d.get("id") or f"F{n}")
        while fid in seen:
            fid += "x"
        seen.add(fid)
        ids = list(dict.fromkeys(str(i).strip() for i in (d.get("entry_ids") or []) if str(i).strip()))
        if not ids:
            rejected.append({"id": fid, "title": str(d.get("title", "")), "reason": "finding has no entry_ids"})
            continue
        payload = {k: v for k, v in d.items() if k in FINDING_FIELDS}   # score/amount/status from the model are ignored
        payload.update(id=fid, entry_ids=ids, amount_at_risk_inr=amount_at_risk(ids), status="proposed")
        try:
            ranked.append(Finding(**payload).model_dump())
        except ValidationError as exc:
            rejected.append({"id": fid, "title": str(d.get("title", "")),
                             "reason": "schema validation failed: " + "; ".join(e["msg"] for e in exc.errors())})
    ranked.sort(key=lambda f: (-f["score"], -f["amount_at_risk_inr"], f["id"]))
    return {"ranked": ranked, "rejected": rejected}
