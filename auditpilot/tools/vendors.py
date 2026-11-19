"""Vendor tests: shared bank accounts and ghost vendors."""
from __future__ import annotations

from .common import GHOST_NEW_VENDOR_DAYS, mask_account, read_employees, read_ledger, read_vendors, result, safe_tool


def _digits(s: str) -> str:
    return "".join(ch for ch in str(s) if ch.isdigit())


@safe_tool
def vendor_bank_overlap() -> dict:
    """Find vendors whose bank account matches an employee's bank account, or another vendor's.

    A vendor paid into an employee's account is a classic fraud and conflict-of-interest indicator (policy clause
    3.2). Account numbers are masked to the last 4 digits in the output.

    Returns {"test", "flagged_ids", "stats", "notes"}. flagged_ids are the ledger entries paid to the matching
    vendors; stats.vendor_employee_matches and stats.vendor_vendor_matches list the matches.
    """
    vendors, emp, led = read_vendors(), read_employees(), read_ledger()
    emp_by_bank = {_digits(b): (e, n) for e, n, b in zip(emp.employee_id, emp.name, emp.bank_account) if _digits(b)}
    ve, vv, vendor_ids = [], [], set()
    seen: dict[str, str] = {}
    for r in vendors.itertuples(index=False):
        b = _digits(r.bank_account)
        if not b:
            continue
        if b in emp_by_bank:
            e_id, e_name = emp_by_bank[b]
            ve.append({"vendor_id": r.vendor_id, "vendor_name": r.name, "employee_id": e_id, "employee_name": e_name,
                       "bank_account_masked": mask_account(b)})
            vendor_ids.add(r.vendor_id)
        if b in seen:
            vv.append({"vendor_id": r.vendor_id, "other_vendor_id": seen[b], "bank_account_masked": mask_account(b)})
            vendor_ids.update({r.vendor_id, seen[b]})
        else:
            seen[b] = r.vendor_id
    paid = led[led.vendor_id.isin(vendor_ids)]
    stats = {"vendor_employee_matches": ve, "vendor_vendor_matches": vv, "vendors_flagged": sorted(vendor_ids),
             "payments_to_flagged_vendors": int(len(paid)), "amount_inr": round(float(paid.amount_inr.sum()), 2)}
    return result("vendor_bank_overlap", list(paid.entry_id), stats,
                  f"{len(ve)} vendor-employee and {len(vv)} vendor-vendor bank matches; {len(paid)} payments affected.")


@safe_tool
def find_ghost_vendors() -> dict:
    """Find possible ghost vendors: missing GSTIN or PAN AND first paid within 45 days of being created.

    Ghost vendors are fictitious or shell suppliers set up to receive payments (policy clause 3.1). A vendor with
    full tax registration, or one that is long established, is not flagged by this test.

    Returns {"test", "flagged_ids", "stats", "notes"}. flagged_ids are the ledger entries paid to the flagged
    vendors; stats.vendors lists vendor_id, missing fields, created_date, first_payment_date and total paid.
    """
    vendors, led = read_vendors(), read_ledger()
    first = led.groupby("vendor_id").date.min()
    out, ids = [], set()
    for r in vendors.itertuples(index=False):
        missing = [f for f, v in (("gstin", r.gstin), ("pan", r.pan)) if not str(v).strip()]
        if not missing or r.vendor_id not in first.index or r.created_date != r.created_date:
            continue
        gap = (first[r.vendor_id] - r.created_date).days
        if 0 <= gap <= GHOST_NEW_VENDOR_DAYS:
            total = float(led[led.vendor_id == r.vendor_id].amount_inr.sum())
            out.append({"vendor_id": r.vendor_id, "vendor_name": r.name, "missing_fields": missing,
                        "created_date": r.created_date, "first_payment_date": first[r.vendor_id],
                        "days_created_to_first_payment": int(gap), "total_paid_inr": round(total, 2)})
            ids.add(r.vendor_id)
    paid = led[led.vendor_id.isin(ids)]
    stats = {"vendors": out, "vendor_count": len(out), "payments": int(len(paid)),
             "amount_inr": round(float(paid.amount_inr.sum()), 2)}
    return result("find_ghost_vendors", list(paid.entry_id), stats,
                  f"{len(out)} possible ghost vendors with {len(paid)} payments.")
