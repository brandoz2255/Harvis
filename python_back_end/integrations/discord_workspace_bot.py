import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass

import discord
from discord import app_commands
import httpx
from fastapi import HTTPException, Request

from workspace.workspace_router import launch_workspace_internal, cancel_workspace_internal
from workspace.task_detector import detect_workspace_task
from plugins.models.resolver import resolve_default_local_model

logger = logging.getLogger(__name__)

def _debug_log(location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    return  # debug logging removed


@dataclass(frozen=True)
class DiscordWorkspaceConfig:
    enabled: bool
    token: str
    default_user_id: int
    mention_only: bool
    allowed_channel_ids: set[int]
    agent_id: str
    model_name: str
    max_wait_seconds: int
    enable_interactive: bool
    history_turns: int


def _parse_int_set(csv: str) -> set[int]:
    out: set[int] = set()
    for part in (csv or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def load_discord_workspace_config() -> DiscordWorkspaceConfig:
    enabled = os.getenv("DISCORD_WORKSPACE_ENABLED", "true").lower() == "true"
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    default_user_id = int(os.getenv("DISCORD_DEFAULT_USER_ID", "2"))
    mention_only = os.getenv("DISCORD_MENTION_ONLY", "true").lower() == "true"
    allowed_channel_ids = _parse_int_set(os.getenv("DISCORD_ALLOWED_CHANNEL_IDS", ""))
    agent_id = os.getenv("DISCORD_WORKSPACE_AGENT_ID", "main").strip() or "main"
    model_name = os.getenv("DISCORD_WORKSPACE_MODEL_NAME", "").strip()
    # Default 600s (10 min). Prior default was 1200s but users routinely waited
    # the full 20 min on stuck runs because the timeout merely *reported* failure
    # — the agent kept burning compute. Both timeout paths now call
    # cancel_workspace_internal so the underlying task actually stops.
    max_wait_seconds = int(os.getenv("DISCORD_WORKSPACE_MAX_WAIT_SECONDS", "600"))
    enable_interactive = os.getenv("DISCORD_WORKSPACE_ENABLE_INTERACTIVE", "false").lower() == "true"
    history_turns = max(0, int(os.getenv("DISCORD_WORKSPACE_HISTORY_TURNS", "10")))
    return DiscordWorkspaceConfig(
        enabled=enabled,
        token=token,
        default_user_id=default_user_id,
        mention_only=mention_only,
        allowed_channel_ids=allowed_channel_ids,
        agent_id=agent_id,
        model_name=model_name,
        max_wait_seconds=max_wait_seconds,
        enable_interactive=enable_interactive,
        history_turns=history_turns,
    )


# ── Runtime model override (mutable, changed via !model command) ─────────────

_model_override: str = ""  # when set, overrides cfg.model_name everywhere

_model_pref_cache: dict[int, tuple[float, str, str]] = {}


# ── Scope 1: failure-driven escalation between paired models ─────────────────
# Per docs/handoffs/2026-05-25-phase3-scopes.md. Default OFF; flip via env
# after smoke tests confirm escalation latency stays under 2 min.
_ESCALATE_ON_FAILURE = (
    os.getenv("HARVIS_ESCALATE_ON_FAILURE", "false").lower() in ("1", "true", "yes")
)

# Symmetric pairing. Failure-driven (NOT capability-detection — see
# [[no-keyword-model-routing]]). qwen3 covers hash/CodeAct, gemma4 covers
# MCQ/decode/crypto/conversational (see [[model-task-pairing]]).
_ESCALATION_PAIRS: dict[str, str] = {
    "qwen3:14b": "gemma4:e4b",
    "gemma4:e4b": "qwen3:14b",
}

# Fabrication banners emitted by workspace_router._validate_hash_claims /
# _validate_ctf_process_claims when the model narrates fake tool calls.
# Pure output-side detection; never inspects the task brief (that would
# reintroduce keyword routing through the back door, killing Scope 1).
_ESCALATION_FAILURE_PATTERNS: tuple[str, ...] = (
    "could not determine plaintext for the provided hash",
    "hash cracking was not performed",
    "the agent narrated a successful crack but made",
    "the agent described running crack attempts but made",
)

async def _get_user_model_preference(pool, user_id: int) -> tuple[str, str]:
    """Return (agent_id, model_name) matching the user's saved preference."""
    now = time.monotonic()
    if user_id in _model_pref_cache:
        cached_at, agent_id, model_name = _model_pref_cache[user_id]
        if now - cached_at < 30.0:
            return agent_id, model_name

    res_agent = "main"
    res_model = ""
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT provider_type, model_id FROM openclaw_llm_config WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
                    user_id
                )
            if row:
                provider = row["provider_type"]
                model = row["model_id"] or ""
                if provider == "ollama":
                    res_agent = "local"
                    res_model = model
                elif provider == "moonshot":
                    res_agent = "kimi"
                    res_model = model
                elif provider == "nvidia":
                    res_agent = "nvidia-kimi"
                    res_model = model
                else:
                    res_agent = "main"
                    res_model = model
        except Exception as exc:
            logger.warning("Failed to fetch user model preference: %s", exc)

    _model_pref_cache[user_id] = (now, res_agent, res_model)
    return res_agent, res_model


# ── Workspace ENGINE preference (separate from the MODEL) ──────────────────
# Engine = who performs the work (Native/OpenClaw tool loop vs Claude Code direct).
# Model = the brain the engine uses. They are independent controls.
_ENGINE_LABELS = {
    "native": "Native (OpenClaw)",
    "claude-code": "Claude Code",
}
_ENGINE_HINTS = {
    "native": "Complex tasks run through OpenClaw's tool loop on your selected model.",
    "claude-code": "Complex tasks run directly through Claude Code on your connected Claude credential.",
}


async def _get_user_engine_preference(pool, user_id: int) -> str:
    """Return the user's saved workspace ENGINE — 'native' (OpenClaw tool loop)
    or 'claude-code' (Claude Code direct engine). Fail-soft → 'native'."""
    if not pool:
        return "native"
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT engine FROM openclaw_llm_config WHERE user_id = $1 "
                "ORDER BY updated_at DESC LIMIT 1",
                user_id,
            )
        eng = ((row["engine"] if row else None) or "native").strip()
        return eng or "native"
    except Exception as exc:
        logger.debug("Failed to fetch user engine preference: %s", exc)
        return "native"


async def _user_has_anthropic_provider(pool, user_id: int) -> bool:
    """True when the user's OpenClaw model provider is Anthropic WITH an API key
    stored — i.e. Path A is ready (OpenClaw runs its tool loop on Claude via the
    Anthropic Messages API). When true, a Claude model is passed through to
    OpenClaw rather than swapped for a local fallback."""
    if not pool:
        return False
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT provider_type, api_key_encrypted FROM openclaw_llm_config "
                "WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
                user_id,
            )
        return bool(row and (row["provider_type"] == "anthropic") and row["api_key_encrypted"])
    except Exception:
        return False


async def _get_last_local_model(pool, user_id: int) -> str:
    """The last LOCAL (non-cloud) model the user selected — used to restore their
    actual pick when a cloud model falls back to the OpenClaw workspace lane."""
    if not pool:
        return ""
    try:
        async with pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT last_local_model_id FROM openclaw_llm_config WHERE user_id = $1 "
                "ORDER BY updated_at DESC LIMIT 1",
                user_id,
            )
        return (v or "").strip()
    except Exception:
        return ""


async def _get_user_orchestrate_pref(pool, user_id: int) -> bool:
    """Whether the user enabled multi-agent (orchestrate) for Discord workspaces."""
    if not pool:
        return False
    try:
        async with pool.acquire() as conn:
            v = await conn.fetchval(
                "SELECT orchestrate_enabled FROM openclaw_llm_config WHERE user_id = $1 "
                "ORDER BY updated_at DESC LIMIT 1",
                user_id,
            )
        return bool(v)
    except Exception:
        return False


def _looks_multi_part(text: str) -> bool:
    """Heuristic: does this task look multi-part / complex enough to fan out to
    several agents? (Used only when the user has multi-agent ON — trivial workspace
    tasks stay single-agent.)"""
    t = (text or "").strip()
    if len(t) >= 200 or "\n" in t:
        return True
    if re.search(
        r"(?:\b\d+[\.\)]\s|\bstep\s*\d|\bthen\b|\balso\b|\bafter that\b"
        r"|\bcompare\b|\bversus\b|\bvs\.?\b|\beach of\b)",
        t,
        re.IGNORECASE,
    ):
        return True
    # multiple "and"-joined asks (e.g. "research X and compare A and B")
    if len(re.findall(r"\band\b", t, re.IGNORECASE)) >= 2:
        return True
    # 2+ substantial sentence-like asks
    parts = [s for s in re.split(r"[.!?]\s+", t) if len(s.strip()) > 15]
    return len(parts) >= 2


# One workspace at a time per (channel/thread id, user id) so OpenClaw sessionKey stays singular.
_discord_workspace_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _discord_workspace_lock(message: discord.Message) -> asyncio.Lock:
    cid = int(getattr(message.channel, "id", 0))
    uid = int(message.author.id)
    key = (cid, uid)
    if key not in _discord_workspace_locks:
        _discord_workspace_locks[key] = asyncio.Lock()
    return _discord_workspace_locks[key]


# ── Fast-path: simple questions answered directly via local Ollama ──────────

_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_FAST_MODEL = os.getenv("WORKSPACE_DETECTOR_OLLAMA_MODEL") or os.getenv(
    "DISCORD_FAST_MODEL", ""
)  # blank = use cfg.model_name or default
_PREFER_WORKSPACE = os.getenv("DISCORD_PREFER_WORKSPACE", "false").lower() == "true"

# ── Quick regex pre-filter: skip the AI classifier for obviously simple messages ──
# These patterns strongly indicate the message NEEDS tools/browser/workspace.
# Messages NOT matching any of these get the fast path directly, avoiding the
# 2-5s Ollama classifier call for greetings, short questions, etc.
_WORKSPACE_SIGNALS = re.compile(
    r"(https?://|\.com\b|\.org\b|\.io\b|\.dev\b|\.net\b"
    r"|screenshot|screen\s*shot|browse|open\s+.*website"
    r"|write\s+(?:a\s+)?(?:file|code|script|program|function|component|page|api)"
    r"|create\s+(?:a\s+)?(?:file|repo|project|pr|pull\s*request|component|endpoint|route)"
    r"|make\s+(?:a\s+)?(?:component|page|api|endpoint|function|class|module)"
    r"|implement|add\s+(?:a\s+)?(?:feature|button|form|modal|table)"
    r"|run\s+(?:a\s+)?(?:command|script|test|code)"
    # Research / web-lookup triggers — natural language forms
    r"|search\s+(?:the\s+)?(?:web|internet|google|online|for)"
    r"|look\s+(?:it|that|this)?\s*up"
    r"|find\s+(?:me|out|info|information|the|some)"
    r"|what(?:\s+is|\s+are|'s|\s+was|\s+were)\s"
    r"|who(?:\s+is|\s+are|'s|\s+was|\s+were)\s"
    r"|latest\s+(?:news|version|release|update)"
    r"|current\s+(?:price|status|version|news)"
    r"|research\s|investigate|fact[-\s]?check|verify"
    r"|download|upload|install|deploy|build|compile"
    r"|fix\s+(?:the\s+)?(?:bug|error|issue|code)"
    r"|debug|refactor|merge|commit|push|pull"
    r"|read\s+(?:the\s+)?file|edit\s+(?:the\s+)?file"
    r"|analyze\s+(?:the\s+)?(?:code|repo|log|image|picture|photo|screenshot)"
    r"|react|nextjs|next\.js|fastapi|python|typescript|javascript"
    r"|component|endpoint|router|schema|migration|dockerfile"
    # Hash/decode/crypto tasks MUST go through workspace (tools + validator).
    # Without this, a bare hash like "5d41402abc4b2a76b9719d911017c592"
    # could hit fast-path if PREFER_WORKSPACE is ever turned off.
    r"|crack|brute.?force|\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{64}\b"
    r"|decode|decrypt|cipher)",
    re.IGNORECASE,
)


_VISUAL_TASK_SIGNALS = re.compile(
    # Visual intent ONLY — explicit screenshot / page-render words.
    # Previously this also matched bare URLs and TLDs, which silently forced
    # `agent_id="main"` for ANY prompt mentioning a link (including our own
    # skill example URLs), overriding the user's `/model` pick. Removed the
    # URL/TLD matches; only kick into the OpenClaw browser path when the user
    # actually asks to see something.
    r"(screenshot|screen\s*shot|screencap|capture\s+screen|"
    r"show\s+me\s+the\s+page|take\s+(?:a\s+)?picture\s+of\s+the\s+page|"
    r"website\s+screenshot|webpage\s+screenshot|"
    r"open\s+(?:the\s+)?(?:url|website|page|browser)|"
    r"navigate\s+to\s+http|render\s+(?:the\s+)?page)",
    re.IGNORECASE,
)


def _looks_like_visual_task(text: str) -> bool:
    """Return True when the request likely needs real browser screenshot tooling."""
    return bool(_VISUAL_TASK_SIGNALS.search(text or ""))


def _is_obviously_simple(text: str) -> bool:
    """Return True for messages that are clearly conversational and don't need
    the AI classifier at all. This saves 2-5s of Ollama classification latency
    for greetings, short questions, etc."""
    # Very long messages are likely complex — route to classifier
    if len(text) > 300:
        return False
    # Any workspace tool signal → needs classifier
    if _WORKSPACE_SIGNALS.search(text):
        return False
    # Short messages without tool signals are conversational
    if len(text) < 200:
        return True
    return False


_DISCORD_MEMORY_META_RE = re.compile(
    r"\b(how far back can you see|what (?:is )?my job|what am i|who am i|"
    r"what did i (?:say|tell you)|do you remember|remember what)\b",
    re.IGNORECASE,
)


def _looks_like_discord_memory_meta_chat(text: str) -> bool:
    """Personal-memory and capability questions should stay in chat mode.

    `DISCORD_PREFER_WORKSPACE=true` intentionally sends many prompts through
    OpenClaw, but identity/memory questions are better answered from recent
    Discord turns. Sending them to workspace tends to trigger the Harvis
    identity prompt instead of answering the user's actual question.
    """
    return bool(_DISCORD_MEMORY_META_RE.search(text or ""))


def _direct_discord_memory_reply(
    content: str,
    prior_history: list[dict],
    history_turns: int,
) -> str:
    low = (content or "").lower().strip()

    if "how far back can you see" in low:
        return (
            f"I can use the recent Discord turns included with this message "
            f"(configured for up to {history_turns} bot/user messages from this channel). "
            "I cannot see your whole Discord history unless it is included in that recent context."
        )

    asks_job = "job" in low or low in {"what am i", "who am i"}
    if not asks_job:
        return ""

    for turn in reversed(prior_history or []):
        if turn.get("role") != "user":
            continue
        text = (turn.get("content") or "").strip()
        match = re.search(
            r"\b(?:i am|i'm|im|my job is|i work as)\s+(?:a|an)?\s*([a-z][a-z\s-]{1,80})",
            text,
            re.IGNORECASE,
        )
        if not match:
            continue
        job = match.group(1).strip(" .,!?:;").lower()
        if job in {"fire fighter", "firefighter"}:
            job = "firefighter"
        return f"Based on what you told me previously, you are a {job}."

    return "I do not see your job in the recent Discord context I was given."


_TOOL_TASK_SIGNALS = re.compile(
    r"\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{64}\b|\b[a-f0-9]{128}\b"
    r"|\$(?:1|2[abxy]?|5|6|argon2)\$"
    r"|crack|hash|decode|decrypt|brute.?force",
    re.IGNORECASE,
)

# Discord embeds timestamps like "12:35:40 am" or "1:05 PM" when users paste
# multi-line content.  These leak into the task brief and confuse the model.
_DISCORD_TIME_ONLY_LINE = re.compile(
    r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\s*$", re.IGNORECASE | re.MULTILINE,
)
_DISCORD_LEADING_TIME = re.compile(
    r"^\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\s+", re.IGNORECASE | re.MULTILINE,
)


def _strip_discord_timestamp_noise(text: str) -> str:
    """Remove stray Discord timestamps from user content."""
    # First pass: drop lines that are *only* a timestamp
    text = _DISCORD_TIME_ONLY_LINE.sub("", text)
    # Second pass: strip leading timestamp prefix from remaining lines
    text = _DISCORD_LEADING_TIME.sub("", text)
    # Collapse multiple blank lines left behind
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


_reset_epochs: dict[tuple[object, int], int] = {}
"""Per-(channel, user) timestamp set by `@bot reset-context`. The value
is an int unix-time so the suffix is unique across backend restarts (a
plain counter would re-use the same suffix after rebuild and OpenClaw's
persistent session-file lookup would find the prior contaminated session).
The epoch is folded into the OpenClaw session_id so the next message starts
a brand-new OpenClaw session."""

_reset_pending: set[tuple[object, int]] = set()
"""Per-(channel, user) tuples that have been reset but haven't yet
consumed their reset (i.e. no new message has arrived since). The first
message after `reset-context` gets `prior_history=[]` injected so prior
Discord-fetched turns don't leak in alongside the wiped OpenClaw session.
Cleared automatically when consumed."""


