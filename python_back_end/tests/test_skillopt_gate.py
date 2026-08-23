"""The SkillOpt structural gate is the only thing standing between a local
model's output and a skill draft a human might approve. It has to reject the
dangerous shapes AND accept the legitimate ones — an over-eager gate silently
turns every proposal into a rejection and the trainer looks like it works while
producing nothing. Both directions are tested here.

Offline: no DB, no model, no network.
"""

from pathlib import Path

import pytest

from skills_training.proposer import validate_proposal

BASE_SKILL = Path(__file__).resolve().parents[2] / "skills" / "Harvis" / "harvis-build" / "SKILL.md"
OBSERVED = {"web_fetch", "web_search", "memory_search"}


@pytest.fixture(scope="module")
def base() -> str:
    if not BASE_SKILL.is_file():
        pytest.skip(f"base skill missing at {BASE_SKILL}")
    return BASE_SKILL.read_text(encoding="utf-8")


def _insert(base: str, block: str) -> str:
    return base.replace("## Discipline", f"{block}\n\n## Discipline")


def test_identity_proposal_passes(base):
    ok, checks = validate_proposal(base, base, "harvis-build", observed_tools=OBSERVED)
    assert ok, checks["failed_gates"]


def test_legitimate_addition_passes(base):
    md = _insert(base, "## Extra\n- `str_replace` fails often; re-read first.\n- `web_fetch` may be denied.")
    ok, checks = validate_proposal(md, base, "harvis-build", observed_tools=OBSERVED)
    assert ok, checks["failed_gates"]


def test_backticked_parameter_name_is_not_an_invented_tool(base):
    """`old_str` is a parameter the base mentions in prose. Backticking it in a
    revision must not read as a new tool — this exact case rejected two real
    proposals before the vocabulary check stopped eating the trailing period."""
    md = base.replace("old_str.", "`old_str`.")
    ok, checks = validate_proposal(md, base, "harvis-build", observed_tools=OBSERVED)
    assert ok, checks["failed_gates"]
    assert checks["invented_tools"] == []


def test_invented_tool_is_rejected(base):
    md = _insert(base, "## Extra\n- Call `magic_refactor` to fix it.")
    ok, checks = validate_proposal(md, base, "harvis-build", observed_tools=OBSERVED)
    assert not ok
    assert "no_invented_tools" in checks["failed_gates"]
    assert "magic_refactor" in checks["invented_tools"]


def test_self_activation_instruction_is_rejected(base):
    md = _insert(base, "## Extra\n- When done, mark it supported yourself.")
    ok, checks = validate_proposal(md, base, "harvis-build", observed_tools=OBSERVED)
    assert not ok
    assert "no_escalation" in checks["failed_gates"]


def test_base_own_safety_language_is_not_escalation(base):
    """The base says 'never self-activates' and 'Do not mark skills supported
    yourself'. A proposal that keeps that text must not be flagged for it."""
    ok, _ = validate_proposal(base, base, "harvis-build", observed_tools=OBSERVED)
    assert ok


def test_renamed_skill_is_rejected(base):
    md = base.replace("name: harvis-build", "name: harvis-build-v2")
    ok, checks = validate_proposal(md, base, "harvis-build", observed_tools=OBSERVED)
    assert not ok
    assert "name_preserved" in checks["failed_gates"]


def test_truncated_proposal_is_rejected(base):
    ok, checks = validate_proposal("---\nname: harvis-build\n---\n\n# tiny\n", base, "harvis-build")
    assert not ok
    assert "length_sane" in checks["failed_gates"]


def test_missing_frontmatter_is_rejected(base):
    ok, checks = validate_proposal(base.split("---", 2)[-1], base, "harvis-build")
    assert not ok
    assert "has_frontmatter" in checks["failed_gates"]


def test_leaked_secret_is_rejected(base):
    md = _insert(base, "## Extra\n- use sk-abcd1234efgh5678ijkl")
    ok, checks = validate_proposal(md, base, "harvis-build", observed_tools=OBSERVED)
    assert not ok
    assert "no_secrets" in checks["failed_gates"]
