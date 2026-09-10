"""The ladder with the agent rung and the hard tier.

Two properties matter and neither is obvious from reading the table:
  1. Under the agent rung, ordinary work runs — including the shell commands
     the in-place ladder calls "high", because an agent works in a throwaway
     clone where they are not destructive.
  2. A hard limit gates under EVERY rung, full-auto included. No session
     setting may pre-approve signing in, paying, sending or deleting.
"""

import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# risk.py holds a pure decision table but lives in a package whose __init__
# imports the whole FastAPI router. Import it normally when the web stack is
# installed (the container), and load the file directly when it is not (a bare
# host checkout) — the module itself is stdlib-only either way.
try:
    from workspace.orchestration.risk import gate_decision, gate_decision_ex
except ImportError:
    _candidates = [
        os.path.join(_ROOT, "workspace", "orchestration", "risk.py"),
        "/app/workspace/orchestration/risk.py",
    ]
    _path = next(p for p in _candidates if os.path.exists(p))
    _spec = importlib.util.spec_from_file_location("harvis_risk_under_test", _path)
    _risk = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_risk)
    gate_decision = _risk.gate_decision
    gate_decision_ex = _risk.gate_decision_ex


# ─── the agent rung ──────────────────────────────────────────────────────────


def test_agent_rung_allows_ordinary_work():
    for tool, args in (
        ("read_file", {"path": "notes.md"}),
        ("edit_file", {"path": "src/app.py"}),
        ("exec", {"command": "npm test"}),
    ):
        assert gate_decision(tool, args, "agent")[0] == "allow", tool


def test_agent_rung_allows_the_shell_shapes_that_would_stall_it():
    # A redirect, an mv and an rm -rf inside the clone are ordinary work. Under
    # 'ask' these gate; under 'agent' they must not, or the teammate stalls on
    # `echo x > file` several times a minute.
    for cmd in ("echo hi > out.txt", "mv a.txt b.txt", "rm -rf node_modules"):
        assert gate_decision("exec", {"command": cmd}, "agent")[0] == "allow", cmd
        assert gate_decision("exec", {"command": cmd}, "ask")[0] == "gate", cmd


# ─── the hard tier ───────────────────────────────────────────────────────────


def test_hard_limit_gates_under_every_rung():
    for mode in ("agent", "ask", "auto-accept", "full-auto"):
        decision, tier, reason = gate_decision_ex("click", {"ref": "r1"}, mode, hard_limit="pay")
        assert decision == "gate", mode
        assert tier == "hard"
        assert "money" in reason


def test_hard_limit_blocks_under_plan():
    decision, tier, _ = gate_decision_ex("click", {}, "plan", hard_limit="send")
    assert decision == "block"
    assert tier == "hard"


def test_hard_limit_reason_names_the_consequence():
    # The approval prompt shows this string; "hard limit: send" would tell the
    # user nothing they can act on.
    for limit, word in (("sign_in", "signs in"), ("pay", "money"),
                        ("send", "sends"), ("delete", "deletes")):
        _, _, reason = gate_decision_ex("click", {}, "agent", hard_limit=limit)
        assert word in reason, limit


def test_no_hard_limit_means_the_ordinary_ladder_still_applies():
    assert gate_decision_ex("exec", {"command": "sudo rm -rf /"}, "ask")[0] == "gate"
    assert gate_decision_ex("read_file", {}, "ask")[0] == "allow"


def test_existing_rungs_are_unchanged():
    # Regression guard: the in-place VibeCode ladder must behave exactly as before.
    assert gate_decision("read_file", {}, "plan") == ("allow", "low")
    assert gate_decision("edit_file", {"path": "a.py"}, "plan") == ("block", "med")
    assert gate_decision("edit_file", {"path": "a.py"}, "ask") == ("gate", "med")
    assert gate_decision("edit_file", {"path": "a.py"}, "auto-accept") == ("allow", "med")
    assert gate_decision("exec", {"command": "git push"}, "auto-accept") == ("gate", "high")
    assert gate_decision("exec", {"command": "git push"}, "full-auto") == ("allow", "high")
