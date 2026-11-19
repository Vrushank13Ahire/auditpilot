"""Phase 4: vendor specialist (bank-account overlaps and ghost vendors)."""
from google.adk.agents import LlmAgent

from auditpilot.tools import find_ghost_vendors, vendor_bank_overlap

from ._common import MODEL, NO_MATH_RULE, UNTRUSTED_TEXT_RULE, callbacks

INSTRUCTION = (
    "You are the Vendor Specialist on an audit team. Intake's data profile is:\n{data_profile}\n\n"
    "Run EVERY tool you own, once each: vendor_bank_overlap and find_ghost_vendors.\n"
    "Then list your findings. For each finding give:\n"
    "- category: shared_bank_account (vendor bank account equals an employee's or another vendor's) or ghost_vendor\n"
    "- entry_ids: the complete list the tool returned in flagged_ids (the ledger payments to those vendors)\n"
    "- evidence: the tool name, the vendor ids, and the exact numbers from stats (masked account endings only)\n"
    "If a tool flags nothing, say so in one line. Do not pad the answer.\n\n"
    + NO_MATH_RULE + "\n" + UNTRUSTED_TEXT_RULE
)

vendor_agent = LlmAgent(
    name="vendor_agent",
    model=MODEL,
    description="Finds vendors sharing bank accounts with employees or other vendors, and possible ghost vendors.",
    instruction=INSTRUCTION,
    tools=[vendor_bank_overlap, find_ghost_vendors],
    output_key="vendor_findings",
    **callbacks(),
)
