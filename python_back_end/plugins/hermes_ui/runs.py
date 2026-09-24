"""Follow a Harvis workspace run and translate its events for the Hermes UI.

The OWUI compat layer answers image / workspace turns with a run-card marker
and streams the run on /api/workspace/stream/{id} (flat `{type, ...}` JSON).
The Hermes UI has no run card, so the run is shown with what it does have:
tool cards (tool.start / tool.complete), grey reasoning lines for the run's
own narration, and the final answer (with artifact links) as the reply text.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, AsyncIterator

import httpx

from .chat import ChatError

log = logging.getLogger("hermes_ui.runs")

WORKSPACE_URL = os.getenv("HARVIS_HERMES_UI_WORKSPACE_URL", "http://127.0.0.1:8000/api/workspace")
_API_LINK_RE = re.compile(r"\]\((/api/[^)\s]+)\)")
_OUTPUT_CAP = 4000


def absolutize(text: str, origin: str) -> str:
    """Markdown links to `/api/...` need the page origin: the UI treats a bare
    root path as a local file, not a URL."""
    if not origin or not text:
        return text
    return _API_LINK_RE.sub(lambda m: f"]({origin}{m.group(1)})", text)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Cookie": f"access_token={token}"}


async def cancel_run(token: str, workspace_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{WORKSPACE_URL}/cancel/{workspace_id}", headers=_headers(token))
    except Exception as exc:  # noqa: BLE001
        log.warning("hermes_ui: cancel of run %s failed: %s", workspace_id, exc)


def _s(value: Any, cap: int = _OUTPUT_CAP) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[-cap:] if len(text) > cap else text


class _Translator:
    def __init__(self, workspace_id: str, origin: str):
        self.ws = workspace_id
        self.origin = origin
        self.n = 0
        self.open: dict[str, list[str]] = {}
        self.terminals: dict[str, dict] = {}
        self.artifacts: list[tuple[str, str, str]] = []
        self.final_text = ""

    def _new_id(self, tag: str) -> str:
        self.n += 1
        return f"{self.ws}-{tag}{self.n}"

    def _tool_start(self, name: str, args: Any) -> tuple[str, dict]:
        tid = self._new_id("t")
        self.open.setdefault(name, []).append(tid)
        return "tool.start", {"tool_id": tid, "name": name, "args": args if isinstance(args, dict) else {"input": args}}

    def _tool_complete(self, name: str, success: bool, output: Any) -> tuple[str, dict]:
        ids = self.open.get(name) or []
        tid = ids.pop() if ids else self._new_id("t")
        payload: dict = {"tool_id": tid, "name": name, "result": {"output": _s(output)}}
        if not success:
            payload["error"] = _s(output, 2000) or "failed"
        return "tool.complete", payload

    def _terminal(self, ev: dict) -> list[tuple[str, Any]]:
        cid = str(ev.get("command_id") or "cmd")
        out: list[tuple[str, Any]] = []
        entry = self.terminals.get(cid)
        if entry is None:
            entry = {"id": self._new_id("c"), "out": []}
            self.terminals[cid] = entry
            target = ev.get("target") or {}
            out.append(("tool.start", {"tool_id": entry["id"], "name": "terminal",
                                       "args": {"command_id": cid, "target": target.get("id") or target.get("kind") or ""}}))
        content = ev.get("content")
        if isinstance(content, str) and content:
            entry["out"].append(content)
        code = ev.get("exit_code")
        if code is not None:
            payload: dict = {"tool_id": entry["id"], "name": "terminal",
                             "result": {"output": _s("".join(entry["out"])), "exit_code": code}}
            if code:
                payload["error"] = f"exit code {code}"
            out.append(("tool.complete", payload))
        return out

    def _artifact_lines(self) -> str:
        lines = []
        for aid, label, mime in self.artifacts:
            if aid and aid in self.final_text:
                continue
            url = f"{self.origin}/api/workspace/artifact/{aid}/raw"
            lines.append(f"![{label}]({url})" if mime.startswith("image/") else f"📎 [{label}]({url})")
        return ("\n\n" + "\n".join(lines) + "\n") if lines else ""

    def translate(self, ev: dict) -> list[tuple[str, Any]]:
        t = ev.get("type")
        if t == "tool_call":
            return [self._tool_start(str(ev.get("tool") or "tool"), ev.get("args") or {})]
        if t == "tool_result":
            return [self._tool_complete(str(ev.get("tool") or "tool"), bool(ev.get("success", True)), ev.get("output", ""))]
        if t == "terminal_output":
            return self._terminal(ev)
        if t == "decision":
            policy, tool, reason = ev.get("policy"), ev.get("tool") or "tool", ev.get("reason") or ""
            if policy == "deny":
                return [("text", f"\n\n⛔ `{tool}` was blocked: {reason}\n")]
            if policy == "gate":
                return [("text", f"\n\n⏸ `{tool}` needs approval ({reason}). Approve it from the Harvis workspace page.\n")]
            return []
        if t == "artifact":
            self.artifacts.append((str(ev.get("artifact_id") or ""), str(ev.get("label") or ev.get("path") or "artifact"),
                                   str(ev.get("mime_type") or "")))
            return []
        if t == "agent_message":
            return [("reasoning", f"**{ev.get('label') or ev.get('role') or 'agent'}:** {ev.get('content') or ''}\n\n")]
        if t == "restated_goal":
            return [("reasoning", f"Goal: {ev.get('restated_goal') or ''}\n\n")]
        if t == "plan":
            steps = ev.get("steps") or []
            lines = "\n".join(f"{i + 1}. {s.get('label') or s.get('task') or ''}" for i, s in enumerate(steps) if isinstance(s, dict))
            return [("reasoning", f"Plan:\n{lines}\n\n")] if lines else []
        if t == "step_started":
            return [("reasoning", f"Step {ev.get('n') or ''}: {ev.get('label') or ''} ({ev.get('engine') or 'engine'})\n\n")]
        if t == "final_message":
            self.final_text = absolutize(str(ev.get("content") or ""), self.origin)
            return [("text", self.final_text)] if self.final_text else []
        if t == "done":
            out: list[tuple[str, Any]] = []
            summary = str(ev.get("summary") or "")
            if not self.final_text and summary:
                self.final_text = absolutize(summary, self.origin)
                out.append(("text", self.final_text))
            extra = self._artifact_lines()
            if extra:
                out.append(("text", extra))
            return out
        if t == "cancelled":
            return [("text", "\n\n[cancelled]")]
        if t == "error":
            raise ChatError(str(ev.get("message") or "workspace run failed"))
        return []


async def follow_run(token: str, workspace_id: str, origin: str) -> AsyncIterator[tuple[str, Any]]:
    tr = _Translator(workspace_id, origin)
    timeout = httpx.Timeout(connect=10.0, read=1800.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", f"{WORKSPACE_URL}/stream/{workspace_id}", headers=_headers(token)) as resp:
            if resp.status_code != 200:
                raise ChatError(f"workspace stream HTTP {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                if ev.get("type") == "stream_end":
                    return
                for item in tr.translate(ev):
                    yield item
