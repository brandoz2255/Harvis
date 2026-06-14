"""Agent profile registry for P5 orchestration.

An agent's behavior = role + model + tools + approval policy + limits (NOT just a
chat session). Models here are **Harvis-real** (local Ollama / Kimi), not the
spec's gpt-5.5/claude-sonnet — the structure is what matters; a launch can always
override a profile's model via `model_name`.
"""

from __future__ import annotations

# role -> profile. `model_provider="local"` = Ollama via model_proxy._resolve_route.
AGENT_PROFILES: dict[str, dict] = {
    "orchestrator": {
        "display_name": "Orchestrator Agent",
        "model_provider": "local",
        "model_name": "qwen3:14b",
        "tools": ["plan", "spawn_agent", "summarize"],
        "approval_policy": "strict",
        "max_steps": 50,
        "max_runtime_seconds": 1800,
        "can_spawn_agents": True,
    },
    "backend": {
        "display_name": "Backend Agent",
        "model_provider": "local",
        "model_name": "qwen3:14b",
        "tools": ["read_file", "edit_file", "exec", "run_tests"],
        "approval_policy": "normal",
        "max_steps": 40,
        "max_runtime_seconds": 1200,
        "can_spawn_agents": False,
    },
    "frontend": {
        "display_name": "Frontend Agent",
        "model_provider": "local",
        "model_name": "qwen3:14b",
        "tools": ["read_file", "edit_file", "exec", "run_tests"],
        "approval_policy": "normal",
        "max_steps": 40,
        "max_runtime_seconds": 1200,
        "can_spawn_agents": False,
    },
    "testing": {
        "display_name": "Testing Agent",
        "model_provider": "local",
        "model_name": "gemma4:e2b",
        "tools": ["read_file", "edit_file", "exec", "run_tests"],
        "approval_policy": "relaxed",
        "max_steps": 30,
        "max_runtime_seconds": 900,
        "can_spawn_agents": False,
    },
    "security": {
        "display_name": "Security Review Agent",
        "model_provider": "local",
        "model_name": "qwen3:14b",
        "tools": ["read_file", "exec"],
        "approval_policy": "strict",
        "max_steps": 30,
        "max_runtime_seconds": 900,
        "can_spawn_agents": False,
    },
    "docs": {
        "display_name": "Documentation Agent",
        "model_provider": "local",
        "model_name": "gemma4:e2b",
        "tools": ["read_file", "edit_file"],
        "approval_policy": "relaxed",
        "max_steps": 25,
        "max_runtime_seconds": 600,
        "can_spawn_agents": False,
    },
}

# Fallback for an unknown role — behaves like a generic backend coding agent.
_DEFAULT_PROFILE = AGENT_PROFILES["backend"]


def get_profile(role: str) -> dict:
    """Return a copy of the profile for `role` (falls back to backend)."""
    return dict(AGENT_PROFILES.get(role or "", _DEFAULT_PROFILE))
