"""Cron scheduler runtime — background tick loop wired into FastAPI lifespan.

Activation: HARVIS_CRON_ENABLED=true (default false). Defaulting to OFF
keeps existing deployments unchanged; operators flip the env var when
they want jobs from the cron_jobs table to actually fire.

Tick body lives in plugins/cron/scheduler.py. This module owns the
runtime loop + the dispatch callback that translates a CronJob into one
of two deliveries, split on metadata.context:
  'coding' (default) → workspace launch via the existing workspace_router
                       entry point (Routines lens)
  'chat'             → one chat completion whose exchange is persisted into
                       an owui chat (Schedules lens)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Optional

from .scheduler import CronScheduler
from .store import PgCronJobStore
from .types import CronJob

logger = logging.getLogger(__name__)

# Chat-delivery lane calls Ollama directly (the tick loop has no Request, and
# per-user cloud credentials aren't plumbed into background tasks), so cloud-
# prefixed models can't be served here — we fall back instead of failing.
_CLOUD_MODEL_PREFIXES = ("anthropic/", "openai/")


async def _user_default_model(pool, user_id: int) -> str:
    """The user's saved default model (Integrations preference), skipping cloud
    models this lane can't reach; else HARVIS_CRON_CHAT_MODEL; else llama3.1:8b."""
    fallback = os.getenv("HARVIS_CRON_CHAT_MODEL", "llama3.1:8b")
    try:
        from owui_compat.capabilities import _read_integrations  # lazy: avoid import-time coupling

        _prefs, dm = await _read_integrations(pool, int(user_id))
        dm = (dm or "").strip()
        if dm and not dm.lower().startswith(_CLOUD_MODEL_PREFIXES):
            return dm
    except Exception:
        logger.debug("cron chat: could not read user default model", exc_info=True)
    return fallback


async def _generate_chat_answer(model: str, prompt: str, job_name: str) -> str:
    """One non-streaming Ollama completion for a fired Schedule. Raises on any
    failure — the dispatch wrapper converts that into (False, error_message)."""
    import httpx  # local import: only touched when a chat-context job fires

    base = (os.getenv("OLLAMA_URL") or "http://ollama:11434").rstrip("/")
    sys_prompt = (
        f"You are Harvis. This prompt comes from the user's scheduled routine "
        f"'{job_name}'. Answer it directly and completely — the reply is posted "
        f"into their chat as a normal assistant message."
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            f"{base}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "think": False,
                "options": {"num_ctx": 8192},
            },
        )
        resp.raise_for_status()
        content = ((resp.json() or {}).get("message") or {}).get("content") or ""
    content = content.strip()
    if not content:
        raise RuntimeError(f"model {model!r} returned an empty reply")
    return content


