"""LLM task-delegation planner for P5 orchestration.

Decomposes a coding task into N **task-named** sub-agents (3–10, scaling to
complexity) — replacing the rule-based frontend/backend/testing keyword split
with delegated, task-specific agent names ("auth-schema", "login-endpoint",
"rate-limiter", "unit-tests", …). Each agent gets its own model from a small
heterogeneous pool (the 8GB-GPU constraint — concurrency is still capped by the
orchestrator's semaphore, so 10 planned agents run a few at a time).

Falls back to the rule-based keyword split (`simple_task_split`) on ANY LLM
failure so orchestration always produces a usable plan.
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx as _httpx

from .profiles import get_profile

logger = logging.getLogger(__name__)

_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

# Small, heterogeneous, proven tool-callers — one model per lane so parallel
# sub-agents don't all load the same heavy model on an 8GB GPU. Round-robined
# across the planned agents (unless the run forces a uniform model).
_POOL = [
    m.strip()
    for m in os.getenv(
        "HARVIS_ORCH_MODEL_POOL", "llama3.1:8b,gemma4:e4b,gemma4:e2b"
    ).split(",")
    if m.strip()
] or ["gemma4:e2b"]

# Models tried (in order) for the planning LLM call itself. Local, cheap, JSON-able.
_PLANNER_MODELS = [
    m.strip()
    for m in os.getenv(
        "HARVIS_ORCH_PLANNER_MODEL", "llama3.1:8b,granite4.1:8b,gemma4:e4b"
    ).split(",")
    if m.strip()
]

# Scale bounds for the fan-out. The user asked for 3–10 task-delegated agents.
_MIN_AGENTS = max(1, int(os.getenv("HARVIS_ORCH_MIN_AGENTS", "3")))
_MAX_AGENTS = max(_MIN_AGENTS, int(os.getenv("HARVIS_ORCH_MAX_AGENTS", "10")))


async def _installed(candidates: list[str]) -> list[str]:
    """`candidates` filtered to the tags the provider actually serves, order preserved.

    Both lists above are *defaults naming specific tags* — the fresh-clone problem in one
    line. `llama3.1:8b` is pulled on the dev box, so a 3-agent orchestrated run worked here
    and spawned three sub-agents against 404s on any machine that never pulled it; the
    planner loop below has the same shape, where an uninstalled pin just burns a round-trip
    per model and then reports "LLM unavailable". Filtering costs one /api/tags call per
    plan — a model-selection path, not a per-token one.

    An EMPTY tag list means the provider was unreachable, not that every candidate is bad,
    so the candidates are returned untouched rather than all discarded on a transient
    outage. That is the same rule the shared resolver applies.
    """
    if not candidates:
        return []
    try:
        from plugins.models.resolver import list_ollama_models
        available = await list_ollama_models(ollama_url=_OLLAMA_URL)
    except Exception:
        logger.exception("orchestrator planner: model list failed")
        return list(candidates)
    if not available:
        return list(candidates)
    keep = [m for m in candidates if m in available]
    dropped = [m for m in candidates if m not in available]
    if dropped:
        logger.info(
            "orchestrator planner: dropping %d uninstalled model(s) from the pool: %s",
            len(dropped), ", ".join(dropped),
        )
    return keep


async def _effective_pool(model_pool: list[str] | None) -> list[str]:
    """The pool to round-robin: caller's pool → env/default pool → whatever is installed.

    Returns [] only when the provider has nothing at all, which the dispatch reports as
    "no model available" rather than naming a tag nobody has.
    """
    pool = await _installed([m for m in (model_pool or []) if m] or _POOL)
    if pool:
        return pool
    try:
        from plugins.models.resolver import resolve_default_local_model
        picked = await resolve_default_local_model(ollama_url=_OLLAMA_URL)
    except Exception:
        logger.exception("orchestrator planner: pool resolution failed")
        picked = None
    return [picked] if picked else []


def _label_from_name(name: str) -> str:
    """'login-endpoint' → 'Login endpoint' for the agent table's name column."""
    s = re.sub(r"[-_]+", " ", (name or "").strip()).strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:1].upper() + s[1:]) if s else "Agent"


