"""The Discord bot speaks as one Harvis account; the admin's People limits apply to it."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "integrations" / "discord_workspace_bot.py").read_text()


def test_bot_checks_the_account_before_any_model_runs():
    gate = SRC.index("_admitted = await admit_turn(pool, cfg.default_user_id, None)")
    assert gate < SRC.index("reply = await _fast_llm_reply(")
    assert gate < SRC.index("data = await launch_workspace_internal(")
    assert gate < SRC.index("esc_data = await launch_workspace_internal(")


def test_local_models_are_kept_on_the_allowed_list():
    assert "_fast_llm_reply(content, _on_list(fast_model)" in SRC
    assert "effective_model_name = _on_list(effective_model_name)" in SRC
    assert "_on_list(_ESCALATION_PAIRS[effective_model_name]) == _ESCALATION_PAIRS[effective_model_name]" in SRC