def _discord_openclaw_session_id(
    message: discord.Message, *, fresh: bool = False,
) -> str:
    """
    One OpenClaw session per Discord channel (or thread) + user.

    Previously we used message.id in the session key, so every new message looked
    like a brand-new Discord/OpenClaw context. That encouraged the model to
    re-introduce "Discord" / identity boilerplate and treat sub-agent spawns as
    separate integrations. Reusing the same session keeps a single logical instance.

    When *fresh* is True the message.id is appended so the session starts with no
    prior turns. Used for tool-dependent tasks (hash cracking, decode) where prior
    OpenClaw session memory bleeds old answers into the new prompt and causes the
    model to skip tool calls.

    A non-zero reset-epoch is also folded in, so `@bot reset-context` cleanly
    pivots the channel onto a new OpenClaw session without restarting anything.
    """
    chan_id = getattr(message.channel, "id", "dm")
    base = f"discord-{chan_id}-{message.author.id}"
    epoch = _reset_epochs.get((chan_id, message.author.id), 0)
    if epoch:
        # `-r<unix-ts>` — unique across backend rebuilds. A counter-style
        # `-e<N>` collides with the prior contaminated session file after
        # a rebuild resets the in-memory counter back to 0.
        base = f"{base}-r{epoch}"
    if fresh:
        return f"{base}-{message.id}"
    return base


# Substrings that identify bot messages we MUST strip from the assistant-role
# history before handing it to the agent. Two failure modes covered:
#
#   1. Failure-fallback turns — "produced no answer", etc. (the original
#      reason this filter exists). Without filtering, the model sees a string
#      of empty bot turns and rationally continues the pattern.
#
#   2. Fabrication-shaped turns — phrases that the Tool Result Honesty HARD
#      RULES in AGENTS.md explicitly forbid the model from emitting. If a
#      prior turn ALREADY broke that rule (because the directive wasn't yet
#      injected, or the model lost a roll against history), keeping that
#      turn in history will train the next turn to repeat the same
#      fabrication. Verified live on 2026-05-18: side-by-side same-prompt
#      test, a fresh channel honestly refused the hash; the contaminated
#      channel parroted the prior "Answer: mew" + "This was confirmed by
#      directly computing hashlib.md5..." verbatim despite the directive
#      being in the system prompt. Filtering kills the poisoning feedback
#      loop.
_BOT_FALLBACK_SIGNALS: tuple[str, ...] = (
    # Original failure-fallback patterns.
    "produced no answer and did not call any tools",
    "If the task requires file or web access, rephrase it more explicitly",
    "I cannot see your whole Discord history",
    # Fabrication-shaped patterns. Any prior bot turn containing these
    # already violated the Tool Result Honesty directive — don't feed it
    # back into the next turn's context.
    "directly computing hashlib.md5",
    "directly computing `hashlib.md5",
    "This was confirmed by directly computing",
    "Direct computation shows",
    "Running this in Python gives",
    "I verified by running",
    "does not override the cryptographic verification",
    "mathematically tied to",
)


async def _fetch_discord_chat_history(
    client: discord.Client,
    message: discord.Message,
    limit: int = 0,
    max_chars_per_msg: int = 1500,
) -> list[dict]:
    """Pull recent messages from the same channel/DM so the agent has context.

    Returns [{role, content}, ...] oldest first. Only messages from the current
    user and the bot are included; other humans in a shared channel are filtered
    out so cross-talk doesn't poison the prompt. The triggering message itself
    is excluded (it becomes the new user turn in `task_brief`).

    Bot fallback strings (`_BOT_FALLBACK_SIGNALS`) are filtered out of the
    assistant-role history so the model doesn't condition on its own past
    failure messages and replay them.
    """
    try:
        history_chan = message.channel
        if history_chan is None:
            return []

        bot_id = client.user.id if client.user else None
        user_id = message.author.id
        cutoff_id = message.id

        collected: list[dict] = []
        async for m in history_chan.history(limit=max(1, limit + 5)):
            if m.id == cutoff_id:
                continue
            a_id = getattr(m.author, "id", None)
            if a_id is None:
                continue
            if a_id == bot_id:
                role = "assistant"
            elif a_id == user_id:
                role = "user"
            else:
                continue  # skip other humans in the same channel

            text = (m.content or "").strip()
            if not text:
                continue
            # Strip any bot-mention form so old mentions don't clutter history.
            if bot_id is not None:
                text = re.sub(rf"<@!?{bot_id}>", "", text).strip()
            if not text:
                continue
            # Drop our own fallback/error messages from the assistant history
            # so the model doesn't condition on them. User messages are kept
            # verbatim — they're the actual intent the agent should serve.
            if role == "assistant" and any(sig in text for sig in _BOT_FALLBACK_SIGNALS):
                logger.debug("Discord history: dropped bot-fallback turn (%d chars)", len(text))
                continue
            if len(text) > max_chars_per_msg:
                text = text[:max_chars_per_msg] + "…"

            collected.append({"role": role, "content": text, "_ts": m.created_at.timestamp()})
            if len(collected) >= limit:
                break

        # channel.history() returns newest first — reverse to chronological order.
        collected.sort(key=lambda m: m["_ts"])
        return [{"role": m["role"], "content": m["content"]} for m in collected]
    except Exception as exc:
        logger.warning("Discord history fetch failed: %s", exc)
        return []


