"""Slash commands for the Hermes UI, mixed into ws.Connection.

The desktop handles /new, /branch, /compress, /title, /help and /research on
its own and falls back to ``slash.exec`` for the rest (/model <name>, /usage,
/web, anything typed that the registry does not know). ``commands.catalog``
feeds /help and the composer popover; ``complete.slash`` completes while typing.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import session_ops, sessions
from .rpc import err as _err, ok as _ok

# (command, description, argument hint, argument mode)
COMMANDS: tuple[tuple[str, str, str, Optional[str]], ...] = (
    ("/new", "Start a new chat", "", None),
    ("/title", "Rename this chat", "<title>", "text"),
    ("/branch", "Branch this chat into a new one", "", None),
    ("/btw", "Ask a side question in its own tab", "<question>", "text"),
    ("/compress", "Summarize older turns to free up context", "[focus]", "text"),
    ("/save", "Save this transcript as Markdown in the workspace", "", None),
    ("/status", "Show this chat's model, size and settings", "", None),
    ("/usage", "Show estimated token use and context left", "", None),
    ("/model", "Show or switch the model for this chat", "<name>", "mixed"),
    ("/web", "Turn live web search on or off for this chat", "on|off", "options"),
    ("/research", "Run deep research on a question", "<question>", "text"),
    ("/deck", "Make a slide deck (.pptx) about a topic", "<topic>", "text"),
    ("/doc", "Make a Word document (.docx) about a topic", "<topic>", "text"),
    ("/sheet", "Make a spreadsheet (.xlsx) about a topic", "<topic>", "text"),
    ("/pdf", "Make a PDF about a topic", "<topic>", "text"),
    ("/help", "List the slash commands", "", None),
)
ALIASES = {"/reset": "/new", "/clear": "/new", "/fork": "/branch", "/aside": "/btw", "/compact": "/compress", "/commands": "/help",
           "/deep-research": "/research", "/deepresearch": "/research",
           "/slides": "/deck", "/ppt": "/deck", "/powerpoint": "/deck", "/excel": "/sheet", "/word": "/doc"}
SECTIONS = (("Chat", ("/new", "/title", "/branch", "/btw", "/compress", "/save")),
            ("Info", ("/status", "/usage", "/help")),
            ("Model and search", ("/model", "/web", "/research")),
            ("Make a file", ("/deck", "/doc", "/sheet", "/pdf")))
# Each file command sends a plain request the doc detector is proven to match
# (tests/test_hermes_doc_routing.py), so a missed wording can still be forced.
FILE_COMMANDS = {"/deck": "slide deck", "/doc": "Word document", "/sheet": "spreadsheet", "/pdf": "PDF"}
# The wording the file commands send, matched by chat.requested_mode so mode words
# in the topic never override the document.
FILE_REQUEST_PREFIX = re.compile(r"^\s*Make a (?:%s) about: " % "|".join(re.escape(k) for k in FILE_COMMANDS.values()))
WEB_OPTIONS = (("on", "Search the web on every message"), ("off", "Answer without searching the web"))


def canonical(name: str) -> str:
    name = "/" + (name or "").strip().lstrip("/").lower()
    return ALIASES.get(name, name)


def _describe(cmd: str) -> str:
    return next((d for c, d, _, _ in COMMANDS if c == cmd), "")


def catalog() -> dict:
    labeled = {c: f"{c} {hint}".strip() for c, _, hint, _ in COMMANDS}
    return {
        "pairs": [[labeled[c], d] for c, d, _, _ in COMMANDS],
        "categories": [{"name": name, "pairs": [[labeled[c], _describe(c)] for c in cmds]} for name, cmds in SECTIONS],
        "canon": dict(ALIASES),
        "commands": {c: {"argument_mode": mode, "desktop": None} for c, _, _, mode in COMMANDS},
        "sub": {}, "skills": {}, "skill_count": 0, "warning": "",
    }


def help_text() -> str:
    lines = ["Slash commands:"]
    for name, cmds in SECTIONS:
        lines += ["", name]
        lines += [f"  {c} - {_describe(c)}" for c in cmds]
    return "\n".join(lines)


def complete(text: str, models: list[str]) -> dict:
    """The popover rows for what has been typed after a leading slash."""
    body = text.lstrip()
    if not body.startswith("/"):
        return {"items": [], "replace_from": 1}
    head, sep, rest = body.partition(" ")
    if not sep:
        prefix = head.lower()
        names = [c for c, _, _, _ in COMMANDS] + list(ALIASES)
        rows = sorted({canonical(n) for n in names if n.startswith(prefix)})
        return {"items": [{"text": c, "display": c, "meta": _describe(c), "kind": "command"} for c in rows],
                "replace_from": 1}
    cmd = canonical(head)
    if cmd == "/web":
        options = [(o, d) for o, d in WEB_OPTIONS if o.startswith(rest.strip().lower())]
    elif cmd == "/model":
        options = [(m, "model") for m in models if rest.strip().lower() in m.lower()][:30]
    else:
        options = []
    return {"items": [{"text": o, "display": o, "meta": d} for o, d in options], "replace_from": len(head) + 1}


class SlashMethods:
    # Provided by ws.Connection.
    pool: Any
    user_id: int
    token: str

    async def _open(self, rid, params):  # pragma: no cover - ws.Connection overrides
        raise NotImplementedError

    async def emit(self, etype, sid=None, payload=None):  # pragma: no cover
        raise NotImplementedError

    async def m_commands_catalog(self, rid, params):
        return _ok(rid, catalog())

    async def m_complete_slash(self, rid, params):
        text = str(params.get("text") or "")
        head, sep, _ = text.lstrip().partition(" ")
        models = await _model_ids(self) if sep and canonical(head) == "/model" else []
        return _ok(rid, complete(text, models))

    async def m_complete_path(self, rid, params):
        return _ok(rid, {"items": []})

    async def m_slash_exec(self, rid, params):
        command = str(params.get("command") or "").strip().lstrip("/")
        if not command:
            return _err(rid, 4004, "empty command")
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        name, _, arg = command.partition(" ")
        result = await self._run_command(s, msgs, canonical(name), arg.strip())
        return _ok(rid, result) if result is not None else _err(rid, 4004, f"unknown command: /{name}")

    async def m_command_dispatch(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        name = str(params.get("name") or "")
        result = await self._run_command(s, msgs, canonical(name), str(params.get("arg") or "").strip())
        if result is None:
            return _err(rid, 4004, f"not a quick/plugin/skill command: {name}")
        return _ok(rid, {"type": "exec", **result} if "type" not in result else result)

    async def _run_command(self, s, msgs: list[dict], cmd: str, arg: str) -> Optional[dict]:
        if cmd == "/help":
            return {"output": help_text()}
        if cmd == "/new":
            return {"output": "Use New chat in the sidebar to start a fresh conversation."}
        if cmd == "/research":
            if not arg:
                return {"output": "Usage: /research <question>"}
            return {"type": "send", "message": f"Deep research: {arg}", "notice": "Starting deep research."}
        if cmd in FILE_COMMANDS:
            if not arg:
                return {"output": f"Usage: {cmd} <topic>"}
            kind = FILE_COMMANDS[cmd]
            return {"type": "send", "message": f"Make a {kind} about: {arg}", "notice": f"Making a {kind}."}
        if cmd == "/web":
            return await self._web_command(s, arg)
        if cmd == "/title":
            if not arg:
                return {"output": f"Title: {s.title or '(untitled)'}"}
            done = await self._set_title(s, arg[:200])
            await self.emit("session.title", s.id, {"title": done["title"]})
            return {"output": f"Renamed to: {done['title']}"}
        if cmd == "/model":
            return await self._model_command(s, arg)
        if cmd == "/usage":
            stats = await self._stats(s, msgs)
            head = (f"Usage: {stats['calls']:,} replies, about {stats['input']:,} tokens in and "
                    f"{stats['output']:,} out")
            return {"output": "\n".join([head, *session_ops.usage_lines(stats)])}
        if cmd == "/status":
            return {"output": session_ops.status_text(s, msgs, await self._stats(s, msgs))}
        if cmd == "/save":
            res = await self.m_session_save(None, {"session_id": s.id})
            if "error" in res:
                return {"output": res["error"]["message"]}
            return {"output": f"Saved transcript to {res['result']['file']}"}
        if cmd == "/branch":
            try:
                child, rows = await self._branch(s, msgs)
            except ValueError as exc:
                return {"output": str(exc)}
            return {"output": f"Branched into \"{child.title}\" ({len(rows)} messages). Open it from the sidebar."}
        if cmd == "/btw":
            if not arg:
                return {"output": "Usage: /btw <question>"}
            return await self._btw(s, msgs, arg)
        if cmd == "/compress":
            if s.running:
                return {"output": "Wait for the current reply to finish, then compress."}
            done = await self._compress(s, msgs, arg)
            return {"output": done["host_ack"]["output"]}
        return None

    async def _web_command(self, s, arg: str) -> dict:
        choice = arg.lower()
        if choice in ("on", "off"):
            s.web_search = choice == "on"
            await self.emit("session.info", s.id, sessions.runtime_info(s))
        elif choice:
            return {"output": "Usage: /web on|off"}
        return {"output": f"Web search is {'on' if s.web_search else 'off'} for this chat."}

    async def _model_command(self, s, arg: str) -> dict:
        if not arg:
            return {"output": f"Model: {s.model or 'Harvis default'}\nUse /model <name> to switch; the model menu lists "
                              "what is available."}
        problem = await session_ops.model_error(self.pool, self.user_id, self.token, arg)
        if problem:
            return {"output": problem}
        s.model = "" if arg == "harvis-default" else arg
        await self.emit("session.info", s.id, sessions.runtime_info(s))
        return {"output": f"This chat now uses {arg}."}


async def _model_ids(conn) -> list[str]:
    from .rest import build_model_options

    options = await build_model_options(conn.pool, conn.user_id, conn.token)
    return [str(m) for p in options.get("providers") or [] for m in p.get("models") or []]
