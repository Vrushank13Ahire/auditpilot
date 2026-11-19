"""Financial ratio table with simple deterministic screens."""
from __future__ import annotations

import pandas as pd

from .common import FIN_COLUMNS, read_raw, result, safe_tool

Z_LIMIT = 2.5
MIN_CURRENT_RATIO = 1.0
MAX_DEBT_TO_EQUITY = 2.0
MAX_DSO_DAYS = 60.0
METRICS = ["gross_margin_pct", "net_margin_pct", "current_ratio", "quick_ratio", "debt_to_equity", "dso_days",
           "dpo_days"]


@safe_tool
def ratio_table() -> dict:
    """Compute monthly financial ratios from data/financials.csv and screen them for unusual months.

    Ratios: gross margin %, net margin %, current ratio, quick ratio, debt-to-equity, DSO and DPO (days, on a
    30-day month). A month is flagged if any ratio is more than 2.5 standard deviations from its own 12-month mean,
    or breaches a hard limit (current ratio < 1.0, debt-to-equity > 2.0, DSO > 60 days).

    Returns {"test", "flagged_ids", "stats", "notes"}. flagged_ids are "FIN:<YYYY-MM>" for flagged months;
    stats.table holds every month's ratios and stats.flags says which screen each flagged month failed.
    """
    df = read_raw("financials.csv", FIN_COLUMNS)
    for c in FIN_COLUMNS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    t = pd.DataFrame({
        "month": df["month"],
        "gross_margin_pct": (df.revenue - df.cogs) / df.revenue * 100,
        "net_margin_pct": df.net_profit / df.revenue * 100,
        "current_ratio": df.current_assets / df.current_liabilities,
        "quick_ratio": (df.current_assets - df.inventory) / df.current_liabilities,
        "debt_to_equity": df.total_debt / df.equity,
        "dso_days": df.receivables / df.revenue * 30,
        "dpo_days": df.payables / df.cogs * 30,
    })
    flags: dict[str, list[str]] = {}
    for m in METRICS:
        s = t[m]
        z = (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0
        for i in t.index[z.abs() > Z_LIMIT]:
            flags.setdefault(f"FIN:{t.month[i]}", []).append(f"{m} is {z[i]:+.1f} standard deviations from its mean")
    for i in t.index:
        key = f"FIN:{t.month[i]}"
        if t.current_ratio[i] < MIN_CURRENT_RATIO:
            flags.setdefault(key, []).append("current_ratio below 1.0")
        if t.debt_to_equity[i] > MAX_DEBT_TO_EQUITY:
            flags.setdefault(key, []).append("debt_to_equity above 2.0")
        if t.dso_days[i] > MAX_DSO_DAYS:
            flags.setdefault(key, []).append("dso_days above 60")
    summary = {m: {"mean": round(float(t[m].mean()), 3), "min": round(float(t[m].min()), 3),
                   "max": round(float(t[m].max()), 3)} for m in METRICS}
    table = [{k: (v if k == "month" else round(float(v), 3)) for k, v in row.items()}
             for row in t.to_dict("records")]
    stats = {"table": table, "summary": summary, "flags": flags, "months": len(t)}
    return result("ratio_table", list(flags), stats,
                  f"{len(flags)} of {len(t)} months flagged." if flags else
                  f"No month breaches a ratio screen across {len(t)} months.")
