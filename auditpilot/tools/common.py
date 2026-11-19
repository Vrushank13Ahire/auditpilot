"""Shared helpers for the deterministic audit tools. No LLM calls, no printing, no randomness."""
from __future__ import annotations

import functools
import math
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

# Policy constants (mirrors data/policy.md)
APPROVAL_LIMIT_INR = 50_000.0
SPLIT_WINDOW_DAYS = 7
SPLIT_BAND_FLOOR = 0.9          # "just under the limit" = 90%..100% of the limit
SPLIT_MIN_PAYMENTS = 3
DUPLICATE_WINDOW_DAYS = 30
GHOST_NEW_VENDOR_DAYS = 45
ROUND_UNIT_INR = 5_000
FY_START = "2025-04-01"
FY_END = "2026-03-31"

LEDGER_COLUMNS = ["entry_id", "date", "posted_by", "approved_by", "account_code", "account_name",
                  "vendor_id", "amount_inr", "description"]
VENDOR_COLUMNS = ["vendor_id", "name", "gstin", "pan", "bank_account", "created_date"]
EMPLOYEE_COLUMNS = ["employee_id", "name", "department", "role", "bank_account"]
TB_COLUMNS = ["account_code", "account_name", "debit_inr", "credit_inr"]
FIN_COLUMNS = ["month", "revenue", "cogs", "opex", "net_profit", "receivables", "payables", "inventory",
               "cash", "current_assets", "current_liabilities", "total_debt", "equity"]


class DataError(Exception):
    """Raised when an input file is missing or malformed."""


def data_dir() -> Path:
    """Folder holding the CSVs. Overridable with AUDITPILOT_DATA_DIR (used by tests)."""
    return Path(os.environ.get("AUDITPILOT_DATA_DIR", REPO_ROOT / "data"))


def read_raw(name: str, required: list[str]) -> pd.DataFrame:
    path = data_dir() / name
    if not path.exists():
        raise DataError(f"{name} not found")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataError(f"{name} is missing required columns: {', '.join(missing)}")
    return df


def read_ledger() -> pd.DataFrame:
    """Ledger with typed columns: date (datetime), amount_inr (float)."""
    df = read_raw("ledger.csv", LEDGER_COLUMNS)
    df["amount_inr"] = pd.to_numeric(df["amount_inr"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["amount_inr"].isna().any() or df["date"].isna().any():
        raise DataError("ledger.csv has unparseable dates or amounts; run load_ledger for details")
    return df


def read_vendors() -> pd.DataFrame:
    df = read_raw("vendors.csv", VENDOR_COLUMNS)
    df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
    return df


def read_employees() -> pd.DataFrame:
    return read_raw("employees.csv", EMPLOYEE_COLUMNS)


def clean(obj: Any) -> Any:
    """Make an object JSON-safe (numpy scalars, NaN, Timestamps)."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    return obj


def result(test: str, flagged_ids: list[str], stats: dict, notes: str) -> dict:
    """The one return shape every tool uses."""
    return {"test": test, "flagged_ids": sorted({str(i) for i in flagged_ids}),
            "stats": clean(stats), "notes": notes}


def mask_account(value: str) -> str:
    """Show only the last 4 digits of a bank account number."""
    v = str(value)
    return "*" * max(len(v) - 4, 0) + v[-4:]


def safe_tool(fn: Callable) -> Callable:
    """Turn any exception into a normal tool result so an agent run never crashes."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DataError as exc:
            return result(fn.__name__, [], {"status": "FAILED", "reasons": [str(exc)]}, f"Input problem: {exc}")
        except Exception as exc:  # noqa: BLE001 - tools must never raise into the agent loop
            return result(fn.__name__, [], {"status": "ERROR", "reasons": [f"{type(exc).__name__}: {exc}"]},
                          f"Tool error: {type(exc).__name__}: {exc}")

    return wrapper
