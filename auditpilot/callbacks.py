"""Phase 9 guardrails: an append-only audit trail and bank-number masking, attached to every LlmAgent via ADK callbacks.

The pure functions (mask_text, scrub_secrets, result_hash, make_record, append_trail) have no ADK dependency and are
unit-tested. The ADK adapters at the bottom only plug them into the callback signatures.

- Audit trail: one JSON line per model call and per tool call: timestamp, agent, tool, args, result hash.
  File: runs/<session_id>/audit_trail.jsonl (override the file with AUDITPILOT_TRAIL_PATH). Append-only.
- Masking: 11-18 digit numbers (bank accounts) are masked to their last 4 digits before text reaches the model.
- Secrets: API keys are scrubbed from anything logged; the trail never stores prompts or full tool results, only a hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tools.common import REPO_ROOT

BANK_RE = re.compile(r"(?<![\d.,])\d{11,18}(?!\d)")
SECRET_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9_\-]{20,}|(?i:(?:api[_-]?key|token|secret)[\"'\s:=]+)[^\s\"',}]+")


def _mask_digits(m: re.Match) -> str:
    s = m.group(0)
    return "*" * (len(s) - 4) + s[-4:]


def mask_text(text: str) -> str:
    """Mask bank-account-length digit runs to their last 4 digits. Amounts (at most 9 digits) are untouched."""
    return BANK_RE.sub(_mask_digits, str(text))


def scrub_secrets(obj: Any) -> Any:
    """Replace anything that looks like an API key or secret, recursively. Applied to everything that is logged."""
    if isinstance(obj, str):
        return SECRET_RE.sub("[REDACTED_SECRET]", obj)
    if isinstance(obj, dict):
        return {str(k): scrub_secrets(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [scrub_secrets(v) for v in obj]
    return obj


def mask_obj(obj: Any) -> Any:
    """mask_text applied recursively to strings inside dicts and lists."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_obj(v) for v in obj]
    return obj


def result_hash(obj: Any) -> str:
    """Short, stable fingerprint of a result, so the trail proves what came back without storing it."""
    blob = json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def trail_path(session_id: str | None) -> Path:
    override = os.environ.get("AUDITPILOT_TRAIL_PATH")
    if override:
        return Path(override)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id or "no_session"))
    return Path(os.environ.get("AUDITPILOT_RUNS_DIR", REPO_ROOT / "runs")) / safe / "audit_trail.jsonl"


def make_record(agent: str, tool: str, args: Any, result: Any, kind: str = "tool") -> dict:
    return {"timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "kind": kind,
            "agent": str(agent), "tool": str(tool), "args": scrub_secrets(mask_obj(args)),
            "result_hash": result_hash(result)}


def append_trail(record: dict, path: Path) -> None:
    """Append one line. The file is only ever opened in append mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")


# ----------------------------------------------------------------------------------------- ADK adapters

def _session_id(ctx: Any) -> str | None:
    for attr in ("session", "_invocation_context"):
        obj = getattr(ctx, attr, None)
        sid = getattr(obj, "id", None) or getattr(getattr(obj, "session", None), "id", None)
        if sid:
            return str(sid)
    return None


def _mask_part(part: Any) -> None:
    if getattr(part, "text", None):
        part.text = mask_text(part.text)
    fr = getattr(part, "function_response", None)
    if fr is not None and getattr(fr, "response", None) is not None:
        fr.response = mask_obj(fr.response)


def before_model(callback_context, llm_request):
    """Mask bank numbers in everything about to reach the model. Never blocks the call."""
    for content in getattr(llm_request, "contents", None) or []:
        for part in getattr(content, "parts", None) or []:
            _mask_part(part)
    si = getattr(getattr(llm_request, "config", None), "system_instruction", None)
    if isinstance(si, str):
        llm_request.config.system_instruction = mask_text(si)
    return None


def after_model(callback_context, llm_response):
    """One trail line per model call (a hash of the reply, never the reply)."""
    parts = getattr(getattr(llm_response, "content", None), "parts", None) or []
    reply = [getattr(p, "text", None) or str(getattr(p, "function_call", "")) for p in parts]
    append_trail(make_record(getattr(callback_context, "agent_name", "?"), "model", {"parts": len(parts)}, reply,
                             kind="model"), trail_path(_session_id(callback_context)))
    return None


def agent_callbacks(after_tool=None) -> dict:
    """Callbacks to hand to an LlmAgent: masking, audit trail, and an optional extra after_tool callback."""

    def _after_tool(tool, args, tool_context, tool_response):
        name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
        append_trail(make_record(getattr(tool_context, "agent_name", "?"), name, args, tool_response),
                     trail_path(_session_id(tool_context)))
        if after_tool is not None:
            return after_tool(tool=tool, args=args, tool_context=tool_context, tool_response=tool_response)
        return None

    return {"before_model_callback": before_model, "after_model_callback": after_model, "after_tool_callback": _after_tool}
