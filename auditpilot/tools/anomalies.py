"""Entry-level anomaly tests: duplicates, split payments, Sunday round-sum payments."""
from __future__ import annotations

import pandas as pd

from .common import (APPROVAL_LIMIT_INR, DUPLICATE_WINDOW_DAYS, ROUND_UNIT_INR, SPLIT_BAND_FLOOR,
                     SPLIT_MIN_PAYMENTS, SPLIT_WINDOW_DAYS, read_ledger, result, safe_tool)


def duplicate_groups(led: pd.DataFrame) -> list[dict]:
    """Groups of payments to the same vendor for the same amount within the duplicate window."""
    groups = []
    for (vendor, amount), g in led.groupby(["vendor_id", "amount_inr"]):
        if len(g) < 2:
            continue
        g = g.sort_values(["date", "entry_id"])
        if (g["date"].max() - g["date"].min()).days > DUPLICATE_WINDOW_DAYS:
            continue
        groups.append({"vendor_id": vendor, "amount_inr": float(amount), "original_id": g.iloc[0]["entry_id"],
                       "duplicate_ids": list(g.iloc[1:]["entry_id"]),
                       "dates": [d.strftime("%Y-%m-%d") for d in g["date"]]})
    return groups


def split_groups(led: pd.DataFrame) -> list[dict]:
    """Clusters of >=3 payments to one vendor within the window, each just under the approval limit."""
    floor = SPLIT_BAND_FLOOR * APPROVAL_LIMIT_INR
    band = led[(led.amount_inr >= floor) & (led.amount_inr < APPROVAL_LIMIT_INR)]
    groups = []
    for vendor, g in band.groupby("vendor_id"):
        g = g.sort_values(["date", "entry_id"]).reset_index(drop=True)
        i = 0
        while i < len(g):
            j = i
            while j + 1 < len(g) and (g.loc[j + 1, "date"] - g.loc[i, "date"]).days <= SPLIT_WINDOW_DAYS:
                j += 1
            members = g.loc[i:j]
            if len(members) >= SPLIT_MIN_PAYMENTS and members.amount_inr.sum() > APPROVAL_LIMIT_INR:
                groups.append({"vendor_id": vendor, "entry_ids": list(members.entry_id),
                               "combined_amount_inr": round(float(members.amount_inr.sum()), 2),
                               "first_date": members.date.min().strftime("%Y-%m-%d"),
                               "last_date": members.date.max().strftime("%Y-%m-%d")})
                i = j + 1
            else:
                i += 1
    return groups


@safe_tool
def find_duplicates() -> dict:
    """Find duplicate payments: same vendor and same amount paid more than once within 30 days.

    The first payment is treated as the original; every later copy is flagged. Policy clause 5.1.

    Returns {"test", "flagged_ids", "stats", "notes"}; flagged_ids are the later copies, stats.groups lists the
    original_id and duplicate_ids per group, and stats.excess_amount_inr is the money paid twice.
    """
    led = read_ledger()
    groups = duplicate_groups(led)
    flagged = [i for g in groups for i in g["duplicate_ids"]]
    excess = float(led[led.entry_id.isin(flagged)].amount_inr.sum())
    stats = {"groups": groups, "group_count": len(groups), "duplicate_entries": len(flagged),
             "excess_amount_inr": round(excess, 2)}
    return result("find_duplicates", flagged, stats,
                  f"{len(groups)} duplicate groups; {len(flagged)} later copies, Rs {excess:,.2f} paid twice.")


@safe_tool
def find_split_payments() -> dict:
    """Find split payments that stay just under the Rs 50,000 approval limit.

    Looks for 3 or more payments to one vendor within 7 days, each between 90% and 100% of the limit (Rs 45,000 to
    just under Rs 50,000), whose combined value exceeds the limit. Policy clause 4.3.

    Returns {"test", "flagged_ids", "stats", "notes"}; flagged_ids are every payment in a suspected split group;
    stats.groups gives vendor, entry_ids and combined amount per group.
    """
    led = read_ledger()
    groups = split_groups(led)
    flagged = [i for g in groups for i in g["entry_ids"]]
    stats = {"groups": groups, "group_count": len(groups), "entries": len(flagged),
             "limit_inr": APPROVAL_LIMIT_INR, "window_days": SPLIT_WINDOW_DAYS}
    return result("find_split_payments", flagged, stats,
                  f"{len(groups)} suspected split groups covering {len(flagged)} payments.")


@safe_tool
def find_weekend_round() -> dict:
    """Find round-amount payments entered on a Sunday.

    Flags entries dated on a Sunday whose amount is an exact multiple of Rs 5,000 (and at least Rs 5,000).
    Genuine invoices rarely look like that. Policy clause 5.2.

    Returns {"test", "flagged_ids", "stats", "notes"}.
    """
    led = read_ledger()
    sunday = led.date.dt.dayofweek == 6
    round_amt = (led.amount_inr >= ROUND_UNIT_INR) & ((led.amount_inr % ROUND_UNIT_INR).abs() < 1e-9)
    hit = led[sunday & round_amt]
    stats = {"sunday_entries": int(sunday.sum()), "round_unit_inr": ROUND_UNIT_INR, "flagged": len(hit),
             "total_amount_inr": round(float(hit.amount_inr.sum()), 2)}
    return result("find_weekend_round", list(hit.entry_id), stats,
                  f"{len(hit)} Sunday round-amount entries out of {int(sunday.sum())} Sunday entries.")
