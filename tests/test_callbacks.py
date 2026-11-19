"""Phase 9: audit trail (append-only, hashes, no secrets) and bank-number masking. Pure functions, no ADK needed."""
import json
from types import SimpleNamespace as NS

from auditpilot import callbacks as cb


def _ctx(agent="anomaly_agent", sid="s1"):
    return NS(agent_name=agent, session=NS(id=sid))


def test_mask_text_masks_bank_numbers_but_not_amounts_or_ids():
    assert cb.mask_text("acct 734598462855 ok") == "acct ********2855 ok"
    assert cb.mask_text("total 192510650.32 and 19,25,10,650 and L00123 and INV-78246") == \
        "total 192510650.32 and 19,25,10,650 and L00123 and INV-78246"
    assert cb.mask_text("12345678901234567890") == "12345678901234567890"      # 20 digits: not a bank number shape


def test_mask_obj_reaches_nested_values():
    out = cb.mask_obj({"a": ["x 734598462855"], "b": {"c": "760217025658"}, "n": 5})
    assert out == {"a": ["x ********2855"], "b": {"c": "********5658"}, "n": 5}


def test_secrets_are_scrubbed_from_what_is_logged():
    out = cb.scrub_secrets({"k": "AIzaSyA1234567890abcdefghijklmnop", "note": "api_key=abc123secret ok", "n": 1})
    text = json.dumps(out)
    assert "AIza" not in text and "abc123secret" not in text and out["n"] == 1


def test_result_hash_is_stable_and_order_independent():
    assert cb.result_hash({"a": 1, "b": 2}) == cb.result_hash({"b": 2, "a": 1}) != cb.result_hash({"a": 1, "b": 3})
    assert len(cb.result_hash({})) == 16


def test_trail_is_append_only_jsonl_with_the_required_fields(tmp_path):
    p = tmp_path / "run" / "audit_trail.jsonl"
    cb.append_trail(cb.make_record("a", "find_duplicates", {}, {"x": 1}), p)
    first = p.read_text()
    cb.append_trail(cb.make_record("b", "ratio_table", {"k": 1}, {"y": 2}), p)
    lines = p.read_text().splitlines()
    assert p.read_text().startswith(first) and len(lines) == 2                    # earlier lines never rewritten
    rec = json.loads(lines[0])
    assert set(rec) == {"timestamp", "kind", "agent", "tool", "args", "result_hash"}
    assert rec["agent"] == "a" and rec["tool"] == "find_duplicates"


def test_trail_path_is_one_file_per_session_and_overridable(monkeypatch, tmp_path):
    monkeypatch.delenv("AUDITPILOT_TRAIL_PATH", raising=False)
    monkeypatch.setenv("AUDITPILOT_RUNS_DIR", str(tmp_path))
    assert cb.trail_path("sess/../1") == tmp_path / "sess_.._1" / "audit_trail.jsonl"
    assert cb.trail_path("a") != cb.trail_path("b")
    monkeypatch.setenv("AUDITPILOT_TRAIL_PATH", str(tmp_path / "x.jsonl"))
    assert cb.trail_path("a") == tmp_path / "x.jsonl"


def test_after_tool_logs_a_line_masks_args_and_chains_the_next_callback(monkeypatch, tmp_path):
    trail = tmp_path / "t.jsonl"
    monkeypatch.setenv("AUDITPILOT_TRAIL_PATH", str(trail))
    seen = {}
    callbacks = cb.agent_callbacks(after_tool=lambda tool, args, tool_context, tool_response: seen.update(r=tool_response))
    assert set(callbacks) == {"before_model_callback", "after_model_callback", "after_tool_callback"}
    tool = NS(name="vendor_bank_overlap")
    callbacks["after_tool_callback"](tool=tool, args={"acct": "734598462855", "key": "AIzaSyA1234567890abcdefghijklmnop"},
                                     tool_context=_ctx("vendor_agent"), tool_response={"flagged_ids": ["L1"]})
    rec = json.loads(trail.read_text())
    assert rec["tool"] == "vendor_bank_overlap" and rec["agent"] == "vendor_agent" and rec["kind"] == "tool"
    assert "734598462855" not in trail.read_text() and "AIza" not in trail.read_text()
    assert "L1" not in trail.read_text(), "results are hashed, never stored"
    assert seen["r"] == {"flagged_ids": ["L1"]}


def test_before_model_masks_text_and_function_responses_in_place():
    part_text = NS(text="pay 734598462855 now", function_response=None)
    part_fn = NS(text=None, function_response=NS(response={"bank": "760217025658"}))
    req = NS(contents=[NS(parts=[part_text, part_fn])], config=NS(system_instruction="acct 734598462855"))
    assert cb.before_model(_ctx(), req) is None                                  # never blocks the call
    assert part_text.text == "pay ********2855 now"
    assert part_fn.function_response.response == {"bank": "********5658"}
    assert req.config.system_instruction == "acct ********2855"


def test_after_model_logs_a_hash_not_the_reply(monkeypatch, tmp_path):
    trail = tmp_path / "t.jsonl"
    monkeypatch.setenv("AUDITPILOT_TRAIL_PATH", str(trail))
    resp = NS(content=NS(parts=[NS(text="secret reply text")]))
    assert cb.after_model(_ctx("risk_assessor"), resp) is None
    rec = json.loads(trail.read_text())
    assert rec["kind"] == "model" and rec["agent"] == "risk_assessor" and "secret reply" not in trail.read_text()