async def _fast_llm_reply(
    content: str,
    model: str,
    chat_history: list[dict] | None = None,
) -> str:
    """Call local Ollama directly for a quick conversational answer.

    When chat_history is provided, prior turns are spliced into the messages
    array so the model has real cross-turn memory on the fast path too
    (not just on the workspace path).
    """
    base_url = _LOCAL_OLLAMA_URL.rstrip("/")

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are Harvis, a helpful AI assistant on Discord. "
                "Give concise, direct answers. Keep responses under 1800 characters. "
                "Do not use markdown headers. Use plain text or simple formatting. "
                "You DO have access to recent conversation — use it. If the user "
                "just told you a fact about themselves (name, job, preference), "
                "remember it for follow-up questions. Never say 'I don't have "
                "memory' when prior turns are in your context.\n"
                "If the user asks what you can see or how far back you can see, "
                "answer only about the recent Discord context included in this "
                "request. Do not pivot to the user's previous topic.\n"
                "\n"
                "You are running in CONVERSATIONAL mode: no tools, no web, no "
                "file access, no code execution. If the user asks for something "
                "that genuinely needs tools (web search, file read, run code, "
                "analyze an image, fetch a URL), tell them briefly and ask them "
                "to use the workspace: \"That needs the workspace — try 'research <topic>' "
                "or attach the file with your message.\" Do NOT invent tool output. "
                "Do NOT say \"as an AI I can't\" — just route them to the workspace."
            ),
        }
    ]
    if chat_history:
        for m in chat_history:
            role = m.get("role")
            text = (m.get("content") or "").strip()
            if not text or role not in ("user", "assistant"):
                continue
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": content})

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "reasoning_effort": "none",
        "options": {"num_ctx": 8192},
    }

    parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            async with client.stream(
                "POST", f"{base_url}/v1/chat/completions", json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.warning("fast_llm_reply: Ollama %s: %s", resp.status_code, body[:300])
                    return ""
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        tok = delta.get("content", "")
                        if tok:
                            parts.append(tok)
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        logger.warning("fast_llm_reply error: %s", exc)
        return ""

    return "".join(parts).strip()


async def _cloud_chat_reply(
    model: str,
    content: str,
    prior_history: list[dict],
    pool,
    user_id: "int | None",
) -> str:
    """Reply to a Discord message with a CLOUD chat model (e.g. Claude) IN-PROCESS.

    OpenClaw/Ollama can't run cloud models, so a cloud pick routes conversationally
    through the same path the web chat uses (``proxy_cloud_chat``), authenticated as
    the default Discord user with their own verified credential — the secret is never
    seen here. Returns plain text, or '' on failure so the caller can fall back to the
    local routing.
    """
    try:
        from owui_compat.cloud_chat import proxy_cloud_chat
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning("cloud_chat_reply: import failed: %s", exc)
        return ""
    messages: list[dict] = []
    for m in (prior_history or []):
        role = m.get("role")
        text = (m.get("content") or "").strip()
        if text and role in ("user", "assistant"):
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": content})
    body = {"model": model, "messages": messages, "stream": False}
    try:
        resp = await proxy_cloud_chat(body, pool, user_id)
        raw = getattr(resp, "body", None)
        if raw is None:
            logger.warning(
                "cloud_chat_reply: response has no body (status=%s)",
                getattr(resp, "status_code", "?"),
            )
            return ""
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        data = json.loads(raw)
        choices = data.get("choices")
        if choices:
            return ((choices[0] or {}).get("message") or {}).get("content") or ""
        err = (data.get("error") or {}).get("message")
        if err:
            logger.warning("cloud_chat_reply: vendor error: %s", err)
            return f"⚠️ {err}"
        return ""
    except Exception as exc:
        logger.warning("cloud_chat_reply failed: %s", exc)
        return ""


async def _wait_for_workspace_completion(
    *, request: Request, workspace_id: str, timeout_s: int
) -> tuple[str, str | None, str | None]:
    """
    Return (status, final_summary, error_message).
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return ("error", None, "Database not available")

    deadline = asyncio.get_running_loop().time() + max(5, timeout_s)
    while asyncio.get_running_loop().time() < deadline:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status, final_summary, error_message FROM workspace_runs WHERE id = $1",
                workspace_id,
            )
        if row:
            status = row.get("status") or "running"
            if status != "running":
                return (status, row.get("final_summary"), row.get("error_message"))
        
        # adaptive polling
        iters = getattr(asyncio.current_task(), "_wait_iters", 0) + 1
        setattr(asyncio.current_task(), "_wait_iters", iters)
        if iters <= 10:
            await asyncio.sleep(0.3)
        elif iters <= 30:
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(2.0)

    # Timeout reached — stop the underlying agent before returning the error.
    # Without this, the OpenClaw run keeps burning compute until manually
    # cancelled (see workspace 37408f92 which ran 1441s vs the 1200s timeout).
    try:
        await cancel_workspace_internal(workspace_id, audit_actor="discord:timeout")
    except Exception as exc:
        logger.warning("Auto-cancel on timeout failed for %s: %s", workspace_id, exc)
    return ("error", None, f"Timed out after {timeout_s}s waiting for workspace completion")


# ── Friendly tool name mapping for Discord progress updates ──────────────────

# Cursor-style verbs (present tense; the filename/arg is appended by the formatter, and the
# action↔result pairing turns each into "⏳ Writing hello.txt" → "✅ Writing hello.txt").
_TOOL_LABELS: dict[str, str] = {
    "exec": "Running",
    "harvis-terminal": "Running",
    "run_tests": "Running tests",
    "run_code": "Running code",
    "read": "Reading",
    "read_file": "Reading",
    "list_files": "Listing",
    "write": "Writing",
    "write_file": "Writing",
    "edit_file": "Writing",
    "str_replace": "Editing",
    "apply_patch": "Editing",
    "git_commit": "Committing",
    "browser/session": "Opening browser",
    "browser/navigate": "Navigating to",
    "browser/screenshot": "Taking screenshot",
    "browser/act": "Interacting with page",
    "browser/close": "Closing browser",
    "web_search": "Researching",
    "web_fetch": "Fetching",
    "memory_search": "Searching memory",
    "memory_search_unified": "Searching memory",
    "memory_store": "Saving memory",
    "memory_get": "Recalling memory",
    "local_rag": "Searching docs",
    "rag_search": "Searching docs",
}

# Tools whose `args.command` should be shown inline next to the call banner.
_TOOLS_WITH_INLINE_CMD = {"exec", "harvis-terminal", "run_tests"}

# Tools whose primary argument should be shown inline (in quotes for queries,
# bare for URLs/paths). Maps tool name → arg-key tuple (first match wins).
class CancelWorkspaceView(discord.ui.View):
    """Discord cancel button attached to the progress message of a running
    workspace. Clicking calls cancel_workspace_internal — same code path as
    the `@bot cancel` text command and the HTTP /cancel endpoint.

    Only the user who launched the task can click. Other clicks get a quiet
    ephemeral notice. The view's own timeout auto-disables the button after
    the workspace timeout + a small margin, matching the run lifecycle.
    """

    def __init__(self, workspace_id: str, author_id: int, *, timeout: float = 700.0):
        super().__init__(timeout=timeout)
        self.workspace_id = workspace_id
        self.author_id = author_id

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="⛔")
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the user who started this task can cancel it.",
                ephemeral=True,
            )
            return

        try:
            result = await cancel_workspace_internal(
                self.workspace_id,
                audit_actor=f"discord:button:{interaction.user.id}",
            )
        except Exception as exc:
            logger.exception("Cancel button: internal call failed: %s", exc)
            await interaction.response.send_message(
                f"Cancel failed: {exc}",
                ephemeral=True,
            )
            return

        # Reflect outcome on the button itself and disable it.
        button.disabled = True
        status = result.get("status")
        if status == "cancelled":
            button.label = "Cancelled"
            button.emoji = "\U0001f6d1"
            button.style = discord.ButtonStyle.secondary
        elif status == "already_terminal":
            button.label = f"Already {result.get('current', 'done')}"
            button.style = discord.ButtonStyle.secondary
        else:
            button.label = "Not tracked"
            button.style = discord.ButtonStyle.secondary
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            # Message may have been edited / dismissed — best-effort only.
            pass


_TOOLS_WITH_INLINE_ARG: dict[str, tuple[str, ...]] = {
    "web_search": ("query", "q"),
    "web_fetch": ("url", "href"),
    # File tools carry the target under `path` — show the filename so a step reads
    # "Writing hello.txt" / "Reading src/app.py", not a bare "Writing file".
    "read_file": ("path", "file", "filename"),
    "read": ("path", "file", "filename"),
    "edit_file": ("path", "file", "filename"),
    "write": ("path", "file", "filename"),
    "write_file": ("path", "file", "filename"),
    "str_replace": ("path", "file", "filename"),
    "apply_patch": ("path", "file", "filename"),
    "list_files": ("path", "dir"),
    "browser/navigate": ("url", "href"),
    "memory_search": ("query", "q"),
    "memory_search_unified": ("query", "q"),
    "memory_get": ("key", "name"),
    "local_rag": ("query", "q"),
    "rag_search": ("query", "q"),
}


def _format_progress_line(event_type: str, payload: dict) -> str | None:
    """Convert a workspace_event row into a short Discord-friendly progress line."""
    if event_type == "log":
        msg = (payload.get("message") or "").strip()
        if msg:
            # \ud83d\udcac narrative + [tool] streamed output benefit from a wider cap;
            # 120 chars cut off useful content right after dividers/banners.
            return f"\u2022 {msg[:200]}"
        return None

    if event_type == "tool_call":
        tool = payload.get("tool", "unknown")
        if tool == "finish":
            return None  # the agent wrapping up \u2014 not a step worth a line
        label = _TOOL_LABELS.get(tool, f"Using {tool}")
        emoji = "\U0001f4bb" if tool == "harvis-terminal" else "\u2699\ufe0f"
        args = payload.get("args") or {}
        if tool in _TOOLS_WITH_INLINE_CMD:
            cmd = args.get("preview") or args.get("command", "")
            if cmd:
                cmd_short = cmd[:80] + ("\u2026" if len(cmd) > 80 else "")
                return f"{emoji} {label}: `{cmd_short}`"
        if tool in _TOOLS_WITH_INLINE_ARG:
            for k in _TOOLS_WITH_INLINE_ARG[tool]:
                val = (args.get(k) or "").strip() if isinstance(args.get(k), str) else ""
                if val:
                    val_short = val if len(val) <= 90 else val[:87] + "\u2026"
                    # Queries get quoted, URLs/paths stay bare for clickability.
                    if k in ("query", "q"):
                        return f"{emoji} {label}: \"{val_short}\""
                    return f"{emoji} {label}: {val_short}"
        return f"{emoji} {label}"

    if event_type == "tool_result":
        success = payload.get("success", True)
        tool = payload.get("tool", "")
        label = _TOOL_LABELS.get(tool, tool or "Tool")
        if tool == "harvis-terminal":
            output = payload.get("output") or {}
            exit_code = output.get("exit_code")
            duration_ms = output.get("duration_ms")
            suffix_parts: list[str] = []
            if exit_code is not None:
                suffix_parts.append(f"exit={exit_code}")
            if duration_ms is not None:
                suffix_parts.append(f"{duration_ms}ms")
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            if success:
                return f"\u2705 {label} complete{suffix}"
            return f"\u274c {label} failed{suffix}"
        if success:
            return f"\u2705 {label} complete"
        return f"\u274c {label} failed"

    if event_type == "agent_start":
        label = payload.get("agent_label", "Agent")
        model = payload.get("model") or ""
        suffix = f" ({model})" if model else ""
        return f"\U0001f916 {label} started{suffix}"

    if event_type == "agent_end":
        label = payload.get("agent_label", "Agent")
        return f"\U0001f3c1 {label} finished"

    return None


async def _wait_with_progress(
    *,
    request: Request,
    workspace_id: str,
    timeout_s: int,
    progress_msg: discord.Message,
    thread=None,
) -> tuple[str, str | None, str | None]:
    """
    Poll workspace_events and edit the Discord progress message with live updates.
    Returns (status, final_summary, error_message).

    `thread` (optional, additive — None keeps every existing caller byte-identical):
    a channel to post PERSISTENT messages into for 'agent_message' conversation
    events (the coder ↔ reviewer review loop). Unlike progress lines (edited into
    one throwaway message), these are the dialogue itself, so each gets its own
    labeled post ("🧑‍💻 coder: …" / "🔎 reviewer: …") that stays in the thread.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return ("error", None, "Database not available")

    deadline = asyncio.get_running_loop().time() + max(5, timeout_s)
    last_seq = -1
    progress_lines: list[str] = ["\u23f3 Starting workspace\u2026"]
    last_tool_idx = -1  # index of the pending "\u23f3 <action>" line awaiting its result (paired)
    last_edit_text = ""
    edit_interval = 2.5  # seconds between Discord message edits (rate limit friendly)
    last_edit_time = 0.0
    start_time = asyncio.get_running_loop().time()
    notified_long = False

    while asyncio.get_running_loop().time() < deadline:
        # Check if workspace is done
        async with pool.acquire() as conn:
            run_row = await conn.fetchrow(
                "SELECT status, final_summary, error_message FROM workspace_runs WHERE id = $1",
                workspace_id,
            )
        if run_row:
            status = run_row.get("status") or "running"
            if status != "running":
                return (status, run_row.get("final_summary"), run_row.get("error_message"))

        # Fetch new events since last_seq
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, event_type, payload
                FROM workspace_events
                WHERE workspace_id = $1 AND seq > $2
                ORDER BY seq ASC
                LIMIT 20
                """,
                workspace_id, last_seq,
            )

        new_lines = False
        for row in rows:
            last_seq = row["seq"]
            payload = row.get("payload") or {}
            if not isinstance(payload, dict):
                try:
                    payload = json.loads(str(payload))
                except Exception:
                    payload = {}
            etype = row["event_type"]

            # agent_message (review loop): a coder↔reviewer CONVERSATION post — render
            # it as its own persistent labeled message, not a throwaway progress line.
            if row["event_type"] == "agent_message" and thread is not None:
                _am_role = str(payload.get("role") or payload.get("label") or "agent").strip().lower()
                _am_emoji = "\U0001f50e" if _am_role == "reviewer" else "\U0001f9d1\u200d\U0001f4bb"
                _am_content = str(payload.get("content") or "").strip()
                if _am_content:
                    try:
                        await _send_long_message(
                            thread, f"{_am_emoji} **{_am_role}**: {_am_content}"
                        )
                    except Exception as exc:
                        logger.warning("agent_message post failed for %s: %s", workspace_id, exc)

            # Cursor-style pairing: a tool_call shows as a pending "⏳ <action> <target>" line;
            # its tool_result marks THAT same line done in place (✅/❌) instead of adding a second
            # line — so the feed reads "⏳ Writing hello.txt" → "✅ Writing hello.txt".
            if etype == "tool_call":
                line = _format_progress_line("tool_call", payload)
                if line:
                    body = line.split(" ", 1)[1] if " " in line else line
                    progress_lines.append("⏳ " + body)
                    last_tool_idx = len(progress_lines) - 1
                    new_lines = True
            elif etype == "tool_result" and 0 <= last_tool_idx < len(progress_lines):
                success = payload.get("success", True)
                base = progress_lines[last_tool_idx]
                body = base.split(" ", 1)[1] if " " in base else base
                progress_lines[last_tool_idx] = ("✅ " if success else "❌ ") + body
                last_tool_idx = -1
                new_lines = True
            elif etype != "agent_message":
                line = _format_progress_line(etype, payload)
                if line:
                    progress_lines.append(line)
                    new_lines = True
                last_tool_idx = -1  # a non-tool event ends the current pairing

            # Cap displayed lines; keep the pending-tool index valid if the head is trimmed.
            if len(progress_lines) > 15:
                _dropped = len(progress_lines) - 15
                progress_lines = progress_lines[-15:]
                last_tool_idx = last_tool_idx - _dropped if last_tool_idx >= _dropped else -1

        # Long task notification
        now_time = asyncio.get_running_loop().time()
        if now_time - start_time > 120.0 and not notified_long:
            progress_lines.append("\u23f3 Task is taking longer than usual, but Harvis is still working on it\u2026")
            new_lines = True
            notified_long = True

        # Edit the progress message if we have new content (rate limited)
        now = time.monotonic()
        if new_lines and (now - last_edit_time) >= edit_interval:
            edit_text = f"**Workspace `{workspace_id}`**\n" + "\n".join(progress_lines)
            # Only edit if text actually changed
            if edit_text != last_edit_text:
                try:
                    await progress_msg.edit(content=edit_text[:2000])
                    last_edit_text = edit_text
                    last_edit_time = now
                except discord.HTTPException:
                    pass  # rate limited or message deleted

        # adaptive polling
        iters = getattr(asyncio.current_task(), "_wait_iters_prog", 0) + 1
        setattr(asyncio.current_task(), "_wait_iters_prog", iters)
        if iters <= 10:
            await asyncio.sleep(0.3)
        elif iters <= 30:
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(2.0)

    # Timeout reached — auto-cancel so the agent doesn't keep running silently.
    try:
        await cancel_workspace_internal(workspace_id, audit_actor="discord:timeout-progress")
    except Exception as exc:
        logger.warning("Auto-cancel on progress-timeout failed for %s: %s", workspace_id, exc)
    return ("error", None, f"Timed out after {timeout_s}s waiting for workspace completion")


def _extract_detail_from_text(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r'"detail"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    return None


def _extract_artifact_path_from_text(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r'"artifact_path"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    # Fallback for plain text formats like: Screenshot saved at: browser/xxx.png
    # Support common image extensions in case browser runner format changes.
    m2 = re.search(r"(browser/[A-Za-z0-9._\-]+\.(?:png|jpg|jpeg|webp))", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


def _extract_artifact_path_from_payload(payload: dict) -> str | None:
    """
    Recursively search an event payload for screenshot artifact paths.
    Handles both structured keys and stringified output blobs.
    """
    if not isinstance(payload, dict):
        return None

    def walk(node) -> str | None:
        if isinstance(node, dict):
            direct = node.get("artifact_path")
            if isinstance(direct, str) and direct.strip():
                return direct.strip()
            for val in node.values():
                found = walk(val)
                if found:
                    return found
            return None
        if isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
            return None
        if isinstance(node, str):
            return _extract_artifact_path_from_text(node)
        return None

    return walk(payload)


def _strip_screenshot_path_lines(text: str) -> str:
    """
    Remove "Screenshot: browser/....png" lines from the message text so the
    user sees the attached image rather than a path listing.
    """
    if not text:
        return ""
    # Remove inline screenshot mentions (with or without backticks)
    text = re.sub(
        r"(Screenshot(\s+saved\s+at)?\s*:\s*`?)(browser/[A-Za-z0-9._\-]+\.png)`?\s*(\(for reference\))?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(Screenshot\s+path\s*:\s*)(browser/[A-Za-z0-9._\-]+\.png)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Clean up leftover punctuation/extra whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text).strip()
    return text


async def _find_latest_screenshot_file(
    *, request: Request, workspace_id: str
) -> tuple[str | None, str | None]:
    """
    Return (absolute_path, relative_artifact_path) for latest screenshot if found.
    Uses workspace_events payload text to locate artifact_path.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return (None, None)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_type, payload
            FROM workspace_events
            WHERE workspace_id = $1
            ORDER BY seq DESC
            LIMIT 160
            """,
            workspace_id,
        )

    rel_path: str | None = None
    for row in rows:
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            try:
                payload = json.loads(str(payload))
            except Exception:
                payload = {}

        # Try structured + nested extraction first.
        rel_path = _extract_artifact_path_from_payload(payload)
        if rel_path:
            break

    if not rel_path:
        return (None, None)

    # Normalize absolute-looking artifact paths into relative browser/... paths.
    if rel_path.startswith("/"):
        marker = "/browser/"
        marker_pos = rel_path.find(marker)
        if marker_pos != -1:
            rel_path = rel_path[marker_pos + 1 :]
        else:
            rel_path = rel_path.lstrip("/")

    candidate_roots = [
        os.environ.get("ARTIFACT_STORAGE_DIR", "/data/artifacts"),
        "/data/artifacts",
        "/app/data/artifacts",
    ]
    seen_roots: set[str] = set()
    for root in candidate_roots:
        if not root:
            continue
        artifact_root = os.path.abspath(root)
        if artifact_root in seen_roots:
            continue
        seen_roots.add(artifact_root)

        abs_path = os.path.abspath(os.path.join(artifact_root, rel_path))
        # Prevent path traversal; must remain under artifact root.
        if not (abs_path + os.sep).startswith(artifact_root + os.sep) and abs_path != artifact_root:
            continue
        if os.path.isfile(abs_path):
            return (abs_path, rel_path)

    return (None, rel_path)


_PREVIEW_IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_PREVIEW_HTML_EXTS = (".html", ".htm", ".svg")
_BROWSER_RUNNER_URL = os.getenv("HARVIS_BROWSER_RUNNER_URL", "http://browser-runner:8765")


def _looks_base64(s: str) -> bool:
    s = (s or "").strip()
    if len(s) < 16 or len(s) % 4 != 0:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", s))


async def _browser_render_html_to_png(html: str, out_path: str) -> bool:
    """Render an HTML/SVG string to a PNG via the headless browser-runner service
    (using a data: URL, since browser-runner can't read the artifact volume).
    Returns True on success."""
    import base64 as _b64
    try:
        b64 = _b64.b64encode((html or "").encode("utf-8")).decode()
        data_url = f"data:text/html;charset=utf-8;base64,{b64}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            s = await client.post(f"{_BROWSER_RUNNER_URL}/session", json={"headless": True})
            if s.status_code != 200:
                return False
            sid = (s.json() or {}).get("sessionId") or (s.json() or {}).get("id")
            if not sid:
                return False
            try:
                await client.post(f"{_BROWSER_RUNNER_URL}/navigate", json={"sessionId": sid, "url": data_url})
                await asyncio.sleep(0.7)  # let it paint
                shot = await client.post(f"{_BROWSER_RUNNER_URL}/screenshot", json={"sessionId": sid})
                png_b64 = (shot.json() or {}).get("pngBase64") or ""
                if not png_b64:
                    return False
                with open(out_path, "wb") as f:
                    f.write(_b64.b64decode(png_b64))
                return True
            finally:
                try:
                    await client.post(f"{_BROWSER_RUNNER_URL}/close", json={"sessionId": sid})
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("browser-runner render failed: %s", exc)
        return False


async def _render_preview_screenshot(request: Request, workspace_id: str) -> "tuple[str | None, str | None]":
    """If a completed run produced a previewable artifact, return (png_abs_path,
    label) of an image to post to Discord — an image artifact is used directly; an
    HTML/SVG artifact is rendered to PNG via the browser-runner. Returns (None, None)
    when nothing previewable (e.g. only code/diff/text). Never raises."""
    import base64 as _b64
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return (None, None)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT path, content FROM workspace_artifacts "
                "WHERE workspace_id = $1 AND artifact_type = 'file' "
                "ORDER BY created_at DESC",
                workspace_id,
            )
    except Exception as exc:
        logger.debug("preview screenshot: artifact query failed: %s", exc)
        return (None, None)
    img_row = None
    html_row = None
    _secret_hints = (".env", "credential", "secret", ".key", ".pem", "id_rsa", "id_ed25519", "apikey", "api_key")
    for r in rows:
        p = (r["path"] or "").lower()
        if any(h in p for h in _secret_hints):
            continue  # never render/post a secret-looking file to a Discord channel
        if img_row is None and p.endswith(_PREVIEW_IMG_EXTS):
            img_row = r
        elif html_row is None and p.endswith(_PREVIEW_HTML_EXTS):
            html_row = r
    out_dir = "/data/artifacts/discord-previews"
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        out_dir = "/tmp"
    # Prefer a direct image artifact (no render needed).
    if img_row is not None:
        try:
            content = img_row["content"] or ""
            data = _b64.b64decode(content) if _looks_base64(content) else content.encode("utf-8", "ignore")
            ext = os.path.splitext(img_row["path"])[1] or ".png"
            out = os.path.join(out_dir, f"{workspace_id}-preview{ext}")
            with open(out, "wb") as f:
                f.write(data)
            return (out, os.path.basename(img_row["path"]))
        except Exception as exc:
            logger.debug("preview image decode failed: %s", exc)
    # Else render an HTML/SVG artifact via the headless browser.
    if html_row is not None:
        out = os.path.join(out_dir, f"{workspace_id}-preview.png")
        if await _browser_render_html_to_png(html_row["content"] or "", out):
            return (out, os.path.basename(html_row["path"]))
    return (None, None)


async def _best_workspace_message(
    *, request: Request, workspace_id: str, final_summary: str | None
) -> str:
    """
    Build the full response text from workspace events.

    Strategy:
      1) Concatenate ALL token events in order (the actual LLM response stream).
      2) If no tokens, fall back to final_summary from workspace_runs.
      3) If neither, try tool_result outputs or log messages.
      4) Last resort: "Done."
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return (final_summary or "Done.").strip()

    # Fetch all events in forward order to reconstruct full response
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_type, payload
            FROM workspace_events
            WHERE workspace_id = $1
            ORDER BY seq ASC
            """,
            workspace_id,
        )

    token_parts: list[str] = []
    latest_detail: str | None = None
    latest_log: str | None = None
    done_summary: str | None = None
    validator_replaced: bool = False

    for row in rows:
        event_type = row.get("event_type")
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            try:
                payload = json.loads(str(payload))
            except Exception:
                payload = {}

        if event_type == "token":
            content = str(payload.get("content") or "")
            if content:
                token_parts.append(content)

        elif event_type == "done":
            s = str(payload.get("summary") or "").strip()
            if s:
                done_summary = s
            if payload.get("_validator_replaced"):
                validator_replaced = True

        elif event_type == "tool_result" and latest_detail is None:
            output = str(payload.get("output") or "")
            detail = _extract_detail_from_text(output)
            if detail:
                latest_detail = detail

        elif event_type == "log" and latest_log is None:
            msg = str(payload.get("message") or "").strip()
            if msg:
                detail = _extract_detail_from_text(msg)
                latest_log = detail or msg

    # If the validator replaced the summary (fabrication caught), the done
    # event's rewritten summary is the ONLY safe text. The streamed tokens
    # contain the original fabrication — sending those to Discord would
    # bypass the validator entirely.
    if validator_replaced and done_summary:
        return done_summary

    # Prefer the full concatenated token stream (the actual LLM output)
    full_tokens = "".join(token_parts).strip()
    if full_tokens:
        return full_tokens

    # Fall back to summaries
    if final_summary and final_summary.strip():
        return final_summary.strip()
    if done_summary:
        return done_summary

    return (latest_detail or latest_log or "Done.").strip()


async def _send_long_message(
    channel: discord.abc.Messageable,
    text: str,
    *,
    file: discord.File | None = None,
) -> None:
    """Send text to Discord, splitting into multiple messages if > 2000 chars.
    The file attachment (if any) is sent with the first chunk."""
    if not text:
        text = "Done."
    limit = 1990  # small margin under 2000
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a newline near the limit
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit  # no good newline, hard split
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    for i, chunk in enumerate(chunks):
        kwargs: dict = {"content": chunk}
        if i == 0 and file is not None:
            kwargs["file"] = file
        await channel.send(**kwargs)


# ═════════════════════════════════════════════════════════════════════════════
# ── /harvis-code — dedicated coding channel (slash-command driven) ───────────
#
# Reuses the EXISTING VibeCode session backend (workspace_router endpoint
# functions: create session / turn / diff / create-pr / approve-deny) — no
# agent-loop reimplementation here, only Discord plumbing.
#
# DORMANT unless HARVIS_CODE_CHANNEL_ID is set: the command group is never
# added to the tree and no component handler is installed, so the bot behaves
# EXACTLY as before. Config is read once at import; invalid values degrade to
# "not configured" (never crash startup).
#
# User mapping is the REAL per-Discord-user mapping (messaging_platforms via
# plugins.messaging.dispatcher.resolve_user_id) — NOT DISCORD_DEFAULT_USER_ID.
# Unmapped users get a refusal, never a default identity.


def _code_env_int(name: str) -> int:
    try:
        return int((os.getenv(name, "") or "").strip() or "0")
    except ValueError:
        logger.warning("harvis-code: %s is not an integer — treating as unset", name)
        return 0


_CODE_CHANNEL_ID = _code_env_int("HARVIS_CODE_CHANNEL_ID")
_CODE_GUILD_ID = _code_env_int("HARVIS_CODE_GUILD_ID")
_CODE_APPROVER_ROLE_IDS = _parse_int_set(os.getenv("HARVIS_CODE_APPROVER_ROLE_IDS", ""))

_CODE_LINK_HINT = (
    "Your Discord account isn't linked to a Harvis user yet. Link it in Harvis "
    "(messaging platform mapping) so I know whose repos and credentials to use — "
    "I won't run coding sessions for unlinked accounts."
)

# thread id → vibecode session id. In-memory cache only; the session id is ALSO
# embedded in the thread name ("… [xxxxxxxx-xxx]") so the mapping survives a
# backend restart (recovered lazily by _code_session_for_thread).
_CODE_SESSION_BY_THREAD: dict[int, str] = {}
# Vibecode session ids are str(uuid4())[:12] → 8 hex chars, '-', 3 hex chars.
_CODE_SESSION_ID_RE = re.compile(r"\[([0-9a-f]{8}-[0-9a-f]{3})\]\s*$")
_CODE_GITHUB_REPO_RE = re.compile(
    r"^(?:https?://github\.com/)?([\w.\-]+)/([\w.\-]+?)(?:\.git)?(?:#([\w./\-]+))?/?$"
)


def _code_channel_kind(channel) -> str:
    """'channel' (the configured #harvis-code), 'thread' (a thread under it), or ''."""
    if channel is None or not _CODE_CHANNEL_ID:
        return ""
    if getattr(channel, "id", None) == _CODE_CHANNEL_ID:
        return "channel"
    if isinstance(channel, discord.Thread) and getattr(channel, "parent_id", None) == _CODE_CHANNEL_ID:
        return "thread"
    return ""


def _code_session_for_thread(channel) -> str | None:
    """Resolve the vibecode session bound to a Discord thread — memory first,
    then the '[<session-id>]' suffix in the thread name (restart-survivable)."""
    tid = int(getattr(channel, "id", 0) or 0)
    sid = _CODE_SESSION_BY_THREAD.get(tid)
    if sid:
        return sid
    m = _CODE_SESSION_ID_RE.search(getattr(channel, "name", "") or "")
    if m:
        sid = m.group(1)
        if tid:
            _CODE_SESSION_BY_THREAD[tid] = sid
        return sid
    return None


def _code_is_approver(user) -> bool:
    """True when no approver roles are configured (everyone may approve), or the
    member holds one of HARVIS_CODE_APPROVER_ROLE_IDS. Gates Approve + PR only."""
    if not _CODE_APPROVER_ROLE_IDS:
        return True
    roles = getattr(user, "roles", None) or []
    return any(int(getattr(r, "id", 0) or 0) in _CODE_APPROVER_ROLE_IDS for r in roles)


async def _code_resolve_harvis_user(pool, interaction: discord.Interaction) -> int | None:
    """The REAL Discord-user → Harvis-user mapping (messaging_platforms). Returns
    None when unmapped or the DB is unavailable — callers refuse, never default."""
    try:
        from plugins.messaging.dispatcher import resolve_user_id
        from plugins.messaging.types import Platform, SessionSource

        source = SessionSource(
            platform=Platform.DISCORD,
            chat_id=str(getattr(interaction.channel, "id", "") or ""),
            sender_id=str(interaction.user.id),
        )
        return await resolve_user_id(pool, source)
    except Exception as exc:
        logger.warning("harvis-code: user resolution failed for %s: %s", interaction.user.id, exc)
        return None


async def _code_active_run(pool, session_id: str) -> str | None:
    """The session's currently-running turn (workspace_runs row id), if any."""
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT id FROM workspace_runs WHERE session_id = $1 AND status = 'running' "
                "ORDER BY started_at DESC LIMIT 1",
                session_id,
            )
    except Exception as exc:
        logger.warning("harvis-code: active-run lookup failed for %s: %s", session_id, exc)
        return None


