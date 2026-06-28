"""Dual-auth (Phase E4B) credential-injection invariants for the Claude Code engine.

Claude Code accepts EITHER an Anthropic API key (ANTHROPIC_API_KEY) OR a Claude subscription
OAuth token (CLAUDE_CODE_OAUTH_TOKEN, from `claude setup-token`). The security-critical rules
this file locks down:

  1. EXACTLY ONE credential env var is injected per mode — never both (ANTHROPIC_API_KEY
     officially takes precedence, so a stray one would silently override a subscription token).
  2. ``--bare`` is NEVER used (bare mode ignores CLAUDE_CODE_OAUTH_TOKEN).
  3. ``CLAUDE_CODE_SIMPLE`` is controlled per mode: OFF (empty) for oauth_token (simple/bare
     mode ignores the OAuth token), ``=1`` for api_key. This was the real-world blocker.
  4. The other engine builders never inject Claude credential env vars.
  5. Auth-mode / engine constants stay in sync (only Claude Code has a subscription mode).

Run: ``python -m pytest tests/test_engine_auth_modes.py`` (PYTHONPATH=/app, inside the
backend image or any env where the orchestration package imports).
"""

import unittest


def _claude_cmd(auth_mode, secret="SECRET123"):
    from workspace.orchestration.engine_adapter import _build_claude_command
    cmd, _model = _build_claude_command(
        "harvis-claude-code", "/work", "do x", "", secret, user_id=1, auth_mode=auth_mode
    )
    return cmd


def _exec_env(cmd):
    """Collect the values passed via ``docker exec -e NAME=VALUE`` as a dict {NAME: VALUE}."""
    env = {}
    for i, tok in enumerate(cmd):
        if tok == "-e" and i + 1 < len(cmd) and "=" in cmd[i + 1]:
            k, v = cmd[i + 1].split("=", 1)
            env[k] = v
    return env


class TestClaudeCredentialInjection(unittest.TestCase):
    def test_api_key_mode(self):
        env = _exec_env(_claude_cmd("api_key", "KEYABC"))
        self.assertEqual(env.get("ANTHROPIC_API_KEY"), "KEYABC")
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)          # never both
        self.assertEqual(env.get("CLAUDE_CODE_SIMPLE"), "1")       # simple mode OK for api key

    def test_oauth_token_mode(self):
        env = _exec_env(_claude_cmd("oauth_token", "TOKXYZ"))
        self.assertEqual(env.get("CLAUDE_CODE_OAUTH_TOKEN"), "TOKXYZ")
        self.assertNotIn("ANTHROPIC_API_KEY", env)                # never both
        self.assertEqual(env.get("CLAUDE_CODE_SIMPLE"), "")        # MUST be off — else token ignored

    def test_never_both_credentials(self):
        for mode in ("api_key", "oauth_token"):
            env = _exec_env(_claude_cmd(mode))
            both = ("ANTHROPIC_API_KEY" in env) and ("CLAUDE_CODE_OAUTH_TOKEN" in env)
            self.assertFalse(both, f"both credential env vars set in {mode} mode")

    def test_never_bare_mode(self):
        for mode in ("api_key", "oauth_token"):
            self.assertNotIn("--bare", _claude_cmd(mode), f"--bare present in {mode} mode")

    def test_unknown_mode_defaults_to_api_key(self):
        # Defensive: an unexpected mode value must NOT leak an OAuth token under the API-key env.
        env = _exec_env(_claude_cmd("garbage"))
        self.assertIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)


class TestOtherBuildersIgnoreClaudeEnv(unittest.TestCase):
    def test_opencode_and_hermes_have_no_claude_creds(self):
        from workspace.orchestration.engine_adapter import (
            _build_opencode_command, _build_hermes_command,
        )
        for builder in (_build_opencode_command, _build_hermes_command):
            cmd, _ = builder("c", "/work", "do x", "", "SECRET", user_id=1, auth_mode="oauth_token")
            env = _exec_env(cmd)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)


class TestAuthModeConstants(unittest.TestCase):
    def test_modes_and_oauth_engines(self):
        from owui_compat.engine_auth import AUTH_MODES, OAUTH_ENGINES, AUTH_ENGINES
        self.assertEqual(AUTH_MODES, {"api_key", "oauth_token"})
        self.assertEqual(OAUTH_ENGINES, {"claude-code"})   # only Claude Code has subscription auth
        self.assertIn("codex", AUTH_ENGINES)
        self.assertNotIn("codex", OAUTH_ENGINES)           # codex is API-key-only


if __name__ == "__main__":
    unittest.main()
