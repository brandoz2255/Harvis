"""Which model actually authors the part, and what the run is told to use (HE-10).

The tranche's headline claim is "the jar through both Claude and Kimi". Until this
gate it was not true for Kimi, and it failed in the one way a user cannot see: a
`kimi-code/*` selection resolved to no lane at all, and "no lane" is the same answer
a local Ollama tag gives, so the request was quietly finished by whatever Ollama had
and reported as done. Nothing errored. Nothing in the timeline said a different model
had built the part.

So these tests are about provenance rather than geometry. A selection either reaches
the provider it names or is refused by name; the lane carries the selection verbatim,
because the activity row is written from it; and the sidecar launches with the
environment that provider actually needs.
"""
from __future__ import annotations

import pytest

from owui_compat import cad_agent
from owui_compat.engine_auth import KIMI_CODE_BASE_URL, KIMI_CODE_DEFAULT_MODEL

KIMI = "kimi-code/kimi-for-coding"
_POOL = object()          # never touched: every lookup on this path is monkeypatched
_USER = 7


@pytest.fixture
def verified(monkeypatch):
    """Answer `get_verified_auth_mode` for one engine and no other.

    Patched on the module rather than on `cad_agent`, because `resolve_lane` imports
    the function at call time — which is also what makes the patch land.
    """
    from owui_compat import engine_auth

    def _install(engine: str | None, mode: str = "api_key"):
        async def _mode(pool, user_id, eng):
            return mode if eng == engine else None
        monkeypatch.setattr(engine_auth, "get_verified_auth_mode", _mode)

        # The Anthropic branch asks for a global API key before it considers a
        # subscription. Answering "none configured" is what puts the subscription
        # path under test rather than the deployment's own config.
        from workspace import model_proxy

        async def _no_global_key():
            return {}
        monkeypatch.setattr(model_proxy, "_get_openclaw_config", _no_global_key)
    return _install


# ---------------------------------------------------------------------------
# resolve_lane — the defect itself
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_kimi_model_resolves_to_the_kimi_sidecar(verified):
    verified("kimi-code")
    lane = await cad_agent.resolve_lane(KIMI, _POOL, _USER)
    assert lane is not None, "kimi-code resolved to no lane — the HE-10 defect"
    # `claude_code` is the *kind* of lane, not the vendor: Kimi Code is the real
    # Claude Code CLI with its base URL repointed, which is why it belongs here and
    # not in the OpenAI-compatible kind.
    assert lane.kind == "claude_code"
    assert lane.engine == "kimi-code"
    assert lane.provider == "kimi-code"


@pytest.mark.asyncio
async def test_the_lane_carries_the_selected_model_verbatim(verified):
    """The activity row is written from `lane.model`, so a rewrite here is a lie there."""
    verified("kimi-code")
    lane = await cad_agent.resolve_lane(KIMI, _POOL, _USER)
    assert lane.model == KIMI


@pytest.mark.asyncio
async def test_kimi_without_a_membership_key_resolves_to_nothing(verified):
    verified("claude-code")     # a Claude credential is not a Kimi credential
    assert await cad_agent.resolve_lane(KIMI, _POOL, _USER) is None


@pytest.mark.asyncio
async def test_a_kimi_selection_that_cannot_run_is_refused_by_name(verified):
    """The other half of the fix: refusing without a reason IS the silent fallback.

    `resolve_lane` returning None is what sends the caller to the local generator, so
    a cloud model that cannot run has to be answered here or it is answered by qwen.
    """
    verified(None)
    assert await cad_agent.resolve_lane(KIMI, _POOL, _USER) is None
    reason = await cad_agent.unavailable_reason(KIMI, _POOL, _USER)
    assert reason and KIMI in reason
    assert "Kimi Code" in reason


@pytest.mark.asyncio
async def test_a_local_tag_is_still_a_local_tag(verified):
    """The one fallback that is legitimate, and it must stay quiet."""
    verified(None)
    assert await cad_agent.resolve_lane("qwen3:14b", _POOL, _USER) is None
    assert await cad_agent.unavailable_reason("qwen3:14b", _POOL, _USER) is None