async def _append_to_chat(pool, job: CronJob, model: str, answer: str) -> None:
    """Persist the fired prompt + answer into an owui chat (OWUI blob shape:
    history.messages keyed by id + parent/children links + linear messages list,
    mirroring Chat.svelte's addMessages). Create-or-append: the job's chat is
    found by the 'harvis_cron_job_id' marker stamped on the blob — top-level
    jsonb merge on save keeps it alive across client edits."""
    from owui_compat import persistence  # lazy: avoid import-time coupling

    marker = str(job.id)
    now_s = int(time.time())
    uid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    user_msg = {
        "id": uid,
        "parentId": None,
        "childrenIds": [aid],
        "role": "user",
        "content": job.prompt,
        "timestamp": now_s,
        "models": [model],
    }
    asst_msg = {
        "id": aid,
        "parentId": uid,
        "childrenIds": [],
        "role": "assistant",
        "content": answer,
        "done": True,
        "model": model,
        "modelName": model,
        "modelIdx": 0,
        "timestamp": now_s,
    }

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM owui_chats
            WHERE user_id = $1 AND chat->>'harvis_cron_job_id' = $2
            ORDER BY updated_at DESC LIMIT 1
            """,
            int(job.user_id),
            marker,
        )

    if row is not None:
        existing = await persistence.get_chat(pool, int(job.user_id), str(row["id"]))
        chat_obj = dict((existing or {}).get("chat") or {})
        history = dict(chat_obj.get("history") or {})
        msgs = dict(history.get("messages") or {})
        cur = history.get("currentId")
        parent = msgs.get(cur) if cur else None
        if isinstance(parent, dict):
            user_msg["parentId"] = parent.get("id")
            parent.setdefault("childrenIds", []).append(uid)
        msgs[uid] = user_msg
        msgs[aid] = asst_msg
        history["messages"] = msgs
        history["currentId"] = aid
        chat_obj["history"] = history
        linear = list(chat_obj.get("messages") or [])
        linear.extend([user_msg, asst_msg])
        chat_obj["messages"] = linear
        chat_obj["harvis_cron_job_id"] = marker
        # Keep the (possibly user-renamed) title — update_chat re-derives from
        # the first user message only when no explicit title survives.
        chat_obj["title"] = chat_obj.get("title") or (existing or {}).get("title") or job.name
        updated = await persistence.update_chat(pool, int(job.user_id), str(row["id"]), chat_obj)
        if updated is None:
            raise RuntimeError("chat update returned no row")
        return

    blob = {
        "title": job.name,
        "models": [model],
        "params": {},
        "tags": [],
        "history": {"messages": {uid: user_msg, aid: asst_msg}, "currentId": aid},
        "messages": [user_msg, asst_msg],
        "timestamp": int(time.time() * 1000),
        "harvis_cron_job_id": marker,
    }
    await persistence.create_chat(pool, int(job.user_id), blob)


async def _dispatch_chat(app, job: CronJob, meta: dict) -> tuple[bool, Optional[str]]:
    """Chat-delivery branch: run the prompt through one model turn and land the
    exchange in an owui chat. Fail-closed — any failure is logged + returned as
    (False, message) so the job records 'error' and the tick loop keeps ticking."""
    try:
        pool = getattr(app.state, "pg_pool", None)
        if pool is None:
            return False, "chat delivery unavailable: no pg_pool on app.state"
        model = str(meta.get("model") or meta.get("model_name") or "").strip()
        if model.lower().startswith(_CLOUD_MODEL_PREFIXES):
            logger.warning(
                "cron chat: job %s asked for cloud model %r — not reachable from the "
                "tick loop; using local default", job.id, model,
            )
            model = ""
        if not model:
            model = await _user_default_model(pool, job.user_id)
        answer = await _generate_chat_answer(model, job.prompt, job.name)
        await _append_to_chat(pool, job, model, answer)
        logger.info("cron chat delivered job %s (%s) via %s", job.id, job.name, model)
        return True, None
    except Exception as e:
        logger.exception("cron chat delivery failed for job %s (%s)", job.id, job.name)
        return False, str(e)


def _make_dispatch(app):
    """Build a CronScheduler dispatch callback bound to ``app``.

    Two delivery lanes, split on metadata.context:
      'chat'   → run the prompt through one chat completion and persist the
                 exchange into an owui chat (Schedules — main chat lens).
      'coding' → (default, incl. jobs that predate the split) launch a
                 workspace run with the job's prompt as task_brief and the
                 job's user_id as the run owner (Routines — coding lens).
    Failure during either propagates back to the scheduler as
    (False, error_message), which leaves the job in 'error' status.
    """
    async def dispatch(job: CronJob) -> tuple[bool, Optional[str]]:
        meta = getattr(job, "metadata", None) or {}
        if str(meta.get("context") or "").strip().lower() == "chat":
            return await _dispatch_chat(app, job, meta)
        try:
            from fastapi import Request
            from workspace.workspace_router import launch_workspace_internal  # type: ignore

            req = Request(scope={"type": "http", "app": app})
            # Automations created from Agent Studio carry metadata.agent_id =
            # "orchestrated" so the scheduled run fans out into the multi-agent
            # orchestrator (same path as a chat Orchestrate run). Default "main"
            # keeps any pre-existing jobs on the single-agent path.
            await launch_workspace_internal(
                request=req,
                user_id=job.user_id,
                task_brief=job.prompt,
                agent_id=str(meta.get("agent_id") or "main"),
                model_name=str(meta.get("model_name") or ""),
                # Tag every fire with a stable per-job session so the Automations
                # dashboard can aggregate real run outcomes (Successful/Failed 7d)
                # + a Run History from workspace_runs.
                session_id=f"cron-{job.id}",
            )
            return True, None
        except Exception as e:
            logger.exception("cron dispatch failed for job %s (%s)", job.id, job.name)
            return False, str(e)

    return dispatch


async def start_cron_tick_loop(app) -> Optional[asyncio.Task]:
    """Start the cron tick loop. Returns the task or None if disabled.

    Idempotent against repeated lifespan starts (the FastAPI lifespan
    only fires once per process, but tests may activate multiple times).
    Runs forever until cancelled by stop_cron_tick_loop.
    """
    if os.getenv("HARVIS_CRON_ENABLED", "false").lower() != "true":
        return None

    pool = getattr(app.state, "pg_pool", None)
    if pool is None:
        logger.warning("cron tick: no pg_pool on app.state — not starting")
        return None

    try:
        interval = float(os.getenv("HARVIS_CRON_TICK_INTERVAL_S", "60"))
    except ValueError:
        interval = 60.0
    interval = max(5.0, interval)  # floor — tighter polls would hammer the DB

    store = PgCronJobStore(pool)
    sched = CronScheduler(store, dispatch=_make_dispatch(app))

    async def _loop_body():
        logger.info("⏰ cron tick loop started (interval=%.1fs)", interval)
        while True:
            try:
                n = await sched.tick()
                if n > 0:
                    logger.info("cron tick dispatched %d job(s)", n)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cron tick raised — continuing")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    task = asyncio.create_task(_loop_body(), name="harvis-cron-tick")
    return task


async def stop_cron_tick_loop(task: Optional[asyncio.Task]) -> None:
    """Cancel and await the tick loop. Safe to call with None."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("cron tick shutdown raised")
    logger.info("⏰ cron tick loop stopped")
