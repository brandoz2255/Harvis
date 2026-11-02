"""Insights generated for a source as soon as it is ready.

After ingestion marks a source READY, a background task writes a Dense Summary and
3 to 5 suggested questions, plus every custom transformation the user flagged
``apply_default``. Results land where on-demand insights already live
(``notebook_transformations``, so the Sources panel lists them), and the source's
metadata records ``insights_status`` (``pending``, ``done`` or ``error``) and the
suggested questions. Nothing here can fail a source: errors are logged and recorded,
and the task retries twice with backoff.

The task runs inside this process. A restart leaves rows at ``pending``;
``fail_stuck_insights`` marks them so the panel stops showing a spinner.

The Dense Summary prompt follows the idea of open-notebook's seeded transformation of the
same name (MIT, (c) 2024 Luis Novo), rewritten to read well for people, not only models.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from . import transform_llm

logger = logging.getLogger(__name__)

RETRY_BACKOFF_S = (2.0, 8.0)  # two retries after the first attempt
DEFAULT_MAX_CHARS = 400_000
MAX_DEFAULT_TRANSFORMS = 3
SUMMARY_MARKER = "auto:dense_summary"
QUESTIONS_MARKER = "auto:suggested_questions"

DENSE_SUMMARY_PROMPT = (
    "You are an expert analyst. Write a dense summary of the content below for someone who has not read it.\n"
    "- Use short, complete sentences and bullet points grouped under a few bold headings.\n"
    "- Capture the main claims, definitions, numbers, names and conclusions with as few words as possible.\n"
    "- Use only what the content says. Do not add outside facts and do not mention these instructions.\n\n"
    "Content:\n\n{content}"
)
QUESTIONS_PROMPT = (
    "Write 4 questions a reader could ask about the content below, each one answerable from the content itself.\n"
    "Output exactly one question per line, ending with a question mark, with no numbering, bullets or "
    "extra text.\n\nContent:\n\n{content}"
)

_tasks: Dict[str, "asyncio.Task[None]"] = {}


class InsightsSkipped(Exception):
    """Insights cannot run and retrying will not help (blocked person, no model, source gone)."""


def enabled() -> bool:
    return (os.getenv("NOTEBOOK_AUTO_INSIGHTS", "1").strip().lower() not in ("0", "false", "no", "off"))


def max_chars() -> int:
    try:
        return max(1000, int(os.getenv("NOTEBOOK_AUTO_INSIGHTS_MAX_CHARS", "") or DEFAULT_MAX_CHARS))
    except ValueError:
        return DEFAULT_MAX_CHARS


def should_run(text_length: int) -> bool:
    """Insights are on by default and skipped for sources too long to summarise cheaply."""
    return enabled() and text_length <= max_chars()


def parse_questions(raw: str) -> List[str]:
    """3 to 5 questions from a model reply, one per line. Raises ValueError when there are fewer than 3."""
    found: List[str] = []
    for line in (raw or "").replace("```", "\n").splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"')
        if len(line) >= 8 and line.endswith("?") and line not in found:
            found.append(line[:300])
    if len(found) < 3:
        raise ValueError("The model did not return enough questions.")
    return found[:5]


def schedule_default_insights(manager, source_id: UUID, user_id: int) -> bool:
    """Start the background task for a READY source. Never raises; returns whether it started."""
    try:
        key = str(source_id)
        previous = _tasks.get(key)
        if previous and not previous.done():
            previous.cancel()
        task = asyncio.get_running_loop().create_task(run_default_insights(manager, source_id, user_id))
        _tasks[key] = task
        task.add_done_callback(lambda t, k=key: _tasks.pop(k, None) if _tasks.get(k) is t else None)
        return True
    except Exception:
        logger.warning("Could not schedule insights for source %s", source_id, exc_info=True)
        return False


async def run_default_insights(manager, source_id: UUID, user_id: int) -> None:
    """Generate the insights, retrying twice with backoff, and record the outcome. Never raises."""
    failure = "Insights could not be generated."
    try:
        for attempt in range(len(RETRY_BACKOFF_S) + 1):
            try:
                await _generate(manager, source_id, user_id)
                return
            except InsightsSkipped as exc:
                failure = str(exc) or failure
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = f"Insights failed ({type(exc).__name__}). Open the source to try again."
                logger.warning("Insights attempt %s failed for source %s: %s", attempt + 1, source_id, exc)
                if attempt < len(RETRY_BACKOFF_S):
                    await asyncio.sleep(RETRY_BACKOFF_S[attempt])
        await _merge_metadata(manager, source_id, {"insights_status": "error", "insights_error": failure[:240]})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Could not record the insights outcome for source %s", source_id, exc_info=True)


async def _merge_metadata(manager, source_id: UUID, update: Dict[str, Any]) -> None:
    async with manager.db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE notebook_sources SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
            json.dumps(update, default=str),
            source_id,
        )


async def _pick_model(manager, user_id: int) -> str:
    """The model this person may run: the admin's first allowed model, else the server default.
    Not counted against the daily message limit; a person who is blocked or limited gets nothing."""
    from plugins.people.controls import admit_turn

    admitted = await admit_turn(manager.db_pool, int(user_id), "", count=False)
    if not admitted.ok:
        raise InsightsSkipped(admitted.reason or "Your account may not run models right now.")
    model = admitted.model or await transform_llm.default_chat_model()
    if not model:
        raise InsightsSkipped("No chat model is installed to write insights with.")
    return model


async def _default_transforms(manager, user_id: int) -> List[Dict[str, Any]]:
    try:
        async with manager.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, COALESCE(title, name) AS title, prompt FROM notebook_transformation_defs "
                "WHERE user_id = $1 AND apply_default ORDER BY created_at LIMIT $2",
                user_id,
                MAX_DEFAULT_TRANSFORMS,
            )
    except Exception:
        logger.info("Custom default transformations are unavailable; skipping them", exc_info=True)
        return []
    return [{"id": str(r["id"]), "title": r["title"], "prompt": r["prompt"]} for r in rows]


async def _store(manager, notebook_id, source_id, user_id, marker: str, kind: str, original: str, output: str, model: str):
    """Replace this source's earlier result for ``marker`` with ``output``. Returns the new row id."""
    async with manager.db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM notebook_transformations WHERE source_id = $1 AND user_id = $2 AND custom_prompt = $3",
                source_id, user_id, marker,
            )
            return await conn.fetchval(
                "INSERT INTO notebook_transformations "
                "(notebook_id, source_id, user_id, transformation_type, original_content, transformed_content, "
                "model_used, custom_prompt) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                notebook_id, source_id, user_id, kind, original[:2000], output, model, marker,
            )


