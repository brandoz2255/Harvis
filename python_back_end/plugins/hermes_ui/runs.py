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
import time
from typing import Any, AsyncIterator

import httpx

from .chat import ChatError

log = logging.getLogger("hermes_ui.runs")

WORKSPACE_URL = os.getenv("HARVIS_HERMES_UI_WORKSPACE_URL", "http://127.0.0.1:8000/api/workspace")
_API_LINK_RE = re.compile(r"\]\((/api/[^)\s]+)\)")
_OUTPUT_CAP = 4000
_MAX_FOLLOWUPS = 3
# TOOL_SCHEMA tools (workspace/orchestration/tools.py) that write the file named by their `path` arg.
_WRITE_TOOLS = frozenset({"edit_file", "str_replace", "apply_patch"})
# coordinator.py appends this to the done summary; the same list is sent as a followups item.
_NEXT_BLOCK_RE = re.compile(r"\s*Worth doing next:[ \t]*(?:\n[ \t]*[-*•][^\n]*)*\s*\Z")
_PREVIEW_KEYS = ("command", "cmd", "path", "file", "file_path", "query", "url", "pattern", "text", "content")


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


def _preview(args: Any, cap: int = 96) -> str:
    """One line saying what a tool call is about, for a subagent row."""
    if isinstance(args, dict):
        for key in _PREVIEW_KEYS:
            if args.get(key):
                args = args[key]
                break
    text = args if isinstance(args, str) else json.dumps(args, default=str) if args else ""
    return " ".join(text.split())[:cap]


def _followups(raw: Any) -> list[dict]:
    """[{title, prompt}] from whatever the run calls its "worth doing next" list: strings or objects."""
    items = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict):
            prompt = str(entry.get("prompt") or entry.get("task") or entry.get("text") or entry.get("title") or "")
            title = str(entry.get("title") or entry.get("label") or prompt)
        else:
            prompt = title = str(entry)
        prompt, title = " ".join(prompt.split()), " ".join(title.split())
        if prompt:
            items.append({"title": title if len(title) <= 60 else title[:59].rstrip() + "…", "prompt": prompt})
    return items[:_MAX_FOLLOWUPS]


