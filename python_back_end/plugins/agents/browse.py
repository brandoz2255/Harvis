"""Plain chat gets the browser: "open instagram and scroll my feed for me".

Only teammates have the computer (the watchable Firefox on browser-runner,
gated by the four hard limits). A person in an ordinary chat, with no
teammate picked, used to get a sandbox run that could not browse. This module
spots a request to *drive a site* and hands it to the user's default
assistant through the same door every teammate run takes
(``intake.create_agent_run``), so the run card, the Computer view, take-over
and the sign-in/pay/send/delete approvals are exactly the teammate's — there
is no second path to the browser.

The detector is deliberately narrow: the message must *start* with a driving
verb aimed at a named site or a bare domain, or ask for the browser by name.
"Search the web for X" is a lookup (chat_reach answers it inline), "install
ComfyUI" is a sandbox job, "what is instagram" is a question, and "check my
feed parser" is about code; none of them opens a browser.

A chat-driven run never uses the teammate's standing clearances: the user
granted those to the teammate on the Agents page for its own jobs, not to
whatever a chat message happens to say. Every sign-in, payment, send and
delete on this path pauses for approval (see ``computer.withhold_clearances``).
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MODE = "browse"

# Sites people drive rather than read. Kept tight on purpose: a word that is
# also an ordinary noun ("target", "canvas", "threads", "booking") or a code
# library ("discord" as in discord.py) is left out, and so are abbreviations
# ("fb", "yt", "insta"). Code hosts are left out too: "go to github and clone
# it" is a sandbox job, not a browsing session.
_SITES = (
    r"instagram|facebook|twitter|tiktok|youtube|reddit|linkedin|pinterest|"
    r"snapchat|twitch|whatsapp|telegram|"
    r"newegg|amazon|ebay|etsy|walmart|best\s?buy|costco|aliexpress|temu|shein|"
    r"craigslist|zillow|airbnb|expedia|doordash|ubereats|grubhub|"
    r"gmail|outlook|hotmail|yahoo\s+mail|protonmail|"
    r"netflix|spotify|hulu|"
    r"blackboard|moodle|mindtap"
)
_CODE_HOSTS = re.compile(
    r"(?:^|\.)(?:github|gitlab|bitbucket|huggingface|pypi|npmjs|crates|readthedocs)\.", re.I
)
# A bare domain: word.tld with an optional scheme, www and path. The TLD list
# is an allowlist, so "auth.py", "timeline.py", "discord.py" and "notes.md"
# are not domains; _CODE_EXT below says the same thing explicitly.
_DOMAIN = (
    r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*"
    r"\.(?:com|net|org|io|co|app|tv|gg|edu|gov|shop|store|me|us|uk|ca|dev|ai|xyz|info|news|fm)"
    r"\b(?:/\S*)?"
)
_CODE_EXT = {
    "py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "md", "json", "yaml", "yml", "toml", "ini",
    "cfg", "txt", "csv", "html", "css", "sh", "rs", "go", "java", "c", "h", "cpp", "rb",
    "php", "sql", "lock", "env", "xml", "svg", "png", "jpg",
}

# The verbs that drive a site. "check", "look at", "watch" and "refresh" are
# not here: they are what people say about code, dates and datasets too.
_VERBS = (
    r"open(?:\s+up)?|go\s+(?:to|on|onto|over\s+to)|head\s+(?:to|over\s+to)|visit|"
    r"browse(?:\s+(?:on|through))?|pull\s+up|navigate\s+to|"
    r"log\s*(?:in|into|in\s+to|on|onto|on\s+to)|sign\s*(?:in|into|in\s+to)|"
    r"scroll(?:\s+(?:through|down|on))?"
)
# What may come before the verb: politeness, the assistant's name, "can you".
_LEAD = (
    r"^\s*(?:(?:please|pls|plz|ok|okay|hey|hi|yo|harvis|hey\s+harvis|now|just)[,!.\s]+)*"
    r"(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+|pls\s+)?"
    r"|i(?:'d|\s+would)?\s+(?:like|want|need)\s+you\s+to\s+)?"
    r"(?:please\s+)?(?:(?:go\s+ahead\s+and|just|quickly)\s+)?"
)
_TARGET = rf"(?:(?:my|the|this|our|on|onto|to|up)\s+)*(?:(?:{_SITES})(?:\.com)?\b|{_DOMAIN})"
_DRIVE_RE = re.compile(rf"{_LEAD}(?:{_VERBS})\s+{_TARGET}", re.I)
_DOMAIN_RE = re.compile(_DOMAIN, re.I)

# Asking for the browser by name. "In the browser" on its own is a fact about
# code ("does this run in a browser?"); it only counts when the message starts
# by telling Harvis to use or open something in it.
_EXPLICIT_RE = re.compile(
    rf"{_LEAD}(?:use|using|open|fire\s+up|start)\s+(?:the|a|your|my)\s+(?:web\s+)?browser\b"
    rf"|{_LEAD}(?:use|open|pull\s+up|load|check|look\s+at|show\s+me|go\s+to|visit)\b"
    r"[^.?!\n]{0,100}?\b(?:in|with|using|via|through|on)\s+(?:the|a|your|my)\s+(?:web\s+)?browser\b",
    re.I,
)
# A refusal in the same breath wins ("don't open a browser, just tell me").
_REFUSAL_RE = re.compile(
    r"\b(?:don'?t|do\s+not|no\s+need\s+to|without)\s+(?:(?:use|open|start|launch)\s+)?"
    r"(?:a\s+|the\s+|your\s+)?(?:web\s+)?(?:browser|computer)\b", re.I
)
# The one lookup that is never a browsing session: see owui_compat.chat_reach.
_WEB_SEARCH_RE = re.compile(
    r"\b(?:search|look\s*up|google)\b.{0,20}\b(?:the\s+)?(?:web|internet|online)\b"
    r"|\bweb\s*search\b|\bgoogle\s+(?:it|for|this)\b", re.I
)


def _declined(t: str) -> bool:
    return not t or bool(_REFUSAL_RE.search(t) or _WEB_SEARCH_RE.search(t))


def _is_code_host_or_file(matched: str) -> bool:
    host = _DOMAIN_RE.search(matched)
    if not host:
        return False
    raw = host.group(0)
    hostname = urlparse(raw if "://" in raw else "https://" + raw).hostname or ""
    if _CODE_HOSTS.search(hostname):
        return True
    return hostname.rsplit(".", 1)[-1].lower() in _CODE_EXT


def is_explicit_browser_request(text: str) -> bool:
    """True when the message asks for the browser by name ("use the browser to…",
    "open it in the browser"). Hermes turns this into harvis_mode=browse."""
    t = (text or "").strip()
    if _declined(t):
        return False
    return bool(_EXPLICIT_RE.search(t))


def is_browse_request(text: str) -> bool:
    """True when the message asks Harvis to drive a site, not to answer about one."""
    t = (text or "").strip()
    if _declined(t):
        return False
    if _EXPLICIT_RE.search(t):
        return True
    m = _DRIVE_RE.match(t)
    if not m:
        return False
    return not _is_code_host_or_file(m.group(0))


def _mode_of(owui_body: dict) -> str:
    return str(owui_body.get("harvis_mode") or "auto").strip().lower()


def claims_turn(owui_body: dict, message: str) -> bool:
    """Whether this chat turn belongs to the browser.

    A bot with web research switched off never browses. A forced "chat" turn
    never does, and "orchestrate" is a deliberate ask for a team; "browse"
    (Hermes read an explicit ask for the browser) always does; "auto" and
    "agent" do when the words drive a site.
    """
    if owui_body.get("harvis_research") is False:
        return False
    mode = _mode_of(owui_body)
    if mode in ("chat", "orchestrate"):
        return False
    if mode == MODE:
        return True
    return is_browse_request(message)


def asked_for_browser(owui_body: dict, message: str) -> bool:
    """Whether the user asked for the browser outright (by mode or by name),
    as opposed to the wording merely reading like a site to drive."""
    return _mode_of(owui_body) == MODE or is_explicit_browser_request(message)


async def runner_ready() -> tuple[bool, str]:
    """Whether a watchable browser can be opened right now. (ok, reason)."""
    from fastapi import HTTPException

    from . import computer

    try:
        health = await computer._runner("GET", "/health", timeout=3.0)
    except HTTPException as exc:
        return False, str(exc.detail)
    if not health.get("ok"):
        return False, "The browser runner reported it is not healthy."
    if not health.get("headedAvailable"):
        return False, "This install's browser runner has no watchable screen."
    return True, ""


def browse_goal(message: str) -> str:
    """The goal as the teammate reads it: the request, then one line that keeps
    it in the browser instead of answering from memory or a text fetch."""
    return (f"{message.strip()}\n\nDo this in the browser you share with the user "
            "(computer_open, then the other computer_* tools); do not answer from memory.")


def chat_model_pick(owui_body: dict) -> str:
    """The model the user is chatting on: Hermes's last pick, else the body's
    model. resolve_run_model still holds it to the allow-list."""
    return str(owui_body.get("harvis_last_model") or owui_body.get("model") or "")


async def maybe_handle_browse(request, owui_body: dict, user):
    """Claim the turn when it asks to drive a site; otherwise None.

    Returning None must stay cheap and side-effect free: the common chat turn
    passes through here on its way to the workspace detector.
    """
    from owui_compat.agent_bridge import _last_user_message, _messages_to_history, _plain, _sse, _stream, marker_content

    history = _messages_to_history(owui_body)
    message = _last_user_message(history)
    if not message or not claims_turn(owui_body, message):
        return None

    explicit = asked_for_browser(owui_body, message)
    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    if pool is None or user_id is None:
        if not explicit:
            return None
        return _plain("none", "Browsing needs the database, which is not available right now.")

    # Say so now rather than letting a run start and stall on its first click —
    # but only when the user asked for the browser. When the wording merely read
    # like a site to drive, the ordinary chat answer is the better fallback.
    ok, reason = await runner_ready()
    if not ok:
        if not explicit:
            logger.info("browse: runner not ready (%s); wording-only request for user %s "
                        "falls through to chat", reason, user_id)
            return None
        logger.info("browse: refused for user %s, runner not ready: %s", user_id, reason)
        return _plain("none", f"I can't open a browser right now: {reason} "
                              "Ask whoever runs this Harvis to check the browser-runner service.")

    try:
        from .store import ensure_default_assistant

        agent = await ensure_default_assistant(pool, int(user_id))
    except Exception:
        logger.exception("browse: no default assistant for user %s", user_id)
        return _plain("none", "I couldn't set up a teammate to browse for you. Pick an enabled default "
                              "assistant on the Agents page and try again.")

    # The run is the teammate's, but not its standing clearances: the gate
    # pauses every sign-in, payment, send and delete on this path.
    from . import computer
    from .intake import create_agent_run

    chat_agent = {**agent, "autonomy": {}}
    computer.withhold_clearances(int(user_id), agent["id"])
    try:
        launch = await create_agent_run(
            request=request,
            user_id=int(user_id),
            agent=chat_agent,
            goal=browse_goal(message),
            override=None,
            chat_history=history[:-1],
            session_id=owui_body.get("chat_id") or None,
            last_pick=chat_model_pick(owui_body),
        )
    except Exception:
        computer.release_withheld(int(user_id), agent["id"])
        logger.exception("browse: launch failed for user %s", user_id)
        return _plain("none", "That browsing run could not start. The workspace service may be down.")

    workspace_id = launch["workspace_id"]
    computer.bind_withheld_run(int(user_id), agent["id"], workspace_id)
    logger.info("browse: launched %s for user %s via teammate %s (model=%r via %s)",
                workspace_id, user_id, agent["id"], launch.get("model"), launch.get("model_source"))
    return _stream(_sse(workspace_id, marker_content(
        workspace_id, chat_agent, goal=message, override=bool(launch.get("override")),
    )))