async def _generate(manager, source_id: UUID, user_id: int) -> None:
    from .manager import SourceNotFoundError

    try:
        await manager.get_source(source_id, user_id)  # owner check; raises when the source is gone
    except SourceNotFoundError as exc:
        raise InsightsSkipped("The source no longer exists.") from exc
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT notebook_id, content_text, status FROM notebook_sources WHERE id = $1", source_id
        )
    if not row or row["status"] != "ready" or not (row["content_text"] or "").strip():
        raise InsightsSkipped("The source is being processed again.")
    notebook_id, text = row["notebook_id"], row["content_text"]
    model = await _pick_model(manager, user_id)

    def call(prompt: str, **kw):
        return transform_llm.run_transformation_llm(prompt, text, model, spread=True, max_chars=12000, **kw)

    summary = (await call(DENSE_SUMMARY_PROMPT)).strip()
    if not summary:
        raise RuntimeError("empty summary")
    questions = parse_questions(await call(QUESTIONS_PROMPT, num_predict=400))
    extras = []
    for transform in await _default_transforms(manager, user_id):
        output = (await call(transform["prompt"])).strip()
        if output:
            extras.append((transform, output))

    summary_id = await _store(
        manager, notebook_id, source_id, user_id, SUMMARY_MARKER, "summarize", text, summary, model
    )
    await _store(
        manager, notebook_id, source_id, user_id, QUESTIONS_MARKER, "custom", text,
        "\n".join(f"- {q}" for q in questions), model,
    )
    for transform, output in extras:
        await _store(
            manager, notebook_id, source_id, user_id, f"auto:def:{transform['id']}", "custom", text, output, model
        )
    await _merge_metadata(
        manager,
        source_id,
        {
            "insights_status": "done",
            "insights_error": None,
            "insights_model": model,
            "summary_insight_id": str(summary_id),
            "suggested_questions": questions,
        },
    )
    logger.info("Insights ready for source %s (%s)", source_id, model)


async def fail_stuck_insights(pool) -> int:
    """Mark every ``pending`` insights row as failed. Call once at startup, when no task can be running."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE notebook_sources SET metadata = metadata || $1::jsonb "
            "WHERE metadata->>'insights_status' = 'pending'",
            json.dumps({"insights_status": "error", "insights_error": "Interrupted by a restart."}),
        )
    try:
        return int(str(result).rsplit(" ", 1)[-1])
    except ValueError:
        return 0
