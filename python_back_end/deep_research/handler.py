"""
Deep Research handler — background task registry + JSON persistence + SSE progress.

Ported (trimmed) from Odysseus's ResearchHandler. Wraps the DeepResearcher
agentic loop, runs it as a background asyncio task, persists results as JSON, and
exposes a read/control surface for the /api/research/* routes. The legacy
fallback engine and chat-session helpers were dropped — Harvis panel research only.
LLM calls go through Harvis's Ollama bridge (see researcher._llm), so only an
Ollama model id is needed (no endpoint URL / headers).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional

from .research_utils import is_low_quality, strip_thinking

logger = logging.getLogger(__name__)

# Persist under the existing writable+persistent artifact volume (the backend
# runs as uid 1001 and can't write /data root, but /data/artifacts is chowned to it).
RESEARCH_DATA_DIR = Path(os.getenv("DEEP_RESEARCH_DATA_DIR", "/data/artifacts/deep_research"))


def _bounded_int(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, n))


class ResearchHandler:
    """Background deep-research tasks with persistence + progress."""

    def __init__(self):
        self._active_tasks: Dict[str, dict] = {}
        try:
            RESEARCH_DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("deep_research: could not create %s: %s", RESEARCH_DATA_DIR, e)

    # ------------------------------------------------------------------
    # Task registry — background research with persistence
    # ------------------------------------------------------------------
    def start_research(
        self,
        session_id: str,
        query: str,
        llm_model: str,
        max_time: int = 300,
        hard_timeout: Optional[int] = None,
        prior_report: str = "",
        prior_findings: list = None,
        prior_urls: set = None,
        max_rounds: int = 20,
        search_provider: str = None,
        category: str = None,
        extraction_timeout: int = None,
        extraction_concurrency: int = None,
        owner: str = "",
    ) -> dict:
        if hard_timeout is None:
            hard_timeout = _bounded_int(
                os.getenv("DEEP_RESEARCH_RUN_TIMEOUT", "1800"),
                default=1800, minimum=60, maximum=86400,
            )
        if session_id in self._active_tasks and self._active_tasks[session_id].get("status") == "running":
            self.cancel_research(session_id)

        entry = {
            "task": None, "researcher": None, "query": query, "status": "running",
            "progress": {}, "result": None, "started_at": time.time(),
            "category": category, "owner": owner or "",
        }
        self._active_tasks[session_id] = entry

        def on_progress(event):
            entry["progress"] = event

        async def _run():
            try:
                result = await asyncio.wait_for(
                    self.call_research_service(
                        query, llm_model, max_time=max_time, progress_callback=on_progress,
                        _task_entry=entry, prior_report=prior_report,
                        prior_findings=prior_findings, prior_urls=prior_urls,
                        max_rounds=max_rounds, search_provider=search_provider,
                        category=category, extraction_timeout=extraction_timeout,
                        extraction_concurrency=extraction_concurrency,
                    ),
                    timeout=hard_timeout,
                )
                entry["result"] = result
                entry["status"] = "done"
                self._save_result(session_id, entry)
            except asyncio.TimeoutError:
                logger.error("deep_research: hard timeout (%ss) for %s", hard_timeout, session_id)
                researcher = entry.get("researcher")
                if researcher and researcher.evolving_report:
                    entry["result"] = self._format_research_report(
                        query, researcher.evolving_report, researcher.get_stats(), hard_timeout)
                    entry["status"] = "done"
                    self._save_result(session_id, entry)
                else:
                    entry["result"] = f"Research timed out after {hard_timeout}s."
                    entry["status"] = "error"
                on_progress({"phase": "error", "message": f"Research timed out after {hard_timeout}s"})
            except asyncio.CancelledError:
                entry["status"] = "cancelled"
                raise
            except Exception as e:
                logger.error("deep_research: background run failed: %s", e, exc_info=True)
                entry["result"] = str(e)
                entry["status"] = "error"

        entry["task"] = asyncio.create_task(_run())
        return {"session_id": session_id, "status": "running", "query": query}

    async def call_research_service(
        self, query: str, llm_model: str, max_time: int = 300,
        progress_callback=None, _task_entry: dict = None,
        prior_report: str = "", prior_findings: list = None, prior_urls: set = None,
        max_rounds: int = 20, search_provider: str = None, category: str = None,
        extraction_timeout: int = None, extraction_concurrency: int = None,
    ) -> str:
        if progress_callback:
            progress_callback({"phase": "probing", "model": llm_model})
        await self._probe_model(llm_model)

        from .researcher import DeepResearcher

        max_report_tokens = _bounded_int(
            os.getenv("DEEP_RESEARCH_MAX_TOKENS", "16384"),
            default=16384, minimum=1024, maximum=32768,
        )
        researcher = DeepResearcher(
            llm_endpoint="", llm_model=llm_model, llm_headers=None,
            max_rounds=max_rounds, min_rounds=min(3, max_rounds), max_time=max_time,
            max_report_tokens=max_report_tokens,
            extraction_timeout=extraction_timeout or 90,
            extraction_concurrency=extraction_concurrency or 3,
            progress_callback=progress_callback,
            search_provider=search_provider, category=category,
        )
        if _task_entry is not None:
            _task_entry["researcher"] = researcher

        start = time.time()
        report = await researcher.research(
            query, prior_report=prior_report,
            prior_findings=prior_findings, prior_urls=prior_urls,
        )
        elapsed = time.time() - start
        stats = researcher.get_stats()
        if _task_entry is not None:
            _task_entry["raw_report"] = strip_thinking(report)
            _task_entry["stats"] = stats
        return self._format_research_report(query, report, stats, elapsed)

    @staticmethod
    async def _probe_model(llm_model: str):
        """Quick liveness probe (local Ollama direct) so we fail fast."""
        import httpx
        base = os.getenv("DEEP_RESEARCH_OLLAMA_URL",
                         os.getenv("OLLAMA_URL", "http://ollama:11434")).rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(
                    f"{base}/api/chat",
                    json={"model": llm_model, "messages": [{"role": "user", "content": "hi"}],
                          "stream": False, "options": {"num_predict": 5}},
                )
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(
                f"Cannot reach model '{llm_model}' at {base} — is it pulled in Ollama? ({e})"
            ) from e

    # ------------------------------------------------------------------
    # Read / control surface
    # ------------------------------------------------------------------
    def get_status(self, session_id: str) -> Optional[dict]:
        if session_id in self._active_tasks:
            e = self._active_tasks[session_id]
            return {"status": e["status"], "progress": e["progress"],
                    "query": e["query"], "started_at": e["started_at"]}
        data = self._get_session_json(session_id)
        if data and not data.get("consumed"):
            return {"status": data.get("status", "done"), "progress": {},
                    "query": data.get("query", ""), "started_at": data.get("started_at", 0)}
        return None

    def cancel_research(self, session_id: str) -> bool:
        if session_id not in self._active_tasks:
            return False
        entry = self._active_tasks[session_id]
        if entry["status"] != "running":
            return False
        researcher = entry.get("researcher")
        if researcher:
            researcher.cancel()
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        entry["status"] = "cancelled"
        return True

    def get_result(self, session_id: str) -> Optional[str]:
        if session_id in self._active_tasks:
            e = self._active_tasks[session_id]
            if e["status"] in ("done", "error", "cancelled"):
                return e.get("result")
        data = self._get_session_json(session_id)
        if data and not data.get("consumed"):
            return data.get("result")
        return None

    def get_sources(self, session_id: str) -> Optional[list]:
        if session_id in self._active_tasks:
            e = self._active_tasks[session_id]
            if e.get("sources"):
                return e["sources"]
            r = e.get("researcher")
            if r and r.findings:
                return self._extract_sources(r.findings)
        data = self._get_session_json(session_id)
        return data.get("sources") if data else None

    def get_raw_findings(self, session_id: str) -> Optional[list]:
        if session_id in self._active_tasks:
            r = self._active_tasks[session_id].get("researcher")
            if r and r.findings:
                return self._extract_raw_findings(r.findings)
        data = self._get_session_json(session_id)
        return data.get("raw_findings") if data else None

    def clear_result(self, session_id: str):
        self._active_tasks.pop(session_id, None)
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["consumed"] = True
                path.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _extract_sources(findings: list) -> list:
        seen, sources = set(), []
        for f in findings:
            url = f.get("url", "")
            title = f.get("title", "") or url
            summary = f.get("summary", "") or f.get("evidence", "")
            if url and url not in seen and not is_low_quality(summary):
                seen.add(url)
                entry = {"url": url, "title": title}
                if f.get("og_image"):
                    entry["image"] = f["og_image"]
                sources.append(entry)
        return sources

    @staticmethod
    def _extract_raw_findings(findings: list) -> list:
        items = []
        for f in findings:
            url = f.get("url", "")
            title = f.get("title", "") or "Untitled"
            content = f.get("summary", "") or (f.get("evidence", "")[:2000])
            if url and content and not is_low_quality(content):
                items.append({"url": url, "title": title, "summary": content})
        return items

    def get_avg_duration(self) -> Optional[float]:
        durations = []
        try:
            for p in RESEARCH_DATA_DIR.glob("*.json"):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    s, c = d.get("started_at", 0), d.get("completed_at", 0)
                    if d.get("status") == "done" and s and c and c > s:
                        durations.append(c - s)
                except Exception:
                    continue
        except Exception:
            pass
        return sum(durations) / len(durations) if durations else None

    def _save_result(self, session_id: str, entry: dict):
        try:
            sources, raw_findings = [], []
            r = entry.get("researcher")
            if r and r.findings:
                sources = self._extract_sources(r.findings)
                raw_findings = self._extract_raw_findings(r.findings)
            entry["sources"] = sources
            data = {
                "query": entry["query"], "status": entry["status"], "result": entry["result"],
                "raw_report": entry.get("raw_report", ""), "sources": sources,
                "raw_findings": raw_findings, "stats": entry.get("stats"),
                "category": entry.get("category"), "started_at": entry["started_at"],
                "completed_at": time.time(), "owner": entry.get("owner", ""),
            }
            (RESEARCH_DATA_DIR / f"{session_id}.json").write_text(json.dumps(data), encoding="utf-8")
            logger.info("deep_research: saved result %s", session_id)
        except Exception as e:
            logger.error("deep_research: failed to save result: %s", e)

    def _get_session_json(self, session_id: str) -> Optional[dict]:
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def get_report_html(self, session_id: str) -> Optional[str]:
        data = self._get_session_json(session_id)
        if not data:
            return None
        try:
            from .visual_report import generate_visual_report
            return generate_visual_report(
                question=data.get("query", ""),
                report_markdown=data.get("raw_report") or data.get("result", ""),
                sources=data.get("sources"),
                stats=data.get("stats"),
                category=data.get("category"),
                session_id=session_id,
                hidden_images=data.get("hidden_images") or [],
            )
        except Exception as e:
            logger.error("deep_research: visual report failed: %s", e, exc_info=True)
            return None

    def hide_image(self, session_id: str, image_url: str) -> bool:
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            hidden = data.get("hidden_images") or []
            if image_url not in hidden:
                hidden.append(image_url)
                data["hidden_images"] = hidden
                path.write_text(json.dumps(data), encoding="utf-8")
            return True
        except Exception as e:
            logger.error("deep_research: hide_image failed: %s", e)
            return False

    def unhide_all_images(self, session_id: str) -> bool:
        path = RESEARCH_DATA_DIR / f"{session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["hidden_images"] = []
            path.write_text(json.dumps(data), encoding="utf-8")
            return True
        except Exception as e:
            logger.error("deep_research: unhide failed: %s", e)
            return False

    def _format_research_report(self, query: str, full_report: str, stats: dict, elapsed: float) -> str:
        full_report = strip_thinking(full_report) or ""
        summary = " | ".join([
            f"**Duration:** {elapsed:.1f}s",
            f"**Rounds:** {stats.get('Rounds', '?')}",
            f"**Queries:** {stats.get('Queries', '?')}",
            f"**URLs Analyzed:** {stats.get('URLs', '?')}",
        ])
        return f"---\n\n## Research Summary\n\n{summary}\n\n---\n\n{full_report}\n"
