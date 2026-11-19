"""Deterministic detector for prompt-injection text hiding in ledger fields.

Ledger text is untrusted data. This is defence in depth: agents are also told to ignore it.
"""
from __future__ import annotations

import re

import pandas as pd

PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(your|the|all)\s+(rules|instructions|guidelines)",
    r"\bsystem\s*:",
    r"you\s+are\s+now\b",
    r"reveal\s+.{0,40}(api[_\s-]?key|password|secret|token)",
    r"\boverride\s*:",
    r"(mark|set)\s+(all|every)\s+(findings?|risk\s+scores?)",
    r"risk\s+scores?\s+to\s+0",
    r"do\s+not\s+report",
    r"approve\s+the\s+memo",
    r"skip\s+the\s+skeptic",
    r"<!--.*-->",
]
_RE = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE | re.DOTALL)

REDACTED = "[REDACTED: suspected prompt injection]"


def is_suspicious(text: str) -> bool:
    return bool(_RE.search(str(text or "")))


def sanitize(text: str) -> str:
    """Return the text, or a redaction marker if it looks like an injection attempt."""
    return REDACTED if is_suspicious(text) else str(text or "")


def find_suspicious_ids(df: pd.DataFrame, id_col: str = "entry_id", text_col: str = "description") -> list[str]:
    mask = df[text_col].map(is_suspicious)
    return [str(i) for i in df.loc[mask, id_col]]
