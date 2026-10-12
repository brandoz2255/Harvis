"""Pieces of the session RPCs that are plain functions: model checks, summaries, exports, status text."""
from __future__ import annotations

import re
import time
from typing import Optional

from plugins import people

from . import chat, sandbox, usage
from .models import is_hidden_model
from .rest import _harvis_models, build_model_options

KEEP_USER_TURNS = 2  # /compress keeps this many of the latest user turns word for word
SUMMARY_PREFIX = "Earlier in this conversation (summarized to save space):\n\n"
_SUMMARY_PROMPT = ("Summarize the earlier part of this conversation so it can replace it in the model's context. "
                   "Keep decisions, facts, names, numbers, file names, open questions and what the user wants. "
                   "Drop pleasantries. Write plain prose or short bullets, under 350 words.")


# ---- model names -----------------------------------------------------------------

async def model_error(pool, user_id: int, token: str, model: str) -> Optional[str]:
    """Why ``model`` cannot be picked, or None. A model list that cannot be read lets any name through:
    refusing everything would be worse than trusting the picker."""
    model = (model or "").strip()
    if not model or model == "harvis-default" or is_hidden_model(model):
        return None
    options = await build_model_options(pool, user_id, token)
    known: set[str] = set()
    server: set[str] = set()
    for provider in options.get("providers") or []:
        ids = {str(m) for m in provider.get("models") or []}
        known |= ids
        if provider.get("auth_type") == "harvis":
            server |= ids
    server.discard("harvis-default")
    if not server:
        return None
    if model not in known:
        return f"I don't know a model called '{model}'. Pick one from the model menu."
    allowed = await people.allowed_for(pool, user_id)
    if allowed is not None and model in server and model not in allowed:
        return ("The Harvis admin limits your account to these models: "
                f"{', '.join(allowed) or 'none'}. Pick one of them in the model menu.")
    return None


async def context_window(token: str, model: str) -> int:
    """The model's context size when Harvis's model list states it, else the default."""
    if model:
        try:
            for row in await _harvis_models(token):
                if row.get("id") == model:
                    ctx = ((row.get("info") or {}).get("meta") or {}).get("context_length")
                    if isinstance(ctx, int) and ctx > 0:
                        return ctx
        except Exception:  # noqa: BLE001
            pass
    return usage.DEFAULT_CONTEXT


# ---- compression -----------------------------------------------------------------

def split_for_compress(msgs: list[dict]) -> tuple[list[dict], list[dict]]:
    """(older rows to summarize, recent rows to keep). Failed replies are dropped from both."""
    live = [m for m in msgs if not m.get("error")]
    users = [i for i, m in enumerate(live) if m["role"] == "user"]
    if len(users) <= KEEP_USER_TURNS:
        return [], live
    cut = users[-KEEP_USER_TURNS]
    return live[:cut], live[cut:]


async def summarize(token: str, model: str, endpoint: Optional[dict], older: list[dict], focus: str = "") -> str:
    text = "\n\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                       for m in older if m.get("content"))
    prompt = _SUMMARY_PROMPT + (f" Pay particular attention to: {focus}." if focus else "")
    turn = [{"role": "system", "content": prompt}, {"role": "user", "content": text[-24000:]}]
    out: list[str] = []
    async for kind, delta in chat.stream_turn(token, turn, model, endpoint, "chat", "",
                                              extra={"harvis_research": False, "harvis_plain": True,
                                                     "max_tokens": 700}):
        if kind == "text":
            out.append(delta)
    return "".join(out).strip()


# ---- text for /status, /usage, session.save ----------------------------------------

def transcript_markdown(title: str, msgs: list[dict]) -> str:
    lines = [f"# {title or 'Harvis chat'}", ""]
    for m in msgs:
        if m.get("error"):
            continue
        lines += [f"## {'You' if m['role'] == 'user' else 'Harvis'}", "", m.get("content") or "", ""]
    return "\n".join(lines).rstrip() + "\n"


def save_name(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "chat").lower()).strip("-")[:48] or "chat"
    return f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}.md"


def usage_lines(stats: dict) -> list[str]:
    return [f"Context: about {stats['context_used']:,} of {stats['context_max']:,} tokens "
            f"({stats['context_percent']}%)", usage.NOTE]


def status_text(s, msgs: list[dict], stats: dict) -> str:
    sent = sum(1 for m in msgs if m["role"] == "user")
    replies = sum(1 for m in msgs if m["role"] == "assistant" and not m.get("error"))
    rows = [
        f"Chat: {s.title or '(untitled)'}",
        f"Model: {s.model or 'Harvis default'}",
        f"Messages: {len(msgs)} ({sent} from you, {replies} replies)",
        f"Web search: {'on' if s.web_search else 'off'}",
        f"Reasoning effort: {s.effort or 'default'}",
        f"Running: {'yes' if s.running else 'no'}",
    ]
    cwd = sandbox.virtual_cwd(s.id)
    if cwd:
        rows.append(f"Workspace: {cwd}")
    return "\n".join([*rows, *usage_lines(stats)])
