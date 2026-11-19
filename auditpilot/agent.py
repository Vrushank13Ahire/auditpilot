"""root_agent for `adk web`. audit_lead hands an audit request to the pipeline, whose first stage is intake."""
from google.adk.agents import LlmAgent, SequentialAgent

from auditpilot.agents._common import MODEL
from auditpilot.agents.intake import intake_agent

audit_pipeline = SequentialAgent(
    name="audit_pipeline",
    description="Runs a full audit: intake first, then the later stages in a fixed order.",
    sub_agents=[intake_agent],
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
