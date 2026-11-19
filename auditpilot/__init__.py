"""AuditPilot: a multi-agent audit and risk copilot (Google ADK + Gemini).

`adk web` imports this package and looks for `auditpilot.agent.root_agent`.
The deterministic layer (auditpilot.tools, scoring, memo, offline) has no ADK dependency, so it stays
importable and testable even where google-adk is not installed.
"""
try:
    from . import agent  # noqa: F401
except ModuleNotFoundError as exc:  # only swallow a missing google-adk / google-genai
    if not (exc.name or "").startswith("google"):
        raise
