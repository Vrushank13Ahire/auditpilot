"""Phase 5: policy specialist. Deterministic limit checks plus retrieval, and every finding cites a clause."""
from google.adk.agents import LlmAgent

from auditpilot.tools import check_approval_limits, retrieve_policy

from ._common import MODEL, NO_MATH_RULE, UNTRUSTED_TEXT_RULE, callbacks

INSTRUCTION = (
    "You are the Policy Specialist on an audit team. Intake's data profile is:\n{data_profile}\n\n"
    "Step 1: call check_approval_limits once. It tests segregation of duties, approval limits and split payments.\n"
    "Step 2: for each group that has entries (stats.self_approved_ids, over_limit_ids, under_authorised_ids, "
    "split_suspect_ids, missing_or_unknown_approver_ids), call retrieve_policy once with a short plain-English "
    "description of the breach, for example 'approving your own payment' or 'splitting a payment to stay under the "
    "approval limit'. Use the top result.\n"
    "Step 3: list findings. For each give:\n"
    "- category: self_approved, approval_limit_breach, split_payment or missing_approver\n"
    "- entry_ids: the complete list from the matching stats list (never invent or drop ids)\n"
    "- policy_clause: the clause_id returned by retrieve_policy\n"
    "- policy_quote: the quote returned by retrieve_policy, copied exactly\n"
    "- evidence: the tool name and the exact numbers from stats\n"
    "RULE: every finding must include the clause id and the quote returned by retrieve_policy. If no retrieved "
    "clause supports a finding, do not raise it. If a group is empty, say so in one line.\n\n"
    + NO_MATH_RULE + "\n" + UNTRUSTED_TEXT_RULE
)

policy_agent = LlmAgent(
    name="policy_agent",
    model=MODEL,
    description="Checks approvals against policy limits and cites the policy clause behind every finding.",
    instruction=INSTRUCTION,
    tools=[check_approval_limits, retrieve_policy],
    output_key="policy_findings",
    **callbacks(),
)
