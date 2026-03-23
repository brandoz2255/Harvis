"""
Workspace backends that bypass OpenClaw — for models that need per-user DB keys
or that are accessed directly via cloud/local endpoints.

  stream_kimi_workspace            — Moonshot Kimi K2.5 (api_key from DB)
  stream_ollama_cloud_workspace    — External/cloud Ollama (EXTERNAL_OLLAMA_URL env var)
  stream_local_ollama_workspace    — Local Ollama (Docker service at OLLAMA_URL)
"""

import json
import logging
import os
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
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Provide a detailed, well-structured response. "
    "If the task involves analysis, provide step-by-step reasoning. "
    "If it involves writing or code, provide the complete output. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)

_OLLAMA_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent powered by GPT-OSS 120B. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Provide detailed, well-structured responses. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)

_LOCAL_OLLAMA_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent running on a local model. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
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
            "message": "Kimi K2.5 API key not configured. Please add your Moonshot API key in Settings."
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
        summary = full_text[:500].rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except Exception as exc:
        logger.error("kimi_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {"message": f"Kimi K2.5 error: {exc}"})


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
            "message": "External Ollama URL not configured (EXTERNAL_OLLAMA_URL missing)."
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
                        "message": f"Cloud Ollama error {resp.status_code}: {err}"
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
        summary = full_text[:500].rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except Exception as exc:
        logger.error("ollama_cloud_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {"message": f"Cloud Ollama error: {exc}"})


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

    payload = {"model": model, "messages": messages, "stream": True}
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
        summary = full_text[:500].rstrip() if full_text else "Task completed."
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