def _safe_role(name: str) -> str:
    """A filesystem-safe handle for the agent's workspace dir / role column."""
    r = re.sub(r"[^a-z0-9_-]+", "-", (name or "").lower()).strip("-")
    return r[:40] or "agent"


def _assign_models(
    n: int, model_name: str, uniform_model: bool, model_pool: list[str] | None = None
) -> list[str]:
    # uniform → ALL agents on ONE model: the caller's model_name (the session's model),
    # falling back to the first pool model only if none was supplied. Otherwise round-robin
    # a pool: the user's CUSTOM pool (Customize, opt-in) when supplied, else the env default.
    #
    # `model_pool=[]` and `model_pool=None` mean DIFFERENT things and must stay distinct:
    # None is "caller expressed no preference" → use the env default; an empty list is
    # _effective_pool saying "the provider serves nothing", and falling back to _POOL there
    # would put the uninstalled default tags straight back into the plan. Empty pool → empty
    # model names, which the dispatch reports as "no model available".
    pool = _POOL if model_pool is None else [m for m in model_pool if m]
    if uniform_model:
        return [model_name or (pool[0] if pool else "")] * n
    if not pool:
        return [""] * n
    return [pool[i % len(pool)] for i in range(n)]


def _build_plan(
    agents: list[dict],
    model_name: str,
    uniform_model: bool,
    model_pool: list[str] | None = None,
    subagents: list[dict] | None = None,
) -> list[dict]:
    """Turn [{name, task, assignee?}, …] into the spawn-ready plan dicts
    run_orchestrated wants: {role, task, profile, model, label}. A step whose
    ``assignee`` (or name) matches one of the user's custom sub-agents gets THAT
    definition's resolved profile (model / system prompt / tool withhold /
    skills / connectors — see subagent_defs.resolve_profile); everything else —
    unknown assignee, 'general', no roster — keeps the generic coding profile
    (the default 'backend' profile) re-labelled with its delegated name + model."""
    by_name = {d["name"]: d for d in (subagents or []) if d.get("name")}
    models = _assign_models(len(agents), model_name, uniform_model, model_pool)
    plan: list[dict] = []
    for i, a in enumerate(agents):
        name = (a.get("name") or a.get("role") or f"agent-{i + 1}").strip()
        task = (a.get("task") or "").strip()
        # Delegation match: explicit assignee first, then a name collision.
        # Unknown assignees clamp to 'general' (the generic profile) — never crash.
        assignee = str(a.get("assignee") or "").strip().lower()
        defn = by_name.get(assignee) or (by_name.get(name.lower()) if not assignee else None)
        if defn is not None:
            from .subagent_defs import resolve_profile

            profile = resolve_profile(
                defn, model_name, uniform_model=uniform_model, model_pool=model_pool
            )
            label = profile["display_name"]
            model = profile["model_name"]
            role = _safe_role(defn["name"])
        else:
            label = _label_from_name(name)
            profile = get_profile("backend")  # generic coding agent (tools/limits)
            profile["display_name"] = label
            profile["model_name"] = models[i]
            model = models[i]
            role = _safe_role(name)
        plan.append({
            "role": role,
            "task": task or "(no task specified)",
            "profile": profile,
            "model": model,
            "label": label,
        })
    return plan


def _fallback_plan(
    task_brief: str, model_name: str, uniform_model: bool, model_pool: list[str] | None = None
) -> list[dict]:
    """Rule-based keyword split → spawn-ready plan (the pre-planner behaviour).
    Lazy-imports simple_task_split to avoid a circular import with orchestrator."""
    from .orchestrator import simple_task_split  # lazy: orchestrator imports us

    steps = simple_task_split(task_brief)
    models = _assign_models(len(steps), model_name, uniform_model, model_pool)
    plan: list[dict] = []
    for i, st in enumerate(steps):
        profile = get_profile(st["role"])
        # _assign_models already encodes the policy (uniform session model / custom pool /
        # default pool), so use its choice — this is how the custom pool reaches the fallback.
        model = models[i]
        profile["model_name"] = model
        plan.append({
            "role": st["role"],
            "task": st["task"],
            "profile": profile,
            "model": model,
            "label": profile["display_name"],
        })
    return plan


