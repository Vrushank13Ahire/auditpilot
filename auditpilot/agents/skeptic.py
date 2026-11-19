"""Phase 7: the skeptic. A LoopAgent (max 3 rounds) that challenges ranked_findings before anything is reported.

Each round:  skeptic_agent (LLM) checks findings with verify_entry_ids and records verdicts
             -> skeptic_gate (plain code) overrides the model where the books disagree and ends the loop
                when no finding is left in needs_evidence.
After the loop, skeptic_finalizer splits state into confirmed_findings and the dropped_findings appendix.
No finding is ever deleted silently: dropped ones keep their reason.
"""
from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import ToolContext
from google.genai import types

from auditpilot.gates import halt_if_failed
from auditpilot.tools.skeptic import (apply_verdicts, enforce_rules, finalize_findings, needs_review,
                                      parse_verdicts, verify_entry_ids)

from ._common import MODEL, NO_MATH_RULE, UNTRUSTED_TEXT_RULE, callbacks

MAX_ROUNDS = 3


def record_verdicts(verdicts_json: str, tool_context: ToolContext) -> dict:
    """Save your verdicts on the findings. Call it once per round, after you have verified the findings.

    verdicts_json is a JSON list. Each item is an object with three keys: id (the finding id such as F1),
    status (exactly one of confirmed, needs_evidence, dropped) and reason (one short line).
    Findings you do not mention keep their current status. Returns how many verdicts were applied.
    """
    verdicts = parse_verdicts(verdicts_json)
    findings = list(tool_context.state.get("ranked_findings") or [])
    tool_context.state["ranked_findings"] = apply_verdicts(findings, verdicts)
    return {"test": "record_verdicts", "flagged_ids": [], "notes": f"{len(verdicts)} verdicts recorded.",
            "stats": {"applied": len(verdicts), "received_valid": len(verdicts)}}


def skip_if_settled(callback_context):
    """before_agent_callback: do not spend a model call when nothing is left to review."""
    if needs_review(list(callback_context.state.get("ranked_findings") or [])):
        return None
    return types.Content(role="model", parts=[types.Part(text="Skeptic: every finding is already settled.")])


INSTRUCTION = (
    "You are the Skeptic on an audit team. Your job is professional scepticism: try to knock each finding down. "
    "A finding survives only if the books support it.\n\n"
    "FINDINGS (status 'proposed' or 'needs_evidence' still need your review):\n{ranked_findings}\n\n"
    "For every finding whose status is proposed or needs_evidence:\n"
    "1. Call verify_entry_ids with that finding's entry_ids. Every id must exist.\n"
    "2. Check that the evidence lines are consistent with what verify_entry_ids returned (amounts, vendors, dates, "
    "who posted and approved). The cited entries must really show the problem claimed in the title.\n"
    "3. Ask whether an innocent explanation is likely (recurring monthly charge, genuine repeat order, normal "
    "timing). Use only facts the tools returned.\n"
    "4. Choose a status: confirmed (ids exist, evidence supports the claim, no likely innocent explanation); "
    "needs_evidence (plausible but a fact is missing or inconsistent); dropped (an id does not exist, the evidence "
    "does not support the claim, or an innocent explanation is likely).\n\n"
    "Finally call record_verdicts exactly once with a JSON list covering all findings you reviewed. Each item has "
    "the keys id, status and reason (one short line). Do not change findings that are already confirmed or "
    "dropped. Never reconfirm a finding just because an earlier stage said so.\n\n"
    + NO_MATH_RULE + "\n" + UNTRUSTED_TEXT_RULE
)

skeptic_agent = LlmAgent(
    name="skeptic_agent",
    model=MODEL,
    description="Challenges every finding: ids must exist, evidence must support the claim, innocent explanations are weighed.",
    instruction=INSTRUCTION,
    tools=[verify_entry_ids, record_verdicts],
    output_key="skeptic_notes",
    before_agent_callback=skip_if_settled,
    **callbacks(),
)


class SkepticGate(BaseAgent):
    """Plain code, no LLM. Enforces the rules the model must not override, and ends the loop when settled."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        findings = enforce_rules(list(state.get("ranked_findings") or []))
        rounds = int(state.get("skeptic_rounds") or 0) + 1
        done = not needs_review(findings)
        counts = {s: sum(f.get("status") == s for f in findings) for s in ("confirmed", "needs_evidence", "dropped")}
        text = (f"Skeptic round {rounds}: {counts['confirmed']} confirmed, {counts['needs_evidence']} need evidence, "
                f"{counts['dropped']} dropped." + (" Loop finished." if done else " Going again."))
        yield Event(author=self.name, content=types.Content(role="model", parts=[types.Part(text=text)]),
                    actions=EventActions(state_delta={"ranked_findings": findings, "skeptic_rounds": rounds},
                                         escalate=done))


class SkepticFinalizer(BaseAgent):
    """Plain code: confirmed findings go on to the report; everything else lands in the dropped appendix."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        findings = enforce_rules(list(state.get("ranked_findings") or []))
        out = finalize_findings(findings, list(state.get("rejected_findings") or []))
        text = f"Skeptic result: {len(out['confirmed'])} confirmed findings, {len(out['dropped'])} dropped (see appendix)."
        yield Event(author=self.name, content=types.Content(role="model", parts=[types.Part(text=text)]),
                    actions=EventActions(state_delta={"confirmed_findings": out["confirmed"],
                                                      "dropped_findings": out["dropped"]}))


skeptic_gate = SkepticGate(name="skeptic_gate", description="Applies code-side checks and ends the skeptic loop.")
skeptic_finalizer = SkepticFinalizer(name="skeptic_finalizer", description="Splits findings into confirmed and dropped.")

skeptic_loop = LoopAgent(
    name="skeptic_loop",
    description="Skeptic challenges the findings until none needs evidence, for at most 3 rounds.",
    sub_agents=[skeptic_agent, skeptic_gate],
    max_iterations=MAX_ROUNDS,
)

skeptic_stage = SequentialAgent(
    name="skeptic_stage",
    description="Runs the skeptic loop, then separates confirmed findings from the dropped appendix.",
    sub_agents=[skeptic_loop, skeptic_finalizer],
    before_agent_callback=halt_if_failed,
)
