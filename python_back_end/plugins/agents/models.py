"""Which model a teammate run actually uses.

A teammate row with no ``model`` (or one of the "auto" sentinels) used to send an
empty model name to the local Ollama, which answered 400 before the first tool
call. "Auto" now resolves, in order:

1. the teammate's own ``model`` when it names one,
2. the model this kind of work wants — see ``TASK_MODELS`` — as long as it is
   actually installed here (an agent run is a tool loop, so a goal that means
   driving the browser gets a proven tool-caller rather than whatever was last
   used for chatting),
3. the model the user last picked in chat (the frontend sends it with the turn),
4. the user's saved preference, then whatever is installed.

The resolved name is stamped on the run so the card shows what is thinking.
Set ``HARVIS_AGENT_TASK_MODELS=0`` to skip step 2 and always run on the last pick.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

AUTO_SENTINELS = frozenset({"", "auto", "default", "user-pref", "dynamic", "harvis-workspace"})

# Ids that are pickable in chat but are not a model a native run can call:
# another teammate, or the Hermes engine (its own server, not an Ollama tag).
_NOT_A_MODEL_PREFIXES = ("agent:",)
_NOT_A_MODEL = frozenset({"hermes-agent"})


# What each kind of work wants, best first, matched as a substring of an
# installed model name. Deliberately family-shaped ("qwen3.5", "llama3.1")
# rather than exact tags: every install has a different set pulled, and a
# pattern that matches nothing simply falls through to the next candidate.
#
# Tool-calling reliability is what an agent run lives on, so the browse/computer
# lane leads with the models that call tools cleanly; the small instruct models
# are last because they time out once the schema gets long.
TASK_MODELS: dict[str, tuple[str, ...]] = {
    "computer": ("qwen3.6", "qwen3.5", "granite4", "llama3.1", "gpt-oss", "qwen3"),
    "code": ("gpt-oss", "qwen3.6", "qwen3.5", "granite4", "llama3.1"),
    "write": ("gemma3", "gemma4", "qwen3.5", "llama3.1"),
    "general": ("qwen3.5", "granite4", "llama3.1", "gpt-oss", "qwen3"),
}

# Never route to these, whatever the pattern says: embeddings, and tags that
# bill per call (":cloud" is Ollama's hosted passthrough).
_NEVER = ("embed", ":cloud")

_COMPUTER_RE = re.compile(
    r"\b(browse|browser|search|google|look\s?up|website|web\s?page|url|online|"
    r"internet|news|price|shop|buy|compare|download|sign\s?in|log\s?in|book|order)\b",
    re.I,
)
_CODE_RE = re.compile(
    r"\b(code|refactor|debug|test|tests|repo|commit|patch|function|class|script|"
    r"build|compile|lint|stack\s?trace|bug)\b",
    re.I,
)
_WRITE_RE = re.compile(
    r"\b(write|draft|essay|blog|post|email|summar\w+|rewrite|translate|outline)\b",
    re.I,
)


def classify_task(goal: str) -> str:
    """Which of ``TASK_MODELS`` this goal belongs to. Cheap and deliberately
    coarse — it only chooses between models that can all do the job."""
    text = goal or ""
    if _COMPUTER_RE.search(text):
        return "computer"
    if _CODE_RE.search(text):
        return "code"
    if _WRITE_RE.search(text):
        return "write"
    return "general"


def task_models_enabled() -> bool:
    return (os.getenv("HARVIS_AGENT_TASK_MODELS", "1") or "").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _model_budget_bytes() -> int:
    """How large a local model this box can afford to load.

    Not a performance knob. A 22 GB tag on a 32 GB laptop does not run slowly,
    it takes the machine down: with the 35B model resident this box sat at
    ~4.9 GB available and hard-crashed four times in one afternoon on the
    global OOM killer. So the picker refuses to name a model it cannot afford.
    Defaults to 45% of RAM, capped by HARVIS_AGENT_MAX_MODEL_GB.
    """
    try:
        cap_gb = float(os.getenv("HARVIS_AGENT_MAX_MODEL_GB", "14") or 14)
    except ValueError:
        cap_gb = 14.0
    cap = int(cap_gb * 1024 ** 3)
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                    return max(1024 ** 3, min(cap, int(total * 0.45)))
    except Exception:
        pass  # Not Linux, or no procfs: the configured cap stands alone.
    return cap


async def _ollama_sizes() -> dict[str, int]:
    """``{tag: bytes on disk}`` from Ollama's /api/tags. Empty on any failure,
    which leaves every tag unfiltered rather than hiding models by accident."""
    try:
        import httpx

        from plugins.models.resolver import _normalize_ollama_base

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{_normalize_ollama_base(None)}/api/tags")
            r.raise_for_status()
        return {
            (e.get("name") or "").strip(): int(e.get("size") or 0)
            for e in (r.json() or {}).get("models") or []
        }
    except Exception:
        logger.debug("agents: ollama size listing failed", exc_info=True)
        return {}


async def _installed() -> list[tuple[str, str]]:
    """``(name, source)`` for every model this box can serve — ``"node"`` for a
    reachable inference node, ``"ollama"`` for a local tag. Empty on any
    failure, which makes the task step a no-op rather than a wrong guess."""
    found: list[tuple[str, str]] = []
    try:
        from plugins.inference_nodes import snapshot

        for state in (await snapshot()).values():
            if getattr(state, "reachable", True):
                found.extend((n, "node") for n in (getattr(state, "models", ()) or ()))
    except Exception:
        logger.debug("agents: inference-node listing failed", exc_info=True)
    try:
        from plugins.models.resolver import list_ollama_models

        # Anything this machine cannot afford to load is not a candidate: the
        # picker's job is to name a model that RUNS, and an oversized one takes
        # the whole box down before it answers. Unknown sizes are kept.
        budget, sizes = _model_budget_bytes(), await _ollama_sizes()
        for n in await list_ollama_models():
            size = sizes.get(n, 0)
            if size and size > budget:
                logger.info(
                    "agents: skipping %s (%.1f GB > %.1f GB budget)",
                    n, size / 1024 ** 3, budget / 1024 ** 3,
                )
                continue
            found.append((n, "ollama"))
    except Exception:
        logger.debug("agents: ollama tag listing failed", exc_info=True)
    return found


async def pick_for_task(goal: str, *, prefer: str | None = None) -> tuple[str, str]:
    """``(model, reason)`` for ``goal``, or ``("", "")`` when nothing fits.

    ``prefer`` (the user's last chat pick) wins whenever it is one of the
    models this kind of work would have chosen anyway — a deliberate pick
    should not be overridden by a tie.
    """
    kind = classify_task(goal)
    patterns = TASK_MODELS.get(kind) or ()
    installed = [
        (n, src) for n, src in await _installed()
        if not any(b in n.lower() for b in _NEVER)
    ]
    if not installed:
        return "", ""
    prefer = (prefer or "").strip()
    for pat in patterns:
        matches = [(n, src) for n, src in installed if pat in n.lower()]
        if not matches:
            continue
        if any(n == prefer for n, _ in matches):
            return prefer, f"last pick, and good for {kind} work"
        # A node serves one model on dedicated hardware, so it answers a tool
        # loop far faster than the same family loaded on demand by Ollama. After
        # that, the shortest name wins: base tags ("llama3.1:8b") over the long
        # community re-uploads that happen to share the family.
        matches.sort(key=lambda m: (m[1] != "node", len(m[0])))
        best, src = matches[0]
        where = "on the inference node" if src == "node" else "installed"
        return best, f"best {where} for {kind} work"
    return "", ""


def is_auto(model: str | None) -> bool:
    return (model or "").strip().lower() in AUTO_SENTINELS


def usable_pick(model: str | None) -> bool:
    """A concrete model name a run could be started on."""
    m = (model or "").strip()
    if is_auto(m) or m in _NOT_A_MODEL:
        return False
    return not m.startswith(_NOT_A_MODEL_PREFIXES)


async def resolve_run_model(
    pool,
    user_id: int | None,
    agent: dict,
    *,
    goal: str = "",
    last_pick: str | None = None,
) -> tuple[str, str]:
    """``(model_name, where_it_came_from)`` for a run of ``agent``.

    An empty model name means nothing is installed anywhere; the caller decides
    how to fail. Never raises.
    """
    own = (agent.get("model") or "").strip()
    if usable_pick(own):
        return own, "teammate setting"
    if goal and task_models_enabled():
        picked, why = await pick_for_task(goal, prefer=last_pick)
        if picked:
            return picked, why
    if usable_pick(last_pick):
        return (last_pick or "").strip(), "last picked in chat"
    try:
        from plugins.models.resolver import resolve_or_describe

        model, why = await resolve_or_describe(pool=pool, user_id=user_id)
    except Exception:
        logger.exception("agents: local model resolution failed")
        model, why = None, "resolver error"
    if model:
        return model, why
    return "", "no model available"
