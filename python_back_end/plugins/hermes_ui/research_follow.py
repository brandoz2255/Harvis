"""Follow a deep-research run started from chat and bring it into the reply.

The OWUI compat layer answers "deep research X" with a ``research_run`` marker
(owui_compat/research_bridge.py) and runs the job in the background. The
Hermes UI has no research card, so the run is shown with what it does have:
each round's searches and the pages being read stream as grey reasoning
lines, and the finished report, its sources, and a link to the report page
become the reply text. Because the report is the reply, later turns in the
same chat have it in their history, and a follow-up "dig deeper" run finds the
research id in that text and builds on the saved findings.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger("hermes_ui.research")

RESEARCH_URL = os.getenv("HARVIS_HERMES_UI_RESEARCH_URL", "http://127.0.0.1:8000/api/research")
POLL_SECONDS = 2.0
MAX_WAIT_SECONDS = 35 * 60
MAX_SOURCES_LISTED = 40


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Cookie": f"access_token={token}"}


def progress_line(p: dict) -> str:
    """One readable line per progress event, or "" when there is nothing new to say."""
    phase = str(p.get("phase") or "")
    rnd = f"Round {p['round']}: " if p.get("round") else ""
    total = p.get("total_sources")
    if phase == "planning":
        return "Planning the research"
    if phase == "searching":
        queries = p.get("queries")
        latest = queries[-1] if isinstance(queries, list) and queries else ""
        return f"{rnd}searching" + (f" “{latest}”" if latest else "") + (f" ({total} sources so far)" if total else "")
    if phase == "reading" and p.get("url"):
        return f"Reading {p.get('title') or p['url']}"
    if phase == "reading":
        return f"{rnd}{p.get('new_sources', 0)} new findings, {total or 0} sources read"
    if phase == "analyzing":
        return f"{rnd}analysing what was found"
    if phase == "writing":
        return str(p.get("message") or f"Writing the report from {total or 0} sources")
    if phase in ("warning", "error"):
        return str(p.get("message") or phase)
    return ""


def report_text(research_id: str, result: str, sources: list, origin: str) -> str:
    urls = [s.get("url") for s in sources if isinstance(s, dict) and s.get("url")]
    body = (result or "").strip() or "The research finished without a report."
    listed = [u for u in urls if u not in body][:MAX_SOURCES_LISTED]
    if listed and len(listed) * 2 > len(urls):
        titles = {s.get("url"): s.get("title") for s in sources if isinstance(s, dict)}
        body += "\n\n### Sources\n\n" + "\n".join(f"- [{titles.get(u) or u}]({u})" for u in listed)
    page = f"{origin}/hermes/#/research?id={research_id}" if origin else ""
    footer = f"[Open the report page]({page}) · " if page else ""
    return f"{body}\n\n---\n{footer}{len(urls)} sources · research `{research_id}`"


async def follow_research(token: str, research_id: str, origin: str = "") -> AsyncIterator[tuple[str, Any]]:
    """Yield ("reasoning", line) while the run works, then ("text", report)."""
    started = time.monotonic()
    seen: set[str] = set()
    status = "running"
    progress: dict = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            yield "reasoning", "Deep research started\n"
            while status == "running" and time.monotonic() - started < MAX_WAIT_SECONDS:
                await asyncio.sleep(POLL_SECONDS)
                resp = await client.get(f"{RESEARCH_URL}/status/{research_id}", headers=_headers(token))
                if resp.status_code != 200:
                    raise RuntimeError(f"research status HTTP {resp.status_code}")
                data = resp.json()
                status = str(data.get("status") or "running")
                progress = data.get("progress") or {}
                line = progress_line(progress)
                if line and line not in seen:
                    seen.add(line)
                    yield "reasoning", line + "\n"
            if status == "running":
                yield "text", f"Research `{research_id}` is still running; it will appear on the Research page when it finishes."
                return
            if status != "done":
                reason = progress.get("message") or status
                yield "text", f"The research did not finish: {reason}"
                return
            resp = await client.post(f"{RESEARCH_URL}/result-peek/{research_id}", headers=_headers(token))
            if resp.status_code != 200:
                raise RuntimeError(f"research result HTTP {resp.status_code}")
            data = resp.json()
            yield "text", report_text(research_id, str(data.get("result") or ""), data.get("sources") or [], origin)
    except asyncio.CancelledError:
        await cancel_research(token, research_id)
        raise


async def cancel_research(token: str, research_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{RESEARCH_URL}/cancel/{research_id}", headers=_headers(token))
    except Exception as exc:  # noqa: BLE001
        log.warning("hermes_ui: cancel of research %s failed: %s", research_id, exc)
