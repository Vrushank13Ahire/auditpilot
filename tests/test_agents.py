"""Agent wiring tests: names, output keys and least-privilege tool lists.

Needs google-adk. Skipped where it is not installed (the deterministic layer is tested elsewhere).
"""
import pytest

pytest.importorskip("google.adk")

from auditpilot import agent as agent_module  # noqa: E402


def _walk(node):
    yield node
    for sub in getattr(node, "sub_agents", []) or []:
        yield from _walk(sub)


def _by_name():
    return {n.name: n for n in _walk(agent_module.root_agent)}


def _tool_names(agent):
    return {getattr(t, "__name__", getattr(t, "name", str(t))) for t in (getattr(agent, "tools", None) or [])}


def test_root_is_audit_lead_and_pipeline_starts_with_intake():
    assert agent_module.root_agent.name == "audit_lead"
    pipeline = _by_name()["audit_pipeline"]
    assert pipeline.sub_agents[0].name == "intake_agent"


def test_intake_has_exactly_two_tools_and_output_key():
    intake = _by_name()["intake_agent"]
    assert _tool_names(intake) == {"load_ledger", "check_trial_balance"}
    assert intake.output_key == "data_profile"
    assert "never estimate" in intake.instruction.lower() or "never calculate" in intake.instruction.lower()


def test_specialists_least_privilege_and_keys():
    agents = _by_name()
    expected = {
        "anomaly_agent": ({"benford_test", "find_duplicates", "find_split_payments", "find_weekend_round"},
                          "anomaly_findings"),
        "vendor_agent": ({"vendor_bank_overlap", "find_ghost_vendors"}, "vendor_findings"),
        "ratio_agent": ({"ratio_table"}, "ratio_findings"),
    }
    for name, (tools, key) in expected.items():
        assert _tool_names(agents[name]) == tools, name
        assert agents[name].output_key == key
        assert "untrusted" in agents[name].instruction.lower()
    keys = [a.output_key for a in _walk(agent_module.root_agent) if getattr(a, "output_key", None)]
    assert len(keys) == len(set(keys)), "output_key clash"


def test_specialists_run_in_parallel_after_intake():
    pipeline = _by_name()["audit_pipeline"]
    names = [type(a).__name__ for a in pipeline.sub_agents]
    assert names[:2] == ["LlmAgent", "ParallelAgent"]
    assert {a.name for a in _by_name()["specialists"].sub_agents} >= {"anomaly_agent", "vendor_agent", "ratio_agent"}