def _code_session_create_request(repo: str, base: str | None, perm: str = ""):
    """Parse the /harvis-code start `repo` argument into a VibecodeSessionCreate:
    'owner/repo' (or a github.com URL, optionally '#branch') → GitHub clone;
    an absolute path → allowlisted server repo (allowlist enforced by the endpoint).
    `perm` sets the permission mode (default 'ask'); returns None when unparseable."""
    from workspace.workspace_router import VibecodeSessionCreate

    repo = (repo or "").strip()
    if not repo:
        return None
    _perm = (perm or "").strip().lower()
    _perm = _perm if _perm in ("plan", "ask", "auto-accept", "full-auto") else "ask"
    if repo.startswith("/"):
        return VibecodeSessionCreate(
            repo_path=repo, title=os.path.basename(repo.rstrip("/")) or repo,
            permission_mode=_perm,
        )
    m = _CODE_GITHUB_REPO_RE.match(repo)
    if not m:
        return None
    owner, name, frag_branch = m.group(1), m.group(2), m.group(3)
    return VibecodeSessionCreate(
        github_owner=owner,
        github_repo=name,
        github_branch=((base or "").strip() or frag_branch or None),
        title=f"{owner}/{name}",
        permission_mode=_perm,
    )


def _code_controls_view(session_id: str) -> discord.ui.View:
    """Session control row. Buttons are custom_id-routed through on_interaction
    (see _register_harvis_code) so they keep working after a bot restart —
    unlike CancelWorkspaceView, nothing here relies on an in-memory timeout."""
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label="Diff", style=discord.ButtonStyle.secondary, emoji="\U0001f4c4",
        custom_id=f"harviscode:diff:{session_id}",
    ))
    v.add_item(discord.ui.Button(
        label="Commit", style=discord.ButtonStyle.primary, emoji="\U0001f4be",
        custom_id=f"harviscode:commit:{session_id}",
    ))
    v.add_item(discord.ui.Button(
        label="PR", style=discord.ButtonStyle.success, emoji="\U0001f500",
        custom_id=f"harviscode:pr:{session_id}",
    ))
    v.add_item(discord.ui.Button(
        label="Stop", style=discord.ButtonStyle.danger, emoji="⛔",
        custom_id=f"harviscode:stop:{session_id}",
    ))
    return v


def _code_approval_view(run_id: str, action_id: str) -> discord.ui.View:
    """Approve/Deny row for a gated action — custom_id-routed, restart-safe."""
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label="Approve", style=discord.ButtonStyle.success, emoji="✅",
        custom_id=f"harviscode:approve:{run_id}:{action_id}",
    ))
    v.add_item(discord.ui.Button(
        label="Deny", style=discord.ButtonStyle.danger, emoji="\U0001f6ab",
        custom_id=f"harviscode:deny:{run_id}:{action_id}",
    ))
    return v


async def _code_pending_action_poller(app_request: Request, thread, run_id: str) -> None:
    """Watch a running turn for gated actions and surface each as an Approve/Deny
    message in the session thread. Cancelled by the caller when the turn ends."""
    from workspace.orchestration.risk import get_pending_for_run

    posted: set[str] = set()
    try:
        while True:
            await asyncio.sleep(2.0)
            pending = get_pending_for_run(run_id)
            if not pending:
                continue
            aid = str(pending.get("action_id") or "")
            if not aid or aid in posted:
                continue
            posted.add(aid)
            tool = pending.get("tool") or "action"
            args = pending.get("args") or {}
            try:
                args_preview = json.dumps(args)[:180]
            except Exception:
                args_preview = str(args)[:180]
            await thread.send(
                f"⚠️ **Approval needed** — `{tool}` `{args_preview}`",
                view=_code_approval_view(run_id, aid),
            )
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("harvis-code: pending-action poller for %s stopped: %s", run_id, exc)


async def _code_run_turn(
    app_request: Request,
    cfg: DiscordWorkspaceConfig,
    thread,
    uid: int,
    session_id: str,
    brief: str,
) -> None:
    """Run ONE vibecode turn for a code thread: launch via the existing
    /vibecode/session/{id}/turn endpoint function, stream progress into the
    thread (same helper the main bot uses), surface approval gates as buttons,
    then post the final answer + the session control row. Never raises."""
    try:
        from workspace.workspace_router import VibecodeTurnRequest, start_vibecode_turn

        try:
            data = await start_vibecode_turn(
                session_id=session_id,
                req=VibecodeTurnRequest(task_brief=brief),
                request=app_request,
                current_user={"id": uid},
            )
        except HTTPException as exc:
            await thread.send(f"Turn refused: {exc.detail}")
            return
        workspace_id = data["workspace_id"]

        progress_msg = await thread.send(
            f"**Turn `{workspace_id}`**\n⏳ Starting workspace…"
        )
        poller = asyncio.create_task(
            _code_pending_action_poller(app_request, thread, workspace_id),
            name=f"harvis-code-pending-{workspace_id}",
        )
        try:
            status, summary, err = await _wait_with_progress(
                request=app_request,
                workspace_id=workspace_id,
                timeout_s=cfg.max_wait_seconds,
                progress_msg=progress_msg,
                thread=thread,  # agent_message (review-loop) posts land in the thread
            )
        finally:
            poller.cancel()
        try:
            await progress_msg.delete()
        except discord.HTTPException:
            pass

        if status in ("done", "completed"):
            msg = await _best_workspace_message(
                request=app_request, workspace_id=workspace_id, final_summary=summary,
            )
            await _send_long_message(thread, msg)
        elif status == "cancelled":
            await thread.send(f"Turn `{workspace_id}` was cancelled.")
        else:
            await thread.send(
                f"Turn `{workspace_id}` failed: {((err or 'Unknown error'))[:1500]}"
            )
        await thread.send("Session controls:", view=_code_controls_view(session_id))
    except Exception as exc:
        logger.exception("harvis-code: turn on session %s errored: %s", session_id, exc)
        try:
            await thread.send(f"Turn error: {str(exc)[:1500]}")
        except Exception:
            pass


async def _code_session_review_status(pool, session_id: str) -> str:
    """The session's current review_status ('off' when unknown). Best-effort."""
    if pool is None:
        return "off"
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT review_status FROM vibecode_sessions WHERE id = $1", session_id,
            ) or "off"
    except Exception as exc:
        logger.warning("harvis-code: review-status lookup failed for %s: %s", session_id, exc)
        return "off"


async def _code_run_review(
    app_request: Request,
    cfg: DiscordWorkspaceConfig,
    thread,
    uid: int,
    session_id: str,
    mode: str = "thread",
    base: str = "",
    reviewer_ids: list[str] | None = None,
) -> None:
    """Run the OPT-IN agent review conversation (coder ↔ reviewer) for a code
    thread's session: launch via the /vibecode/session/{id}/review endpoint
    function, stream progress + the agents' dialogue into the thread (each
    agent_message becomes a labeled post), surface approval gates as buttons,
    then report the outcome ('agreed' unlocks the PR gate; 'needs_human' asks
    the human to decide). Mirrors _code_run_turn; never raises."""
    try:
        from workspace.workspace_router import VibecodeReviewRequest, start_vibecode_review

        try:
            data = await start_vibecode_review(
                session_id=session_id,
                req=VibecodeReviewRequest(mode=mode, base=base, reviewer_ids=reviewer_ids or []),
                request=app_request,
                current_user={"id": uid},
            )
        except HTTPException as exc:
            await thread.send(f"Review refused: {exc.detail}")
            return
        workspace_id = data["workspace_id"]

        progress_msg = await thread.send(
            f"**Review `{workspace_id}`**\n\U0001f50e Coder and reviewer are going "
            "over the session's changes…"
        )
        poller = asyncio.create_task(
            _code_pending_action_poller(app_request, thread, workspace_id),
            name=f"harvis-code-review-pending-{workspace_id}",
        )
        try:
            status, summary, err = await _wait_with_progress(
                request=app_request,
                workspace_id=workspace_id,
                timeout_s=cfg.max_wait_seconds,
                progress_msg=progress_msg,
                thread=thread,  # the coder↔reviewer dialogue posts land here
            )
        finally:
            poller.cancel()
        try:
            await progress_msg.delete()
        except discord.HTTPException:
            pass

        pool = getattr(app_request.app.state, "pg_pool", None)
        review_status = await _code_session_review_status(pool, session_id)
        if status in ("done", "completed"):
            if review_status == "agreed":
                await thread.send(
                    f"✅ **Agents agreed** — {(summary or 'the reviewer approved the changes.')[:1500]}\n"
                    "The PR gate is unlocked."
                )
            else:
                await thread.send(
                    f"\U0001f9d1‍⚖️ **Needs a human** — {(summary or 'no agreement was reached.')[:1500]}\n"
                    "Keep iterating (`/harvis-code prompt`, then `/harvis-code review` "
                    "again), or open the PR anyway with the Override button when the PR "
                    "gate refuses."
                )
        elif status == "cancelled":
            await thread.send(f"Review `{workspace_id}` was cancelled.")
        else:
            await thread.send(
                f"Review `{workspace_id}` failed: {((err or 'Unknown error'))[:1500]}\n"
                "Review status is `needs a human` — re-run it, or override on PR."
            )
        await thread.send("Session controls:", view=_code_controls_view(session_id))
    except Exception as exc:
        logger.exception("harvis-code: review on session %s errored: %s", session_id, exc)
        try:
            await thread.send(f"Review error: {str(exc)[:1500]}")
        except Exception:
            pass


async def _code_send_diff(interaction: discord.Interaction, app_request: Request, uid: int, session_id: str) -> None:
    """Post the session's accumulated diff (file list + fenced, chunked, capped).
    Caller must have deferred the interaction already."""
    from workspace.workspace_router import get_vibecode_session_diff

    data = await get_vibecode_session_diff(
        session_id=session_id, request=app_request, current_user={"id": uid},
    )
    files = data.get("files") or []
    diff = (data.get("diff") or "").strip()
    if diff == "(no changes)":
        diff = ""
    if not diff and not files:
        await interaction.followup.send("No changes yet in this session.")
        return
    header_lines = [f"**Changes** ({len(files)} file(s))"]
    for f in files[:20]:
        header_lines.append(f"`{(f.get('status') or 'M')}` {f.get('path') or '?'}")
    if len(files) > 20:
        header_lines.append(f"… and {len(files) - 20} more")
    await interaction.followup.send("\n".join(header_lines)[:1990])
    chunk_size, max_chunks = 1800, 3
    for i in range(0, min(len(diff), chunk_size * max_chunks), chunk_size):
        await interaction.channel.send(f"```diff\n{diff[i:i + chunk_size]}\n```")
    if len(diff) > chunk_size * max_chunks:
        await interaction.channel.send(
            "… diff truncated — open the session in the Harvis Build UI for the full view."
        )


async def _code_commit_session(app_request: Request, uid: int, session_id: str, message: str) -> str:
    """Local-only commit of the session workspace on its WORK branch — the same
    _git_commit_workspace policy the agent tool uses (refuses main/master, never
    pushes). Returns a user-facing note."""
    if not message:
        return "Commit message is required."
    pool = getattr(app_request.app.state, "pg_pool", None)
    from workspace.workspace_router import _vibecode_session_row

    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        return "Session not found (or it isn't yours)."
    wp = dict(sess).get("workspace_path")
    if not wp or not os.path.isdir(wp):
        return "The session workspace is no longer available."
    from workspace.orchestration.tools import _git_commit_workspace

    out, ok = await _git_commit_workspace(wp, message)
    if not ok:
        return f"Commit failed: {out[:500]}"
    try:
        data = json.loads(out)
    except Exception:
        data = {}
    if data.get("committed"):
        return f"\U0001f4be Committed `{data.get('sha')}` — {message}"
    return f"Nothing to commit ({data.get('message') or 'no changes'})."


# Title typed into the PR modal, remembered per session so the Override button can
# reuse it (in-memory only — after a restart the override falls back to the default
# title, which is harmless).
_CODE_PENDING_PR_TITLE: dict[str, str] = {}


def _code_pr_override_view(session_id: str) -> discord.ui.View:
    """Shown when the agent-review gate refuses a PR: the human's explicit choices —
    run (another) review, or override the gate. custom_id-routed, restart-safe."""
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label="Run agent review", style=discord.ButtonStyle.primary, emoji="\U0001f50e",
        custom_id=f"harviscode:review:{session_id}",
    ))
    v.add_item(discord.ui.Button(
        label="Override — open PR anyway", style=discord.ButtonStyle.danger, emoji="⚠️",
        custom_id=f"harviscode:proverride:{session_id}",
    ))
    return v


async def _code_create_pr(
    app_request: Request, uid: int, session_id: str, title: str, *, override: bool = False,
) -> tuple[str, bool]:
    """HUMAN-ONLY PR from the session's accumulated diff — the existing endpoint
    function (refuses main/master head, needs a connected GitHub token). Returns
    (note, review_gated): review_gated=True means the agent-review gate refused
    (409) and the caller should offer the Override / Run-review buttons."""
    from workspace.workspace_router import VibecodeCreatePrRequest, create_pr_for_vibecode_session

    try:
        result = await create_pr_for_vibecode_session(
            session_id=session_id,
            req=VibecodeCreatePrRequest(title=(title or None), override=override),
            request=app_request,
            current_user={"id": uid},
        )
    except HTTPException as exc:
        if exc.status_code == 409 and "review" in str(exc.detail).lower():
            # Agent-review gate — remember the typed title so Override reuses it.
            _CODE_PENDING_PR_TITLE[session_id] = title or ""
            return (f"\U0001f512 {exc.detail}", True)
        return (f"PR failed: {exc.detail}", False)
    return (
        f"\U0001f500 PR opened: {result.get('pr_url')} "
        f"(branch `{result.get('branch')}` → `{result.get('base')}`)"
        + (" — review gate overridden by you." if override else ""),
        False,
    )


async def _code_stop_active_run(app_request: Request, uid: int, session_id: str, *, actor: str) -> str:
    """Cancel the session's running turn (same cancel path as everything else)."""
    pool = getattr(app_request.app.state, "pg_pool", None)
    from workspace.workspace_router import _vibecode_session_row

    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        return "Session not found (or it isn't yours)."
    run_id = await _code_active_run(pool, session_id)
    if not run_id:
        return "No turn is running on this session."
    try:
        result = await cancel_workspace_internal(run_id, audit_actor=actor)
    except Exception as exc:
        return f"Cancel failed: {str(exc)[:300]}"
    if result.get("status") == "cancelled":
        return f"⛔ Stopped turn `{run_id}`."
    return f"Turn `{run_id}` is already {result.get('current', 'done')}."