@pytest.mark.asyncio
async def test_a_claude_subscription_still_resolves_to_its_own_engine(verified):
    """Regression guard: the branch above must not have swallowed the Claude path."""
    verified("claude-code", mode="oauth_token")
    lane = await cad_agent.resolve_lane("anthropic/claude-opus-5", _POOL, _USER)
    assert lane is not None and lane.kind == "claude_code"
    assert lane.engine == "claude-code" and lane.provider == "anthropic"


def test_the_shared_router_still_declines_kimi_by_name():
    """One model, one route. `provider_route` owns the OpenAI-compatible providers
    and says so about Kimi Code; the lane above is the *other* answer, not a second
    copy of the same one. If this ever starts returning a route, two code paths will
    both believe they own the model."""
    from workspace.orchestration.provider_route import has_own_tools
    assert has_own_tools(KIMI) is True


# ---------------------------------------------------------------------------
# What the sidecar is actually launched with
# ---------------------------------------------------------------------------

def _env(flags: list[str]) -> dict[str, str]:
    return dict(f.split("=", 1) for f in flags if f != "-e")


def test_a_kimi_run_pins_every_model_slot():
    """Not decoration. The CLI resolves its own aliases — a Sonnet-tier model for the
    main loop, Haiku-tier for cheap side calls, another for subagents — and any slot
    left unpinned asks Kimi for an Anthropic model id it does not serve. The run then
    dies partway through, long after the first token made it look healthy."""
    cred, model_id = cad_agent.sidecar_launch_env(
        "kimi-code", "secret-value", "api_key", KIMI)
    env = _env(cred)
    assert env["ANTHROPIC_BASE_URL"] == KIMI_CODE_BASE_URL
    for slot in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                 "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                 "CLAUDE_CODE_SUBAGENT_MODEL"):
        assert env[slot] == model_id
    assert model_id == "kimi-for-coding"      # the catalog prefix is stripped
    assert env["CLAUDE_CODE_SIMPLE"] == "1"   # Kimi is API-key only
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_a_model_kimi_does_not_serve_falls_back_to_its_default():
    _, model_id = cad_agent.sidecar_launch_env(
        "kimi-code", "secret-value", "api_key", "kimi-code/claude-opus-5")
    assert model_id == KIMI_CODE_DEFAULT_MODEL


def test_a_subscription_run_clears_simple_mode():
    """Inverted from Kimi's, and load-bearing: simple mode reads ANTHROPIC_API_KEY
    only and ignores the OAuth token, so leaving it set authenticates against
    nothing."""
    cred, _ = cad_agent.sidecar_launch_env(
        "claude-code", "oauth-secret", "oauth_token", "anthropic/claude-opus-5")
    env = _env(cred)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-secret"
    assert env["CLAUDE_CODE_SIMPLE"] == ""
    assert "ANTHROPIC_API_KEY" not in env


def test_an_api_key_run_keeps_simple_mode():
    cred, _ = cad_agent.sidecar_launch_env(
        "claude-code", "sk-test", "api_key", "anthropic/claude-opus-5")
    env = _env(cred)
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert env["CLAUDE_CODE_SIMPLE"] == "1"


def test_the_thinking_budget_goes_to_anthropic_and_not_to_kimi():
    """Extended thinking is an Anthropic feature. Kimi Code serves an
    Anthropic-COMPATIBLE API, which is not the same promise."""
    claude, _ = cad_agent.sidecar_launch_env(
        "claude-code", "sk-test", "api_key", "anthropic/claude-opus-5",
        think_tokens=4000)
    assert _env(claude)["MAX_THINKING_TOKENS"] == "4000"

    kimi, _ = cad_agent.sidecar_launch_env(
        "kimi-code", "sk-test", "api_key", KIMI, think_tokens=4000)
    assert "MAX_THINKING_TOKENS" not in _env(kimi)


def test_no_credential_is_ever_returned_as_a_bare_value():
    """The env list is built for `docker exec`, so the secret is only ever half of an
    `-e NAME=value` pair. A bare element would end up as an argv word."""
    cred, _ = cad_agent.sidecar_launch_env(
        "kimi-code", "secret-value", "api_key", KIMI)
    assert "secret-value" not in cred