class _Translator:
    def __init__(self, workspace_id: str, origin: str):
        self.ws = workspace_id
        self.origin = origin
        self.n = 0
        self.open: dict[str, list[str]] = {}
        self.terminals: dict[str, dict] = {}
        self.artifacts: list[tuple[str, str, str]] = []
        self.final_text = ""
        self.task_count = 0
        self.steps: dict[str, dict] = {}  # step child run id -> {label, n, started, tools}
        self.followups_sent = False
        self.error: ChatError | None = None  # set by an 'error' event; follow_run raises it after the flush

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

    def _step_started(self, ev: dict) -> list[tuple[str, Any]]:
        child = str(ev.get("step_run_id") or "")
        label, n = str(ev.get("label") or ""), int(ev.get("n") or 0)
        line = ("reasoning", f"Step {n or ''}: {label} ({ev.get('engine') or 'engine'})\n\n")
        if not child:
            return [line]
        self.steps[child] = {"label": label, "n": n, "started": time.monotonic(), "tools": 0, "files": []}
        start: dict = {"subagent_id": child, "goal": label, "task_index": max(n - 1, 0),
                       "task_count": max(self.task_count, n), "status": "running"}
        if ev.get("engine"):
            start["engine"] = str(ev["engine"])
        return [line, ("subagent.start", start)]

    def _step_end(self, step: dict, child: str, ev: dict, status: str | None = None) -> list[tuple[str, Any]]:
        """Complete a step from its agent_end (`ev`), or force it closed with `status` when the run ended first."""
        seconds = ev.get("duration_ms")
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            seconds = None
        done: dict = {"subagent_id": child, "goal": step["label"], "task_index": max(step["n"] - 1, 0),
                      "task_count": max(self.task_count, step["n"]),
                      "status": status or ("failed" if ev.get("success") is False else "completed"),
                      "summary": str(ev.get("summary") or ""), "tool_count": step["tools"],
                      "duration_seconds": round(seconds / 1000 if seconds is not None else time.monotonic() - step["started"], 1)}
        if ev.get("model"):
            done["model"] = str(ev["model"])
        if step["files"]:
            done["files_written"] = list(step["files"])
        usage = ev.get("usage_detail") if isinstance(ev.get("usage_detail"), dict) else {}
        # prompt_tokens is only the last call's context size; usage_detail.input is the step's billed total.
        for dst, value in (("input_tokens", usage.get("input", ev.get("prompt_tokens"))),
                           ("output_tokens", usage.get("output", ev.get("completion_tokens")))):
            if isinstance(value, int) and not isinstance(value, bool):
                done[dst] = value
        return [("subagent.complete", done)]

    def _close_steps(self, status: str) -> list[tuple[str, Any]]:
        """A run that ends with steps still open would leave their rows running forever."""
        out: list[tuple[str, Any]] = []
        for child, step in list(self.steps.items()):
            out += self._step_end(step, child, {}, status)
        self.steps.clear()
        return out

    def finish(self) -> list[tuple[str, Any]]:
        """The stream ended without a terminal event."""
        return self._close_steps("interrupted")

    def _strip_next_block(self, text: str) -> str:
        return _NEXT_BLOCK_RE.sub("", text) if self.followups_sent else text

    def _suggested(self, ev: dict) -> list[tuple[str, Any]]:
        if self.followups_sent or ev.get("status") == "running":  # "running": the run is doing them itself
            return []
        items = _followups(ev.get("suggestions"))
        self.followups_sent = bool(items)
        return [("followups", {"items": items})] if items else []

    def translate(self, ev: dict) -> list[tuple[str, Any]]:
        t = ev.get("type")
        step = self.steps.get(str(ev.get("run_id") or ""))
        if t == "tool_call":
            args = ev.get("args") or {}
            out = [self._tool_start(str(ev.get("tool") or "tool"), args)]
            if step:
                step["tools"] += 1
                path = args.get("path") if isinstance(args, dict) else None
                # Counted when its tool_result succeeds: a denied or failed edit wrote nothing.
                step["pending"] = path if ev.get("tool") in _WRITE_TOOLS and isinstance(path, str) and path \
                    and not args.get("delete") else None
                out.append(("subagent.tool", {"subagent_id": ev["run_id"], "tool_name": str(ev.get("tool") or "tool"),
                                              "tool_preview": _preview(args)}))
            return out
        if t == "agent_end" and step:
            del self.steps[str(ev["run_id"])]
            return self._step_end(step, ev["run_id"], ev)
        if t == "propose_next":
            return self._suggested(ev)
        if t == "tool_result":
            pending = step.pop("pending", None) if step else None
            if pending and ev.get("success", True) and pending not in step["files"]:
                step["files"].append(pending)
            return [self._tool_complete(str(ev.get("tool") or "tool"), bool(ev.get("success", True)), ev.get("output", ""))]
        if t == "terminal_output":
            return self._terminal(ev)
        if t == "exec_output":
            # The agent's exec, live, for its read-only terminal tab. The tool
            # card for the same call still comes from tool_call/tool_result.
            pid = str(ev.get("command_id") or "exec")
            chunk = str(ev.get("content") or "")
            if "ok" in ev:
                chunk += "\n[done]\n" if ev.get("ok") else "\n[finished with an error]\n"
            payload: dict = {"process_id": pid, "chunk": chunk}
            if ev.get("command"):
                payload["command"] = str(ev["command"])
            return [("agent_terminal", payload)] if chunk or "command" in payload else []
        if t == "decision":
            policy, tool, reason = ev.get("policy"), ev.get("tool") or "tool", ev.get("reason") or ""
            if policy == "deny":
                return [("text", f"\n\n⛔ `{tool}` was blocked: {reason}\n")]
            if policy == "gate":
                from .ws_approvals import delivers_for_run
                if delivers_for_run(self.ws):
                    return []  # the approval prompt is raised in this chat
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
            self.task_count = len([s for s in steps if isinstance(s, dict)])
            return [("reasoning", f"Plan:\n{lines}\n\n")] if lines else []
        if t == "step_started":
            return self._step_started(ev)
        if t == "final_message":
            suggested = self._suggested(ev)
            self.final_text = self._strip_next_block(absolutize(str(ev.get("content") or ""), self.origin))
            return ([("text", self.final_text)] if self.final_text else []) + suggested
        if t == "done":
            out = self._close_steps("interrupted")  # every step ends in its own agent_end before done
            suggested = self._suggested(ev)
            summary = str(ev.get("summary") or "")
            if not self.final_text and summary:
                self.final_text = self._strip_next_block(absolutize(summary, self.origin))
                if self.final_text:
                    out.append(("text", self.final_text))
            extra = self._artifact_lines()
            if extra:
                out.append(("text", extra))
            return out + suggested
        if t == "cancelled":
            return self._close_steps("interrupted") + [("text", "\n\n[cancelled]")]
        if t == "error":
            self.error = ChatError(str(ev.get("message") or "workspace run failed"))
            return self._close_steps("failed")
        return []


async def follow_run(token: str, workspace_id: str, origin: str) -> AsyncIterator[tuple[str, Any]]:
    tr = _Translator(workspace_id, origin)
    timeout = httpx.Timeout(connect=10.0, read=1800.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", f"{WORKSPACE_URL}/stream/{workspace_id}", headers=_headers(token)) as resp:
            if resp.status_code != 200:
                raise ChatError(f"workspace stream HTTP {resp.status_code}")
            try:
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
                        break
                    for item in tr.translate(ev):
                        yield item
                    if tr.error:
                        raise tr.error
            except httpx.HTTPError:
                # A dropped stream ends the turn with an error; settle the open steps first.
                for item in tr._close_steps("failed"):
                    yield item
                raise
        for item in tr.finish():
            yield item
