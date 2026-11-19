"""Rules from the PDF that are properties of the repo itself: hidden answer key, no secrets, pure tools."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "auditpilot"


def _py(folder):
    return [p for p in folder.rglob("*.py") if "__pycache__" not in p.parts]


def test_agents_and_tools_never_touch_the_answer_key():
    offenders = [str(p.relative_to(ROOT)) for p in _py(PKG) if "ground_truth" in p.read_text()]
    assert offenders == []


def test_tools_are_pure_python_no_llm_no_printing_no_randomness():
    for p in _py(PKG / "tools"):
        src = p.read_text()
        assert not re.search(r"^\s*print\(", src, re.M), f"{p.name} prints"
        assert not re.search(r"import random|numpy\.random|np\.random|google\.(adk|genai)|from google", src), p.name


def test_env_and_secrets_are_not_tracked_or_printed():
    assert ".env" in (ROOT / ".gitignore").read_text().split()
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [t for t in tracked if t.endswith("/.env") or t == ".env" or t.endswith(".venv")]
    for p in _py(ROOT):
        src = p.read_text()
        assert not re.search(r"AIza[0-9A-Za-z_\-]{35}", src), p                    # no real-key-shaped literal in code
        assert not re.search(r"print\(.*(GOOGLE_API_KEY|os\.environ\b)", src), p


def test_required_repo_layout_exists():
    for rel in (".agent/rules/auditpilot.md", ".gitignore", "README.md", "requirements.txt", "data/ground_truth.csv",
                "scripts/make_data.py", "auditpilot/agent.py", "auditpilot/schemas.py", "auditpilot/callbacks.py",
                "auditpilot/agents", "auditpilot/tools", "tests", "evals/run_eval.py", "docs"):
        assert (ROOT / rel).exists(), rel
