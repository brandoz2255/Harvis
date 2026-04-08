"""
Workspace backends that bypass OpenClaw — for models that need per-user DB keys
or that are accessed directly via cloud/local endpoints.

  stream_kimi_workspace            — Moonshot Kimi K2.5 (api_key from DB)
  stream_ollama_cloud_workspace    — External/cloud Ollama (EXTERNAL_OLLAMA_URL env var)
  stream_local_ollama_workspace    — Local Ollama (Docker service at OLLAMA_URL)
"""

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator

import httpx

from moonshot_api import MoonshotClient, MOONSHOT_BASE_URL
from .openclaw_client import OpenClawEvent

logger = logging.getLogger(__name__)

# Local Ollama — Docker service or host Ollama.
_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

# Cloud Ollama — URL and API key come from the backend manifest env vars.
_EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
_EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")

_KIMI_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent powered by Kimi K2.5. "
    "You are part of a multi-agent workspace that can spawn parallel sub-agents for efficiency. "
    "When a task has independent parts (e.g., research + code, multiple file edits, parallel analysis), "
    "the orchestrator will automatically split them across sub-agents running concurrently. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Keep your response focused and concise — avoid restating the task or listing capabilities. "
    "Provide a detailed, well-structured response. "
    "If the task involves analysis, provide step-by-step reasoning. "
    "If it involves writing or code, provide the complete output. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)

_OLLAMA_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent powered by GPT-OSS 120B. "
    "You are part of a multi-agent workspace that can spawn parallel sub-agents for efficiency. "
    "When a task has independent parts, the orchestrator splits them across sub-agents running concurrently. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Keep your response focused and concise — avoid restating the task or listing capabilities. "
    "Provide detailed, well-structured responses. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)

_LOCAL_OLLAMA_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent running on a local model. "
    "You are part of a multi-agent workspace that can spawn parallel sub-agents for efficiency. "
    "When a task has independent parts, the orchestrator splits them across sub-agents running concurrently. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Keep your response focused and concise — avoid restating the task or listing capabilities. "
    "Provide a detailed, well-structured response. "
    "If the task involves analysis, provide step-by-step reasoning. "
    "If it involves writing or code, provide the complete output. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)


def _build_context_message(task_message: str, chat_history: list[dict], cap: int = 10) -> str:
    context_lines = [
        f"{m['role'].upper()}: {m['content']}"
        for m in chat_history[-cap:]
        if isinstance(m.get("content"), str) and m["content"].strip()
    ]
    if context_lines:
        return (
            f"[RECENT CONVERSATION]\n{chr(10).join(context_lines)}\n\n"
            f"[YOUR TASK]\n{task_message}\n\n"
            "Begin executing the task now. Be specific and thorough."
        )
    return f"[YOUR TASK]\n{task_message}\n\nBegin executing the task now. Be specific and thorough."


async def stream_kimi_workspace(
    task_message: str,
    chat_history: list[dict],
    api_key: str,
    api_url: str = "",
) -> AsyncGenerator[OpenClawEvent, None]:
    """
    Run a workspace task using Kimi K2.5 directly (bypasses OpenClaw).
    api_key must be the decrypted Moonshot key fetched from the user's DB row.

    Yields OpenClawEvent objects in the same format as OpenClawClient.stream().
    """
    if not api_key:
        yield OpenClawEvent("error", {
            "message": "Kimi K2.5 API key not configured. Please add your Moonshot API key in Settings.",
            "fix_hint": "Add your Moonshot API key in Settings -> Workspace, or set MOONSHOT_API_KEY in your environment.",
        })
        return

    base_url = api_url or MOONSHOT_BASE_URL
    client = MoonshotClient(api_key=api_key, base_url=base_url)
    messages = [
        {"role": "system", "content": _KIMI_SYSTEM_PROMPT},
        {"role": "user", "content": _build_context_message(task_message, chat_history)},
    ]

    full_text_parts: list[str] = []
    try:
        async for chunk in client.chat_completion_stream(model="kimi-k2.5", messages=messages):
            if chunk:
                full_text_parts.append(chunk)
                yield OpenClawEvent("token", {"content": chunk})

        full_text = "".join(full_text_parts)
        summary = full_text.rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except Exception as exc:
        logger.error("kimi_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {
            "message": f"Kimi K2.5 error: {exc}",
            "fix_hint": "Check your API key is valid and Moonshot's API is reachable. See https://platform.moonshot.cn for status.",
        })


