"""Phase 0 placeholder: a hello-world root agent (replaced in Phase 3)."""
from google.adk.agents import LlmAgent

root_agent = LlmAgent(
    name="audit_lead",
    model="gemini-flash-latest",
    description="Lead auditor (placeholder).",
    instruction="You are the AuditPilot lead. Greet the user and say the setup works.",
)
