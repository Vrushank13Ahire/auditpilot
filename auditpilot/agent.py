"""root_agent for `adk web`. audit_lead hands an audit request to the pipeline, whose first stage is intake."""
from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from auditpilot.agents._common import MODEL
from auditpilot.agents.anomaly import anomaly_agent
from auditpilot.agents.intake import intake_agent
from auditpilot.agents.policy import policy_agent
from auditpilot.agents.ratio import ratio_agent
from auditpilot.agents.vendor import vendor_agent
from auditpilot.gates import halt_if_failed

specialists = ParallelAgent(
    name="specialists",
    description="Runs the specialist agents at the same time; each writes its own findings key to state.",
    sub_agents=[anomaly_agent, vendor_agent, ratio_agent, policy_agent],
    before_agent_callback=halt_if_failed,
)

audit_pipeline = SequentialAgent(
    name="audit_pipeline",
    description="Runs a full audit: intake first, then the later stages in a fixed order.",
    sub_agents=[intake_agent, specialists],
)

root_agent = LlmAgent(
    name="audit_lead",
    model=MODEL,
    description="Lead auditor. Starts the audit pipeline when asked.",
    instruction=(
        "You are the lead auditor of AuditPilot. When the user asks you to start, run or begin an audit, "
        "transfer to audit_pipeline immediately; do not analyse anything yourself. "
        "For any other message, answer briefly and say you can run an audit when they type 'start audit'."
    ),
    sub_agents=[audit_pipeline],
)