async def stream_ollama_cloud_workspace(
    task_message: str,
    chat_history: list[dict],
    model: str = "gpt-oss:120b",
) -> AsyncGenerator[OpenClawEvent, None]:
    """
    Run a workspace task using the cloud/external Ollama instance.
    Uses EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY from the backend env
    (injected via the K8s manifest secret).

    Yields OpenClawEvent objects in the same format as OpenClawClient.stream().
    """
    if not _EXTERNAL_OLLAMA_URL:
        yield OpenClawEvent("error", {
            "message": "External Ollama URL not configured (EXTERNAL_OLLAMA_URL missing).",
            "fix_hint": "Set the EXTERNAL_OLLAMA_URL environment variable to your cloud Ollama endpoint.",
        })
        return

    # Ollama's OpenAI-compat endpoint
    target_url = f"{_EXTERNAL_OLLAMA_URL}/v1/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _EXTERNAL_OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {_EXTERNAL_OLLAMA_API_KEY}"

    messages = [
        {"role": "system", "content": _OLLAMA_SYSTEM_PROMPT},
        {"role": "user", "content": _build_context_message(task_message, chat_history)},
    ]
    payload = {"model": model, "messages": messages, "stream": True}

    logger.info("ollama_cloud_workspace: streaming model=%s from %s", model, target_url)

    full_text_parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            async with client.stream("POST", target_url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    err = (await resp.aread()).decode(errors="replace")[:200]
                    logger.error("ollama_cloud_workspace: HTTP %s: %s", resp.status_code, err)
                    yield OpenClawEvent("error", {
                        "message": f"Cloud Ollama error {resp.status_code}: {err}",
                        "fix_hint": "Check EXTERNAL_OLLAMA_URL is correct and the model is available on the remote instance.",
                    })
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        chunk = delta.get("content", "")
                        if chunk:
                            full_text_parts.append(chunk)
                            yield OpenClawEvent("token", {"content": chunk})
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

        full_text = "".join(full_text_parts)
        summary = full_text.rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except Exception as exc:
        logger.error("ollama_cloud_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {
            "message": f"Cloud Ollama error: {exc}",
            "fix_hint": "Check your cloud Ollama instance is running and reachable. Verify EXTERNAL_OLLAMA_URL and EXTERNAL_OLLAMA_API_KEY.",
        })


async def stream_local_ollama_workspace(
    task_message: str,
    chat_history: list[dict],
    model: str = "",
) -> AsyncGenerator[OpenClawEvent, None]:
    """
    Run a workspace task using the LOCAL Ollama instance.
    If `model` is empty, auto-detect the first available model.
    Yields OpenClawEvent objects matching the standard workspace format.
    """
    base_url = _LOCAL_OLLAMA_URL.rstrip("/")
    if "/v1" in base_url:
        base_url = base_url.replace("/v1", "")

    # Resolve model name
    if not model:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if models:
                    model = models[0]["name"]
                    yield OpenClawEvent("log", {
                        "message": f"Auto-selected local model: {model}",
                    })
                else:
                    yield OpenClawEvent("error", {
                        "message": "Ollama is running but has no models pulled.",
                        "fix_hint": "Run `ollama pull qwen2.5:7b` (or any model) then retry.",
                    })
                    return
        except Exception as exc:
            yield OpenClawEvent("error", {
                "message": f"Cannot reach local Ollama at {base_url}: {exc}",
                "fix_hint": (
                    "Ensure Ollama is running (`ollama serve`) and reachable. "
                    "If running in Docker, check that the `ollama` service is up "
                    "and OLLAMA_URL is set correctly."
                ),
            })
            return

    messages = [
        {"role": "system", "content": _LOCAL_OLLAMA_SYSTEM_PROMPT},
        {"role": "user", "content": _build_context_message(task_message, chat_history)},
    ]

    yield OpenClawEvent("log", {"message": f"Starting task on local model: {model}"})

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "reasoning_effort": "none",
    }
    full_text_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                json=payload,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    yield OpenClawEvent("error", {
                        "message": f"Ollama returned HTTP {response.status_code}: {body.decode(errors='replace')[:500]}",
                        "fix_hint": f"Check that model '{model}' is pulled and Ollama has enough memory.",
                    })
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_text_parts.append(content)
                            yield OpenClawEvent("token", {"content": content})
                    except json.JSONDecodeError:
                        continue

        full_text = "".join(full_text_parts)
        summary = full_text.rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except httpx.ConnectError as exc:
        yield OpenClawEvent("error", {
            "message": f"Connection to local Ollama lost: {exc}",
            "fix_hint": "Ollama may have crashed or run out of VRAM. Check `ollama logs` and GPU memory.",
        })
    except httpx.ReadTimeout:
        yield OpenClawEvent("error", {
            "message": "Local Ollama timed out (>5 min). The model may be too large for your hardware.",
            "fix_hint": "Try a smaller model (e.g., qwen2.5:7b instead of 70b) or increase timeout.",
        })
    except Exception as exc:
        logger.error("local_ollama_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {
            "message": f"Local Ollama error: {exc}",
            "fix_hint": "Check Ollama logs for details.",
        })


