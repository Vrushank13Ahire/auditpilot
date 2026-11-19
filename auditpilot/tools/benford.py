"""Benford's-law first-digit test (a population-level screen, not an entry-level test)."""
from __future__ import annotations

import math

import pandas as pd

from .common import read_ledger, result, safe_tool

# Nigrini's mean-absolute-deviation conformity bands for first-digit tests
MAD_BANDS = [(0.006, "close conformity"), (0.012, "acceptable conformity"), (0.015, "marginally acceptable"),
             (float("inf"), "nonconformity")]


def first_digit(x: float) -> int:
    return int(f"{abs(x):e}"[0])


@safe_tool
def benford_test() -> dict:
    """Compare the leading-digit distribution of ledger amounts with Benford's law.

    Natural financial amounts have a leading digit 1 about 30% of the time, 2 about 18%, and so on. Large
    departures can indicate fabricated or manipulated amounts. This is a population screen, so flagged_ids is
    empty unless conformity is "nonconformity"; then it lists entries starting with the most over-represented digit.

    Returns {"test", "flagged_ids", "stats", "notes"}; stats include per-digit observed and expected percentages,
    mad (mean absolute deviation), chi_square and the conformity label.
    """
    led = read_ledger()
    digits = led["amount_inr"].map(first_digit)
    n = len(digits)
    rows, mad_sum, chi = [], 0.0, 0.0
    for d in range(1, 10):
        exp = math.log10(1 + 1 / d)
        obs = float((digits == d).sum()) / n
        mad_sum += abs(obs - exp)
        chi += (obs * n - exp * n) ** 2 / (exp * n)
        rows.append({"digit": d, "observed_pct": round(obs * 100, 2), "expected_pct": round(exp * 100, 2),
                     "deviation_pp": round((obs - exp) * 100, 2)})
    mad = mad_sum / 9
    label = next(name for limit, name in MAD_BANDS if mad <= limit)
    worst = max(rows, key=lambda r: r["deviation_pp"])
    flagged: list[str] = []
    if label == "nonconformity":
        flagged = list(led.loc[digits == worst["digit"], "entry_id"])
    stats = {"n": n, "digits": rows, "mad": round(mad, 5), "chi_square": round(chi, 2),
             "chi_square_critical_5pct_8df": 15.51, "conformity": label,
             "most_over_represented_digit": worst["digit"]}
    notes = (f"MAD {mad:.4f} = {label}. With thousands of rows chi-square is almost always significant, so MAD "
             f"is the primary measure. Benford screens the population; it does not prove any single entry wrong.")
    return result("benford_test", flagged, stats, notes)
