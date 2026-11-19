"""Deterministic pipeline gates. Plain Python; ADK only supplies the callback plumbing.

If an intake tool reports FAILED, a flag is written to session state *by code*. Every later stage checks that
flag before it runs, so the pipeline stops no matter what the model says.
"""
from __future__ import annotations

from typing import Any

INTAKE_TOOLS = {"load_ledger", "check_trial_balance"}
BAD_STATUSES = {"FAILED", "ERROR"}


def record_intake_status(tool_name: str, tool_response: Any, state: Any) -> bool:
    """Set state['intake_failed'] when an intake tool reports FAILED/ERROR. Returns True if it did."""
    if tool_name not in INTAKE_TOOLS or not isinstance(tool_response, dict):
        return False
    stats = tool_response.get("stats") or {}
    if stats.get("status") not in BAD_STATUSES:
        return False
    reasons = list(state.get("intake_failure_reasons") or [])
    reasons += [f"{tool_name}: {r}" for r in (stats.get("reasons") or ["unspecified"])]
    state["intake_failed"] = True
    state["intake_failure_reasons"] = reasons
    return True


def halt_message(state: Any) -> str | None:
    """Return the stop message if intake failed, otherwise None."""
    if not state.get("intake_failed"):
        return None
    reasons = "; ".join(state.get("intake_failure_reasons") or ["unknown reason"])
    return (f"Pipeline stopped: intake validation FAILED ({reasons}). "
            f"Fix the data files and run 'start audit' again.")


# ---- ADK callback adapters (keyword names follow the ADK callback signatures) ------------------------------

def reset_intake_flags(callback_context):
    """before_agent_callback for intake_agent: start every run with a clean slate."""
    callback_context.state["intake_failed"] = False
    callback_context.state["intake_failure_reasons"] = []
    return None


def intake_after_tool(tool, args, tool_context, tool_response):
    """after_tool_callback for intake_agent: record FAILED results in state (never changes the tool result)."""
    record_intake_status(getattr(tool, "name", str(tool)), tool_response, tool_context.state)
    return None


def halt_if_failed(callback_context):
    """before_agent_callback for every stage after intake: skip the stage if intake failed."""
    msg = halt_message(callback_context.state)
    if msg is None:
        return None
    from google.genai import types  # imported lazily so this module works without ADK installed
    return types.Content(role="model", parts=[types.Part(text=msg)])
