"""Phase 4: anomaly specialist (statistical and pattern tests on the ledger)."""
from google.adk.agents import LlmAgent

from auditpilot.tools import benford_test, find_duplicates, find_split_payments, find_weekend_round

from ._common import MODEL, NO_MATH_RULE, UNTRUSTED_TEXT_RULE, callbacks

INSTRUCTION = (
    "You are the Anomaly Specialist on an audit team. Intake's data profile is:\n{data_profile}\n\n"
    "Run EVERY tool you own, once each: benford_test, find_duplicates, find_split_payments, find_weekend_round.\n"
    "Then list your findings. For each finding give:\n"
    "- category: one of benford, duplicate_payment, split_payment, weekend_round\n"
    "- entry_ids: the complete list the tool returned in flagged_ids (never invent or drop ids)\n"
    "- evidence: the tool name and the exact numbers from its stats (counts, amounts, groups)\n"
    "Benford is a population screen: report its conformity and MAD; raise a finding only if it says nonconformity.\n"
    "If a tool returns nothing flagged, say so in one line. Do not pad the answer.\n\n"
    + NO_MATH_RULE + "\n" + UNTRUSTED_TEXT_RULE
)

anomaly_agent = LlmAgent(
    name="anomaly_agent",
    model=MODEL,
    description="Runs Benford, duplicate, split-payment and Sunday round-amount tests.",
    instruction=INSTRUCTION,
    tools=[benford_test, find_duplicates, find_split_payments, find_weekend_round],
    output_key="anomaly_findings",
    **callbacks(),
)
