"""Which connected servers a chat message is about, and which of their tools only read.

Split from ``chat_tools`` so the pure, I/O-free half (word matching and the
read-only rule) can be read and tested on its own. Nothing here touches the
network, the database or the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_WORD_RE = re.compile(r"[a-z0-9]+")
# Words that name a transport or a TLD rather than a service. "mcp" in "github-mcp"
# must not make every message that says "mcp" match the GitHub server by name.
_GENERIC = frozenset({
    "mcp", "server", "servers", "api", "remote", "www", "com", "org", "net", "io",
    "dev", "app", "ai", "http", "https", "connector", "tools", "tool", "sse",
    "stdio", "local", "the", "npx", "uvx", "docker", "run",
})
_MAX_FALLBACK_SERVERS = 3
_CONNECTOR_RE = re.compile(r"\b(connectors?|mcp|integrations?)\b", re.I)
# A name match alone is not a request ("what do you think of GitHub?" still gets
# a plain answer); it needs the shape of one.
_CUE_RE = re.compile(
    r"(\?|\b(list|show|get|find|search|check|read|fetch|look|pull|see|view|what|which|"
    r"who|when|how|any|my|our|latest|recent|open|unread|summari[sz]e|status|tell|give|"
    r"display|count|pending|assigned)\b)", re.I)
_READ_CUE_RE = re.compile(
    r"(\?|\b(list|show|get|find|search|check|read|fetch|look|pull|see|view|what|which|"
    r"who|when|how\s+many|any|latest|recent|unread|summari[sz]e|status|tell|display|count)\b)",
    re.I)
_WRITE_INTENT_RE = re.compile(
    r"\b(create|add|post|send|delete|remove|merge|push|update|edit|close|reopen|comment|"
    r"reply|assign|publish|generate|upload|write|submit|approve|archive|rename|file\s+an?)\b",
    re.I)


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def _terms(cfg) -> set[str]:
    """Words a user would use for this server: its name and its host's brand label."""
    parts = [getattr(cfg, "server_name", "") or ""]
    try:
        host = urlsplit(getattr(cfg, "url", "") or "").hostname or ""
    except ValueError:
        host = ""
    parts.append(host)
    return {t for p in parts for t in _tokens(p) if len(t) >= 3 and t not in _GENERIC}


def _term_hit(term: str, words: set[str]) -> bool:
    if term in words or f"{term}s" in words:
        return True
    # "github" for a server called githubcopilot, and the reverse. The user's word
    # must be long enough to be a deliberate abbreviation: "higgs" (a boson) is
    # not "higgsfield".
    return any(
        (len(w) >= 6 and term.startswith(w)) or (len(w) >= 5 and len(term) >= 5 and w.startswith(term))
        for w in words
    )


def _tool_named(message: str, tools: list) -> bool:
    """True when the message spells a tool's identifier as a whole token.

    Only the identifier itself counts (``list_pull_requests``), never a spaced
    variant of it: "get me a pancake recipe" is not a call to ``get_me``.
    """
    lower = message.lower()
    for t in tools:
        name = str(t.get("name") or "").lower()
        if len(name) < 8 and not re.search(r"[_\-]", name):
            continue
        if re.search(rf"(?<![a-z0-9_\-]){re.escape(name)}(?![a-z0-9_\-])", lower):
            return True
    return False


@dataclass
class Match:
    configs: list = field(default_factory=list)
    write_intent: bool = False
    read_cue: bool = False


def gate(message: str, configs: list, cached_tools=lambda cfg: None) -> Match | None:
    """Which connected servers this message is plausibly about. No I/O."""
    if not configs or not (message or "").strip():
        return None
    words = set(_tokens(message))
    padded = f" {' '.join(_tokens(message))} "
    cued = bool(_CUE_RE.search(message) or _WRITE_INTENT_RE.search(message))
    matched = []
    for cfg in configs:
        named = cued and (
            any(_term_hit(t, words) for t in _terms(cfg))
            # "local-fs" is all generic or too-short words, so it only matches whole.
            or f" {' '.join(_tokens(cfg.server_name))} " in padded
        )
        cached = cached_tools(cfg)
        if named or (cued and cached and _tool_named(message, cached)):
            matched.append(cfg)
    if not matched and cued and _CONNECTOR_RE.search(message):
        # Cold stdio servers spawn a container to list, so warm ones first and few.
        matched = sorted(configs, key=lambda c: cached_tools(c) is None)[:_MAX_FALLBACK_SERVERS]
    if not matched:
        return None
    return Match(
        configs=matched,
        write_intent=bool(_WRITE_INTENT_RE.search(message)),
        read_cue=bool(_READ_CUE_RE.search(message)),
    )


# ── read-only classification ────────────────────────────────────────────────
_READ_VERBS = frozenset({
    "get", "list", "search", "read", "fetch", "query", "find", "describe", "show",
    "lookup", "view", "browse", "count", "retrieve", "summarize",
})
_WRITE_VERBS = frozenset({
    "create", "add", "delete", "remove", "update", "edit", "write", "send", "post",
    "push", "merge", "close", "reopen", "comment", "reply", "assign", "publish",
    "upload", "generate", "set", "put", "patch", "run", "execute", "start", "stop",
    "cancel", "submit", "approve", "archive", "rename", "move", "fork", "invite",
    "share", "deploy", "trigger", "dispatch", "transfer", "pay", "buy", "order",
    "book", "schedule", "enable", "disable", "save", "insert", "append", "clear",
    "reset", "revoke", "grant", "import", "sync", "attach", "detach",
    "replace", "kill", "drop", "purge", "destroy", "mark", "apply", "install",
    "uninstall", "restore", "register", "subscribe", "modify", "truncate", "restart",
    "terminate", "upgrade", "configure", "unlock", "toggle", "disconnect", "ack",
})
# Words that are verbs in "star_repo" but nouns in "get_label": they make a name a
# write unless the server itself says readOnlyHint, so the hint can still rescue a
# genuine read.
_WEAK_WRITE = frozenset({
    "store", "label", "tag", "pin", "star", "like", "vote", "block", "lock",
    "follow", "change", "refresh", "connect", "resolve", "accept", "reject",
})
# "find_and_replace", "list_then_drop": a second verb we may not know about.
_COMPOUND = frozenset({"and", "then", "or"})


def _name_tokens(name: str) -> list[str]:
    return _tokens(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name or ""))


def is_read_only(tool: dict) -> bool:
    """True only when calling this tool cannot change anything, as far as we can tell.

    A write verb in the name wins over a ``readOnlyHint`` — the hint is the
    server's own claim, and a tool called ``create_issue`` that says it is
    read-only is more likely wrong than right. Absent a ``readOnlyHint: true``, a
    name that chains verbs ("and"/"then"/"or") or holds a verb-or-noun like "tag"
    is a write too; and only a name that starts with a plain read verb counts, an
    unknown name being treated as a write.
    """
    tokens = _name_tokens(str(tool.get("name") or ""))
    if not tokens or any(t in _WRITE_VERBS for t in tokens):
        return False
    ann = tool.get("annotations")
    if isinstance(ann, dict):
        if ann.get("readOnlyHint") is True:
            return True
        if ann.get("readOnlyHint") is False or ann.get("destructiveHint") is True:
            return False
    if any(t in _COMPOUND or t in _WEAK_WRITE for t in tokens):
        return False
    return tokens[0] in _READ_VERBS
