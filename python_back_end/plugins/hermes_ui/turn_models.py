"""Which models answer a Hermes chat turn: the main model, its fallbacks, or a mixture of agents.

Settings ▸ Model has three parts and this module is what makes each one real:

* **Main model** — the session's model (or the active custom endpoint), as before.
* **Fallback models** — ``fallback_providers`` in the config, a list of
  ``{provider, model}``. When the main model fails *before it has said anything*,
  each fallback is tried in order and a note says which one took over. A model that
  fails halfway through an answer is not retried: the half answer is already on screen.
* **Mixture of agents** — a saved preset shows up in the model picker as
  ``moa:<preset>``. Picking it asks every reference model the same conversation
  at once, then streams the aggregator's answer, written from the references'
  replies with the aggregator prompt from the MoA paper (as upstream Hermes does,
  tools/mixture_of_agents_tool.py).

It also adds the chat settings a turn needs: the chosen personality and the
user's local time, as one system note ahead of the conversation.

``provider`` is either a custom endpoint id (the user's own OpenAI-compatible
server, key and all) or anything else, which means "Harvis's own chat route",
where the model id picks Ollama, a cloud key, and so on.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import chat, providers, settings_store

log = logging.getLogger("hermes_ui.turn_models")

MOA_PREFIX = "moa:"
MOA_KEY = "moa"
MIN_SUCCESSFUL_REFERENCES = 1
DEFAULT_REFERENCE_TIMEOUT = 180.0

# From the MoA paper, as upstream Hermes uses it.
AGGREGATOR_SYSTEM_PROMPT = (
    "You have been provided with a set of responses from various open-source models to the latest user "
    "query. Your task is to synthesize these responses into a single, high-quality response. It is crucial "
    "to critically evaluate the information provided in these responses, recognizing that some of it may be "
    "biased or incorrect. Your response should not simply replicate the given answers but should offer a "
    "refined, accurate, and comprehensive reply to the instruction. Ensure your response is well-structured, "
    "coherent, and adheres to the highest standards of accuracy and reliability.\n\nResponses from models:"
)

# Upstream Hermes's built-in personalities (cli.py agent.personalities), with the
# assistant's name changed to Harvis. A user's own ``agent.personalities`` win.
PERSONALITIES = {
    "helpful": "You are a helpful, friendly AI assistant.",
    "concise": "You are a concise assistant. Keep responses brief and to the point.",
    "technical": "You are a technical expert. Provide detailed, accurate technical information.",
    "creative": "You are a creative assistant. Think outside the box and offer innovative solutions.",
    "teacher": "You are a patient teacher. Explain concepts clearly with examples.",
    "kawaii": "You are a kawaii assistant! Use cute expressions like (◕‿◕), ★, ♪, and ~! Add sparkles and be "
              "super enthusiastic about everything! Every response should feel warm and adorable desu~!",
    "catgirl": "You are Neko-chan, an anime catgirl AI assistant, nya~! Add 'nya' and cat-like expressions to "
               "your speech. Use kaomoji like (=^･ω･^=). Be playful and curious like a cat, nya~!",
    "pirate": "Arrr! Ye be talkin' to Captain Harvis, the most tech-savvy pirate to sail the digital seas! Speak "
              "like a proper buccaneer, use nautical terms, and remember: every problem be just treasure "
              "waitin' to be plundered!",
    "shakespeare": "Respond in the eloquent manner of William Shakespeare, with flowery prose, dramatic flair, "
                   "and perhaps a soliloquy or two.",
    "surfer": "You're the chillest AI on the web, dude! Keep everything totally rad and super chill while you "
              "help catch the gnarly waves of knowledge.",
    "noir": "You are Harvis, a hard-boiled detective in a city of silicon and secrets. Answer like a noir "
            "narrator: rain, shadows, and the truth that hides in the codebase.",
    "uwu": "You are a fwiendwy assistant uwu~ Talk in uwu-speak while still being vewy hewpful >w<",
    "philosopher": "You contemplate the deeper meaning behind every query. Examine not just the 'how' but the "
                   "'why' of each question.",
    "hype": "You are EXTREMELY PUMPED to help! Every question is AMAZING and you answer with maximum hype "
            "and energy!",
}


class _Failed(RuntimeError):
    """A model failed before saying anything, so the next fallback may take over."""


def _clean(value: Any) -> str:
    return str(value or "").strip()


# ── the system note (personality + local time) ──────────────────────────────

def personality_text(config: dict) -> str:
    name = _clean(settings_store.get_path(config, "display.personality")).lower()
    if not name or name in {"default", "none"}:
        return ""
    custom = settings_store.get_path(config, "agent.personalities")
    custom = custom if isinstance(custom, dict) else {}
    value = custom.get(name, PERSONALITIES.get(name, ""))
    if isinstance(value, dict):  # upstream allows {system_prompt: ...}
        value = value.get("system_prompt") or value.get("prompt") or ""
    return _clean(value)


def time_text(config: dict, now: datetime | None = None) -> str:
    zone = _clean(settings_store.get_path(config, "timezone"))
    if not zone:
        return ""
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        log.info("hermes_ui: ignoring unknown timezone %r", zone)
        return ""
    local = (now or datetime.now(tz)).astimezone(tz)
    return f"The user's local time is {local:%A %Y-%m-%d %H:%M} ({zone})."


def system_note(config: dict, now: datetime | None = None) -> dict | None:
    lines = [line for line in (personality_text(config), time_text(config, now)) if line]
    return {"role": "system", "content": "\n\n".join(lines)} if lines else None


# ── resolving a {provider, model} pick ──────────────────────────────────────

async def resolve_target(pool, uid: int, provider: str, model: str) -> tuple[str, dict | None]:
    """(model, endpoint) for chat.stream_turn. A custom endpoint id gets its own
    URL and key with ``model`` swapped in; anything else runs on Harvis's route."""
    provider, model = _clean(provider) or "harvis", _clean(model)
    if model.startswith(MOA_PREFIX):
        raise chat.ChatError("a mixture-of-agents preset cannot run inside another model slot")
    if model == "harvis-default":
        model = ""
    if provider != "harvis":
        endpoint = await providers.resolve_endpoint(pool, uid, provider)
        if endpoint:
            model = model or endpoint["model"]
            return model, {**endpoint, "model": model}
    return model, None