# ─── Planner prompt for task splitting ────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = (
    "You are a task planner. Given a user task, decide if it should be split into "
    "parallel sub-tasks that can run concurrently as separate sub-agents.\n\n"
    "Rules:\n"
    "- Split into 2-6 genuinely independent parts when possible.\n"
    "- Be aggressive about splitting — more parallel agents = faster completion.\n"
    "- Each sub-task must be self-contained and executable independently.\n"
    "- Give each sub-agent a descriptive label (e.g., 'Research Agent', 'Code Agent', 'Analysis Agent').\n"
    "- If the task is truly atomic and cannot be split, return a single sub-task.\n"
    "- Respond ONLY with valid JSON, no markdown fences.\n\n"
    "Format:\n"
    '{"subtasks": [{"label": "Research Agent", "task": "description"}, '
    '{"label": "Code Agent", "task": "description"}, ...]}\n\n'
    "If no split is needed:\n"
    '{"subtasks": [{"label": "Agent", "task": "the original task"}]}'
)


async def _plan_subtasks(
    task_message: str,
    chat_history: list[dict],
    *,
    api_key: str = "",
    api_url: str = "",
    model: str = "",
    provider: str = "local",
) -> list[dict]:
    """
    Ask the model to split the task into parallel sub-tasks.
    Returns a list of {"label": str, "task": str} dicts.
    Falls back to a single task on any failure.
    """
    fallback = [{"label": "Agent", "task": task_message}]

    context = _build_context_message(task_message, chat_history, cap=5)
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    try:
        if provider == "kimi" and api_key:
            from moonshot_api import MoonshotClient, MOONSHOT_BASE_URL
            client = MoonshotClient(api_key=api_key, base_url=api_url or MOONSHOT_BASE_URL)
            parts: list[str] = []
            async for chunk in client.chat_completion_stream(model="kimi-k2.5", messages=messages):
                if chunk:
                    parts.append(chunk)
            raw = "".join(parts).strip()
        else:
            # Local or cloud Ollama
            base_url = _LOCAL_OLLAMA_URL.rstrip("/")
            if "/v1" in base_url:
                base_url = base_url.replace("/v1", "")
            target_model = model or "qwen2.5:7b"
            payload = {
                "model": target_model,
                "messages": messages,
                "stream": False,
                "temperature": 0.1,
            }
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as hc:
                resp = await hc.post(f"{base_url}/v1/chat/completions", json=payload)
            if resp.status_code != 200:
                return fallback
            data = resp.json()
            raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON response
        raw = raw.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        plan = json.loads(raw)
        subtasks = plan.get("subtasks", [])
        if not subtasks or not isinstance(subtasks, list):
            return fallback
        # Validate and cap at 6 sub-agents
        validated = []
        for st in subtasks[:6]:
            if isinstance(st, dict) and st.get("task"):
                validated.append({
                    "label": st.get("label", f"Sub-Agent {len(validated) + 1}"),
                    "task": st["task"],
                })
        return validated if validated else fallback

    except Exception as exc:
        logger.debug("Planner failed, using single agent: %s", exc)
        return fallback


async def _run_subagent_stream(
    label: str,
    task: str,
    run_id: str,
    parent_run_id: str,
    chat_history: list[dict],
    queue: asyncio.Queue,
    *,
    api_key: str = "",
    api_url: str = "",
    model: str = "",
    provider: str = "local",
) -> str:
    """
    Run a single sub-agent and push events to the shared queue.
    Returns the sub-agent's full text output.
    """
    # Emit agent_start
    await queue.put(OpenClawEvent("agent_start", {
        "agent_label": label,
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "model": model or provider,
    }))

    full_text_parts: list[str] = []
    try:
        if provider == "kimi":
            stream = stream_kimi_workspace(task, chat_history, api_key=api_key, api_url=api_url)
        elif provider == "cloud-ollama":
            stream = stream_ollama_cloud_workspace(task, chat_history, model=model)
        else:
            stream = stream_local_ollama_workspace(task, chat_history, model=model)

        async for event in stream:
            # Tag events with sub-agent info
            event.data["agent_label"] = label
            event.data["run_id"] = run_id
            event.data["parent_run_id"] = parent_run_id
            if event.event_type == "token":
                full_text_parts.append(event.data.get("content", ""))
            # Don't forward sub-agent's own 'done' — the orchestrator emits the final one
            if event.event_type not in ("done", "stream_end"):
                await queue.put(event)

    except Exception as exc:
        logger.error("Sub-agent %s error: %s", label, exc)
        await queue.put(OpenClawEvent("error", {
            "message": f"{label} error: {exc}",
            "agent_label": label,
            "run_id": run_id,
        }))

    # Emit agent_end
    await queue.put(OpenClawEvent("agent_end", {
        "agent_label": label,
        "run_id": run_id,
        "parent_run_id": parent_run_id,
    }))

    return "".join(full_text_parts)


