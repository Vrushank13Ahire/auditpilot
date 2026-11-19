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


def test_policy_agent_tools_key_and_citation_rule():
    policy = _by_name()["policy_agent"]
    assert _tool_names(policy) == {"check_approval_limits", "retrieve_policy"}
    assert policy.output_key == "policy_findings"
    assert "clause" in policy.instruction.lower() and "do not raise it" in policy.instruction.lower()


def test_risk_agent_structured_output_and_code_scoring():
    agents = _by_name()
    assessor = agents["risk_assessor"]
    assert assessor.output_schema.__name__ == "RiskAssessment"
    assert not _tool_names(assessor)                       # ADK: an agent with output_schema cannot use tools
    assert agents["risk_scorer"].name == "risk_scorer"      # plain-code step computes score and amount
    names = [a.name for a in agents["risk_agent"].sub_agents]
    assert names == ["risk_assessor", "risk_scorer"]


def test_specialists_run_in_parallel_after_intake():
    pipeline = _by_name()["audit_pipeline"]
    names = [type(a).__name__ for a in pipeline.sub_agents]
    assert names[:2] == ["LlmAgent", "ParallelAgent"]
    assert {a.name for a in _by_name()["specialists"].sub_agents} >= {"anomaly_agent", "vendor_agent", "ratio_agent"}


def test_skeptic_is_a_bounded_loop_with_a_code_gate_and_finalizer():
    agents = _by_name()
    loop = agents["skeptic_loop"]
    assert type(loop).__name__ == "LoopAgent" and loop.max_iterations == 3
    assert [a.name for a in loop.sub_agents] == ["skeptic_agent", "skeptic_gate"]
    skeptic = agents["skeptic_agent"]
    assert _tool_names(skeptic) == {"verify_entry_ids", "record_verdicts"}
    assert [a.name for a in agents["skeptic_stage"].sub_agents] == ["skeptic_loop", "skeptic_finalizer"]


def test_report_agent_can_only_write_the_memo_and_root_owns_sign_off():
    agents = _by_name()
    assert _tool_names(agents["report_agent"]) == {"write_audit_memo"}
    assert "sign_off" not in _tool_names(agents["report_agent"])               # the report agent can never self-approve
    assert _tool_names(agent_module.root_agent) == {"sign_off"}
    assert "human" in agent_module.root_agent.instruction.lower()


def test_pipeline_order_is_the_one_in_the_pdf():
    names = [a.name for a in _by_name()["audit_pipeline"].sub_agents]
    assert names == ["intake_agent", "specialists", "risk_agent", "skeptic_stage", "report_agent"]
    assert len({a.name for a in _walk(agent_module.root_agent)}) == len(list(_walk(agent_module.root_agent)))


def test_every_llm_agent_has_untrusted_text_rule_masking_and_trail_callbacks():
    for a in _walk(agent_module.root_agent):
        if type(a).__name__ != "LlmAgent" or a.name == "audit_lead":
            continue
        assert "untrusted" in a.instruction.lower(), a.name
        assert getattr(a, "before_model_callback", None) and getattr(a, "after_tool_callback", None), a.name


def test_stages_after_intake_are_gated_on_intake_success():
    agents = _by_name()
    for name in ("specialists", "risk_agent", "skeptic_stage", "report_agent"):
        assert getattr(agents[name], "before_agent_callback", None) is not None, name