def _register_harvis_code(
    client: discord.Client,
    tree: app_commands.CommandTree,
    app_request: Request,
    cfg: DiscordWorkspaceConfig,
) -> None:
    """Install the /harvis-code command group + the persistent component router.
    Called ONLY when HARVIS_CODE_CHANNEL_ID is configured."""

    async def _thread_context(interaction: discord.Interaction) -> tuple[str | None, int | None]:
        """(session_id, harvis_uid) for a command inside a code thread — or
        (None, None) after sending the appropriate ephemeral refusal."""
        if _code_channel_kind(interaction.channel) != "thread":
            await interaction.response.send_message(
                f"Use this inside a `/harvis-code start` thread in <#{_CODE_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return None, None
        sid = _code_session_for_thread(interaction.channel)
        if not sid:
            await interaction.response.send_message(
                "This thread isn't linked to a coding session — start one with "
                "`/harvis-code start` in the code channel.",
                ephemeral=True,
            )
            return None, None
        pool = getattr(app_request.app.state, "pg_pool", None)
        if pool is None:
            await interaction.response.send_message(
                "Backend database isn't ready — try again shortly.", ephemeral=True,
            )
            return None, None
        uid = await _code_resolve_harvis_user(pool, interaction)
        if uid is None:
            await interaction.response.send_message(_CODE_LINK_HINT, ephemeral=True)
            return None, None
        return sid, uid

    group = app_commands.Group(
        name="harvis-code",
        description="Coding sessions in the code channel (repo → thread → prompt/diff/commit/PR)",
    )

    # ── Autocomplete: let the user PICK from DETECTED repos/branches instead of
    # typing blind and hoping (or getting denied). Best-effort + fast (Discord
    # times out at 3s) — every callback fails to an empty list, never errors. ──
    async def _ac_token(interaction):
        pool = getattr(app_request.app.state, "pg_pool", None)
        if pool is None:
            return None
        uid = await _code_resolve_harvis_user(pool, interaction)
        if uid is None:
            return None
        try:
            from workspace.repo_manager import _get_github_token
            return await _get_github_token(pool, uid)
        except Exception:
            return None

    def _ac_repo_full(raw: str) -> str:
        s = (raw or "").strip().split("#", 1)[0].strip()
        if not s:
            return ""
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", s)
        if m:
            return m.group(1)
        return s if s.count("/") == 1 else ""

    async def _ac_gh_get(interaction, url):
        tok = await _ac_token(interaction)
        if not tok:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.5) as _c:
                r = await _c.get(url, headers={"Authorization": f"Bearer {tok}",
                                               "Accept": "application/vnd.github+json"})
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def _ac_repos(interaction: discord.Interaction, current: str):
        data = await _ac_gh_get(interaction, "https://api.github.com/user/repos?per_page=100&sort=updated")
        if not isinstance(data, list):
            return []
        cur = (current or "").lower()
        names = [x.get("full_name") for x in data if isinstance(x, dict) and x.get("full_name")]
        return [app_commands.Choice(name=n, value=n) for n in names if cur in n.lower()][:25]

    async def _ac_branches(interaction, current, full):
        if not full or "/" not in full:
            return []
        owner, repo = full.split("/", 1)
        data = await _ac_gh_get(interaction, f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100")
        if not isinstance(data, list):
            return []
        cur = (current or "").lower()
        brs = [b.get("name") for b in data if isinstance(b, dict) and b.get("name")]
        return [app_commands.Choice(name=b, value=b) for b in brs if cur in b.lower()][:25]

    async def _ac_start_base(interaction: discord.Interaction, current: str):
        raw = getattr(getattr(interaction, "namespace", None), "repo", "") or ""
        return await _ac_branches(interaction, current, _ac_repo_full(raw))

    async def _ac_review_base(interaction: discord.Interaction, current: str):
        try:
            pool = getattr(app_request.app.state, "pg_pool", None)
            sid = _code_session_for_thread(interaction.channel)
            if not (pool and sid):
                return []
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT workspace_path FROM vibecode_sessions WHERE id=$1", sid)
            if not row or not row["workspace_path"]:
                return []
            from workspace.orchestration.review_github import resolve_owner_repo
            owner, repo = await resolve_owner_repo(row["workspace_path"])
            if not owner:
                return []
            return await _ac_branches(interaction, current, f"{owner}/{repo}")
        except Exception:
            return []

    @group.command(name="start", description="Start a coding session on a repo (creates a thread)")
    @app_commands.describe(
        repo="Start typing to pick one of your GitHub repos (or paste owner/repo, a URL, or a server path)",
        base="Start typing to pick a branch of the chosen repo (default: the repo's default)",
        task="Optional first task to run immediately",
        perm="Permission mode (default: Ask). Auto won't prompt per action — the diff/PR is the gate.",
    )
    @app_commands.choices(
        perm=[
            app_commands.Choice(name="Ask — approve each action", value="ask"),
            app_commands.Choice(name="Auto — auto-accept, review the diff", value="auto-accept"),
            app_commands.Choice(name="Full-auto — no prompts at all", value="full-auto"),
            app_commands.Choice(name="Plan — read-only, drafts a plan", value="plan"),
        ]
    )
    @app_commands.autocomplete(repo=_ac_repos, base=_ac_start_base)
    async def code_start(
        interaction: discord.Interaction,
        repo: str,
        base: str | None = None,
        task: str | None = None,
        perm: app_commands.Choice[str] | None = None,
    ):
        if _code_channel_kind(interaction.channel) != "channel":
            await interaction.response.send_message(
                f"Use this in <#{_CODE_CHANNEL_ID}> (not inside a thread).", ephemeral=True,
            )
            return
        pool = getattr(app_request.app.state, "pg_pool", None)
        if pool is None:
            await interaction.response.send_message(
                "Backend database isn't ready — try again shortly.", ephemeral=True,
            )
            return
        uid = await _code_resolve_harvis_user(pool, interaction)
        if uid is None:
            await interaction.response.send_message(_CODE_LINK_HINT, ephemeral=True)
            return
        req = _code_session_create_request(repo, base, perm.value if perm else "")
        if req is None:
            await interaction.response.send_message(
                "Couldn't parse `repo` — use `owner/repo`, a github.com URL, or an absolute server path.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        from workspace.workspace_router import create_vibecode_session
        try:
            data = await create_vibecode_session(
                req=req, request=app_request, current_user={"id": uid},
            )
        except HTTPException as exc:
            await interaction.followup.send(f"Session refused: {exc.detail}")
            return
        sid = data["id"]
        label = req.github_repo or os.path.basename((req.repo_path or "repo").rstrip("/"))
        await interaction.followup.send(
            f"**Coding session `{sid}`** on `{repo}`"
            + (f" (base `{base}`)" if base else "")
            + f"\nMode: `{data.get('isolation_mode')}` · permission `{data.get('permission_mode')}`"
        )
        try:
            msg = await interaction.original_response()
            thread = await msg.create_thread(
                name=f"{label} [{sid}]"[:100], auto_archive_duration=1440,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"Session `{sid}` was created but I couldn't open a thread for it "
                f"({str(exc)[:200]}) — check my Create Threads permission."
            )
            return
        _CODE_SESSION_BY_THREAD[thread.id] = sid
        # Persist the Discord origin so the web Build UI can show a "Discord session
        # online" chip while this session has a running turn (see /active-discord).
        try:
            _pool = getattr(app_request.app.state, "pg_pool", None)
            if _pool is not None:
                async with _pool.acquire() as _conn:
                    await _conn.execute(
                        "UPDATE vibecode_sessions SET discord_channel_id=$1 WHERE id=$2",
                        str(thread.id), sid,
                    )
        except Exception:
            logger.warning("harvis-code: couldn't mark session %s discord-launched", sid, exc_info=True)
        await thread.send(
            "Session ready — use `/harvis-code prompt` here for follow-ups.",
            view=_code_controls_view(sid),
        )
        if task and task.strip():
            asyncio.create_task(
                _code_run_turn(app_request, cfg, thread, uid, sid, task.strip()),
                name=f"harvis-code-turn-{sid}",
            )

    @group.command(name="set-perm", description="Set this session's permission mode (Auto = don't prompt per action)")
    @app_commands.describe(mode="How much the agent does without asking")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Ask — approve each action", value="ask"),
            app_commands.Choice(name="Auto — auto-accept, review the diff", value="auto-accept"),
            app_commands.Choice(name="Full-auto — no prompts at all", value="full-auto"),
            app_commands.Choice(name="Plan — read-only, drafts a plan", value="plan"),
        ]
    )
    async def code_set_perm(
        interaction: discord.Interaction, mode: app_commands.Choice[str]
    ):
        pool = getattr(app_request.app.state, "pg_pool", None)
        if pool is None:
            await interaction.response.send_message(
                "Backend database isn't ready — try again shortly.", ephemeral=True,
            )
            return
        session_id = _code_session_for_thread(interaction.channel)
        if not session_id:
            await interaction.response.send_message(
                "Use this **inside a `/harvis-code` session thread**.", ephemeral=True,
            )
            return
        uid = await _code_resolve_harvis_user(pool, interaction)
        if uid is None:
            await interaction.response.send_message(_CODE_LINK_HINT, ephemeral=True)
            return
        _mode = mode.value if mode.value in ("plan", "ask", "auto-accept", "full-auto") else "ask"
        try:
            async with pool.acquire() as conn:
                res = await conn.execute(
                    "UPDATE vibecode_sessions SET permission_mode=$1, updated_at=NOW() "
                    "WHERE id=$2 AND user_id=$3",
                    _mode, session_id, uid,
                )
        except Exception as exc:
            await interaction.response.send_message(
                f"Couldn't update the permission mode: {str(exc)[:200]}", ephemeral=True,
            )
            return
        if isinstance(res, str) and res.rsplit(" ", 1)[-1] == "0":
            await interaction.response.send_message(
                "This session isn't yours (or wasn't found).", ephemeral=True,
            )
            return
        _label = {
            "ask": "Ask", "auto-accept": "Auto (auto-accept)",
            "full-auto": "Full-auto", "plan": "Plan (read-only)",
        }.get(_mode, _mode)
        _extra = (
            " The agent works on a clone; the diff/PR is still your review gate."
            if _mode in ("auto-accept", "full-auto") else ""
        )
        await interaction.response.send_message(
            f"Permission mode set to **{_label}** — applies to the next turn.{_extra}"
        )

    @group.command(name="prompt", description="Send the next coding instruction to this session")
    @app_commands.describe(text="What the agent should do next")
    async def code_prompt(interaction: discord.Interaction, text: str):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        pool = getattr(app_request.app.state, "pg_pool", None)
        active = await _code_active_run(pool, sid)
        if active:
            await interaction.response.send_message(
                f"Turn `{active}` is still running — wait for it or `/harvis-code stop` first.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"\U0001f6e0️ Queued: {text[:150]}")
        asyncio.create_task(
            _code_run_turn(app_request, cfg, interaction.channel, uid, sid, text.strip()),
            name=f"harvis-code-turn-{sid}",
        )

    @group.command(name="tests", description="Run the project's test suite in this session")
    async def code_tests(interaction: discord.Interaction):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        pool = getattr(app_request.app.state, "pg_pool", None)
        active = await _code_active_run(pool, sid)
        if active:
            await interaction.response.send_message(
                f"Turn `{active}` is still running — wait for it or `/harvis-code stop` first.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("\U0001f9ea Running the test suite…")
        brief = (
            "Run this project's test suite using the run_tests tool (or the standard test "
            "command for this repo) and report the results: pass/fail counts and details of "
            "any failures. Do not modify any files."
        )
        asyncio.create_task(
            _code_run_turn(app_request, cfg, interaction.channel, uid, sid, brief),
            name=f"harvis-code-tests-{sid}",
        )

    @group.command(name="status", description="Status of this thread's session (or your recent sessions)")
    async def code_status(interaction: discord.Interaction):
        kind = _code_channel_kind(interaction.channel)
        if not kind:
            await interaction.response.send_message(
                f"Use this in <#{_CODE_CHANNEL_ID}> or one of its session threads.", ephemeral=True,
            )
            return
        pool = getattr(app_request.app.state, "pg_pool", None)
        if pool is None:
            await interaction.response.send_message(
                "Backend database isn't ready — try again shortly.", ephemeral=True,
            )
            return
        uid = await _code_resolve_harvis_user(pool, interaction)
        if uid is None:
            await interaction.response.send_message(_CODE_LINK_HINT, ephemeral=True)
            return
        if kind == "thread":
            sid = _code_session_for_thread(interaction.channel)
            if not sid:
                await interaction.response.send_message(
                    "This thread isn't linked to a coding session.", ephemeral=True,
                )
                return
            from workspace.workspace_router import _vibecode_session_row
            sess = await _vibecode_session_row(pool, sid, uid)
            if not sess:
                await interaction.response.send_message(
                    "Session not found (or it isn't yours).", ephemeral=True,
                )
                return
            s = dict(sess)
            run_id = await _code_active_run(pool, sid)
            await interaction.response.send_message(
                f"**Session `{sid}`** — {s.get('title') or 'untitled'}\n"
                f"State: `{s.get('lifecycle') or s.get('status')}`"
                + (f" · running turn `{run_id}`" if run_id else "")
                + f"\nMode: `{s.get('isolation_mode')}` · permission `{s.get('permission_mode')}`\n"
                f"Branch: `{s.get('work_branch') or '-'}` (base `{s.get('base_branch') or '-'}`)"
            )
            return
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, title, lifecycle, status FROM vibecode_sessions "
                "WHERE user_id = $1 AND status != 'deleted' ORDER BY updated_at DESC LIMIT 5",
                uid,
            )
        if not rows:
            await interaction.response.send_message(
                "No coding sessions yet — start one with `/harvis-code start`.",
            )
            return
        lines = ["**Your recent coding sessions:**"] + [
            f"• `{r['id']}` — {r['title'] or 'untitled'} (`{r['lifecycle'] or r['status']}`)"
            for r in rows
        ]
        await interaction.response.send_message("\n".join(lines)[:1990])

    @group.command(name="diff", description="Show this session's accumulated diff")
    async def code_diff(interaction: discord.Interaction):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        await interaction.response.defer(thinking=True)
        try:
            await _code_send_diff(interaction, app_request, uid, sid)
        except HTTPException as exc:
            await interaction.followup.send(f"Diff failed: {exc.detail}")

    @group.command(name="stop", description="Stop this session's running turn")
    async def code_stop(interaction: discord.Interaction):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        await interaction.response.defer(thinking=True)
        note = await _code_stop_active_run(
            app_request, uid, sid, actor=f"discord:harvis-code:{interaction.user.id}",
        )
        await interaction.followup.send(note)

    @group.command(name="commit", description="Commit the session's changes on its work branch (local only)")
    @app_commands.describe(message="Commit message")
    async def code_commit(interaction: discord.Interaction, message: str):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        await interaction.response.defer(thinking=True)
        note = await _code_commit_session(app_request, uid, sid, message.strip())
        await interaction.followup.send(note)

    @group.command(name="pr", description="Open a GitHub PR from this session's accumulated diff")
    @app_commands.describe(title="PR title")
    async def code_pr(interaction: discord.Interaction, title: str):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        if not _code_is_approver(interaction.user):
            await interaction.response.send_message(
                "You need an approver role to open PRs.", ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        note, review_gated = await _code_create_pr(app_request, uid, sid, title.strip())
        if review_gated:
            # Agent-review gate refused — offer the human's two explicit outs.
            await interaction.followup.send(note, view=_code_pr_override_view(sid))
        else:
            await interaction.followup.send(note)

    @group.command(
        name="review",
        description="Agent code review of this session — coder and reviewer talk it out here",
    )
    async def code_review(interaction: discord.Interaction):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        pool = getattr(app_request.app.state, "pg_pool", None)
        active = await _code_active_run(pool, sid)
        if active:
            await interaction.response.send_message(
                f"Turn `{active}` is still running — wait for it or `/harvis-code stop` first.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "\U0001f50e Starting the agent review — the coder and reviewer will discuss "
            "the session's changes in this thread (up to 5 rounds). PRs stay gated "
            "until they agree (you can always override)."
        )
        asyncio.create_task(
            _code_run_review(app_request, cfg, interaction.channel, uid, sid),
            name=f"harvis-code-review-{sid}",
        )

    async def _ac_subagents(interaction: discord.Interaction, current: str):
        """Autocomplete: the user's ENABLED custom sub-agents (by name) for the review-github
        `reviewers` field. The name(s) are resolved to sub-agent ids server-side."""
        try:
            pool = getattr(app_request.app.state, "pg_pool", None)
            if pool is None:
                return []
            uid = await _code_resolve_harvis_user(pool, interaction)
            if uid is None:
                return []
            from workspace.orchestration.subagent_defs import load_subagents
            cur = (current or "").rsplit(",", 1)[-1].strip().lower()
            names = [(d.get("name") or "").strip() for d in await load_subagents(pool, uid)]
            names = [n for n in names if n and cur in n.lower()][:25]
            return [app_commands.Choice(name=n, value=n) for n in names]
        except Exception:
            return []

    @group.command(
        name="review-github",
        description="Review on a real GitHub draft PR — agents discuss + approve there",
    )
    @app_commands.describe(
        base="Start typing to pick the PR's target branch (default: this session's base)",
        reviewers="Optional: your custom review agent(s) by name, comma-separated. Blank = the built-in reviewer.",
    )
    @app_commands.autocomplete(base=_ac_review_base, reviewers=_ac_subagents)
    async def code_review_github(interaction: discord.Interaction, base: str = "", reviewers: str = ""):
        sid, uid = await _thread_context(interaction)
        if not sid:
            return
        pool = getattr(app_request.app.state, "pg_pool", None)
        active = await _code_active_run(pool, sid)
        if active:
            await interaction.response.send_message(
                f"Turn `{active}` is still running — wait for it or `/harvis-code stop` first.",
                ephemeral=True,
            )
            return
        # Resolve custom reviewer names → sub-agent ids (unknown names are ignored).
        reviewer_ids: list[str] = []
        _names = [n.strip() for n in (reviewers or "").split(",") if n.strip()]
        if _names and pool is not None:
            try:
                from workspace.orchestration.subagent_defs import load_subagents
                _by_name = {(d.get("name") or "").strip().lower(): d["id"] for d in await load_subagents(pool, uid)}
                reviewer_ids = [_by_name[n.lower()] for n in _names if n.lower() in _by_name]
            except Exception:
                reviewer_ids = []
        _base_note = f" targeting `{base}`" if base.strip() else " (targeting this session's base branch)"
        _rev_note = (
            f" with your custom reviewer(s): {', '.join(_names)}" if reviewer_ids
            else (" (couldn't match that reviewer name — using the built-in reviewer)" if _names else "")
        )
        await interaction.response.send_message(
            f"\U0001f419 Opening a draft PR{_base_note} and running the review THERE{_rev_note} — the "
            "coder and reviewer(s) discuss the changes as PR comments, and it's marked ready-for-review "
            "when they agree. You still merge."
        )
        asyncio.create_task(
            _code_run_review(
                app_request, cfg, interaction.channel, uid, sid,
                mode="github", base=base.strip(), reviewer_ids=reviewer_ids or None,
            ),
            name=f"harvis-code-review-github-{sid}",
        )

    if _CODE_GUILD_ID:
        tree.add_command(group, guild=discord.Object(id=_CODE_GUILD_ID))
    else:
        tree.add_command(group)

    # ── Persistent component router ──────────────────────────────────────────
    # Buttons carry all state in their custom_id ("harviscode:<kind>:...") and
    # are routed here from the raw interaction event — so they keep working
    # after a bot restart, with no reliance on the in-memory view store or the
    # 700s View timeout the CancelWorkspaceView uses.
    def _commit_modal(uid: int, session_id: str) -> discord.ui.Modal:
        class _CommitModal(discord.ui.Modal, title="Commit session changes"):
            message = discord.ui.TextInput(
                label="Commit message", placeholder="What changed?", max_length=200,
            )

            async def on_submit(self, modal_itx: discord.Interaction) -> None:
                await modal_itx.response.defer(thinking=True)
                note = await _code_commit_session(
                    app_request, uid, session_id, str(self.message.value or "").strip(),
                )
                await modal_itx.followup.send(note)

        return _CommitModal()

    def _pr_modal(uid: int, session_id: str) -> discord.ui.Modal:
        class _PrModal(discord.ui.Modal, title="Open a GitHub PR"):
            pr_title = discord.ui.TextInput(
                label="PR title", placeholder="Harvis: …", max_length=200,
            )

            async def on_submit(self, modal_itx: discord.Interaction) -> None:
                await modal_itx.response.defer(thinking=True)
                note, review_gated = await _code_create_pr(
                    app_request, uid, session_id, str(self.pr_title.value or "").strip(),
                )
                if review_gated:
                    await modal_itx.followup.send(note, view=_code_pr_override_view(session_id))
                else:
                    await modal_itx.followup.send(note)

        return _PrModal()

    async def _handle_code_component(interaction: discord.Interaction, cid: str) -> None:
        parts = cid.split(":")
        kind = parts[1] if len(parts) > 1 else ""
        pool = getattr(app_request.app.state, "pg_pool", None)
        uid = await _code_resolve_harvis_user(pool, interaction)
        if uid is None:
            await interaction.response.send_message(_CODE_LINK_HINT, ephemeral=True)
            return

        if kind in ("approve", "deny") and len(parts) >= 4:
            run_id = parts[2]
            action_id = ":".join(parts[3:])
            if kind == "approve" and not _code_is_approver(interaction.user):
                await interaction.response.send_message(
                    "You need an approver role to approve actions.", ephemeral=True,
                )
                return
            from workspace.workspace_router import _resolve_run_action
            try:
                result = await _resolve_run_action(
                    app_request, {"id": uid}, run_id, action_id, kind == "approve",
                )
            except HTTPException as exc:
                await interaction.response.send_message(
                    f"Couldn't resolve the action: {exc.detail}", ephemeral=True,
                )
                return
            verdict = "✅ Approved" if kind == "approve" else "\U0001f6ab Denied"
            resumed = " — agent resuming." if result.get("resumed") else "."
            await interaction.response.send_message(
                f"{verdict} by {interaction.user.mention}{resumed}"
            )
            return

        session_id = parts[2] if len(parts) > 2 else ""
        if not session_id:
            await interaction.response.send_message("Malformed button.", ephemeral=True)
            return
        if kind == "diff":
            await interaction.response.defer(thinking=True)
            try:
                await _code_send_diff(interaction, app_request, uid, session_id)
            except HTTPException as exc:
                await interaction.followup.send(f"Diff failed: {exc.detail}")
            return
        if kind == "stop":
            await interaction.response.defer(thinking=True)
            note = await _code_stop_active_run(
                app_request, uid, session_id,
                actor=f"discord:harvis-code:{interaction.user.id}",
            )
            await interaction.followup.send(note)
            return
        if kind == "commit":
            await interaction.response.send_modal(_commit_modal(uid, session_id))
            return
        if kind == "pr":
            if not _code_is_approver(interaction.user):
                await interaction.response.send_message(
                    "You need an approver role to open PRs.", ephemeral=True,
                )
                return
            await interaction.response.send_modal(_pr_modal(uid, session_id))
            return
        if kind == "review":
            # Kick off the agent review conversation (same as /harvis-code review).
            active = await _code_active_run(pool, session_id)
            if active:
                await interaction.response.send_message(
                    f"Turn `{active}` is still running — wait for it or `/harvis-code stop` first.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "\U0001f50e Starting the agent review — coder and reviewer will discuss "
                "the changes in this thread."
            )
            asyncio.create_task(
                _code_run_review(app_request, cfg, interaction.channel, uid, session_id),
                name=f"harvis-code-review-{session_id}",
            )
            return
        if kind == "proverride":
            # Explicit HUMAN bypass of the agent-review PR gate — approver-only,
            # reuses the title typed into the refused PR attempt (if remembered).
            if not _code_is_approver(interaction.user):
                await interaction.response.send_message(
                    "You need an approver role to override the review gate.", ephemeral=True,
                )
                return
            await interaction.response.defer(thinking=True)
            title = _CODE_PENDING_PR_TITLE.pop(session_id, "")
            note, _gated = await _code_create_pr(
                app_request, uid, session_id, title, override=True,
            )
            await interaction.followup.send(note)
            return
        await interaction.response.send_message("Unknown action.", ephemeral=True)

    @client.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        # Only component clicks with our prefix are handled here; slash commands
        # and other views are dispatched by discord.py exactly as before.
        try:
            if interaction.type != discord.InteractionType.component:
                return
            cid = str((interaction.data or {}).get("custom_id") or "")
            if not cid.startswith("harviscode:"):
                return
            await _handle_code_component(interaction, cid)
        except Exception as exc:
            logger.exception("harvis-code: component handler error: %s", exc)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"Error: {str(exc)[:300]}", ephemeral=True,
                    )
            except Exception:
                pass


# ── Native BYO OpenClaw config write-through ────────────────────────────────
#
# When the user picks a model via Discord `/model`, we want the choice to
# propagate to the native OpenClaw gateway's default agent model. OpenClaw
# hot-reloads its config on file change, so a JSON rewrite is enough.
#
# Requires `HOST_OPENCLAW_CONFIG` to be set to a path that is writable from
# inside the backend container (typically a bind mount of
# `~/.openclaw/openclaw.json`). If the env var is unset or the path isn't
# writable, we degrade gracefully — the model still applies to the fast path
# and DB-backed workspace routing.

_HOST_OPENCLAW_CONFIG = os.getenv("HOST_OPENCLAW_CONFIG", "").strip()
_BUNDLED_OPENCLAW_CONFIG = os.getenv(
    "BUNDLED_OPENCLAW_CONFIG",
    "/app/openclaw_config/bundled/openclaw.json",
).strip()
_BUNDLED_OPENCLAW_CONTAINER = os.getenv(
    "BUNDLED_OPENCLAW_CONTAINER", "harvis-openclaw"
).strip()


def _rewrite_openclaw_config_sync(path: str, model: str, provider: str) -> tuple[str, bool]:
    """Set the primary model in an OpenClaw config. Returns (written_ref, changed)."""
    target = f"{provider}/{model}"
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    before = json.dumps(cfg, sort_keys=True)

    agents = cfg.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    default_model = defaults.setdefault("model", {})
    default_model["primary"] = target

    subagents = defaults.get("subagents")
    if isinstance(subagents, dict) and isinstance(subagents.get("model"), str):
        subagents["model"] = target

    agent_list = agents.get("list")
    if isinstance(agent_list, list):
        for entry in agent_list:
            if isinstance(entry, dict):
                entry_model = entry.setdefault("model", {})
                if isinstance(entry_model, dict):
                    entry_model["primary"] = target

    providers = cfg.setdefault("models", {}).setdefault("providers", {})
    prov = providers.get(provider)
    if isinstance(prov, dict):
        # Additive merge — preserve the user's existing models list rather
        # than replacing it with a single-element list. The previous
        # `prov["models"] = [{...}]` form silently truncated BYO configs
        # from "qwen3.5, llama3.1:8b, gpt-oss, gemma4:e4b, gemma4:e2b, ..."
        # down to one entry on every /model call, which made subsequent
        # `/model <other>` selections fail because the chosen model was no
        # longer in the providers list.
        existing = prov.get("models")
        if isinstance(existing, list):
            if not any(
                isinstance(m, dict) and m.get("id") == model
                for m in existing
            ):
                existing.append({"id": model, "name": model})
        else:
            prov["models"] = [{"id": model, "name": model}]

    after = json.dumps(cfg, sort_keys=True)
    if before == after:
        return target, False

    with open(path, "r+", encoding="utf-8") as f:
        f.seek(0)
        f.truncate()
        json.dump(cfg, f, indent=2)
        f.write("\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    return target, True


def _restart_openclaw_container_sync(container: str) -> tuple[bool, str]:
    import subprocess
    try:
        out = subprocess.run(
            ["docker", "restart", container],
            capture_output=True,
            text=True,
            timeout=20,
        )
        ok = out.returncode == 0
        return ok, (out.stdout + out.stderr).strip()[:240]
    except Exception as exc:
        return False, str(exc)[:240]


async def _wait_openclaw_ready(host: str = "openclaw", port: int = 18789, total_s: float = 12.0) -> bool:
    """Poll the bundled OpenClaw gateway port until it accepts TCP, bounded."""
    deadline = time.monotonic() + total_s
    while time.monotonic() < deadline:
        try:
            fut = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(fut, timeout=1.5)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            await asyncio.sleep(0.5)
    return False


def _looks_like_escalation_worthy_failure(
    status: str, summary: str | None, err: str | None
) -> tuple[bool, str]:
    """Return (escalate, reason). Reason is a short label for logging/notice.

    Pure output-side detection: workspace terminal-status errors, plus the
    fabrication banners the hash/CTF validators inject when a model narrates
    tool calls instead of emitting them. Never inspects the task brief.
    """
    if status == "error":
        return True, "workspace_error"
    text = ((summary or "") + " " + (err or "")).lower()
    for pat in _ESCALATION_FAILURE_PATTERNS:
        if pat in text:
            return True, pat[:48]
    return False, ""


async def _apply_model_to_native_openclaw(model: str) -> str:
    """Rewrite every reachable OpenClaw config (host BYO + bundled) so the
    native gateway picks up the current global/user model. Returns a short
    human-readable note for the Discord reply.

    The bundled config is authoritative for the in-cluster OpenClaw pod at
    ws://openclaw:18789 and uses the `harvis-proxy` provider (backend-fronted
    OpenAI-compat). The host BYO config uses `ollama`.
    """
    targets = [
        ("host-byo", _HOST_OPENCLAW_CONFIG, "ollama", None),
        ("bundled", _BUNDLED_OPENCLAW_CONFIG, "harvis-proxy", _BUNDLED_OPENCLAW_CONTAINER),
    ]
    notes: list[str] = []
    for label, path, provider, container in targets:
        if not path or not os.path.exists(path) or not os.access(path, os.W_OK):
            continue
        try:
            written, changed = await asyncio.to_thread(
                _rewrite_openclaw_config_sync, path, model, provider
            )
            logger.info(
                "Rewrote %s OpenClaw default model → %s (%s, changed=%s)",
                label, written, path, changed,
            )
            if changed and container:
                ok, detail = await asyncio.to_thread(
                    _restart_openclaw_container_sync, container
                )
                ready = False
                if ok:
                    ready = await _wait_openclaw_ready()
                notes.append(
                    f"{label}→`{written}` (restart {'ok' if ok else 'failed: ' + detail}"
                    f"{', ready' if ready else (', not-ready' if ok else '')})"
                )
            else:
                notes.append(f"{label}→`{written}`" + ("" if changed else " (unchanged)"))
        except Exception as exc:
            logger.warning("Failed to rewrite %s OpenClaw config at %s: %s", label, path, exc)
            notes.append(f"{label} error: {str(exc)[:80]}")
    if not notes:
        return "_(no OpenClaw config files writable — applied to fast-path + workspace routing only)_"
    return "_(propagated to native OpenClaw → " + ", ".join(notes) + ")_"


async def _persist_model_selection(
    new_model: str,
    cfg: DiscordWorkspaceConfig,
    pool,
    ollama_url: str,
) -> str:
    """Apply a model switch across all three stores (process global, DB, native
    OpenClaw config) and return a user-visible confirmation message."""
    global _model_override
    _model_override = new_model
    _model_pref_cache.clear()
    logger.info("Discord model switched to: %s", new_model)

    try:
        from owui_compat.cloud_chat import is_cloud_chat_model
        _is_cloud = is_cloud_chat_model(new_model)
    except Exception:
        _is_cloud = False
    # Remember the last LOCAL model the user picked, so a cloud→local fallback
    # restores their actual pick (not a generic default). A cloud pick leaves
    # last_local_model_id unchanged (COALESCE on NULL).
    _last_local = None if _is_cloud else new_model

    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO openclaw_llm_config (
                        user_id, provider_url, api_key_encrypted,
                        model_id, provider_type, is_active, last_local_model_id
                    )
                    VALUES ($1, $2, NULL, $3, 'ollama', TRUE, $4)
                    ON CONFLICT (user_id) DO UPDATE SET
                        provider_url = EXCLUDED.provider_url,
                        model_id = EXCLUDED.model_id,
                        provider_type = 'ollama',
                        is_active = TRUE,
                        last_local_model_id = COALESCE($4, openclaw_llm_config.last_local_model_id),
                        updated_at = NOW()
                    """,
                    cfg.default_user_id,
                    ollama_url,
                    new_model,
                    _last_local,
                )
        except Exception as exc:
            logger.warning("Failed to persist model pref: %s", exc)

    if _is_cloud:
        # Cloud chat models (e.g. Claude) run through the user's verified
        # credential, NOT OpenClaw — skip the native-model sync entirely.
        return (
            f"Switched to **`{new_model}`** (saved). Cloud chat model — "
            "replies run on your connected credential."
        )

    byo_note = await _apply_model_to_native_openclaw(new_model)
    msg = f"Switched to **`{new_model}`** (saved)."
    if byo_note:
        msg += f"\n{byo_note}"
    return msg


async def _persist_engine_selection(
    new_engine: str,
    cfg: "DiscordWorkspaceConfig",
    pool,
    ollama_url: str,
) -> str:
    """Persist the user's workspace ENGINE choice (separate from the model).
    Upserts the `engine` column on openclaw_llm_config without disturbing the
    saved model."""
    eng = (new_engine or "native").strip().lower()
    if eng not in _ENGINE_LABELS:
        opts = ", ".join(f"`{e}`" for e in _ENGINE_LABELS)
        return f"Unknown engine `{new_engine}`. Choose one of: {opts}"
    _model_pref_cache.clear()
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO openclaw_llm_config (
                        user_id, provider_url, api_key_encrypted,
                        model_id, provider_type, is_active, engine
                    )
                    VALUES ($1, $2, NULL, '', 'ollama', TRUE, $3)
                    ON CONFLICT (user_id) DO UPDATE SET
                        engine = EXCLUDED.engine,
                        updated_at = NOW()
                    """,
                    cfg.default_user_id, ollama_url, eng,
                )
        except Exception as exc:
            logger.warning("Failed to persist engine pref: %s", exc)
            return "Couldn't save the engine preference — try again."
    hint = _ENGINE_HINTS.get(eng, "")
    return f"Engine set to **{_ENGINE_LABELS[eng]}** (`{eng}`). {hint}".strip()


async def _persist_orchestrate_pref(
    enabled: bool,
    cfg: "DiscordWorkspaceConfig",
    pool,
    ollama_url: str,
) -> str:
    """Persist the user's multi-agent (orchestrate) opt-in for Discord tasks."""
    _model_pref_cache.clear()
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO openclaw_llm_config (
                        user_id, provider_url, api_key_encrypted,
                        model_id, provider_type, is_active, orchestrate_enabled
                    )
                    VALUES ($1, $2, NULL, '', 'ollama', TRUE, $3)
                    ON CONFLICT (user_id) DO UPDATE SET
                        orchestrate_enabled = EXCLUDED.orchestrate_enabled,
                        updated_at = NOW()
                    """,
                    cfg.default_user_id, ollama_url, enabled,
                )
        except Exception as exc:
            logger.warning("Failed to persist orchestrate pref: %s", exc)
            return "Couldn't save the multi-agent preference — try again."
    if enabled:
        return (
            "**Multi-agent ON.** Complex tasks now fan out to several sub-agents working "
            "in parallel (simple ones stay single-agent). Open a run to watch the agents."
        )
    return "**Multi-agent OFF.** Tasks run with a single agent."


# `@bot set-model <name>` / `@bot set model <name>` / `@bot setmodel` — text
# command alternative to the `/model` slash command. Also accepts `list` and a
# bare form (no arg) which prints the current model + available list.
_SET_MODEL_RE = re.compile(r"^\s*set[-_ ]?model(?:\s+(.+?))?\s*$", re.IGNORECASE)

# `@bot cancel` / `stop` / `abort` (with optional one-word qualifier like
# "it", "this", "task", "workspace") — terminates the user's most recent
# running workspace in the current Discord session. Single-word commands
# only; longer messages (e.g. "cancel my dinner plans") do NOT match.
_CANCEL_RE = re.compile(
    r"^\s*(cancel|stop|abort|kill)(\s+(it|this|that|task|workspace|run))?\s*[.!?]*\s*$",
    re.IGNORECASE,
)

# `@bot reset-context` / `reset context` / `clear context` / `fresh session` —
# bumps the per-(channel, user) reset epoch so the next message starts a brand
# new OpenClaw session, dropping prior assistant turns that may have anchored
# the model on a wrong answer. Single-line commands only.
_RESET_CTX_RE = re.compile(
    r"^\s*(reset|clear|fresh|new)[\s-]+(context|session|history|chat|memory)"
    r"\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def start_discord_workspace_bot(app_request: Request) -> discord.Client | None:
    """
    Start a Discord client in the background.

    Notes:
    - Uses DM + mention-only defaults to avoid responding in every channel.
    - Launches Harvis Workspace runs (agent_id defaults to 'main' = OpenClaw).
    """
    cfg = load_discord_workspace_config()
    if not cfg.enabled:
        logger.info("Discord workspace bot disabled (DISCORD_WORKSPACE_ENABLED=false)")
        return None
    if not cfg.token:
        logger.info("Discord workspace bot not started (DISCORD_BOT_TOKEN not set)")
        return None

    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    async def _list_ollama_models() -> list[str]:
        """Fetch model names from local + desktop Ollama in PARALLEL (deduped).

        Discord autocomplete has a hard ~3s deadline; this used to call the
        two endpoints sequentially with a 5s timeout each, which made the
        autocomplete fail with `Unknown interaction (10062)` whenever the
        desktop was unreachable. Parallel + tight timeout caps the worst case
        at ~1.5s.
        """
        results_per_host: list[list[str]] = [[], []]

        async def _fetch(base_url: str, label: str, idx: int, timeout_s: float):
            if not base_url:
                return
            base = base_url.rstrip("/")
            tags_url = base.replace("/v1", "") + "/api/tags" if "/v1" in base else f"{base}/api/tags"
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as c:
                    resp = await c.get(tags_url)
                if resp.status_code == 200:
                    results_per_host[idx] = [
                        m["name"] for m in resp.json().get("models", []) if m.get("name")
                    ]
            except Exception as e:
                logger.warning("Failed to list Ollama models from %s: %s", label, e)

        desktop_url = os.getenv("DESKTOP_OLLAMA_URL", "")
        await asyncio.gather(
            _fetch(_LOCAL_OLLAMA_URL, "laptop", 0, 2.5),
            _fetch(desktop_url, "desktop", 1, 1.5),
        )
        # Laptop entries first; dedupe across hosts.
        names: list[str] = []
        seen: set[str] = set()
        for host_models in results_per_host:
            for n in host_models:
                if n not in seen:
                    seen.add(n)
                    names.append(n)
        return names

    async def _selectable_models() -> list[str]:
        """Models offered in /model + /set-model: local Ollama models PLUS the
        cloud chat models (Claude / GPT) the default Discord user can use via
        their verified Integrations credential. Fail-soft: cloud lookup errors
        just leave the Ollama list unchanged."""
        models = await _list_ollama_models()
        try:
            pool = getattr(app_request.app.state, "pg_pool", None)
            if pool:
                from owui_compat.cloud_chat import cloud_chat_model_entries

                entries = await cloud_chat_model_entries(pool, cfg.default_user_id)
                for e in entries:
                    mid = e.get("id")
                    if mid and mid not in models:
                        models.append(mid)
        except Exception as exc:
            logger.debug("Discord: cloud model list unavailable: %s", exc)
        return models

    class ModelSelectMenu(discord.ui.Select):
        def __init__(self, models: list[str], current: str):
            options = []
            for m in models[:25]:  # Discord max 25 options
                options.append(discord.SelectOption(
                    label=m,
                    value=m,
                    default=(m == current),
                ))
            super().__init__(placeholder="Pick a model...", options=options)

        async def callback(self, interaction: discord.Interaction):
            pool = getattr(app_request.app.state, "pg_pool", None)
            msg = await _persist_model_selection(
                self.values[0], cfg, pool, _LOCAL_OLLAMA_URL
            )
            await interaction.response.edit_message(content=msg, view=None)

    class ModelSelectView(discord.ui.View):
        def __init__(self, models: list[str], current: str):
            super().__init__(timeout=60)
            self.add_item(ModelSelectMenu(models, current))

    @tree.command(name="model", description="Pick which model Harvis runs on")
    async def model_command(interaction: discord.Interaction):
        models = await _selectable_models()
        if not models:
            await interaction.response.send_message("No models found — is Ollama running?")
            return
        current = (
            _model_override or _FAST_MODEL or cfg.model_name
            or await resolve_default_local_model() or "(no models installed in Ollama)"
        )
        view = ModelSelectView(models, current)
        await interaction.response.send_message(
            f"**Current model:** `{current}`\nPick a new one:",
            view=view,
        )

    async def _model_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        models = await _selectable_models()
        lower = (current or "").lower()
        filtered = [m for m in models if lower in m.lower()] if lower else models
        return [app_commands.Choice(name=m, value=m) for m in filtered[:25]]

    @tree.command(
        name="set-model",
        description="Switch Harvis's model by name (type to autocomplete).",
    )
    @app_commands.describe(model="Model name (e.g. qwen3.5-32k:latest)")
    @app_commands.autocomplete(model=_model_autocomplete)
    async def set_model_command(
        interaction: discord.Interaction, model: str
    ):
        models = await _selectable_models()
        if models and model not in models:
            # Accept substring match as a convenience.
            candidates = [m for m in models if model.lower() in m.lower()]
            if len(candidates) == 1:
                model = candidates[0]
            elif len(candidates) > 1:
                hit_list = "\n".join(f"- `{m}`" for m in candidates)
                await interaction.response.send_message(
                    f"Multiple matches for `{model}`:\n{hit_list}\nBe more specific.",
                    ephemeral=True,
                )
                return
            else:
                await interaction.response.send_message(
                    f"Model `{model}` not found.", ephemeral=True
                )
                return

        pool = getattr(app_request.app.state, "pg_pool", None)
        await interaction.response.defer(thinking=True)
        reply = await _persist_model_selection(
            model, cfg, pool, _LOCAL_OLLAMA_URL
        )
        await interaction.followup.send(reply)

    @tree.command(
        name="engine",
        description="Pick which engine runs your workspace tasks (Native or Claude Code).",
    )
    @app_commands.describe(
        engine="Native = OpenClaw tool loop · Claude Code = Claude runs it directly"
    )
    @app_commands.choices(
        engine=[
            app_commands.Choice(name="Native (OpenClaw)", value="native"),
            app_commands.Choice(name="Claude Code", value="claude-code"),
        ]
    )
    async def engine_command(
        interaction: discord.Interaction, engine: app_commands.Choice[str]
    ):
        pool = getattr(app_request.app.state, "pg_pool", None)
        await interaction.response.defer(thinking=True)
        reply = await _persist_engine_selection(
            engine.value, cfg, pool, _LOCAL_OLLAMA_URL
        )
        await interaction.followup.send(reply)

    @tree.command(
        name="agents",
        description="Multi-agent: when ON, complex tasks fan out to several parallel sub-agents.",
    )
    @app_commands.describe(mode="on = complex tasks run multiple agents · off = single agent")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="On", value="on"),
            app_commands.Choice(name="Off", value="off"),
        ]
    )
    async def agents_command(
        interaction: discord.Interaction, mode: app_commands.Choice[str]
    ):
        pool = getattr(app_request.app.state, "pg_pool", None)
        await interaction.response.defer(thinking=True)
        reply = await _persist_orchestrate_pref(
            mode.value == "on", cfg, pool, _LOCAL_OLLAMA_URL
        )
        await interaction.followup.send(reply)

    # ── /harvis-code coding channel — DORMANT unless HARVIS_CODE_CHANNEL_ID is
    # set. Registration failure is logged and swallowed: the rest of the bot
    # (on_message, /model, /engine, /agents) must start exactly as before.
    if _CODE_CHANNEL_ID:
        try:
            _register_harvis_code(client, tree, app_request, cfg)
            logger.info(
                "harvis-code: enabled (channel=%s guild=%s approver_roles=%s)",
                _CODE_CHANNEL_ID, _CODE_GUILD_ID or "global",
                sorted(_CODE_APPROVER_ROLE_IDS) or "any",
            )
        except Exception as exc:
            logger.exception("harvis-code: registration failed — feature disabled: %s", exc)
    else:
        logger.info("harvis-code: dormant (HARVIS_CODE_CHANNEL_ID not set)")

    @client.event
    async def on_ready():
        # Sync slash commands to EACH guild the bot is in (instant), not just
        # globally (which can take ~1 hour to propagate to clients). Without this,
        # newly-added commands like /engine and /agents don't show up for a while.
        guild_count = 0
        for guild in list(getattr(client, "guilds", []) or []):
            try:
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
                guild_count += 1
            except Exception as exc:
                logger.warning("Discord per-guild command sync failed for %s: %s", getattr(guild, "id", "?"), exc)
        try:
            await tree.sync()  # keep the global registry in sync too
        except Exception as exc:
            logger.warning("Discord global command sync failed: %s", exc)
        logger.info(
            "Discord workspace bot online as %s — slash commands synced (%d guild(s) + global)",
            getattr(client.user, "name", "unknown"), guild_count,
        )

    @client.event
    async def on_message(message: discord.Message):
        try:
            if message.author.bot:
                return

            # Channel allowlist (if configured)
            if cfg.allowed_channel_ids and message.channel and hasattr(message.channel, "id"):
                if int(message.channel.id) not in cfg.allowed_channel_ids and not isinstance(
                    message.channel, discord.DMChannel
                ):
                    return

            # Mention-only behavior (default): allow DMs always
            is_dm = isinstance(message.channel, discord.DMChannel)
            if cfg.mention_only and not is_dm:
                if client.user is None:
                    return
                if client.user not in getattr(message, "mentions", []):
                    return

            content = (message.content or "").strip()
            content = _strip_discord_timestamp_noise(content)

            # Extract Discord attachments (images, PDFs, etc.) so the agent can
            # actually process what the user sent. Each becomes {url, name, mime_type}.
            raw_attachments = list(getattr(message, "attachments", []) or [])
            discord_attachments: list[dict] = []
            for att in raw_attachments:
                url = getattr(att, "url", None) or getattr(att, "proxy_url", None)
                if not url:
                    continue
                discord_attachments.append({
                    "url": url,
                    "name": getattr(att, "filename", None) or "",
                    "mime_type": getattr(att, "content_type", None) or "",
                })

            if not content and not discord_attachments:
                return

            # Strip the bot mention prefix if present (helps prompt quality).
            # Discord sends either `<@id>` or `<@!id>` (nickname mention form),
            # depending on whether the bot has a server nickname. Handle both.
            if client.user is not None:
                bot_id = client.user.id
                content = re.sub(
                    rf"<@!?{bot_id}>", "", content
                ).strip()

            if not content and not discord_attachments:
                return

            # If the message is only an attachment with no text, give the agent a
            # sensible default task so it runs the image skill instead of idling.
            if not content and discord_attachments:
                content = "Analyze the attached file(s) and tell me what's in them."

            logger.debug(
                "Discord on_message (mention-stripped): %r", content[:120]
            )

            pool = getattr(app_request.app.state, "pg_pool", None)

            # ── `@bot reset-context` / `clear-session` text command ──
            # Bumps the per-(channel, user) reset epoch so the next message
            # starts a brand-new OpenClaw session. Used to recover when prior
            # assistant turns in the session have anchored the model on a wrong
            # answer (the model becomes self-consistent with its own past).
            if _RESET_CTX_RE.match(content):
                import time as _time_mod
                chan_id = getattr(message.channel, "id", "dm")
                key = (chan_id, message.author.id)
                # Unix-timestamp epoch — guarantees unique session_id across
                # backend restarts. A counter would collide with a prior
                # session file after the in-memory counter resets to 0 on
                # rebuild.
                _reset_epochs[key] = int(_time_mod.time())
                _reset_pending.add(key)
                new_epoch = _reset_epochs[key]
                logger.warning(
                    "Discord reset-context: channel=%s user=%s epoch_ts=%d "
                    "(also dropping Discord chat-history on next message)",
                    chan_id, message.author.id, new_epoch,
                )
                await message.channel.send(
                    f"Context reset. Next message will start a fresh "
                    f"OpenClaw session AND drop Discord chat history — "
                    f"the model will see only your next message, nothing prior."
                )
                return

            # ── `@bot cancel` / `stop` / `abort` text command ──
            # Terminates the user's most recent RUNNING workspace in this
            # Discord session. Reports back the outcome (cancelled / nothing
            # running / already done). Returns early before any new workspace
            # launch happens.
            if _CANCEL_RE.match(content):
                session_id_for_cancel = _discord_openclaw_session_id(message)
                if not pool:
                    await message.channel.send("Cancel unavailable: backend DB pool not ready.")
                    return
                try:
                    async with pool.acquire() as conn:
                        # Use prefix match (LIKE) because tool-dependent tasks
                        # append message.id to the session_id for isolation.
                        # The base session_id is always the prefix.
                        row = await conn.fetchrow(
                            "SELECT id FROM workspace_runs "
                            "WHERE session_id LIKE $1 AND status = 'running' "
                            "ORDER BY started_at DESC LIMIT 1",
                            session_id_for_cancel + "%",
                        )
                except Exception as exc:
                    logger.exception("Cancel: DB lookup failed: %s", exc)
                    await message.channel.send(f"Cancel failed at DB lookup: {exc}")
                    return

                if not row:
                    await message.channel.send("No running workspace to cancel for this session.")
                    return

                ws_id = row["id"]
                try:
                    from workspace.workspace_router import cancel_workspace_internal
                    result = await cancel_workspace_internal(
                        ws_id,
                        audit_actor=f"discord:{message.author.id}",
                    )
                except Exception as exc:
                    logger.exception("Cancel: internal call failed: %s", exc)
                    await message.channel.send(f"Cancel failed: {exc}")
                    return

                short = ws_id[:8]
                if result["status"] == "cancelled":
                    outcome = result.get("wait_outcome", "ok")
                    await message.channel.send(
                        f"Cancelled workspace `{short}` ({outcome})."
                    )
                elif result["status"] == "already_terminal":
                    await message.channel.send(
                        f"Workspace `{short}` is already {result.get('current')}."
                    )
                else:
                    # not_found — DB said running but in-memory dict didn't have it
                    # (probably backend restart between launch and now).
                    await message.channel.send(
                        f"Workspace `{short}` not tracked in memory — likely stale row. "
                        f"Use POST /api/workspace/cancel if you need to force-close server-side."
                    )
                return

            # ── `@bot set-model <name>` text command ──
            set_model_match = _SET_MODEL_RE.match(content)
            if set_model_match:
                arg = (set_model_match.group(1) or "").strip()
                models = await _list_ollama_models()
                current = (
            _model_override or _FAST_MODEL or cfg.model_name
            or await resolve_default_local_model() or "(no models installed in Ollama)"
        )

                if not arg or arg.lower() in {"list", "ls", "?"}:
                    if not models:
                        await message.channel.send(
                            "No models found — is Ollama running?"
                        )
                        return
                    listing = "\n".join(f"- `{m}`" for m in models)
                    await _send_long_message(
                        message.channel,
                        f"**Current model:** `{current}`\n"
                        f"**Available models:**\n{listing}\n\n"
                        f"Usage: `@<bot> set-model <name>`",
                    )
                    return

                if not models:
                    await message.channel.send(
                        f"Can't switch to `{arg}` — Ollama did not return a model list."
                    )
                    return

                # Exact match wins; otherwise try unique substring/prefix match.
                picked: str | None = None
                if arg in models:
                    picked = arg
                else:
                    lower = arg.lower()
                    candidates = [
                        m for m in models
                        if m.lower() == lower
                        or m.lower().startswith(lower)
                        or lower in m.lower()
                    ]
                    if len(candidates) == 1:
                        picked = candidates[0]
                    elif len(candidates) > 1:
                        hit_list = "\n".join(f"- `{m}`" for m in candidates)
                        await message.channel.send(
                            f"Multiple matches for `{arg}`:\n{hit_list}\n"
                            f"Be more specific."
                        )
                        return

                if not picked:
                    hint = "\n".join(f"- `{m}`" for m in models[:10])
                    await message.channel.send(
                        f"Model `{arg}` not found.\n**Available:**\n{hint}"
                    )
                    return

                reply = await _persist_model_selection(
                    picked, cfg, pool, _LOCAL_OLLAMA_URL
                )
                await _send_long_message(message.channel, reply)
                return

            pref_agent_id = cfg.agent_id
            pref_model_name = cfg.model_name
            if pool:
                db_agent_id, db_model_name = await _get_user_model_preference(pool, cfg.default_user_id)
                pref_agent_id = db_agent_id or cfg.agent_id
                pref_model_name = db_model_name or cfg.model_name
            # When `/model` was used in this process, surface the in-memory
            # override so subsequent on_message calls reflect it immediately
            # (the DB row is fresh, but the local cache may be stale for ~30s).
            if _model_override:
                pref_model_name = _model_override
            # Phase 3 (model_proxy auto): prefer agent=main so the workspace
            # runs through OpenClaw on the desktop, which gives full tool-calling
            # + skill loading. The desktop's default model is `harvis-proxy/auto`,
            # which the model_proxy resolves to the user's saved DB pick on every
            # request — so the picked model actually runs WITH tools.
            # Override DB's `agent=local` ONLY when the user has set a real
            # workspace model preference; that local path is text-only.
            if pref_model_name and pref_agent_id == "local":
                pref_agent_id = "main"
            # ── Engine preference (separate from the model): Native vs Claude Code ──
            pref_engine = await _get_user_engine_preference(pool, cfg.default_user_id)
            _use_claude_engine = pref_engine == "claude-code"
            # Path A readiness: native engine + Claude model runs on OpenClaw via
            # the Anthropic API key. When ready, don't swap the Claude model for a
            # local one — let it flow through to OpenClaw → model_proxy → Anthropic.
            _path_a_ready = await _user_has_anthropic_provider(pool, cfg.default_user_id)
            # Multi-agent opt-in (the /agents toggle).
            _orchestrate_enabled = await _get_user_orchestrate_pref(pool, cfg.default_user_id)

            # Force browser-capable OpenClaw path for visual tasks.
            # Local/Kimi workspace runners are text-only and can "simulate" screenshots.
            visual_task = _looks_like_visual_task(content)
            if visual_task and pref_agent_id != "main":
                logger.info(
                    "Discord visual task forcing agent route: %s -> main",
                    pref_agent_id,
                )
                pref_agent_id = "main"

            # ── Claude Code engine (Path B): run the task DIRECTLY through Claude ──
            # Only for non-visual tasks — Claude Code can't take browser
            # screenshots, so visual tasks stay on OpenClaw. The `claude` lane
            # runs `claude -p` in the sidecar on the user's verified credential.
            if _use_claude_engine and not visual_task and pref_agent_id != "claude":
                logger.info(
                    "Discord: Claude Code engine selected — routing workspace to "
                    "agent=claude (was %s)",
                    pref_agent_id,
                )
                pref_agent_id = "claude"

            # ── Multi-agent (/agents ON): fan a complex task out to several parallel
            # sub-agents. Native/OpenClaw only — Claude Code + visual tasks stay
            # single. Trivial tasks fast-path before the workspace lane, so this
            # only takes effect for real (multi-part) workspace tasks.
            if (
                _orchestrate_enabled
                and pref_agent_id != "claude"
                and not visual_task
                and _looks_multi_part(content)
            ):
                logger.info(
                    "Discord: multi-agent ON — routing workspace to orchestrate (was %s)",
                    pref_agent_id,
                )
                pref_agent_id = "orchestrated"

            # Fetch history ONCE — both paths use it. Without this, fast-path
            # replies have no memory even though workspace-path replies do.
            prior_history = await _fetch_discord_chat_history(
                client, message, limit=cfg.history_turns
            )

            # ── Reset-context drain ─────────────────────────────────────────
            # If `@bot reset-context` ran since the user's last message, drop
            # Discord-fetched history on this turn. Without this, OpenClaw
            # would get a fresh session (good) but the message brief would
            # still embed prior turns via chat_history (bad), defeating the
            # reset.
            _chan_id_for_reset = getattr(message.channel, "id", "dm")
            _reset_key = (_chan_id_for_reset, message.author.id)
            if _reset_key in _reset_pending:
                logger.info(
                    "Discord: dropped %d prior history turns because reset-context "
                    "was issued (consuming the pending reset).",
                    len(prior_history),
                )
                prior_history = []
                _reset_pending.discard(_reset_key)

            # ── Attachment-fresh policy ────────────────────────────────────
            # When the user attaches a file, drop the channel chat history.
            # Otherwise prior bot rejections like "I can't find the file"
            # poison the new task — the model pattern-completes that refusal
            # even though the new attachment is fully inlined into the brief.
            # A fresh attachment-bearing task should be treated as a clean
            # slate; the file content + the user's question are self-contained.
            if discord_attachments and prior_history:
                logger.info(
                    "Discord: dropped %d prior history turns because attachments are present "
                    "(prevents refusal-pattern pollution).",
                    len(prior_history),
                )
                prior_history = []

            memory_meta_reply = _direct_discord_memory_reply(
                content, prior_history, cfg.history_turns
            )
            if memory_meta_reply:
                logger.info(
                    "Discord memory/meta direct reply: history_turns=%d msg=%r",
                    len(prior_history), content[:80],
                )
                await _send_long_message(message.channel, memory_meta_reply)
                return

            # ── Resolve the selected model + whether it's a cloud chat model ──
            # A cloud model (e.g. Claude) can only do a conversational reply via
            # the user's credential — it can't drive the OpenClaw/Ollama workspace
            # tool loop. So a cloud pick is handled in the FAST path below (simple
            # chat), while a COMPLEX task falls through to the workspace lane and
            # runs on a local model (until Path A — OpenClaw→Claude — lands).
            _resolved_model = (_model_override or pref_model_name or "").strip()
            try:
                from owui_compat.cloud_chat import is_cloud_chat_model
                _model_is_cloud = is_cloud_chat_model(_resolved_model)
            except Exception:
                _model_is_cloud = False

            # ── Workspace-first mode or standard routing ──
            use_fast_path = False
            if discord_attachments:
                # Attachments (images/files) can only be processed by the
                # workspace path — fast path has no access to the image skill
                # or the /api/tools/vision-query endpoint.
                use_fast_path = False
            elif _PREFER_WORKSPACE:
                # In workspace-first mode, only fast-path ultra-short greetings
                # plus Discord memory/meta questions. Those rely on recent
                # channel context and should not go through the OpenClaw
                # workspace identity prompt.
                use_fast_path = (
                    _looks_like_discord_memory_meta_chat(content)
                    or (len(content) < 20 and not _WORKSPACE_SIGNALS.search(content))
                )
            elif _is_obviously_simple(content):
                use_fast_path = True
            else:
                # Dynamic Router: use AI to decide if a workspace is needed.
                # Pass real history so the detector knows whether this is a
                # tool-needing follow-up vs. casual chat.
                detector_hist = list(prior_history) + [{"role": "user", "content": content}]
                suggestion = await detect_workspace_task(detector_hist)
                if not suggestion.should_suggest:
                    use_fast_path = True

            # ── Fast path: simple questions → direct LLM call, no workspace ──
            if use_fast_path:
                async with message.channel.typing():
                    if _model_is_cloud:
                        # Conversational reply via the user's cloud credential
                        # (e.g. Claude). Only SIMPLE messages reach here; complex
                        # tasks fall through to the workspace lane below.
                        logger.info(
                            "Discord fast-path (cloud): model=%s history_turns=%d msg=%r",
                            _resolved_model, len(prior_history), content[:80],
                        )
                        reply = await _cloud_chat_reply(
                            _resolved_model, content, prior_history, pool, cfg.default_user_id
                        )
                    else:
                        fast_model = (
                            _model_override or _FAST_MODEL or pref_model_name
                            or await resolve_default_local_model(pool=pool, user_id=cfg.default_user_id)
                            or ""
                        )
                        logger.info(
                            "Discord fast-path: model=%s history_turns=%d msg=%r",
                            fast_model, len(prior_history), content[:80],
                        )
                        reply = await _fast_llm_reply(content, fast_model, prior_history)
                if reply:
                    # Split into chunks if longer than Discord's 2000-char limit
                    await _send_long_message(message.channel, reply)
                    return
                # If fast path returned empty (Ollama down, etc.), fall through to workspace
                logger.warning("Discord fast-path returned empty — falling back to workspace")

            # ── Workspace path: complex tasks needing tools/browser/agents ──
            lock = _discord_workspace_lock(message)
            if lock.locked():
                await message.channel.send(
                    "\u23f3 A workspace is already running for you in this channel — "
                    "wait for it to finish, then send your next message."
                )
                return

            async with lock:
                # Tool-dependent tasks (hash cracking, decode) get a fresh
                # OpenClaw session so prior turns don't bleed old answers
                # into the prompt, causing the model to skip tool calls.
                needs_fresh_session = bool(_TOOL_TASK_SIGNALS.search(content))
                session_id = _discord_openclaw_session_id(
                    message, fresh=needs_fresh_session,
                )
                if needs_fresh_session:
                    logger.info(
                        "Discord: using fresh session for tool-dependent task "
                        "(session_id=%s msg=%r)",
                        session_id, content[:80],
                    )
                    # Context-hygiene (2026-05-29): a fresh-session tool task
                    # also drops rendered chat history. The fresh sessionId
                    # already clears OpenClaw's STRUCTURED replay; this also
                    # strips the ~4000-char `_build_context_brief` text block,
                    # which can carry a prior "...cracked successfully" reply
                    # that mildly suppresses tool-call emission (harness:
                    # 88% vs 100% clean). Mirrors the attachment-fresh policy
                    # below. Safe because the tool brief is self-contained:
                    # `_TOOL_TASK_SIGNALS` only matched because the hashes/
                    # ciphertext are in THIS message, so dropping prior chat
                    # loses nothing the task needs.
                    if prior_history:
                        logger.info(
                            "Discord: dropped %d prior history turns for "
                            "fresh tool task (rendered-context hygiene).",
                            len(prior_history),
                        )
                        prior_history = []

                # Keep OpenClaw main-agent model aligned with the current global/user model.
                # Without this, OpenClaw may retain a stale default (e.g. gemma4:4b) and fail
                # with "model not found" even when Discord is configured to another model.
                effective_model_name = (_model_override or pref_model_name or "").strip()
                # ── Cloud model can't drive the OpenClaw workspace tool loop ──
                # (Path A — OpenClaw→Claude via Anthropic API key — isn't wired
                # yet.) Fall back to a local model AND say so plainly, so a
                # local-model run is never mistaken for "OpenClaw used Claude".
                # The `claude` lane (Claude Code engine) DOES run the cloud model
                # directly, so skip the fallback there. And when Path A is ready
                # (Anthropic API key as the OpenClaw provider), OpenClaw itself
                # routes the Claude model to Anthropic — so don't fall back either.
                if _model_is_cloud and pref_agent_id != "claude" and not _path_a_ready:
                    _cloud_pick = effective_model_name
                    # Prefer the user's LAST LOCAL model (their actual pick before
                    # they switched to a cloud model), then the configured fast
                    # model, then a sensible installed default.
                    effective_model_name = (
                        await _get_last_local_model(pool, cfg.default_user_id)
                        or _FAST_MODEL
                        or await resolve_default_local_model(pool=pool, user_id=cfg.default_user_id)
                        or ""
                    )
                    logger.info(
                        "Discord workspace: cloud model %s can't run the OpenClaw loop — "
                        "falling back to last-used local model %r",
                        _cloud_pick, effective_model_name,
                    )
                    _fb_label = f"`{effective_model_name}`" if effective_model_name else "a local model"
                    await message.channel.send(
                        f"ℹ️ `{_cloud_pick}` is a cloud model and can't drive the OpenClaw "
                        f"workspace yet — running this task with {_fb_label} instead."
                    )
                if pref_agent_id == "main" and effective_model_name:
                    sync_note = await _apply_model_to_native_openclaw(effective_model_name)
                    logger.info(
                        "Discord workspace synced main-agent model to %s %s",
                        effective_model_name,
                        sync_note or "",
                    )

                progress_msg = await message.channel.send(
                    f"**Workspace launching\u2026**\n\u23f3 Starting workspace\u2026"
                )

                # prior_history was fetched once at the top of on_message
                data = await launch_workspace_internal(
                    request=app_request,
                    user_id=cfg.default_user_id,
                    task_brief=content,
                    chat_history=prior_history,
                    agent_id=pref_agent_id,
                    model_name=effective_model_name,
                    session_id=session_id,
                    enable_interactive=cfg.enable_interactive,
                    attachments=discord_attachments,
                    # Multi-agent: keep all sub-agents on the selected (local) model
                    # so the 8GB box doesn't load heavy per-role profile models.
                    uniform_model=(pref_agent_id == "orchestrated"),
                )
                workspace_id = data["workspace_id"]

                # Attach a Cancel button to the progress message now that we
                # have a workspace_id. Same code path as the @bot cancel text
                # command. Timeout = workspace timeout + 60s margin so the
                # button outlives the run.
                try:
                    _cancel_view = CancelWorkspaceView(
                        workspace_id,
                        message.author.id,
                        timeout=float(cfg.max_wait_seconds + 60),
                    )
                    await progress_msg.edit(view=_cancel_view)
                except Exception as exc:
                    logger.warning(
                        "Failed to attach cancel button to progress msg for %s: %s",
                        workspace_id, exc,
                    )


                status, summary, err = await _wait_with_progress(
                    request=app_request,
                    workspace_id=workspace_id,
                    timeout_s=cfg.max_wait_seconds,
                    progress_msg=progress_msg,
                )

                # Delete the progress message — replace with clean final result
                try:
                    await progress_msg.delete()
                except discord.HTTPException:
                    pass

                # ── Scope 1: failure-driven escalation between paired models ──
                # Single retry on the alternate model with reset-context
                # semantics (fresh session, dropped history). Off by default;
                # flip HARVIS_ESCALATE_ON_FAILURE=true after smoke tests pass.
                escalation_note: str | None = None
                if (
                    _ESCALATE_ON_FAILURE
                    and effective_model_name in _ESCALATION_PAIRS
                ):
                    should_escalate, escalation_reason = (
                        _looks_like_escalation_worthy_failure(status, summary, err)
                    )
                    if should_escalate:
                        alternate_model = _ESCALATION_PAIRS[effective_model_name]
                        logger.warning(
                            "[workspace:%s] Escalating from %s -> %s (reason=%s)",
                            workspace_id, effective_model_name,
                            alternate_model, escalation_reason,
                        )
                        try:
                            await message.channel.send(
                                f"⤴ Default model `{effective_model_name}` couldn't "
                                f"complete ({escalation_reason}); retrying on "
                                f"`{alternate_model}` with fresh context…"
                            )
                        except discord.HTTPException:
                            pass

                        # Heavyweight swap: for the OpenClaw 'main' route this
                        # restarts the openclaw container so the alternate
                        # becomes the active default. For 'local' / 'kimi' /
                        # 'nvidia-kimi' / 'cloud-ollama', the model_name arg
                        # below drives selection directly.
                        if pref_agent_id == "main":
                            try:
                                await _apply_model_to_native_openclaw(alternate_model)
                            except Exception as exc:
                                logger.warning(
                                    "Escalation: failed to apply alternate %s "
                                    "to openclaw config: %s",
                                    alternate_model, exc,
                                )

                        # Reset-context semantics: fresh session_id + empty
                        # history. Alternate sees the task cold so the failed
                        # default's narrative cannot poison the retry.
                        escalation_session_id = f"{session_id}-esc-{workspace_id}"
                        try:
                            escalation_progress_msg = await message.channel.send(
                                f"**Re-launching on `{alternate_model}`…**\n"
                                f"⏳ Starting workspace…"
                            )
                        except discord.HTTPException:
                            escalation_progress_msg = None

                        esc_data = await launch_workspace_internal(
                            request=app_request,
                            user_id=cfg.default_user_id,
                            task_brief=content,
                            chat_history=[],
                            agent_id=pref_agent_id,
                            model_name=alternate_model,
                            session_id=escalation_session_id,
                            enable_interactive=cfg.enable_interactive,
                            attachments=discord_attachments,
                        )
                        esc_workspace_id = esc_data["workspace_id"]

                        if escalation_progress_msg is not None:
                            esc_status, esc_summary, esc_err = await _wait_with_progress(
                                request=app_request,
                                workspace_id=esc_workspace_id,
                                timeout_s=cfg.max_wait_seconds,
                                progress_msg=escalation_progress_msg,
                            )
                            try:
                                await escalation_progress_msg.delete()
                            except discord.HTTPException:
                                pass
                        else:
                            esc_status, esc_summary, esc_err = (
                                await _wait_for_workspace_completion(
                                    request=app_request,
                                    workspace_id=esc_workspace_id,
                                    timeout_s=cfg.max_wait_seconds,
                                )
                            )

                        # Replace original results with the escalation outcome.
                        # No chaining: even if alternate also failed, we surface
                        # its output (per scope: "return alternate's output with
                        # a 'neither model succeeded' wrapper").
                        original_model_for_note = effective_model_name
                        workspace_id = esc_workspace_id
                        status = esc_status
                        summary = esc_summary
                        err = esc_err
                        if esc_status == "done":
                            escalation_note = (
                                f"\n\n_⤴ Escalated to `{alternate_model}` "
                                f"after `{original_model_for_note}` failed "
                                f"({escalation_reason})._"
                            )
                        else:
                            escalation_note = (
                                f"\n\n_⤴ Escalated to `{alternate_model}` "
                                f"after `{original_model_for_note}` failed "
                                f"({escalation_reason}); alternate also failed "
                                f"(status={esc_status})._"
                            )

                if status == "done":
                    msg = await _best_workspace_message(
                        request=app_request,
                        workspace_id=workspace_id,
                        final_summary=summary,
                    )
                    if escalation_note:
                        msg = (msg or "Done.") + escalation_note
                    screenshot_abs, screenshot_rel = await _find_latest_screenshot_file(
                        request=app_request,
                        workspace_id=workspace_id,
                    )
                    if screenshot_abs:
                        cleaned_msg = _strip_screenshot_path_lines(msg)
                        if not cleaned_msg:
                            cleaned_msg = "Here's the result:"
                        try:
                            # Send response text + screenshot attachment
                            await _send_long_message(
                                message.channel,
                                cleaned_msg,
                                file=discord.File(screenshot_abs, filename=os.path.basename(screenshot_abs)),
                            )
                        except Exception as send_exc:
                            logger.warning("Discord file upload failed: %s", send_exc)
                            await _send_long_message(message.channel, msg)
                    else:
                        # No agent screenshot — if the run produced a previewable
                        # artifact (an image, or an HTML/SVG rendered via the
                        # headless browser), screenshot it and post it with the result.
                        preview_abs, _preview_label = await _render_preview_screenshot(
                            request=app_request, workspace_id=workspace_id,
                        )
                        if preview_abs:
                            try:
                                await _send_long_message(
                                    message.channel,
                                    msg or "Here's the result:",
                                    file=discord.File(preview_abs, filename=os.path.basename(preview_abs)),
                                )
                            except Exception as send_exc:
                                logger.warning("Discord preview upload failed: %s", send_exc)
                                await _send_long_message(message.channel, msg)
                        else:
                            await _send_long_message(message.channel, msg)
                elif status == "cancelled":
                    await message.channel.send(f"Workspace `{workspace_id}` was cancelled.")
                else:
                    failure_msg = (
                        f"Workspace `{workspace_id}` failed: "
                        f"{((err or 'Unknown error')[:1800])}"
                    )
                    if escalation_note:
                        failure_msg += escalation_note
                    await message.channel.send(failure_msg)

        except Exception as exc:
            logger.exception("Discord workspace bot error: %s", exc)
            try:
                await message.channel.send(f"Workspace error: {str(exc)[:1800]}")
            except Exception:
                pass

    # Start the bot in the background
    async def _runner():
        await client.start(cfg.token)

    asyncio.create_task(_runner(), name="discord-workspace-bot")
    return client