async def stream_parallel_workspace(
    task_message: str,
    chat_history: list[dict],
    *,
    api_key: str = "",
    api_url: str = "",
    model: str = "",
    provider: str = "local",
) -> AsyncGenerator[OpenClawEvent, None]:
    """
    Multi-agent workspace: plans subtasks, runs them in parallel, yields events.
    The orchestrator emits agent lifecycle events so the frontend graph visualizes them.
    """
    orchestrator_run_id = str(uuid.uuid4())[:8]

    # Emit orchestrator start
    yield OpenClawEvent("agent_start", {
        "agent_label": "Agent",
        "run_id": orchestrator_run_id,
        "parent_run_id": None,
        "model": model or provider,
    })

    # Plan subtasks
    yield OpenClawEvent("log", {
        "message": "Planning task decomposition...",
        "agent_label": "Agent",
        "run_id": orchestrator_run_id,
    })

    subtasks = await _plan_subtasks(
        task_message, chat_history,
        api_key=api_key, api_url=api_url, model=model, provider=provider,
    )

    if len(subtasks) == 1:
        # Single task — no splitting needed, run directly
        yield OpenClawEvent("log", {
            "message": "Single agent executing task directly.",
            "agent_label": "Agent",
            "run_id": orchestrator_run_id,
        })
        # Stream the single agent's output directly
        if provider == "kimi":
            stream = stream_kimi_workspace(task_message, chat_history, api_key=api_key, api_url=api_url)
        elif provider == "cloud-ollama":
            stream = stream_ollama_cloud_workspace(task_message, chat_history, model=model)
        else:
            stream = stream_local_ollama_workspace(task_message, chat_history, model=model)

        async for event in stream:
            event.data["agent_label"] = "Agent"
            event.data["run_id"] = orchestrator_run_id
            yield event
        return

    # Multiple subtasks — run in parallel
    yield OpenClawEvent("log", {
        "message": f"Spawning {len(subtasks)} sub-agents in parallel: "
                   + ", ".join(st["label"] for st in subtasks),
        "agent_label": "Agent",
        "run_id": orchestrator_run_id,
    })

    queue: asyncio.Queue = asyncio.Queue()
    tasks: list[asyncio.Task] = []

    for st in subtasks:
        sub_run_id = str(uuid.uuid4())[:8]
        task_coro = _run_subagent_stream(
            label=st["label"],
            task=st["task"],
            run_id=sub_run_id,
            parent_run_id=orchestrator_run_id,
            chat_history=chat_history,
            queue=queue,
            api_key=api_key,
            api_url=api_url,
            model=model,
            provider=provider,
        )
        tasks.append(asyncio.create_task(task_coro))

    # Yield events as they arrive from all sub-agents
    finished = 0
    total = len(tasks)
    while finished < total:
        # Check if all tasks are done
        done_tasks = [t for t in tasks if t.done()]
        if len(done_tasks) == total and queue.empty():
            break

        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            yield event
        except asyncio.TimeoutError:
            continue

    # Drain remaining events
    while not queue.empty():
        yield await queue.get()

    # Gather results
    results: list[str] = []
    for t in tasks:
        try:
            result = await t
            if result:
                results.append(result)
        except Exception as exc:
            logger.error("Sub-agent task error: %s", exc)

    # Emit orchestrator end
    yield OpenClawEvent("agent_end", {
        "agent_label": "Agent",
        "run_id": orchestrator_run_id,
    })

    # Compose final summary
    combined = "\n\n---\n\n".join(results) if results else "All sub-agents completed."
    summary = combined[:2000] if len(combined) > 2000 else combined
    yield OpenClawEvent("done", {"summary": summary})
