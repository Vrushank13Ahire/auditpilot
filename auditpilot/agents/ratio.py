"""Phase 4: ratio specialist (financial-statement ratios by month)."""
from google.adk.agents import LlmAgent

from auditpilot.tools import ratio_table

from ._common import MODEL, NO_MATH_RULE, UNTRUSTED_TEXT_RULE, callbacks

INSTRUCTION = (
    "You are the Ratio Specialist on an audit team. Intake's data profile is:\n{data_profile}\n\n"
    "Run your one tool, ratio_table, once.\n"
    "Then summarise: the average, minimum and maximum of each ratio as returned in stats.summary, and every month "
    "the tool flagged (entry id = the 'FIN:YYYY-MM' value in flagged_ids) with the reason from stats.flags.\n"
    "Raise a finding (category: ratio_anomaly) only for months the tool flagged. If none are flagged, say so in "
    "one line.\n\n"
    + NO_MATH_RULE + "\n" + UNTRUSTED_TEXT_RULE
)

ratio_agent = LlmAgent(
    name="ratio_agent",
    model=MODEL,
    description="Computes monthly financial ratios and reports months that breach a screen.",
    instruction=INSTRUCTION,
    tools=[ratio_table],
    output_key="ratio_findings",
    **callbacks(),
)