def _label(provider: str, model: str) -> str:
    provider, model = _clean(provider), _clean(model)
    return f"{model} ({provider})" if provider and provider != "harvis" else (model or "the Harvis default")


def _short(exc: BaseException) -> str:
    first = exc.args[0] if exc.args else None
    raw = first.get("message") if isinstance(first, dict) and first.get("message") else exc
    text = " ".join(str(raw).split()) or type(exc).__name__
    return text[:200]


# ── fallbacks ───────────────────────────────────────────────────────────────

def fallback_chain(config: dict) -> list[dict[str, str]]:
    rows = config.get("fallback_providers")
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and _clean(row.get("model")):
            out.append({"provider": _clean(row.get("provider")) or "harvis", "model": _clean(row["model"])})
    return out


async def _guarded(stream: AsyncIterator[tuple[str, Any]]) -> AsyncIterator[tuple[str, Any]]:
    """Pass a stream through; a failure before any answer text becomes _Failed.

    Reasoning lines (a model's thinking, MoA's progress notes) are not an answer,
    so a model that fails after only those still hands over to the next fallback."""
    said = False
    try:
        async for item in stream:
            said = said or item[0] != "reasoning"
            yield item
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        if said:
            raise
        raise _Failed(_short(exc)) from exc


# ── mixture of agents ───────────────────────────────────────────────────────

async def moa_preset(pool, uid: int, model: str) -> tuple[str, dict] | None:
    """The saved preset a ``moa:<name>`` model id names, or None for any other model."""
    if not _clean(model).startswith(MOA_PREFIX):
        return None
    name = _clean(model)[len(MOA_PREFIX):]
    saved = await settings_store.get_key(pool, uid, MOA_KEY, {})
    presets = saved.get("presets") if isinstance(saved, dict) else None
    preset = presets.get(name) if isinstance(presets, dict) else None
    if not isinstance(preset, dict):
        raise chat.ChatError(f"Mixture of agents preset '{name}' is not set up (Settings ▸ Model ▸ Mixture of agents)")
    return name, preset


def moa_ready(preset: dict) -> bool:
    agg = preset.get("aggregator") if isinstance(preset.get("aggregator"), dict) else {}
    refs = [r for r in preset.get("reference_models") or [] if isinstance(r, dict)]
    return (preset.get("enabled") is not False and bool(_clean(agg.get("model")))
            and any(_clean(r.get("model")) and r.get("enabled", True) is not False for r in refs))


def aggregator_prompt(responses: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(responses))
    return f"{AGGREGATOR_SYSTEM_PROMPT}\n\n{numbered}"