_PROMPT = (
    "You are a software task planner. Break the user's coding task into a set of "
    "INDEPENDENT sub-tasks that specialized agents can work on in parallel.\n\n"
    "Rules:\n"
    f"- Use between {_MIN_AGENTS} and {_MAX_AGENTS} agents, scaling to the task's "
    "complexity. A small task uses fewer agents; a large, multi-part task uses more. "
    "Only create an agent for a genuinely separable piece of work — never pad the count.\n"
    "- Name each agent after WHAT IT DOES, as a short kebab-case handle "
    '(e.g. "auth-schema", "login-endpoint", "rate-limiter", "unit-tests", "api-docs"). '
    'Do NOT use generic names like "frontend", "backend", "agent1".\n'
    "- Give each a single-sentence task describing exactly its responsibility.\n\n"
    'Respond with ONLY compact JSON: {"agents": [{"name": "kebab-name", "task": "one sentence"}, ...]}. '
    "No prose, no markdown, no code fences.\n\n"
)


def _roster_section(subagents: list[dict] | None) -> str:
    """Custom sub-agent roster appended to the planning prompt so the LLM can
    auto-delegate a step to the specialist whose DESCRIPTION matches it."""
    if not subagents:
        return ""
    lines = "\n".join(
        f"- {d['name']}: {' '.join((d.get('description') or '(no description)').split())[:200]}"
        for d in subagents
        if d.get("name")
    )
    if not lines:
        return ""
    return (
        "Available specialist agents — assign a step to one when its DESCRIPTION "
        "matches that step's work:\n" + lines + "\n\n"
        'Add an "assignee" field to each agent object: the matching specialist\'s '
        'name, or "general" when no specialist fits.\n\n'
    )


async def plan_agents(
    task_brief: str,
    *,
    model_name: str = "",
    uniform_model: bool = False,
    model_pool: list[str] | None = None,
    subagents: list[dict] | None = None,
) -> list[dict]:
    """LLM-decided delegation → spawn-ready plan dicts. Falls back to the keyword
    split on any failure. Always returns at least one agent. `model_pool` (the user's
    Customize pool) is round-robined across the agents when supplied + not uniform.
    `subagents` (Customize → Sub-agents, enabled defs) adds a specialist roster the
    planner assigns steps to by description; unmatched steps keep the generic profile."""
    # Resolve the pool ONCE per plan, against what the provider actually serves, and pass
    # that everywhere below — so the LLM path and the keyword fallback can't disagree about
    # which models the sub-agents get.
    pool = await _effective_pool(model_pool)

    brief = (task_brief or "").strip()
    if not brief:
        return _fallback_plan(task_brief, model_name, uniform_model, pool)

    # concat (NOT .format — the prompt has literal { } JSON)
    prompt = _PROMPT + _roster_section(subagents) + "Task: " + brief[:1500]
    # Pinned planner models that aren't installed can only waste a request each and then
    # hand the whole plan to the keyword split; the pool is the honest second choice since
    # it is already known-installed.
    planner_models = await _installed(_PLANNER_MODELS) or pool
    for model in planner_models:
        try:
            async with _httpx.AsyncClient(timeout=90.0) as c:
                r = await c.post(
                    f"{_OLLAMA_URL.rstrip('/')}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 700, "num_ctx": 8192},
                    },
                )
            if r.status_code != 200:
                continue
            text = (r.json().get("response") or "").strip()
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                continue
            obj = json.loads(m.group(0))
            raw = obj.get("agents") or obj.get("steps") or []
            agents = [
                a for a in raw
                if isinstance(a, dict) and (a.get("name") or a.get("role")) and a.get("task")
            ]
            if not agents:
                continue
            # Clamp to the scale bounds. Below the floor → still honour the model's
            # call (a genuinely small task), but never exceed the ceiling.
            agents = agents[:_MAX_AGENTS]
            logger.info(
                "orchestrator planner: model=%s produced %d task-delegated agent(s): %s",
                model, len(agents), ", ".join(a.get("name", "?") for a in agents),
            )
            return _build_plan(agents, model_name, uniform_model, pool, subagents)
        except Exception as exc:
            logger.debug("orchestrator planner model %s failed: %s", model, exc)
            continue

    logger.info("orchestrator planner: LLM unavailable — falling back to keyword split")
    return _fallback_plan(task_brief, model_name, uniform_model, pool)