async def _collect(pool, uid, token, turn, slot, origin, timeout) -> str:
    model, endpoint = await resolve_target(pool, uid, slot.get("provider", ""), slot.get("model", ""))

    async def run() -> str:
        parts = []
        async for kind, delta in chat.stream_turn(token, turn, model, endpoint, "chat", "", origin):
            if kind == "text":
                parts.append(delta)
        return "".join(parts).strip()

    text = await asyncio.wait_for(run(), timeout=timeout)
    if not text:
        raise chat.ChatError("empty answer")
    return text


async def run_moa(pool, uid: int, token: str, turn: list[dict], name: str, preset: dict, mode: str,
                  origin: str, extra: dict | None) -> AsyncIterator[tuple[str, Any]]:
    if not moa_ready(preset):
        raise chat.ChatError(f"Mixture of agents preset '{name}' is off or has no reference and aggregator models")
    refs = [r for r in preset.get("reference_models") or []
            if isinstance(r, dict) and _clean(r.get("model")) and r.get("enabled", True) is not False]
    try:
        timeout = float(preset.get("reference_timeout") or DEFAULT_REFERENCE_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_REFERENCE_TIMEOUT
    loud = preset.get("degraded_reference_policy") != "silent"
    yield "reasoning", f"Mixture of agents '{name}': asking {len(refs)} reference model(s).\n"
    results = await asyncio.gather(*(_collect(pool, uid, token, turn, r, origin, timeout) for r in refs),
                                   return_exceptions=True)
    answers = []
    for slot, result in zip(refs, results):
        if isinstance(result, BaseException):
            if isinstance(result, asyncio.CancelledError):
                raise result
            why = "timed out" if isinstance(result, asyncio.TimeoutError) else _short(result)
            if loud:
                yield "reasoning", f"Reference {_label(slot.get('provider'), slot.get('model'))} failed: {why}\n"
        else:
            answers.append(result)
    if len(answers) < MIN_SUCCESSFUL_REFERENCES:
        raise chat.ChatError("no reference model answered")
    agg = preset["aggregator"]
    yield "reasoning", (f"{len(answers)} of {len(refs)} reference(s) answered; "
                        f"{_label(agg.get('provider'), agg.get('model'))} is writing the reply.\n")
    model, endpoint = await resolve_target(pool, uid, agg.get("provider", ""), agg.get("model", ""))
    lead = [m for m in turn if m.get("role") == "system"]
    rest = [m for m in turn if m.get("role") != "system"]
    agg_turn = [*lead, {"role": "system", "content": aggregator_prompt(answers)}, *rest]
    async for item in chat.stream_turn(token, agg_turn, model, endpoint, mode, "", origin, extra=extra):
        yield item


# ── the turn ────────────────────────────────────────────────────────────────

async def stream(pool, uid: int, token: str, turn: list[dict], model: str, endpoint: dict | None, mode: str,
                 effort: str, origin: str, *, extra: dict | None = None,
                 config: dict | None = None, bot: bool = False) -> AsyncIterator[tuple[str, Any]]:
    """chat.stream_turn with the Model settings applied (same items out).

    A bot chat keeps its own instructions, so the personality note is left out
    of it; fallbacks and MoA apply to every chat."""
    if config is None:
        from .rest import CONFIG
        config = await settings_store.config_for(pool, uid, CONFIG)
    note = None if bot else system_note(config)
    if note:
        turn = [note, *turn]
    moa = await moa_preset(pool, uid, model)

    def primary() -> AsyncIterator[tuple[str, Any]]:
        if moa:
            return run_moa(pool, uid, token, turn, moa[0], moa[1], mode, origin, extra)
        return chat.stream_turn(token, turn, model, endpoint, mode, effort, origin, extra=extra)

    chain = fallback_chain(config)
    try:
        async for item in _guarded(primary()):
            yield item
        return
    except _Failed as exc:
        if not chain:
            raise chat.ChatError(str(exc)) from exc.__cause__
        why = str(exc)
        failed = (f"Mixture of agents '{moa[0]}'" if moa else
                  _label((endpoint or {}).get("id") or "harvis", (endpoint or {}).get("model") or model))
    for row in chain:
        yield "reasoning", f"{failed} failed ({why}). Trying fallback {_label(row['provider'], row['model'])}.\n"
        failed = _label(row["provider"], row["model"])
        try:
            fb_model, fb_endpoint = await resolve_target(pool, uid, row["provider"], row["model"])
        except chat.ChatError as exc:
            why = _short(exc)
            continue
        try:
            async for item in _guarded(chat.stream_turn(token, turn, fb_model, fb_endpoint, mode, "", origin,
                                                        extra=extra)):
                yield item
            return
        except _Failed as exc:
            why = str(exc)
    raise chat.ChatError(f"every model failed; last was {failed}: {why}")
