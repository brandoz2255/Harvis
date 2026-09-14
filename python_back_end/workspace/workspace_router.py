"""
Harvis Workspaces API router.

Endpoints:
  POST /api/workspace/suggest          — Analyze chat, return workspace suggestion
  POST /api/workspace/launch           — Confirm launch, start OpenClaw task
  GET  /api/workspace/stream/{ws_id}   — SSE stream of workspace activity log
  POST /api/workspace/cancel/{ws_id}   — Cancel a running workspace
  GET  /api/workspace/status/{ws_id}   — Get current workspace status
  GET  /api/workspace/history          — Last 50 workspace runs for current user
                                         (?run_id=<id> → that one run, Build turns included)
  GET  /api/workspace/run/{ws_id}/events — Get all stored events for a run
  POST /api/workspace/run/{ws_id}/rerun  — Re-run a previous workspace task

Architecture — Background Task + Queue + DB:
  1. /launch  → inserts workspace_runs row + starts _run_workspace_bg() asyncio.Task
  2. Background task drives client.stream():
       • Saves every event to workspace_events (DB is the authoritative log)
       • Pushes (seq, event) tuples to a per-workspace asyncio.Queue for live SSE
       • Puts a None sentinel when done
       • Keeps running even if the SSE client disconnects
  3. /stream  → two-phase async generator:
       Phase 1: replay all workspace_events from DB  (reconnection, history)
       Phase 2: consume live events from asyncio.Queue (near-real-time streaming)
       SSE disconnect does NOT cancel the background task — sub-agents finish.
  4. /cancel  → signals client.cancel() and cancels the asyncio.Task
"""

import asyncio
import json
import logging
import mimetypes
import os
import re
import secrets
import time
import uuid
from typing import Optional

import httpx as _httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from .openclaw_client import (
    OpenClawClient,
    OpenClawEvent,
    PROTOCOL_VERSION,
    _CLIENT_ID,
    _CLIENT_MODE,
    _CLIENT_SCOPES,
    _build_device_params,
)
from .openclaw_resolver import resolve_openclaw_config
from .orchestration import artifact_mcp as _artifact_mcp
from .secret_redaction import redact_payload
from .kimi_workspace import (
    stream_kimi_workspace,
    stream_ollama_cloud_workspace,
    stream_local_ollama_workspace,
    stream_parallel_workspace,
)
from .task_detector import detect_workspace_task
from .terminal_container import allocate_event_seq

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/workspace", tags=["workspace"])
def _append_debug_log(location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    return  # debug logging removed

# ─── Provider probe URLs (read once at module load) ──────────────────────────
_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
_EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")
_MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")


def _external_engines_enabled() -> bool:
    """ONE global flag (no per-engine flags) gating ALL external code engines (E1+E2)."""
    return (os.getenv("HARVIS_OWUI_EXTERNAL_ENGINES") or "").strip().lower() in {"1", "true", "yes", "on"}


def _hermes_engine_enabled() -> bool:
    """Phase E4 (now ``hermes-native``, experimental fallback): flag gating the Hermes
    *native* engine (SubAgentRunner + SOUL persona on a local Hermes Ollama model)."""
    return (os.getenv("HARVIS_OWUI_HERMES_ENGINE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _hermes_agent_engine_enabled() -> bool:
    """Phase E4B: separate flag gating the FULL Hermes Agent app engine (the real
    NousResearch hermes-agent runtime in the harvis-hermes-agent sidecar). Decoupled from
    both the external-engines flag and the E4 native-hermes flag."""
    return (os.getenv("HARVIS_OWUI_HERMES_AGENT_ENGINE") or "").strip().lower() in {"1", "true", "yes", "on"}

# Engine ids stored in vibecode_sessions.engine. opencode = local (no auth); codex +
# claude-code = CLOUD (per-user API key); hermes-agent = the full Hermes Agent app
# (local Ollama, no key) run via the engine-adapter sidecar (Phase E4B). All of these
# route to the engine-adapter. The auth-row engine id == the engine id here.
EXTERNAL_ENGINE_IDS = {"opencode", "codex", "claude-code", "hermes-agent"}
CLOUD_ENGINE_IDS = {"codex", "claude-code"}
# Phase E4 (renamed): the experimental NATIVE Hermes engine (vibecode-turn SubAgentRunner
# + SOUL persona, NOT a sidecar). Kept as an opt-in fallback alongside the real app engine.
NATIVE_ENGINE_IDS = {"hermes-native"}
# Kimi = the ORIGINAL Harvis workspace engine (Moonshot/Kimi K2.5). NOT a sidecar and NOT the
# native SubAgentRunner — it's a cloud reasoning engine that streams via stream_kimi_workspace
# (agent_id="kimi"). Gated on a Moonshot API key (per-user row OR MOONSHOT_API_KEY env).
KIMI_ENGINE_IDS = {"kimi"}
# Kimi Code = the MEMBERSHIP product (api.kimi.com/coding) — a DIFFERENT product from `kimi`
# above (Moonshot pay-as-you-go). Its own set because it belongs to neither of the others:
# NOT EXTERNAL_ENGINE_IDS, because that set is gated by _engine_enabled()'s external-engines
# flag while capabilities.py reports kimi-code ready on a VERIFIED key alone — a gate that
# disagrees with the readiness probe offers the user an engine the server then refuses.
# NOT KIMI_ENGINE_IDS, because that routes to stream_kimi_workspace: wrong API, wrong bill.
# It runs the real Claude Code CLI against the session clone through the engine-adapter,
# with ANTHROPIC_BASE_URL repointed. See docs/kimi-integration.md.
KIMI_CODE_ENGINE_IDS = {"kimi-code"}


# A model's provider -> the Build engine (lane) that can actually run it. This MUST agree
# with `engineForOwner` in the Build page: the picker decides the lane there, and the
# session row decides it here, so a disagreement sends a model down a lane that cannot
# serve it. That is not theoretical - a session created as `native`, then given
# `anthropic/claude-sonnet-5` by a picker that had carried over from another chat, POSTed
# to Ollama and came back `404 Not Found for http://...:11434/v1/chat/completions`.
#
# The provider is the segment before the first "/" of the model id, which is how every
# non-Ollama model is namespaced (`anthropic/...`, `kimi-code/...`, `openrouter/...`). A
# bare id with no slash is a local Ollama tag and belongs to the native loop.
def _engine_for_model(model_name: str) -> str:
    name = (model_name or "").strip().lower()
    if "/" not in name:
        return "native"
    owner = name.split("/", 1)[0]
    if owner.startswith("anthropic"):
        return "claude-code"
    if owner.startswith("hermes"):
        return "hermes-agent"
    if owner == "openai":
        return "codex"
    # Before the generic kimi/moonshot arm: "kimi-code" also starts with "kimi", and
    # falling through would run a MEMBERSHIP model on the pay-as-you-go Moonshot lane.
    if owner == "kimi-code":
        return "kimi-code"
    if owner.startswith("moonshot") or owner.startswith("kimi"):
        return "kimi"
    # openrouter / groq / cerebras / ... are OpenAI-compatible endpoints the native runner
    # already speaks; they need no sidecar.
    return "native"


def _engine_runnable(engine: str) -> bool:
    """Can this lane actually serve a turn right now? Mirrors the dispatch below."""
    if engine in ("native", "kimi", "kimi-code"):
        return True  # kimi-code is gated on a verified key, resolved at dispatch
    if engine == "hermes-native":
        return _hermes_engine_enabled()
    return _engine_enabled(engine)


def _engine_enabled(engine: str) -> bool:
    """Per-engine enablement: hermes-agent has its OWN flag; the other external engines
    (opencode/codex/claude-code) share the external-engines flag. (hermes-native is NATIVE,
    gated by _hermes_engine_enabled separately.)"""
    if engine == "hermes-agent":
        return _hermes_agent_engine_enabled()
    if engine in EXTERNAL_ENGINE_IDS:
        return _external_engines_enabled()
    return False


async def _installed_hermes_models() -> Optional[list[str]]:
    """Phase E4: best-effort list of installed Ollama tags containing 'hermes' (local +
    optional desktop). Returns ``None`` if the tags probe FAILED on every endpoint — so
    callers can fail-OPEN on a transient error rather than falsely rejecting a Hermes
    session. Returns ``[]`` when the probe succeeded but no Hermes model is installed.
    Never raises; never logs model contents."""
    urls = [_LOCAL_OLLAMA_URL]
    _desk = os.getenv("DESKTOP_OLLAMA_URL", "")
    if _desk:
        urls.append(_desk)
    any_ok = False
    found: list[str] = []
    for base in urls:
        if not base:
            continue
        b = base.rstrip("/")
        tags_url = b.replace("/v1", "") + "/api/tags" if "/v1" in b else f"{b}/api/tags"
        try:
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
                resp = await client.get(tags_url)
            if resp.status_code == 200:
                any_ok = True
                for m in (resp.json() or {}).get("models", []) or []:
                    name = m.get("name") or m.get("model") or ""
                    if "hermes" in name.lower():
                        found.append(name)
        except Exception as exc:
            logger.debug("hermes-model probe failed for %s: %s", b, exc)
    return found if any_ok else None
_NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")


# ─── Provider probe functions ────────────────────────────────────────────────

async def _probe_local_ollama() -> dict:
    """Ping local Ollama and list available models.

    Also merges in the desktop Ollama (`DESKTOP_OLLAMA_URL`) so workspace tasks
    using the "local" provider can see — and select — models that only exist on
    the GPU host. The actual routing is handled by `stream_local_ollama_workspace`,
    which transparently sends desktop-only models to the desktop.
    """
    async def _fetch_tags(base: str) -> list[str]:
        if not base:
            return []
        b = base.rstrip("/")
        tags_url = b.replace("/v1", "") + "/api/tags" if "/v1" in b else f"{b}/api/tags"
        try:
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
                resp = await client.get(tags_url)
            if resp.status_code == 200:
                return [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
        except Exception as exc:
            logger.debug("Ollama probe failed for %s: %s", b, exc)
        return []

    laptop_models = await _fetch_tags(_LOCAL_OLLAMA_URL)
    desktop_url = os.getenv("DESKTOP_OLLAMA_URL", "")
    desktop_models = await _fetch_tags(desktop_url) if desktop_url else []

    # Dedupe: laptop entries first; desktop-only entries appended.
    seen: set[str] = set(laptop_models)
    merged = list(laptop_models)
    for name in desktop_models:
        if name not in seen:
            seen.add(name)
            merged.append(name)

    if merged:
        return {
            "id": "local",
            "label": "Local Ollama" + (" + Desktop 5080" if desktop_models else ""),
            "status": "online",
            "models": merged,
            "reason": None,
        }
    if not laptop_models and not desktop_models:
        # Both unreachable
        return {
            "id": "local",
            "label": "Local Ollama",
            "status": "offline",
            "models": [],
            "reason": "Cannot reach laptop or desktop Ollama.",
        }
    return {
        "id": "local",
        "label": "Local Ollama",
        "status": "offline",
        "models": [],
        "reason": "Local Ollama is not reachable. Ensure Ollama is running (ollama serve) or the OLLAMA_URL env var is correct.",
    }


async def _probe_kimi(pool, user_id: int) -> dict:
    """Check Moonshot API key -- per-user DB row first, then env var."""
    has_key = bool(_MOONSHOT_API_KEY)

    if not has_key and pool:
        try:
            from main import get_user_api_key
            config = await get_user_api_key(pool, user_id, "moonshot")
            if config and config.get("api_key"):
                has_key = True
        except Exception:
            pass

    if has_key:
        return {
            "id": "kimi",
            "label": "Kimi",
            "description": "Moonshot API",
            "status": "online",
            "models": ["kimi-k3", "kimi-k2.6", "kimi-k2.5"],
            "reason": None,
        }
    return {
        "id": "kimi",
        "label": "Kimi",
        "description": "Moonshot API",
        "status": "no_key",
        "models": [],
        "reason": "No Moonshot API key found. Add one in Settings or set MOONSHOT_API_KEY env var.",
    }


def _probe_nvidia() -> dict:
    """Check NVIDIA NIM API key."""
    if _NVIDIA_API_KEY:
        return {
            "id": "nvidia-kimi",
            "label": "Kimi K2.5 (NVIDIA NIM)",
            "description": "NVIDIA NIM",
            "status": "online",
            "models": ["nvidia-kimi"],
            "reason": None,
        }
    return {
        "id": "nvidia-kimi",
        "label": "Kimi K2.5 (NVIDIA NIM)",
        "description": "NVIDIA NIM",
        "status": "no_key",
        "models": [],
        "reason": "NVIDIA_API_KEY not configured.",
    }


async def _probe_cloud_ollama() -> dict:
    """Probe external/cloud Ollama instance."""
    if not _EXTERNAL_OLLAMA_URL:
        return {
            "id": "cloud-ollama",
            "label": "Cloud Ollama",
            "status": "offline",
            "models": [],
            "reason": "EXTERNAL_OLLAMA_URL not configured.",
        }
    try:
        headers: dict[str, str] = {}
        if _EXTERNAL_OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {_EXTERNAL_OLLAMA_API_KEY}"
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
            resp = await client.get(
                f"{_EXTERNAL_OLLAMA_URL.rstrip('/')}/api/tags",
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return {
                "id": "cloud-ollama",
                "label": "Cloud Ollama",
                "status": "online" if models else "online_no_models",
                "models": models,
                "reason": None if models else "Cloud Ollama reachable but no models available.",
            }
    except Exception as exc:
        logger.debug("Cloud Ollama probe failed: %s", exc)
    return {
        "id": "cloud-ollama",
        "label": "Cloud Ollama",
        "status": "offline",
        "models": [],
        "reason": f"Could not reach {_EXTERNAL_OLLAMA_URL}. Check EXTERNAL_OLLAMA_URL and network.",
    }

async def _get_kimi_credentials(pool, user_id: int) -> tuple[str, str]:
    """Return ``(api_key, base_url)`` for Moonshot -- DB row first, then env var.

    The base URL matters: a key issued on platform.moonshot.ai 401s on .cn and vice versa.
    It is recorded per key at save time (verify_moonshot_key picks whichever platform
    accepted it), so callers must carry it through instead of assuming the env default.
    An empty base URL means "use the env default" and is normal for env-provided keys.
    """
    if pool:
        try:
            from main import get_user_api_key
            config = await get_user_api_key(pool, user_id, "moonshot")
            if config and config.get("api_key"):
                return config["api_key"], (config.get("api_url") or "")
        except Exception as exc:
            logger.debug("Failed to fetch Kimi key from DB: %s", exc)
    return _MOONSHOT_API_KEY, ""


async def _get_kimi_key(pool, user_id: int) -> str:
    """Key only — for gate checks that just need to know whether Kimi is usable."""
    key, _ = await _get_kimi_credentials(pool, user_id)
    return key


# ─── In-memory workspace registry ─────────────────────────────────────────────
# Maps workspace_id → {client, status, task_brief, session_id, ...}
# Safe for replicas=1 (Ollama co-location requirement keeps backend single-replica).
_workspaces: dict[str, dict] = {}

class WorkspaceLiveBroadcaster:
    """
    Fan-out live workspace events to every subscriber (chat bridge, SSE /stream, research, etc.).
    Replaces a single asyncio.Queue so multiple consumers each receive a full copy of (seq, event)
    items and the terminal None sentinel — no stolen events.
    """

    __slots__ = ("_subscribers", "_backlog")
    # Keep recent (seq, event) items so a subscriber that connects AFTER emission has
    # begun still receives them. Without this, the replay→subscribe gap in the SSE
    # endpoint drops live events (put() no-ops when there are no subscribers yet) and
    # the card sits on "Connecting…" until a manual reload replays from the DB.
    _BACKLOG_MAX = 512

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._backlog: list = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        # Pre-load the backlog so a late subscriber catches up; the SSE endpoint
        # de-dupes anything already replayed from the DB via `seq <= last_seq`.
        # subscribe() is fully synchronous (no await) so put() can't interleave here.
        for item in self._backlog:
            q.put_nowait(item)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def put(self, item) -> None:
        if item is None:
            # Run ended — DB replay covers any future reconnect; free the backlog.
            self._backlog = []
        else:
            self._backlog.append(item)
            if len(self._backlog) > self._BACKLOG_MAX:
                self._backlog = self._backlog[-self._BACKLOG_MAX:]
        subs = list(self._subscribers)
        if not subs:
            return
        await asyncio.gather(*(q.put(item) for q in subs))


# Per-workspace live event fan-out (DB remains authoritative for replay).
_workspace_broadcasters: dict[str, WorkspaceLiveBroadcaster] = {}

# asyncio.Task references so /cancel can cancel the background task.
_workspace_tasks: dict[str, asyncio.Task] = {}


# ─── OpenClaw single-agent artifact capture ─────────────────────────────────────
# The OpenClaw / native single-agent lanes don't run the file collector that
# vibecode / orchestrator / engine-adapter use. So we capture the files the agent
# WRITES (the full body is in the write tool_call args) and persist them as `file`
# artifacts — letting a plain chat "build me an html" auto-pop the Artifacts tab too.
_OC_WRITE_TOOLS = {"write", "file_write", "create_file"}
_OC_MAX_ARTIFACT_BYTES = 512 * 1024  # mirrors isolation._MAX_FILE_BYTES


def _is_search_tool(name: str) -> bool:
    """True when a tool_call is a web-search-shaped tool (drives 'search_trace' events)."""
    n = (name or "").lower()
    # Exact allowlist — never substring-match: `"search" in n` would catch
    # memory_search / repo search / research, and web_fetch is a fetch (carries a
    # url, not a query), so none of those get a search_trace.
    return n in ("web_search", "websearch", "search_web")


def _clean_oc_artifact_path(path: str) -> str:
    """OpenClaw writes land under 'session-<id>/...'; strip that prefix for a clean
    gallery name (matches how vibecode artifacts use a repo-relative path)."""
    p = (path or "").strip()
    p = re.sub(r"^\.?/+", "", p)            # drop a leading ./ or /
    p = re.sub(r"^session-[^/]+/", "", p)   # drop the session-<id>/ prefix
    return p or (path or "")


# ─── Request / Response models ─────────────────────────────────────────────────

class SuggestRequest(BaseModel):
    chat_history: list[dict]


class LaunchRequest(BaseModel):
    task_brief: str
    chat_history: list[dict]
    session_id: Optional[str] = None
    agent_id: str = "main"
    model_name: str = ""
    enable_interactive: bool = True
    live_web: bool = True  # When True, OpenClaw gets X-Live-Web (broad web + browser navigate)
    parallel: bool = True   # When True, planner may split task into parallel sub-agents
    # When set (a path to a git repo bind-mounted read-only into the backend), an
    # orchestrated run uses clone-local "attached" isolation: each sub-agent runs in
    # a `git clone --local` of this repo and produces a real `git diff` vs HEAD.
    repo_path: Optional[str] = None
    # User-uploaded files (images, PDFs, docs). Each entry should carry at least
    # one of: `url` (e.g. http://backend:8000/api/images/<id>.jpg), `path`
    # (inside a shared volume), or `file_id` (UUID from POST /api/uploads).
    # `name` + `mime_type` are optional hints for the agent.
    attachments: list[dict] = []


class InteractiveEnableRequest(BaseModel):
    workspace_id: str
    ttl_seconds: int = 3600


class WorkspaceStatus(BaseModel):
    workspace_id: str
    status: str
    task_brief: str
    session_id: str


def _looks_like_browser_task(task_brief: str, chat_history: list[dict] | None = None) -> bool:
    """
    Heuristic: should this workspace default to interactive Tier 3?
    True when the user is clearly asking to open a URL in a browser / website context.
    """
    text_parts: list[str] = [task_brief or ""]
    if chat_history:
        for msg in chat_history:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    text_parts.append(content)
    blob = " ".join(text_parts).lower()

    # Explicit URLs
    if "http://" in blob or "https://" in blob:
        return True

    # Bare domain names (e.g. "gemini.google.com", "github.com/repo")
    if re.search(r'\b[a-z0-9-]+\.[a-z]{2,}(?:\.[a-z]{2,})?(?:/\S*)?', blob):
        # Must also have a browsing-related verb or keyword to avoid false positives
        # on mentions of "file.txt" or "model.py"
        domain_hints = [
            ".com", ".org", ".net", ".io", ".dev", ".ai", ".co",
            ".edu", ".gov", ".app", ".me", ".gg",
        ]
        if any(h in blob for h in domain_hints):
            return True

    # Screenshot/browser keywords — expanded verb list
    keywords = [" browser", "website", "web site", "screenshot", "screen shot", "webpage", "web page"]
    verbs = [
        "open ", "go to ", "navigate to ", "visit ", "take ", "capture ",
        "show ", "check ", "look at ", "browse ", "see ", "view ",
        "screenshot ", "screencap ",
    ]
    if any(k in blob for k in keywords) and any(v in blob for v in verbs):
        return True

    # "screenshot" or "screen shot" alone is strong enough signal
    if "screenshot" in blob or "screen shot" in blob:
        return True

    return False


def _repo_in_allowlist(repo_path: str, env_name: str) -> bool:
    """True iff repo_path is a member of the comma-separated allowlist in env_name.
    Realpath membership (NOT a string prefix) so `..` traversal + symlink escapes can't
    smuggle in an arbitrary on-host git repo. The frontend only ever offers allowlisted
    repos, so a non-member path is a tampering attempt → the caller rejects it (403)."""
    if not repo_path:
        return False
    try:
        target = os.path.realpath(repo_path)
    except Exception:
        return False
    allowed = {
        os.path.realpath(s.strip())
        for s in os.getenv(env_name, "").split(",")
        if s.strip()
    }
    return target in allowed


def _browse_root() -> str:
    """Realpath'd READ-ONLY filesystem-browse root from HARVIS_FS_BROWSE_ROOT, or "" when
    unset. The deliberately-mounted host tree the "Open folder…" picker can reach — distinct
    from the explicit single-repo allowlist. CLONE-MODE ONLY: a repo opened from here is cloned
    (never edited in place), so the source mount stays read-only and contained."""
    v = os.getenv("HARVIS_FS_BROWSE_ROOT", "").strip()
    try:
        return os.path.realpath(v) if v else ""
    except Exception:
        return ""


def _browse_root_rw() -> str:
    """Realpath'd filesystem-browse root for the host-folder picker (HARVIS_FS_BROWSE_ROOT_RW,
    default = the dedicated browse mount /data/host-fs-rw — point HARVIS_FS_BROWSE_ROOT_RW_HOST at
    a real, secrets-free projects dir to browse it). Browsed repos default to CLONE-mode; they are
    only IN-PLACE eligible when HARVIS_INPLACE_ON_BROWSED is on (see _inplace_on_browsed). Distinct
    from the read-only _browse_root(); realpath-contained; containment is by the MOUNT."""
    v = os.getenv("HARVIS_FS_BROWSE_ROOT_RW", "/data/host-fs-rw").strip()
    try:
        return os.path.realpath(v) if v else ""
    except Exception:
        return ""


def _inplace_on_browsed() -> bool:
    """Whether a git repo under the RW browse root may be edited IN-PLACE (real files). OFF by
    default: until the permission ladder + an `exec` sandbox are verified for this path, browsed
    folders are CLONE-mode only (the throwaway-clone/diff is the gate). The one explicit
    HARVIS_ATTACHED_REPOS_RW repo is always in-place-eligible regardless of this flag."""
    return os.getenv("HARVIS_INPLACE_ON_BROWSED", "").strip().lower() in ("1", "true", "yes", "on")


def _browse_display_label() -> str:
    """Human label for the browse root in the UI (e.g. 'Projects'), not the container path."""
    label = os.getenv("HARVIS_FS_BROWSE_ROOT_LABEL", "").strip()
    if label:
        return label
    host = os.getenv("HARVIS_FS_BROWSE_ROOT_HOST", "").strip()
    if host:
        return os.path.basename(host.rstrip(os.sep)) or "Projects"
    root = _browse_root()
    return os.path.basename(root.rstrip(os.sep)) if root else ""


def _browse_display_path(container_path: str) -> str:
    """Map a container path under the browse mount to a host-relative display string
    (e.g. '/data/host-fs/Recent-EX/Harvis' → 'Projects/Recent-EX/Harvis')."""
    if not container_path:
        return ""
    root = _browse_root()
    if not root:
        return container_path
    try:
        p = os.path.realpath(container_path)
        r = os.path.realpath(root)
    except Exception:
        return container_path
    label = _browse_display_label()
    if p == r:
        return label
    if p.startswith(r + os.sep):
        rel = p[len(r) + 1 :].replace(os.sep, "/")
        return f"{label}/{rel}" if rel else label
    return os.path.basename(p)


def _repo_display_path(repo_path: str | None) -> str:
    """User-facing repo label for chips/headers — host-style when mappable, else basename."""
    if not repo_path:
        return ""
    if _under_root(repo_path, _browse_root()):
        return _browse_display_path(repo_path)
    # Explicit allowlist mount (e.g. /data/attached-repos/harvis) → host path when configured.
    host_attach = os.getenv("HARVIS_ATTACH_REPO_HOST", "").strip()
    browse_host = os.getenv("HARVIS_FS_BROWSE_ROOT_HOST", "").strip()
    if host_attach and browse_host:
        try:
            ha = os.path.realpath(host_attach)
            bh = os.path.realpath(browse_host)
            if ha == bh or ha.startswith(bh + os.sep):
                rel = ha[len(bh) :].lstrip(os.sep).replace(os.sep, "/")
                label = _browse_display_label()
                return f"{label}/{rel}" if rel else label
        except Exception:
            pass
    if host_attach:
        return host_attach.replace(os.sep, "/")
    return os.path.basename(repo_path.rstrip(os.sep))


def _session_repo_display(repo_path: str | None, title: str | None) -> str:
    """Display label for a VibeCode session's repo chip/header. A GitHub-clone (or copy-seed)
    session stores repo_path = the clone UNDER the session-workspace root — it has no host
    source, so the generic host-attach fallback in _repo_display_path mislabels it (e.g.
    "/tmp/harvis-attach-test"). For those, show the session title ("owner/repo" for GitHub)
    instead; every other session keeps the normal host-style mapping."""
    try:
        from .orchestration.isolation import SESSION_WORKSPACE_ROOT
        rp = os.path.realpath(repo_path or "")
        root = os.path.realpath(SESSION_WORKSPACE_ROOT)
        if rp and (rp == root or rp.startswith(root + os.sep)):
            return ((title or "").strip() or os.path.basename(rp) or "repo")
    except Exception:
        pass
    return _repo_display_path(repo_path)


def _under_root(path: str, root: str) -> bool:
    """True iff realpath(path) is `root` itself or strictly inside it. realpath collapses
    `..` AND resolves symlinks, so neither traversal nor a symlink can escape the root."""
    if not path or not root:
        return False
    try:
        t = os.path.realpath(path)
    except Exception:
        return False
    return t == root or t.startswith(root + os.sep)


def _dir_is_git_repo(path: str) -> bool:
    """True iff `path` is a git repo whose `.git` is a REAL directory (not a symlink/gitfile).
    Rejecting a symlinked `.git` is load-bearing: a dir under the browse root whose `.git`
    symlinks to ANOTHER repo's `.git` would otherwise pass the is-repo test and let
    `git clone --local` exfiltrate that out-of-tree repo."""
    git = os.path.join(path, ".git")
    try:
        return (not os.path.islink(git)) and os.path.isdir(git)
    except Exception:
        return False


def _is_repo_under_browse_root(repo_path: str) -> bool:
    """True iff repo_path is a git repo living under the configured (read-only) browse root.
    Lets the "Open folder…" picker clone a repo that isn't on the explicit allowlist —
    realpath-contained, and the `.git` itself must also resolve under the root so a planted
    `.git` symlink can't escape the tree."""
    root = _browse_root()
    if not _under_root(repo_path, root):
        return False
    try:
        rp = os.path.realpath(repo_path)
    except Exception:
        return False
    # `.git` must be a real dir AND its realpath must stay under the root — blocks the
    # `.git`-symlink-to-an-out-of-tree-repo escape that `git clone --local` would follow.
    return _dir_is_git_repo(rp) and _under_root(os.path.join(rp, ".git"), root)


def _is_repo_under_browse_root_rw(repo_path: str) -> bool:
    """True iff repo_path is a git repo under the configured READ-WRITE browse root. Lets the
    "Browse writable folders…" picker target a repo for IN-PLACE editing without an explicit
    per-repo allowlist entry — realpath-contained, and the `.git` itself must resolve under the
    RW root (blocks the planted-`.git`-symlink escape, same discipline as the RO gate)."""
    root = _browse_root_rw()
    if not _under_root(repo_path, root):
        return False
    try:
        rp = os.path.realpath(repo_path)
    except Exception:
        return False
    return _dir_is_git_repo(rp) and _under_root(os.path.join(rp, ".git"), root)


def _is_dir_under_browse_root(repo_path: str) -> bool:
    """True iff repo_path is a real directory under EITHER browse root — even when it is NOT a
    git repo. Lets the "Use this folder" picker target ANY folder: a non-git folder is
    copy-seeded into a fresh clone workspace (the real folder is only READ, never modified).
    realpath-contained on both roots, so `..`/symlink can't escape; clone-mode only (never
    in-place — that still requires a real `.git` + the RW gate)."""
    if not repo_path:
        return False
    try:
        rp = os.path.realpath(repo_path)
    except Exception:
        return False
    if not os.path.isdir(rp):
        return False
    return _under_root(rp, _browse_root()) or _under_root(rp, _browse_root_rw())


def _is_allowed_repo(repo_path: str) -> bool:
    """Read-only clone-mode sources: the explicit HARVIS_ATTACHED_REPOS allowlist, OR any git
    repo under EITHER browse root, OR ANY folder under a browse root (non-git folders are
    copy-seeded into a clone workspace). All clone-mode — the real source is only read."""
    return (
        _repo_in_allowlist(repo_path, "HARVIS_ATTACHED_REPOS")
        or _is_repo_under_browse_root(repo_path)
        or _is_repo_under_browse_root_rw(repo_path)
        or _is_dir_under_browse_root(repo_path)
    )


def _is_allowed_repo_rw(repo_path: str) -> bool:
    """Writable in-place targets. ALWAYS includes the explicit HARVIS_ATTACHED_REPOS_RW allowlist
    (the one deliberately-chosen repo). A git repo under the RW browse root is in-place-eligible
    ONLY when HARVIS_INPLACE_ON_BROWSED is on — until the ladder + an `exec` sandbox are verified
    for that path, browsed folders stay CLONE-mode (the diff/PR is the gate). The READ-ONLY browse
    root is never honored here."""
    if _repo_in_allowlist(repo_path, "HARVIS_ATTACHED_REPOS_RW"):
        return True
    return _inplace_on_browsed() and _is_repo_under_browse_root_rw(repo_path)


# ─── Database helpers ──────────────────────────────────────────────────────────

async def _db_create_run(
    pool, workspace_id: str, user_id: int, session_id: str, task_brief: str,
    *,
    parent_run_id: Optional[str] = None,
    role: Optional[str] = None,
    model_provider: Optional[str] = None,
    model_name: Optional[str] = None,
    workspace_path: Optional[str] = None,
    branch_name: Optional[str] = None,
) -> None:
    """Create a workspace_run row. The P5 orchestration columns (parent_run_id,
    role, model_*, workspace_path, branch_name) are optional — existing single-run
    callers pass none and get NULLs (unchanged behavior); the orchestrator passes
    them so sub-agent runs are first-class rows under their parent."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_runs
                    (id, user_id, session_id, task_brief, status, started_at,
                     parent_run_id, role, model_provider, model_name, workspace_path, branch_name)
                VALUES ($1, $2, $3, $4, 'running', NOW(), $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                workspace_id, user_id, session_id, task_brief,
                parent_run_id, role, model_provider, model_name, workspace_path, branch_name,
            )
    except Exception as exc:
        logger.error("DB: failed to create workspace_run %s: %s", workspace_id, exc)


async def _db_save_artifact(
    pool, workspace_id: str, artifact_type: str,
    *, path: Optional[str] = None, content: Optional[str] = None,
    content_bytes: Optional[bytes] = None,
) -> Optional[str]:
    """Persist an agent artifact (diff / changed_files / summary / log) and return its id.

    E2: pass ``content_bytes`` (instead of ``content``) for a BINARY artifact
    (STL/3MF/G-code/PNG…) — it lands in the BYTEA column and the raw/download
    endpoints serve it verbatim."""
    if pool is None:
        return None
    artifact_id = uuid.uuid4().hex[:16]
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_artifacts (id, workspace_id, artifact_type, path, content, content_bytes)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                artifact_id, workspace_id, artifact_type, path, content, content_bytes,
            )
        # NOTE: the typed 'artifact' trace event is emitted by the run loop
        # (_flush_oc_writes), not here — this helper is called mid-stream from
        # several lanes that emit their own trace events. All emissions now draw
        # seq from the single allocate_event_seq allocator, so there is no
        # collision risk either way; keeping the emit in the loop just avoids
        # duplicate 'artifact' events per save.
        return artifact_id
    except Exception as exc:
        logger.error("DB: failed to save artifact for workspace %s: %s", workspace_id, exc)
        return None


async def _db_set_run_repo(pool, workspace_id: str, repo_path: str) -> None:
    """Persist the attached repo path on a run so Create-PR can resolve its GitHub
    origin + base branch long after the clone-local workspace is torn down."""
    if pool is None or not repo_path:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_runs SET repo_path = $2 WHERE id = $1",
                workspace_id, repo_path,
            )
    except Exception as exc:
        logger.error("DB: failed to set repo_path for %s: %s", workspace_id, exc)


async def _db_set_run_source(pool, workspace_id: str, source: str) -> None:
    """Tag a run's kind (e.g. 'vibecode' for a VibeCode-session turn). Mirrors
    _db_set_run_repo — the create is ON CONFLICT DO NOTHING, so an UPDATE is how the
    marker lands. Keeps VibeCode turns filterable + out of generic history lists."""
    if pool is None or not source:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_runs SET source = $2 WHERE id = $1",
                workspace_id, source,
            )
    except Exception as exc:
        logger.error("DB: failed to set source for %s: %s", workspace_id, exc)


async def _db_set_run_attachments(pool, workspace_id: str, attachments: list) -> None:
    """Persist the user's ORIGINAL attachments (image/file refs) on a turn so the chat
    thread can render them inline. The agent's brief carries the machine-readable refs
    separately — this is purely for display (and survives reload)."""
    if pool is None or not attachments:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_runs SET attachments = $2::jsonb WHERE id = $1",
                workspace_id, json.dumps(attachments),
            )
    except Exception as exc:
        logger.error("DB: failed to set attachments for %s: %s", workspace_id, exc)


async def _db_save_event(pool, workspace_id: str, seq: int, event: OpenClawEvent) -> None:
    if pool is None:
        return
    try:
        payload: dict = {}
        for key in (
            "content", "tool", "args", "output", "success", "message",
            "summary", "fix_hint", "model", "parent_run_id",
            "run_id", "agent_label", "steps",
            "action_id", "risk", "approved",  # per-action permission gate (in-place)
            "analysis_md",  # Build Result Narrator: full written analysis on the terminal event
            # Harvis Execution Trace (Phase 1) — fields for the new event types
            # terminal_output / artifact / decision / search_trace. Keys not in
            # this whitelist are silently DROPPED at persist time.
            "stream", "command_id", "target", "exit_code", "duration_ms",
            "truncated", "lane", "tier", "policy", "reason",
            "artifact_id", "path", "mime_type", "size_bytes", "label",
            "phase", "query", "provider", "result_count", "results",
            "collapsed_by_default",
            # Replay parity: persist usage + final-text fields so a page reload
            # replays the run identically to the live stream (usage meter + text).
            "prompt_tokens", "completion_tokens", "total_tokens",
            "context_window", "source", "text",
            # agent_message (review loop): which persona is speaking (coder|reviewer);
            # label/content/run_id are already whitelisted above.
            "role",
            # The run's output files. `changed_files` is what the chat run card gates
            # its artifact list on, and `files` is the same list on a failed agent_end.
            # Both were being enriched onto the live event and then dropped here, so a
            # reload replayed a run with its files missing — the card showed prose only.
            "changed_files", "files",
        ):
            val = event.data.get(key)
            if val is not None:
                payload[key] = val
        # Always persist sub-agent tracking fields when present on the event object.
        if event.run_id and "run_id" not in payload:
            payload["run_id"] = event.run_id
        if event.agent_label and "agent_label" not in payload:
            payload["agent_label"] = event.agent_label

        # Last stop before the payload becomes a durable row. A Build run that ran
        # `env` once put a live API key into workspace_events in plaintext, where it
        # outlived the session and was readable by anything that reads run history.
        # The live stream still shows the operator their own output; only the stored
        # copy is scrubbed.
        payload = redact_payload(payload)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_events (workspace_id, seq, event_type, payload, ts)
                VALUES ($1, $2, $3, $4::jsonb, NOW())
                """,
                workspace_id, seq, event.type, json.dumps(payload),
            )
    except Exception as exc:
        logger.error("DB: failed to save event seq=%s workspace=%s: %s", seq, workspace_id, exc)


async def _db_complete_run(
    pool,
    workspace_id: str,
    status: str,
    summary: Optional[str],
    error: Optional[str],
    tool_calls: int,
    event_count: int,
    started_epoch: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    analysis_md: Optional[str] = None,
) -> None:
    if pool is None:
        return
    try:
        duration_ms = int((time.monotonic() - started_epoch) * 1000)
        async with pool.acquire() as conn:
            # Tokens are written CONDITIONALLY (COALESCE/NULLIF): a 0 leaves any existing
            # value intact — so the bg loop completing a vibecode/main run (which sets its
            # own tokens elsewhere) never clobbers them, while orchestrated sub-agents
            # (which pass real counts) get attributed. Powers the Background-tasks table.
            # analysis_md likewise: NULL leaves any prior value intact (non-Build runs don't
            # narrate, so they never clobber a Build run's analysis).
            await conn.execute(
                """
                UPDATE workspace_runs
                SET status            = $2,
                    completed_at      = NOW(),
                    duration_ms       = $3,
                    event_count       = $4,
                    tool_calls        = $5,
                    final_summary     = $6,
                    error_message     = $7,
                    prompt_tokens     = COALESCE(NULLIF($8, 0), prompt_tokens),
                    completion_tokens = COALESCE(NULLIF($9, 0), completion_tokens),
                    analysis_md       = COALESCE($10, analysis_md)
                WHERE id = $1
                """,
                workspace_id, status, duration_ms, event_count, tool_calls,
                summary, error, int(prompt_tokens or 0), int(completion_tokens or 0),
                analysis_md,
            )
    except Exception as exc:
        logger.error("DB: failed to complete workspace_run %s: %s", workspace_id, exc)


# ── Build Result Narrator helpers ─────────────────────────────────────────────────────────────
_NARRATOR_ENGINE_LABELS = {
    "opencode": "OpenCode", "codex": "Codex", "codex-local": "Codex", "codex-cloud": "Codex",
    "claude-code": "Claude Code", "hermes-agent": "Hermes Agent", "hermes-native": "Hermes",
    "native": "Native",
}


def _narrator_engine_label(ws: dict, agent_id: str) -> str:
    """Human label for the engine that ran this Build turn (for 'Built with X')."""
    eng = (ws.get("engine") or "").strip()
    if eng:
        return _NARRATOR_ENGINE_LABELS.get(eng, eng)
    if (ws.get("vibecode_persona_engine") or "").strip() == "hermes":
        return "Hermes"
    if agent_id == "claude":
        return "Claude Code"
    if agent_id == "kimi-code":
        return "Kimi Code"
    if agent_id in ("vibecode-turn", "orchestrated"):
        return "Native"
    return "Harvis"


async def _load_run_diff_summary(pool, workspace_id: str):
    """Read the run's diff + changed-files + file-artifact count from workspace_artifacts.
    Returns (changed_files: list[str], diff_text: str, file_count: int). Fail-soft → empties."""
    changed_files: list[str] = []
    diff_parts: list[str] = []
    file_paths: list[str] = []
    file_count = 0
    if pool is None:
        return changed_files, "", 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT artifact_type, content, path FROM workspace_artifacts WHERE workspace_id = $1",
                workspace_id,
            )
        for r in rows:
            at = r["artifact_type"]
            content = r["content"] or ""
            if at == "changed_files" and content:
                changed_files = [x.strip() for x in content.split("\n") if x.strip()]
            elif at == "diff" and content:
                diff_parts.append(content)
            elif at == "file":
                file_count += 1
                if r["path"]:
                    file_paths.append(r["path"])
    except Exception as exc:
        logger.warning("narrator: failed to load artifacts for %s: %s", workspace_id, exc)
    diff_text = "\n".join(diff_parts)
    if not changed_files and diff_text:
        changed_files = re.findall(r"^\+\+\+ b/(.+)$", diff_text, re.M)
    # Lanes with no git diff (e.g. the cloud-Claude chat lane) only emit `file` artifacts —
    # use their paths as the changed-files list so the analysis still names what was written.
    if not changed_files and not diff_text and file_paths:
        changed_files = file_paths
    return changed_files, diff_text, file_count


async def _compose_run_analysis(
    pool, ws: dict, agent_id: str, model_name: str, *, status: str, raw_summary: str,
    changed_files: list[str], diff_text: str, file_count: int, tool_calls: int,
    started_epoch: float, error_message: str = "", fix_hint: str = "",
) -> Optional[str]:
    """Compose the written Build analysis (deterministic; AI when flagged on, with fallback)."""
    from .build_narrator import (
        compose_build_analysis, build_narrator_ai_enabled, narrate_build_ai,
    )
    engine_label = _narrator_engine_label(ws, agent_id)
    rp = (ws.get("repo_path") or "").rstrip("/")
    repo_name = rp.rsplit("/", 1)[-1] if rp else ""
    task_brief = ws.get("task_brief") or ""
    duration_ms = int((time.monotonic() - started_epoch) * 1000)
    md = compose_build_analysis(
        task_brief=task_brief, engine_label=engine_label, model_name=model_name, status=status,
        raw_summary=raw_summary, changed_files=changed_files, diff_text=diff_text,
        file_count=file_count, tool_calls=tool_calls, duration_ms=duration_ms,
        error_message=error_message, fix_hint=fix_hint, repo_name=repo_name,
    )
    if status == "done" and build_narrator_ai_enabled():
        ai = await narrate_build_ai(
            deterministic_md=md, task_brief=task_brief, engine_label=engine_label,
            raw_summary=raw_summary, diff_text=diff_text,
        )
        if ai:
            md = ai
    return md


async def _db_mark_run_orphaned(pool, workspace_id: str, detail: str) -> None:
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workspace_runs
                SET status = 'error',
                    completed_at = COALESCE(completed_at, NOW()),
                    error_message = COALESCE(error_message, $2)
                WHERE id = $1
                  AND status = 'running'
                """,
                workspace_id,
                detail,
            )
    except Exception as exc:
        logger.error("DB: failed to mark orphaned workspace_run %s: %s", workspace_id, exc)


async def _db_enable_interactive(
    pool,
    *,
    workspace_id: str,
    user_id: int,
    ttl_seconds: int = 3600,
) -> str:
    """Enable Tier 3 for one workspace and return capability token."""
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    ttl = max(300, min(int(ttl_seconds or 3600), 7200))
    token = secrets.token_urlsafe(32)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_web_caps(workspace_id, user_id, interactive_enabled, capability_token, expires_at)
            VALUES ($1, $2, TRUE, $3, NOW() + ($4 * INTERVAL '1 second'))
            ON CONFLICT (workspace_id) DO UPDATE
              SET user_id = EXCLUDED.user_id,
                  interactive_enabled = TRUE,
                  capability_token = EXCLUDED.capability_token,
                  expires_at = EXCLUDED.expires_at
            """,
            workspace_id,
            user_id,
            token,
            ttl,
        )
    return token


# ─── Background task ────────────────────────────────────────────────────────────

async def _run_workspace_bg(workspace_id: str, pool, started_epoch: float) -> None:
    """
    Background asyncio.Task that drives the OpenClaw WebSocket stream to completion.

    This task is independent of the SSE connection.  If the browser disconnects
    (navigates away, Nginx timeout, pod event), the task keeps running so that
    sub-agents can finish, long tool calls complete, and every event gets saved
    to the DB.

    Events are also fan-out via WorkspaceLiveBroadcaster so every connected
    SSE or chat-bridge subscriber receives them in near-real-time without polling.
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        logger.warning("[workspace:%s] _run_workspace_bg: workspace not found", workspace_id)
        return

    client: OpenClawClient = ws["client"]
    task_brief: str = ws["task_brief"]
    chat_history: list[dict] = ws["chat_history"]
    agent_id: str = ws.get("agent_id", "main")
    model_name: str = ws.get("model_name", "")
    broadcaster: WorkspaceLiveBroadcaster = _workspace_broadcasters[workspace_id]

    # seq values come from the shared allocate_event_seq allocator (one monotonic
    # counter per workspace, shared with emit_terminal_event — no collisions).
    # `seq` holds the most recently allocated value; `event_count` counts this
    # loop's own emissions (for the completion row / log, as before).
    seq = -1
    event_count = 0
    tool_call_count = 0
    executing_tool_call_count = 0
    _RETRIEVAL_ONLY_TOOLS = {
        "memory_search",
        "memory_search_unified",
        "memory_get",
        "sessions_history",
        "sessions_list",
        "sessions_send",
        "session_status",
        "agents_list",
    }
    terminal_status = "done"
    final_summary: Optional[str] = None
    final_error: Optional[str] = None
    final_analysis_md: Optional[str] = None  # Build Result Narrator output (Build-like runs)
    token_chunks: list[str] = []

    # OpenClaw / native single-agent lanes: capture files the agent writes so chat
    # builds produce artifacts (+ auto-pop) like vibecode/orchestrator already do.
    # Excludes the lanes that already collect via _db_save_artifact internally.
    _oc_writes: dict[str, str] = {}
    _collect_writes = agent_id not in ("orchestrated", "vibecode-turn", "engine-adapter", "claude", "kimi-code")

    async def _flush_oc_writes() -> None:
        nonlocal event_count
        if not (_collect_writes and _oc_writes):
            return
        try:
            from .orchestration.isolation import _is_secret_artifact as _is_secret
        except Exception:
            def _is_secret(_n: str) -> bool:
                return False
        for _ap, _ac in list(_oc_writes.items()):
            if _is_secret(_ap):
                continue  # never expose .env / keys / credentials as artifacts
            _save = _ac if len(_ac) <= _OC_MAX_ARTIFACT_BYTES else f"<{len(_ac)} bytes — not snapshotted>"
            try:
                _aid = await _db_save_artifact(pool, workspace_id, "file", path=_ap, content=_save)
            except Exception as _exc:
                logger.warning("[workspace:%s] artifact save failed for %r: %s", workspace_id, _ap, _exc)
                continue
            # Harvis Execution Trace: surface the written file as a typed 'artifact'
            # event (seq from the shared allocator). size_bytes = true UTF-8 byte
            # length of the FULL content (not the possibly-truncated snapshot).
            if _aid:
                try:
                    _art = OpenClawEvent("artifact", {
                        "run_id": workspace_id,
                        "artifact_id": _aid,
                        "path": _ap,
                        "mime_type": (mimetypes.guess_type(_ap)[0] or "text/plain"),
                        "size_bytes": len((_ac or "").encode("utf-8")),
                        "label": os.path.basename(_ap) or "file",
                    })
                    _art_seq = await allocate_event_seq(pool, workspace_id)
                    await _db_save_event(pool, workspace_id, _art_seq, _art)
                    await broadcaster.put((_art_seq, _art))
                    event_count += 1
                except Exception as _exc:
                    logger.warning("[workspace:%s] artifact event emit failed for %r: %s", workspace_id, _ap, _exc)
        _oc_writes.clear()

    # ── Select the event stream based on agent_id ────────────────────────────
    event_stream = None
    use_parallel = ws.get("parallel", True)
    # The turn's raw attachment refs. Every lane below gets them: the API lanes turn
    # images into real multimodal parts, the CLI lanes stage them as files. A lane
    # that silently drops them is how "the model ignored my screenshot" happens.
    _attachments = ws.get("attachments") or []

    if agent_id == "local":
        if use_parallel:
            event_stream = stream_parallel_workspace(
                task_brief, chat_history, model=model_name, provider="local",
                attachments=_attachments, user_id=ws["user_id"],
            )
        else:
            event_stream = stream_local_ollama_workspace(
                task_brief, chat_history, model=model_name, attachments=_attachments, user_id=ws["user_id"],
            )

    elif agent_id == "kimi":
        api_key, kimi_url = await _get_kimi_credentials(pool, ws["user_id"])
        if api_key:
            if use_parallel:
                event_stream = stream_parallel_workspace(
                    task_brief, chat_history, api_key=api_key, model=model_name, provider="kimi",
                    api_url=kimi_url, attachments=_attachments, user_id=ws["user_id"],
                )
            else:
                event_stream = stream_kimi_workspace(
                    task_brief, chat_history, api_key, model=model_name, api_url=kimi_url,
                    attachments=_attachments, user_id=ws["user_id"],
                )
        else:
            logger.warning("No Kimi API key for user %s — falling back to local Ollama", ws["user_id"])
            fallback_event = OpenClawEvent("log", {
                "message": "Kimi (Moonshot) API key not found. Falling back to local Ollama.",
            })
            seq = await allocate_event_seq(pool, workspace_id)
            await _db_save_event(pool, workspace_id, seq, fallback_event)
            await broadcaster.put((seq, fallback_event))
            event_count += 1
            if use_parallel:
                event_stream = stream_parallel_workspace(
                    task_brief, chat_history, model=model_name, provider="local",
                    attachments=_attachments, user_id=ws["user_id"],
                )
            else:
                event_stream = stream_local_ollama_workspace(
                    task_brief, chat_history, model=model_name, attachments=_attachments, user_id=ws["user_id"],
                )

    elif agent_id == "claude":
        # Cloud Claude as a workspace engine — `claude -p` (the user's verified subscription
        # oauth or api_key) drives its OWN agentic tool-loop (web_search, exec, file ops) in
        # the harvis-claude-code sidecar. Zero GPU; mirrors the Kimi lane but for Claude.
        from .orchestration.engine_adapter import run_claude_chat_workspace
        event_stream = run_claude_chat_workspace(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id", ""),
            launch_mode=ws.get("launch_mode", "user"),  # Phase D: auto → Claude sidecar read-only
            # Attachments are staged into the sidecar's workdir — the CLI reads files,
            # it cannot be handed a multimodal image part.
            attachments=ws.get("attachments") or [],
        )

    elif agent_id == "kimi-code":
        # Kimi Code MEMBERSHIP as a workspace engine. Identical lane to `claude` above — the
        # same sidecar, the same `claude -p` agentic loop, the same tool set — with the CLI's
        # ANTHROPIC_BASE_URL repointed at Kimi Code and the user's verified membership key
        # injected. Kimi supplies the reasoning; Claude Code supplies the loop that reads
        # files, runs commands, and feeds tool results back. Zero GPU.
        from .orchestration.engine_adapter import run_claude_chat_workspace
        event_stream = run_claude_chat_workspace(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id", ""),
            launch_mode=ws.get("launch_mode", "user"),
            engine="kimi-code",
            attachments=ws.get("attachments") or [],
        )

    elif agent_id == "nvidia-kimi":
        nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        if nvidia_key:
            if use_parallel:
                event_stream = stream_parallel_workspace(
                    task_brief, chat_history, api_key=nvidia_key,
                    api_url="https://integrate.api.nvidia.com/v1", provider="kimi",
                    attachments=_attachments, user_id=ws["user_id"],
                )
            else:
                event_stream = stream_kimi_workspace(
                    task_brief, chat_history, nvidia_key,
                    api_url="https://integrate.api.nvidia.com/v1",
                    attachments=_attachments, user_id=ws["user_id"],
                )
        else:
            logger.warning("No NVIDIA API key — falling back to local Ollama")
            fallback_event = OpenClawEvent("log", {
                "message": "NVIDIA NIM key not found. Falling back to local Ollama.",
            })
            seq = await allocate_event_seq(pool, workspace_id)
            await _db_save_event(pool, workspace_id, seq, fallback_event)
            await broadcaster.put((seq, fallback_event))
            event_count += 1
            event_stream = stream_local_ollama_workspace(
                task_brief, chat_history, model=model_name, attachments=_attachments, user_id=ws["user_id"],
            )

    elif agent_id in ("cloud-ollama", "gpt-oss"):
        if use_parallel:
            event_stream = stream_parallel_workspace(
                task_brief, chat_history, model=model_name or "gpt-oss:120b", provider="cloud-ollama",
                attachments=_attachments, user_id=ws["user_id"],
            )
        else:
            event_stream = stream_ollama_cloud_workspace(
                task_brief, chat_history, model=model_name or "gpt-oss:120b", attachments=_attachments, user_id=ws["user_id"],
            )

    elif agent_id == "orchestrated":
        # P5: Harvis-native multi-agent orchestrator — parent → isolated sub-agent(s)
        # in git-tracked scratch dirs → diff artifact. Emits the same OpenClawEvent
        # stream, so the persist/broadcast loop + RunView/Neural Map render it
        # unchanged. See workspace/orchestration/.
        from .orchestration.orchestrator import run_orchestrated
        _repo_path = ws.get("repo_path")
        # Custom orchestration model pool (Agent Studio → Customize, opt-in). When the user
        # has ACTIVATED a pool, every orchestrate run re-models its task-delegated agents
        # across that pool (round-robin); else the run's own policy (uniform session model) holds.
        _custom_pool = None
        try:
            from owui_compat.orchestration_pool import get_orchestration_pool
            _cfg = await get_orchestration_pool(pool, ws["user_id"])
            if _cfg.get("active") and _cfg.get("models"):
                _custom_pool = _cfg["models"]
        except Exception:
            _custom_pool = None
        event_stream = run_orchestrated(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id") or f"ws-{workspace_id}",
            # Active custom pool → draw from it (heterogeneous); else the launch's uniform flag.
            uniform_model=False if _custom_pool else ws.get("uniform_model", False),
            model_pool=_custom_pool,
            # Attached-repo (clone-local) isolation when a repo is attached; else scratch.
            isolation_mode="attached" if _repo_path else "scratch",
            repo_config={"repo_path": _repo_path} if _repo_path else None,
            # Offer-time tool policy: auto-detected launches get heavy tools withheld.
            launch_mode=ws.get("launch_mode", "user"),
        )

    elif agent_id == "agent-native":
        # Agent pill on a model whose lane does NOT bring its own tool-loop: run ONE
        # Harvis agent through the native runner. This is the only lane that offers
        # WIRE_TOOL_SCHEMA — Agent Reach (web_read / gh_view / rss_read / yt_transcript)
        # included — so routing here is what makes "Agent" mean the same thing on an
        # Ollama tag as it does on a CLI engine. The previous default was OpenClaw,
        # which has no reach tools and deliberately never will (no outbound internet).
        # Escape hatch: HARVIS_OWUI_WORKSPACE_AGENT=main puts it back on OpenClaw.
        from .orchestration.orchestrator import run_orchestrated
        _repo_path = ws.get("repo_path")
        event_stream = run_orchestrated(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id") or f"ws-{workspace_id}",
            uniform_model=True,          # one agent, on the model the user picked
            single_agent=True,           # skip the planner — nothing to delegate
            isolation_mode="attached" if _repo_path else "scratch",
            repo_config={"repo_path": _repo_path} if _repo_path else None,
            launch_mode=ws.get("launch_mode", "user"),
        )

    elif agent_id == "vibecode-turn":
        # VibeCode cumulative-session turn: ONE agent on the session's PERSISTENT
        # working clone (clone-mode). Each follow-up builds on prior turns' edits;
        # the diff accumulates vs the session's fixed base_sha. See orchestration/
        # session_turn.py. Same OpenClawEvent stream → unchanged persist/broadcast.
        from .orchestration.session_turn import run_vibecode_turn
        event_stream = run_vibecode_turn(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id") or f"ws-{workspace_id}",
            vibecode_session_id=ws.get("vibecode_session_id") or "",
            workspace_path=ws.get("workspace_path") or "",
            base_sha=ws.get("base_sha") or "",
            repo_path=ws.get("repo_path") or "",
            isolation_mode=ws.get("vibecode_isolation_mode") or "session",
            permission_mode=ws.get("vibecode_permission_mode") or "ask",
            # Phase E4: "hermes" → SOUL persona + Hermes model; "" → plain native runner.
            persona_engine=ws.get("vibecode_persona_engine") or "",
            # Offer-time tool policy: auto-detected launches get heavy tools withheld.
            launch_mode=ws.get("launch_mode", "user"),
            # Image attachments become real multimodal parts on the first user
            # message — a screenshot the model can actually look at.
            attachments=ws.get("attachments") or [],
        )

    elif agent_id == "vibecode-review":
        # Agent Review Conversation (opt-in): coder ↔ reviewer dialogue over the
        # session's ACCUMULATED diff, in the session's OWN workspace. Emits
        # 'agent_message' conversation events + the usual tool/approval stream;
        # sets vibecode_sessions.review_status ('agreed' | 'needs_human'). See
        # orchestration/review.py. Same OpenClawEvent stream → unchanged
        # persist/broadcast.
        from .orchestration.review import run_review_conversation
        event_stream = run_review_conversation(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id") or f"ws-{workspace_id}",
            vibecode_session_id=ws.get("vibecode_session_id") or "",
            workspace_path=ws.get("workspace_path") or "",
            base_sha=ws.get("base_sha") or "",
            repo_path=ws.get("repo_path") or "",
            isolation_mode=ws.get("vibecode_isolation_mode") or "session",
            permission_mode=ws.get("vibecode_permission_mode") or "ask",
            launch_mode=ws.get("launch_mode", "user"),
            base_branch=ws.get("vibecode_review_base") or "",
            mode=ws.get("vibecode_review_mode") or "thread",
            reviewer_ids=ws.get("vibecode_reviewer_ids") or None,
        )

    elif agent_id == "engine-adapter":
        # External code engine (Phase E1, e.g. OpenCode): run an external CLI against the
        # session's clone via the sidecar; same OpenClawEvent stream → unchanged persist/
        # broadcast/RunView. CLONE (session) isolation only — enforced at turn dispatch.
        from .orchestration.engine_adapter import run_external_engine_adapter
        event_stream = run_external_engine_adapter(
            task_brief, chat_history,
            model_name=model_name, pool=pool,
            parent_workspace_id=workspace_id, user_id=ws["user_id"],
            session_id=ws.get("session_id") or f"ws-{workspace_id}",
            vibecode_session_id=ws.get("vibecode_session_id") or "",
            workspace_path=ws.get("workspace_path") or "",
            base_sha=ws.get("base_sha") or "",
            repo_path=ws.get("repo_path") or "",
            engine=ws.get("engine") or "opencode",
            api_key=ws.get("engine_key"),  # decrypted per-user credential for cloud engines; None for opencode
            auth_mode=ws.get("engine_auth_mode") or "api_key",  # E4B: api_key vs subscription oauth_token
            # Staged into the clone before the CLI launches — an external engine reads
            # files, so this is the only way an attached screenshot reaches it.
            attachments=ws.get("attachments") or [],
        )

    else:
        # Default: route through OpenClaw WebSocket
        event_stream = client.stream(
            task_brief,
            chat_history,
            interactive_context=ws.get("interactive_context"),
            live_web=ws.get("live_web", True),
        )

    try:
        async for event in event_stream:
            if event.type == "tool_call":
                tool_call_count += 1
                _tname = (event.data or {}).get("tool", "")
                if _tname not in _RETRIEVAL_ONLY_TOOLS:
                    executing_tool_call_count += 1
                # Capture file writes (full body lives in the write tool_call args) so
                # this lane produces artifacts. Latest content wins per path.
                if _collect_writes and _tname in _OC_WRITE_TOOLS:
                    _wargs = (event.data or {}).get("args") or {}
                    _wpath, _wcontent = _wargs.get("path"), _wargs.get("content")
                    if isinstance(_wpath, str) and _wpath and isinstance(_wcontent, str):
                        _oc_writes[_clean_oc_artifact_path(_wpath)] = _wcontent
                # Harvis Execution Trace: surface web-search tool calls as typed
                # 'search_trace' events (seq from the shared allocator; a failed
                # emit never blocks the run).
                if _is_search_tool(_tname):
                    try:
                        _sargs = (event.data or {}).get("args") or {}
                        _st = OpenClawEvent("search_trace", {
                            "run_id": workspace_id,
                            "query": _sargs.get("query") or _sargs.get("q") or "",
                            "provider": "web",
                            "result_count": 0,
                            "results": [],
                            "phase": "searching",
                        })
                        _st_seq = await allocate_event_seq(pool, workspace_id)
                        await _db_save_event(pool, workspace_id, _st_seq, _st)
                        await broadcaster.put((_st_seq, _st))
                        event_count += 1
                    except Exception as exc:
                        logger.warning(
                            "[workspace:%s] failed to emit search_trace event: %s",
                            workspace_id, exc,
                        )
            elif event.type == "token":
                tok = event.data.get("content")
                if isinstance(tok, str) and tok:
                    token_chunks.append(tok)
                    # Bound memory while still preserving recent output for fallback summary.
                    if len(token_chunks) > 400:
                        token_chunks = token_chunks[-400:]

            # Persist NON-terminal events first (authoritative for replays). TERMINAL events
            # (done/cancelled/error) are saved AFTER the validators + Build narrator enrich
            # event.data below, so a reload/replay carries the final summary + analysis_md.
            if event.type not in ("done", "cancelled", "error"):
                seq = await allocate_event_seq(pool, workspace_id)
                await _db_save_event(pool, workspace_id, seq, event)

            if event.type in ("done", "cancelled", "error"):
                terminal_status = event.type
                ws["status"] = event.type
                structured = None  # set in the 'done' branch; referenced by the narrator below
                # Persist captured file writes as artifacts BEFORE the terminal event is
                # broadcast, so the frontend auto-pop (fetches /run/{id}/artifacts on
                # 'done') finds them. No-op for lanes that already collect.
                await _flush_oc_writes()
                if event.type == "done":
                    raw_summary = event.data.get("summary") or ""
                    if not raw_summary.strip():
                        raw_summary = "".join(token_chunks).strip()
                        if raw_summary:
                            event.data["summary"] = raw_summary

                    # Validator passes — catch fabricated claims before they
                    # reach the user. Two layers:
                    #   1. Hash-specific: recomputes md5/sha1/sha256 of claimed
                    #      plaintexts against hashes in the brief.
                    #   2. General CTF: catches zero-tool_call process claims
                    #      for any skill (decode, crypto, forensics, hash).
                    try:
                        validated, was_fabricated = _validate_hash_claims(
                            task_brief, raw_summary,
                            tool_call_count=executing_tool_call_count,
                        )
                        if was_fabricated:
                            logger.warning(
                                "[workspace:%s] Hash-claim fabrication caught + "
                                "replaced. Original summary (first 300 chars): %r",
                                workspace_id, raw_summary[:300],
                            )
                            raw_summary = validated
                            event.data["summary"] = validated
                            event.data["_validator_replaced"] = True
                    except Exception as exc:
                        logger.exception(
                            "[workspace:%s] Hash-claim validator crashed; "
                            "letting original summary through: %s",
                            workspace_id, exc,
                        )
                    # Layer 2: general CTF process-claim validator
                    if not event.data.get("_validator_replaced"):
                        try:
                            validated2, was_fab2 = _validate_ctf_process_claims(
                                task_brief, raw_summary,
                                tool_call_count=executing_tool_call_count,
                            )
                            if was_fab2:
                                logger.warning(
                                    "[workspace:%s] CTF process-claim fabrication "
                                    "caught. Original (first 300 chars): %r",
                                    workspace_id, raw_summary[:300],
                                )
                                raw_summary = validated2
                                event.data["summary"] = validated2
                                event.data["_validator_replaced"] = True
                        except Exception as exc:
                            logger.exception(
                                "[workspace:%s] CTF process-claim validator "
                                "crashed: %s", workspace_id, exc,
                            )

                    final_summary = raw_summary
                    # Parse structured result from research/document skills
                    structured = _parse_structured_result(raw_summary)
                    if structured is not None:
                        # Inject structured data into the done event so the frontend
                        # SSE client can render source cards + artifact download cards
                        event.data.update(structured)
                elif event.type == "error":
                    final_error = event.data.get("message")

                # A terminal 'done' whose agents all failed is not a success. The
                # orchestrator now says so in the payload; without this the run row
                # was written 'done' and the narrator headline read "Build complete"
                # over a run the user watched error out. The event type stays 'done'
                # so the summary still renders — only the verdict changes.
                _agents_failed = (
                    event.type == "done" and event.data.get("success") is False
                )
                if _agents_failed:
                    terminal_status = "error"
                    ws["status"] = "error"
                    if not final_error:
                        final_error = "The agent did not finish the task."

                # ── Build Result Narrator: compose the full written analysis as the assistant
                #    message. Scoped to Build-like runs (a git diff exists OR a VibeCode turn);
                #    skips CTF (no diff) + research/document (structured source-card output).
                #    Fail-soft: any error → no analysis_md, the short summary still renders.
                try:
                    from .build_narrator import build_narrator_enabled
                    if build_narrator_enabled():
                        _bn_changed, _bn_diff, _bn_fc = await _load_run_diff_summary(pool, workspace_id)
                        # Build-like = a git diff (VibeCode/orchestrated) OR a VibeCode turn OR a
                        # chat cloud-Claude build that wrote files (agent_id="claude" — distinct from
                        # the OpenClaw CTF lane, so this never narrates hash/decode tasks).
                        _build_like = bool(
                            _bn_changed or _bn_diff or ws.get("vibecode_session_id")
                            or (agent_id in ("claude", "kimi-code") and _bn_fc > 0)
                        )
                        if event.type == "done" and _build_like and structured is None:
                            final_analysis_md = await _compose_run_analysis(
                                pool, ws, agent_id, model_name,
                                status="error" if _agents_failed else "done",
                                raw_summary=final_summary or "", changed_files=_bn_changed,
                                diff_text=_bn_diff, file_count=_bn_fc,
                                tool_calls=executing_tool_call_count, started_epoch=started_epoch,
                                error_message=final_error or "" if _agents_failed else "",
                            )
                        elif event.type in ("error", "cancelled") and ws.get("vibecode_session_id"):
                            final_analysis_md = await _compose_run_analysis(
                                pool, ws, agent_id, model_name, status=event.type,
                                raw_summary=final_summary or "", changed_files=[], diff_text="",
                                file_count=0, tool_calls=executing_tool_call_count,
                                started_epoch=started_epoch,
                                error_message=final_error or event.data.get("message") or "",
                                fix_hint=event.data.get("fix_hint") or "",
                            )
                        if final_analysis_md:
                            event.data["analysis_md"] = final_analysis_md
                except Exception as exc:
                    logger.warning("[workspace:%s] Build narrator failed: %s", workspace_id, exc)

                # The files the run produced, on the terminal event itself. The chat run
                # card gates its artifact list on `done.changed_files`, and nothing was
                # ever putting that key there — so a run that wrote a real file showed the
                # user prose and no file at all. The artifacts were already in the
                # database; only the pointer was missing. Computed here rather than inside
                # the narrator block above because the narrator is flag-gated and the file
                # list is not optional.
                if event.type == "done" and not event.data.get("changed_files"):
                    try:
                        _cf, _, _ = await _load_run_diff_summary(pool, workspace_id)
                        if _cf:
                            event.data["changed_files"] = _cf
                    except Exception as exc:
                        logger.warning(
                            "[workspace:%s] changed_files lookup failed: %s", workspace_id, exc
                        )

                # Harvis Execution Trace: additionally emit the final answer as a typed
                # 'final_message' envelope BEFORE the 'done' event below (the shared
                # allocator guarantees final_message gets seq N and done gets N+1 — no
                # collision, no dropped 'done'). The 'done' event is unchanged; this is
                # purely additive for non-UI consumers (Discord/CLI).
                if event.type == "done":
                    try:
                        _final_content = event.data.get("summary") or ""
                        if _final_content:
                            _fm = OpenClawEvent("final_message", {
                                "run_id": workspace_id, "content": _final_content,
                            })
                            _fm_seq = await allocate_event_seq(pool, workspace_id)
                            await _db_save_event(pool, workspace_id, _fm_seq, _fm)
                            await broadcaster.put((_fm_seq, _fm))
                            event_count += 1
                    except Exception as exc:
                        logger.warning(
                            "[workspace:%s] failed to emit final_message event: %s",
                            workspace_id, exc,
                        )

                # Persist the ENRICHED terminal event (validated summary + analysis_md), then
                # fan-out to live subscribers.
                seq = await allocate_event_seq(pool, workspace_id)
                await _db_save_event(pool, workspace_id, seq, event)
                await broadcaster.put((seq, event))
                event_count += 1
                break

            # Fan-out to all live subscribers (chat bridge, /stream SSE, etc.)
            # — same seq the persist above used for this event.
            await broadcaster.put((seq, event))
            event_count += 1

        logger.info(
            "[workspace:%s] Background task finished: status=%s events=%d tool_calls=%d",
            workspace_id, terminal_status, event_count, tool_call_count,
        )

    except asyncio.CancelledError:
        # /cancel was called — save a terminal event so SSE sees it
        terminal_status = "cancelled"
        ws["status"] = "cancelled"
        cancelled_event = OpenClawEvent("cancelled", {"message": "Workspace cancelled."})
        seq = await allocate_event_seq(pool, workspace_id)
        await _db_save_event(pool, workspace_id, seq, cancelled_event)
        await broadcaster.put((seq, cancelled_event))
        event_count += 1

    except Exception as exc:
        logger.error("[workspace:%s] Background task error: %s", workspace_id, exc)
        terminal_status = "error"
        final_error = str(exc)
        ws["status"] = "error"
        err_event = OpenClawEvent("error", {
            "message": str(exc),
            "fix_hint": "An unexpected error occurred in the workspace background task. Check backend logs.",
        })
        seq = await allocate_event_seq(pool, workspace_id)
        await _db_save_event(pool, workspace_id, seq, err_event)
        await broadcaster.put((seq, err_event))
        event_count += 1

    finally:
        # Safety net: persist any captured writes not yet flushed (cancel/error paths
        # skip the in-loop terminal block). No-op on the normal 'done' path.
        await _flush_oc_writes()
        # None sentinel signals each subscriber that the stream has ended
        await broadcaster.put(None)

        await _db_complete_run(
            pool, workspace_id, terminal_status,
            final_summary, final_error, tool_call_count, event_count, started_epoch,
            analysis_md=final_analysis_md,
        )
        # Build Space lifecycle: a vibecode turn reached a terminal status (done/error/
        # cancelled) → flip the session back to 'ready'. Guarded on lifecycle='running'
        # so a 'blocked' session is never overwritten. Fail-open.
        _vib_sid = ws.get("vibecode_session_id")
        if _vib_sid and pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE vibecode_sessions SET lifecycle = 'ready', updated_at = NOW() "
                        "WHERE id = $1 AND lifecycle = 'running'",
                        _vib_sid,
                    )
            except Exception as exc:
                logger.warning("vibecode: lifecycle reset failed for %s: %s", _vib_sid, exc)
        # Agent-review safety net: a review run that ended WITHOUT the loop writing a
        # terminal review_status (cancelled mid-conversation, task killed) must not
        # wedge the PR gate at 'pending' forever → land it on 'needs_human'. The WHERE
        # makes this a no-op after a normal finish ('agreed'/'needs_human' already set).
        if agent_id == "vibecode-review" and _vib_sid and pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE vibecode_sessions SET review_status = 'needs_human', "
                        "updated_at = NOW() WHERE id = $1 AND review_status = 'pending'",
                        _vib_sid,
                    )
            except Exception as exc:
                logger.warning("vibecode: review-status repair failed for %s: %s", _vib_sid, exc)
        # Gate re-lock: a COMPLETED coding turn (not a review) produces new changes that
        # invalidate a prior 'agreed' review — the reviewers approved the OLD diff, so shipping
        # now would pass changes nobody reviewed. Flip 'agreed' → 'stale' so Create-PR re-blocks
        # until a fresh review runs. The WHERE makes it a no-op unless the review was agreed.
        # 'engine-adapter' = an external-engine (opencode/codex/claude-code/hermes) coding turn on
        # the SAME session tree, so it invalidates a prior agreement exactly like a native turn.
        # 'orchestrated' is excluded (sub-agents work on isolated clones); 'vibecode-review' too.
        if agent_id in ("vibecode-turn", "engine-adapter") and terminal_status == "done" and _vib_sid and pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE vibecode_sessions SET review_status = 'stale', "
                        "updated_at = NOW() WHERE id = $1 AND review_status = 'agreed'",
                        _vib_sid,
                    )
            except Exception as exc:
                logger.warning("vibecode: review-gate re-lock failed for %s: %s", _vib_sid, exc)
        _workspace_tasks.pop(workspace_id, None)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _validate_hash_claims(
    task_brief: str,
    summary: str,
    *,
    tool_call_count: int = 0,
) -> tuple[str, bool]:
    """Catch fabricated plaintext claims for hashes that appear in the task brief.

    Small open-weight models (qwen3:14b, hermes-4) sometimes claim a verified
    plaintext for a hash even when their tool calls returned `verified: false`,
    or invent a fake JSON tool response in their text. This validator catches
    those by recomputing md5/sha1/sha256 of any claimed plaintext and
    comparing against the hashes in the task brief.

    `tool_call_count` is the number of **executing** tool_call events (caller
    excludes memory_search / sessions_history / etc.). If a "verified / cracked /
    matches" claim appears with zero such calls, the run is fabricated by
    construction — no exec happened, so no hash could have been computed.
    Caught deterministically below.

    Returns (possibly_rewritten_summary, was_fabricated). If was_fabricated is
    True, the summary has been replaced with honest-failure text — the caller
    should use the new summary for both the SSE event and DB persistence.

    Rationale: industry-standard "tool receipts" mitigation pattern (NABAOS).
    All directive-based fabrication-mitigation is probabilistic; this is
    deterministic.
    """
    import hashlib
    import re

    if not summary or not task_brief:
        return summary, False

    # Find hex hash candidates in the brief (MD5=32, SHA1=40, SHA224=56,
    # SHA256=64, SHA384=96, SHA512=128). Word-boundary anchored.
    hash_re = re.compile(r"\b([a-f0-9]{32}|[a-f0-9]{40}|[a-f0-9]{56}|[a-f0-9]{64}|[a-f0-9]{96}|[a-f0-9]{128})\b", re.IGNORECASE)
    target_hashes = list({h.lower() for h in hash_re.findall(task_brief)})
    if not target_hashes:
        return summary, False

    # ── Pre-check: zero-tool_call crack-success claims ────────────────────
    # If the run made NO real tool calls but the response narrates a
    # "cracked / verified / matched" outcome, the response is fabricated by
    # construction. No exec happened, so no hash could have been computed,
    # so any matches-claim is invented. Catch this deterministically before
    # we even bother pattern-matching plaintexts.
    success_signal_re = re.compile(
        r"\b("
        r"verified[\s:]+(?:via|with|by|using|true)"
        r"|verified\s*[:=]\s*true"
        r"|cracked\s+(?:with|via|using|by|the\s+hash|successfully)"
        r"|plaintext[\s\S]{0,60}?matches"
        r"|matches\s+(?:the\s+)?target\s+hash"
        r"|hash\s+(?:was\s+)?cracked"
        r"|successfully\s+cracked"
        r"|tiers?_tried"
        # Channel 2 regression patterns (2026-05-19)
        r"|corresponds\s+to\s+(?:the\s+)?plaintext"
        r"|no\s+additional\s+tool\s+calls\s+(?:were\s+)?needed"
        r"|directly\s+computing\s+hashlib"
        r"|running\s+this\s+in\s+python\s+gives"
        r"|I\s+verified\s+by\s+running"
        r")\b",
        re.IGNORECASE,
    )
    if tool_call_count == 0 and success_signal_re.search(summary):
        replacement_lines = [
            "**Could not determine plaintext for the provided hash(es).**",
            "",
            "The agent narrated a successful crack but made **zero tool calls** "
            "during this run — meaning no hash was actually computed or compared. "
            "The output is hallucinated text, not a real result. Suppressing it.",
            "",
            f"Target hash(es): `{target_hashes}`",
            "",
            "Re-run the workspace; the model must emit real `exec` tool calls "
            "(not narrate them in prose). If the agent keeps text-narrating "
            "tool calls instead of emitting them through the tool channel, "
            "swap to a model with stronger tool-use compliance.",
        ]
        return "\n".join(replacement_lines), True

    # ── Pre-check: zero-tool_call fabricated PROCESS claims ─────────────
    # Catches the case where the model claims to have *run* tools (even
    # reporting a negative result like "verified: false") but emitted zero
    # tool_calls. This is subtler than the success-signal check above —
    # the model says "I ran the cracker and it failed" without ever calling
    # exec. The response SOUNDS honest ("not cracked") but the process
    # description is fabricated. Groudon regression (2026-05-20).
    process_claim_re = re.compile(
        r"\b("
        r"I\s+(?:ran|executed|used|attempted|applied|tried)\s+(?:the\s+)?(?:hash|crack|tool|skill|script|cracker)"
        r"|(?:ran|executed|used)\s+(?:the\s+)?(?:Harvis\s+)?hash.?crack"
        r"|applying\s+all\s+(?:supported\s+)?tiers"
        r"|all\s+(?:supported\s+)?tiers?\s+(?:were\s+)?(?:tried|attempted|exhausted|run)"
        r"|the\s+(?:tool|cracker|script)\s+(?:reported|returned|confirmed|showed)"
        r"|after\s+exhausting\s+(?:every|all|its)"
        r"|all\s+attempts\s+returned"
        r"|verified\s*[:=]\s*false\s+after"
        r"|cracking\s+(?:tool|skill|script)\s+confirmed"
        r"|none\s+of\s+these\s+attempts\s+matched"
        r")\b",
        re.IGNORECASE,
    )
    if tool_call_count == 0 and process_claim_re.search(summary):
        replacement_lines = [
            "**Hash cracking was not performed.**",
            "",
            "The agent described running crack attempts but made **zero tool "
            "calls** during this run — the process narrative is fabricated. "
            "No exec tool was invoked, so no wordlist or online lookup was "
            "actually tried.",
            "",
            f"Target hash(es): `{target_hashes}`",
            "",
            "Please re-run the request. The model must use the `exec` tool to "
            "call cracker.py — describing the process in text is not the same "
            "as executing it.",
        ]
        return "\n".join(replacement_lines), True

    # ── Zero-tool MEMORIZATION / context-echo guard ──────────────────────
    # With no executing tool calls, the model did no cracking — it cannot have
    # legitimately *obtained* any plaintext. If the summary nonetheless reveals
    # a string that hashes to a target, that answer was recalled from the model's
    # training weights (e.g. it "knows" md5(password)=5f4dcc…) or read from the
    # conversation — NOT cracked. This enforces the "must obtain it itself" rule:
    # a bare correct answer with zero tools is cheating, regardless of phrasing
    # (the phrase-gated checks above only catch "cracked/verified/I ran …").
    if tool_call_count == 0:
        target_set = set(target_hashes)
        # Candidate plaintexts: tokenize, treating quotes/backticks/asterisks as
        # delimiters so `password` / **password** / "password" all surface.
        cleaned = re.sub(r"[`'\"*]", " ", summary)
        candidates = set()
        for tok in re.findall(r"\S{1,70}", cleaned):
            candidates.add(tok)  # raw (a password may legitimately end in punctuation)
            stripped = tok.strip(".,!?;:()[]{}<>")  # …but usually it's a sentence ender
            if stripped:
                candidates.add(stripped)
        leaked = None
        for cand in candidates:
            for algo in ("md5", "sha1", "sha256"):
                try:
                    if hashlib.new(algo, cand.encode("utf-8")).hexdigest() in target_set:
                        leaked = cand
                        break
                except (ValueError, UnicodeError):
                    continue
            if leaked:
                break
        if leaked:
            replacement_lines = [
                "**Answer suppressed — the agent did not actually crack the hash.**",
                "",
                "It produced a correct plaintext with **zero tool calls** — meaning "
                "the answer was recalled from the model's training (or read from the "
                "conversation), not obtained by cracking. The hash must be solved by "
                "running the cracker (`exec`) or a web search, never stated from memory.",
                "",
                f"Target hash(es): `{target_hashes}`",
                "",
                "Re-run; the model must emit a real `exec` (cracker.py) or `web_search` "
                "tool call and report only its verified output.",
            ]
            return "\n".join(replacement_lines), True

    # ── Stray-hash check ──────────────────────────────────────────────
    # If the summary references a hex hash that does NOT appear in the
    # task_brief, the model is answering a DIFFERENT question (likely
    # pulled from session memory or chat history contamination). This
    # catches the Channel 2 regression where the brief had 1c885e...
    # but the model answered about 5d4140... from a prior turn.
    summary_hashes = {h.lower() for h in hash_re.findall(summary)}
    stray_hashes = summary_hashes - set(target_hashes)
    if stray_hashes and not summary_hashes.intersection(target_hashes):
        replacement_lines = [
            "**Could not determine plaintext for the provided hash(es).**",
            "",
            "The agent's response referenced hash(es) "
            f"`{sorted(stray_hashes)[:3]}` which do NOT appear in the "
            f"original request. The target was `{target_hashes}`. "
            "This is a cross-contamination artifact — the model answered "
            "a different question (likely from a prior conversation turn). "
            "Suppressing.",
            "",
            "Re-run the workspace; the model should only address the "
            "hash(es) in the current request.",
        ]
        return "\n".join(replacement_lines), True

    _FALSE_POSITIVE_PLAINTEXT = frozenset({
        # English prose after "plaintext is …" ("known to cryptographers", etc.)
        "known",
        "unknown",
        "unavailable",
        "uncertain",
        "undetermined",
        "unclear",
        "possible",
        "possibly",
        "unlikely",
        "likely",
        "still",
        "not",
        "yet",
        "never",
        "being",
        "currently",
        "presently",
        "simply",
        # Short copulas/connectors that the greedy regex grabs when a real
        # plaintext is markdown-bolded on the next line, e.g. "verified
        # plaintext is:\n\n**basculin**" → regex captures "is" (basculin
        # 2026-05-23 false positive).
        "is",
        "be",
        "are",
        "was",
        "were",
        "this",
        "that",
        "it",
        "they",
        "we",
        "you",
        "may",
        "might",
        "could",
        "would",
        "should",
        "result",
        "results",
        "match",
        "matches",
    })

    # Patterns where the agent claims a specific plaintext.
    # Pull candidates from any of these shapes.
    claim_patterns = [
        # "the plaintext is `m3w`" / "plaintext is m3w" / "plaintext: m3w"
        r"plaintext(?:\s+is|\s*[=:])\s*[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+",
        # Reject adjunct capture: "plaintext is known to analysts ..." → not a password literal
        r"plaintext(?:\s+is|\s*[=:])\s+([A-Za-z0-9_\-\.!@#\$%]+)\b(?!\s+to\b)",
        # "plaintext "password" matches" / "plaintext `m3w` matches" — no is/=/: between
        r"plaintext\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+\s*(?:matches|matched|=|:|hashes\s+to)",
        # "corresponds to `m3w`" / "corresponds to **m3w**"
        r"corresponds to\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+",
        # "Answer: m3w" / "Final answer: m3w" — only when followed by a short token
        r"(?:^|\n)(?:Final\s+)?Answer\s*[:\-]\s*[`'\"\*]*\s*([A-Za-z0-9_\-\.!@#\$%]{1,32})\s*[`'\"\*]*\s*(?:$|\n|\.)",
        # JSON-shaped fake tool response: "plaintext": "m3w"
        r'"plaintext"\s*:\s*"([A-Za-z0-9_\-\.!@#\$%]+)"',
        # "verified plaintext X" / "X (lowercase)" form
        r"verified plaintext[\s:]+[`'\"\*]*([A-Za-z0-9_\-\.!@#\$%]+)[`'\"\*]*",
        # Python hashlib call narrated in prose: `md5("password")` / md5('hello')
        r"(?:md5|sha1|sha256|sha512)\s*\(\s*[`'\"]([A-Za-z0-9_\-\.!@#\$%]+)[`'\"]",
        # "Cracked with X tier ... plaintext Y" / "cracked: plaintext"
        r"[Cc]racked\b[^\.\n]{0,80}?plaintext[\s:]+[`'\"\*]*([A-Za-z0-9_\-\.!@#\$%]+)[`'\"\*]*",
        # "matched: X" / "match: X" in cracker-output-mirroring contexts
        r"(?:^|\s)matched?\s*[:=]\s*[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+",
        # Hedged-guess patterns (granite4.1:8b regression 2026-05-23). The
        # model says "the intended answer might be 'charizard'" instead of
        # honestly reporting unverified. Each pattern requires a noun like
        # answer/plaintext/password/key paired with a hedge verb, so
        # generic prose ("the wordlist might be in /tmp") doesn't match.
        r"\b(?:intended\s+|final\s+)?answer\s+(?:might|could|may|would|should|is\s+likely)\s+be\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]{1,32})\s*[`'\"\*]+",
        r"\bplaintext\s+(?:might|could|may|would|should|is\s+likely)\s+be\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]{1,32})\s*[`'\"\*]+",
        r"\b(?:might|could|may)\s+be\s+(?:the\s+)?(?:plaintext|password|answer|key)\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]{1,32})\s*[`'\"\*]+",
        # Quoted hedged guess without anchor noun: "likely 'X'" / "probably 'Y'"
        # Higher FP risk (e.g. 'the file is likely "config.json"') but the
        # downstream md5/sha1/sha256 == target check filters non-matches.
        r"\b(?:likely|probably|most\s+likely)\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]{1,32})\s*[`'\"\*]+",
        # Markdown-bolded plaintext after "plaintext is:" or "plaintext:"
        # ("verified plaintext is:\n\n**basculin**" — basculin 2026-05-23).
        # Catches real cracks reported in canonical markdown-summary format.
        r"plaintext\s+(?:is\s*)?[:=]\s*[\s\n\r]*\*\*([A-Za-z0-9_\-\.!@#\$%]{1,32})\*\*",
        # Same but without colon: "plaintext is **basculin**"
        r"plaintext\s+is\s+\*\*([A-Za-z0-9_\-\.!@#\$%]{1,32})\*\*",
    ]

    claimed: set[str] = set()
    for pat in claim_patterns:
        for m in re.finditer(pat, summary, re.IGNORECASE | re.MULTILINE):
            cand = (m.group(1) or "").strip().strip("'\"`*.,")
            if not cand or len(cand) > 64:
                continue
            low = cand.lower()
            junk = _FALSE_POSITIVE_PLAINTEXT | {
                "null", "none", "verified", "false", "true", "unknown",
                "n/a", "na", "nil", "undefined", "x", "y", "value",
                "string", "any", "tbd", "todo", "unverified",
            }
            if low in junk:
                continue
            claimed.add(cand)

    if not claimed:
        return summary, False

    # For each target hash, check if any claimed plaintext genuinely hashes to it
    algo_by_len = {
        32:  hashlib.md5,
        40:  hashlib.sha1,
        56:  hashlib.sha224,
        64:  hashlib.sha256,
        96:  hashlib.sha384,
        128: hashlib.sha512,
    }

    any_verified = False
    fabricated_hash_list: list[str] = []
    for h in target_hashes:
        algo = algo_by_len.get(len(h))
        if algo is None:
            continue
        matched_for_this_hash = False
        for cand in claimed:
            computed = algo(cand.encode("utf-8")).hexdigest().lower()
            if computed == h:
                matched_for_this_hash = True
                any_verified = True
                break
        if not matched_for_this_hash:
            fabricated_hash_list.append(h)

    # If at least one claim is genuine, let the response through (don't punish
    # a real crack just because the model also mentioned an unrelated string).
    if any_verified:
        return summary, False

    # Every target hash had claims that don't verify. Replace.
    if tool_call_count > 0:
        tail = (
            "The agent did run tools, but the plaintext token(s) extracted from its "
            "answer do not hash to the target — this is often a false positive from "
            "English prose (e.g. “known”, “unknown”) or a wrong guess. Prefer the "
            "cracker JSON (`verified`, `tiers_tried`) in the original response when "
            "available."
        )
    else:
        tail = (
            "Either the cracker tool returned `verified: false`, or the agent skipped "
            "the verification step. No reliable answer is available from this run."
        )
    replacement_lines = [
        "**Could not determine plaintext for the provided hash(es).**",
        "",
        "The agent produced an answer that did not pass verification: it claimed "
        f"plaintext(s) `{sorted(claimed)}` but md5/sha1/sha256 of these does NOT "
        "match the target hash(es). The claim has been suppressed because it "
        "would otherwise be misleading.",
        "",
        f"Target hash(es): `{fabricated_hash_list}`",
        "",
        tail,
    ]
    return "\n".join(replacement_lines), True


def _validate_ctf_process_claims(
    task_brief: str,
    summary: str,
    *,
    tool_call_count: int = 0,
) -> tuple[str, bool]:
    """Catch fabricated process claims for CTF skills (decode, crypto, forensics).

    Complements _validate_hash_claims (which handles hash-specific verification).
    This validator catches the general case: the model claims to have run a
    CTF skill tool (decoder.py, cipher.py, analyze.py) but tool_call_count is 0.

    Only fires when:
    1. The task brief matches a CTF skill pattern (decode/crypto/forensics keywords)
    2. tool_call_count == 0
    3. The summary contains process-claim language ("I ran", "the tool returned", etc.)

    Does NOT fire for hash tasks (those are handled by _validate_hash_claims).
    """
    import re

    if not summary or not task_brief or tool_call_count > 0:
        return summary, False

    # Skip if this is a hash task — _validate_hash_claims handles those.
    _hash_re = re.compile(
        r"\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{64}\b", re.IGNORECASE
    )
    if _hash_re.search(task_brief):
        return summary, False

    # Detect if the brief is a CTF skill task
    _ctf_brief_re = re.compile(
        r"\b(decode|decrypt|base64|base32|hex(?:adecimal)?|binary|morse"
        r"|caesar|vigen[eè]re|atbash|shift\s+cipher|rotation\s+cipher"
        r"|cipher(?:\s*text)?"
        r"|forensics?|exiftool|binwalk|strings|metadata"
        r"|find\s+(?:the\s+)?flag|hidden\s+data|embedded"
        r"|analyze\s+(?:this\s+)?(?:file|image|binary|archive))\b",
        re.IGNORECASE,
    )
    if not _ctf_brief_re.search(task_brief):
        return summary, False

    # Check for process claims in the summary
    _process_re = re.compile(
        r"\b("
        r"I\s+(?:ran|executed|used|attempted|applied|tried)\s+(?:the\s+)?(?:tool|skill|script|decoder|cipher|analyz)"
        r"|(?:ran|executed|used)\s+(?:the\s+)?(?:decode|cipher|forensic|analyz)"
        r"|the\s+(?:tool|decoder|cipher|script|analyzer)\s+(?:reported|returned|confirmed|showed|found)"
        r"|after\s+(?:running|executing|analyzing)"
        r"|all\s+(?:methods?|encodings?|ciphers?|shifts?)\s+(?:were\s+)?(?:tried|attempted|tested)"
        r"|candidates?\s+(?:were\s+)?(?:found|returned|generated)"
        r"|no\s+(?:candidates?|matches?|results?)\s+(?:were\s+)?(?:found|returned)"
        r"|verified\s*[:=]\s*(?:true|false)"
        r"|score\s*[:=]\s*\d"
        r")\b",
        re.IGNORECASE,
    )
    if not _process_re.search(summary):
        return summary, False

    # Determine which skill type for the message
    _skill_type = "CTF skill"
    if re.search(r"\b(decode|base64|base32|hex|binary|morse)\b", task_brief, re.I):
        _skill_type = "decode"
    elif re.search(r"\b(caesar|vigen|atbash|cipher)\b", task_brief, re.I):
        _skill_type = "classical-crypto"
    elif re.search(r"\b(forensic|exiftool|binwalk|flag|metadata)\b", task_brief, re.I):
        _skill_type = "forensics"

    replacement_lines = [
        f"**{_skill_type.title()} analysis was not performed.**",
        "",
        "The agent described running the skill tool but made **zero tool "
        "calls** during this run — the process narrative is fabricated. "
        "No `exec` was invoked.",
        "",
        "Please re-run the request. The model must use the `exec` tool to "
        "call the appropriate skill script — describing the process in text "
        "is not the same as executing it.",
    ]
    return "\n".join(replacement_lines), True


def _parse_structured_result(summary: str) -> Optional[dict]:
    """
    If the agent's final summary contains a JSON block with type
    "research_result" or "document_result", extract and return it so the
    frontend can render source cards + artifact download cards.

    Returns None if no structured result is found.
    """
    if not summary:
        return None
    # Look for a JSON code block or bare JSON object in the summary text
    json_pattern = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)
    match = json_pattern.search(summary)
    raw_json = match.group(1) if match else None

    if raw_json is None:
        # Try bare JSON object (agent may not wrap in fences)
        bare = re.search(r'(\{[^{}]*"type"\s*:\s*"(?:research|document)_result"[^{}]*\})', summary, re.DOTALL)
        if bare:
            raw_json = bare.group(1)

    if raw_json is None:
        return None

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    result_type = data.get("type")
    if result_type == "research_result":
        return {
            "structured_type": "research_result",
            "structured_summary": data.get("summary", ""),
            "structured_sources": data.get("sources", []),
            "structured_artifact_id": data.get("artifact_id"),
        }
    if result_type == "document_result":
        return {
            "structured_type": "document_result",
            "structured_title": data.get("title", ""),
            "structured_artifact_id": data.get("artifact_id"),
        }
    return None


_GENERIC_BRIEFS = {
    "execute the task in a harvis workspace",
    "execute task in harvis workspace",
    "workspace",
    "/workspace",
    "",
}


def _resolve_task_brief(brief: str, chat_history: list[dict]) -> str:
    if brief.strip().lower() in _GENERIC_BRIEFS:
        last_user = next(
            (m for m in reversed(chat_history) if m.get("role") == "user"),
            None,
        )
        if last_user and isinstance(last_user.get("content"), str):
            extracted = last_user["content"].strip()
            if extracted:
                return extracted[:500]
    return brief


# Inline-attachment knobs. Defaults sized for an 8K-context model: an 80KB log
# is roughly 20K tokens, leaving room for the task + reply. Tune via env if
# upstream models have larger windows.
_ATTACH_INLINE_MAX_BYTES = int(os.getenv("HARVIS_ATTACH_INLINE_MAX_BYTES", "80000"))
_ATTACH_DOWNLOAD_HARD_CAP = int(os.getenv("HARVIS_ATTACH_DOWNLOAD_HARD_CAP", str(5 * 1024 * 1024)))
_ATTACH_HEAD_LINES = int(os.getenv("HARVIS_ATTACH_HEAD_LINES", "200"))
_ATTACH_TAIL_LINES = int(os.getenv("HARVIS_ATTACH_TAIL_LINES", "200"))


def _is_text_like(name: str, mime: str) -> bool:
    lower_name = name.lower()
    lower_mime = mime.lower()
    return (
        lower_mime.startswith("text/")
        or "json" in lower_mime
        or "csv" in lower_mime
        or "xml" in lower_mime
        or "yaml" in lower_mime
        or "toml" in lower_mime
        or "graphql" in lower_mime
        or "ipynb" in lower_mime
        or lower_name.endswith((
            # Logs / docs
            ".log", ".txt", ".md", ".mdx", ".rst", ".adoc", ".org", ".tex",
            # Data
            ".csv", ".tsv", ".json", ".ndjson", ".jsonl", ".xml",
            ".yaml", ".yml", ".toml", ".sql", ".graphql", ".gql", ".proto",
            # Diffs
            ".diff", ".patch",
            # Config
            ".ini", ".conf", ".cfg", ".properties", ".env",
            # Web
            ".html", ".htm", ".css", ".scss", ".sass", ".less",
            ".vue", ".svelte",
            # Code
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".go", ".rs", ".rb", ".php", ".java", ".kt", ".swift",
            ".scala", ".dart", ".lua", ".pl", ".r", ".cs",
            ".c", ".h", ".cpp", ".hpp", ".cc", ".m", ".mm",
            # Shell
            ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat",
            # Notebooks (treated as text-like — they're JSON)
            ".ipynb",
        ))
    )


def _is_image_like(name: str, mime: str) -> bool:
    lower_name = name.lower()
    lower_mime = mime.lower()
    return lower_mime.startswith("image/") or lower_name.endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp")
    )


async def _download_text_attachment(url: str) -> Optional[str]:
    """Fetch up to _ATTACH_DOWNLOAD_HARD_CAP bytes from `url`, return decoded text.

    Returns None on any error (network, decode, oversize, blocked). The caller
    falls back to the URL-only behavior so the agent can still try to fetch it.

    The URL comes from the client and whatever comes back is inlined verbatim
    into the model's context, so an unrestricted GET here was a read primitive
    for anything the backend can reach — ``http://ollama:11434``,
    ``http://pgsql:5432``, a cloud metadata endpoint. Two rules close it:

    * the host must be on the same allowlist ``vision_to_code/attachments.py``
      uses, which in practice means the Discord CDN — the only producer of an
      absolute attachment URL anywhere in Harvis;
    * the fetch goes through Agent Reach's hardened GET, which refuses
      private/loopback/link-local addresses, re-validates scheme, host and DNS
      on every redirect hop rather than following blindly, and pins the TCP
      target to the address it resolved, so a rebind between check and connect
      lands nowhere.

    Web-composer uploads are unaffected: they arrive as a relative
    ``/api/v1/files/<id>/content`` path, which was never fetchable here anyway.
    """
    try:
        from urllib.parse import urlparse

        from agent_reach.tools import _safe_get
        from vision_to_code.attachments import REMOTE_ATTACHMENT_HOSTS

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            logger.info(
                "_download_text_attachment: not an absolute http(s) URL, no inline: %s",
                url[:120],
            )
            return None

        resp = await _safe_get(
            url, timeout=10.0, host_allowlist=REMOTE_ATTACHMENT_HOSTS
        )
        data = resp.content
        if len(data) > _ATTACH_DOWNLOAD_HARD_CAP:
            logger.warning(
                "_download_text_attachment: %d bytes exceeds hard cap %d, skipping inline",
                len(data), _ATTACH_DOWNLOAD_HARD_CAP,
            )
            return None
        # Try utf-8 first, fall back to latin-1 (lossless single-byte mapping).
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("_download_text_attachment: failed for %s: %s", url[:120], exc)
        return None


def _format_inlined_text(name: str, content: str) -> tuple[str, bool]:
    """Build the <<<FILE_BEGIN ... FILE_END>>> block. Returns (block, was_truncated)."""
    if len(content.encode("utf-8", errors="ignore")) <= _ATTACH_INLINE_MAX_BYTES:
        return (
            f"<<<FILE_BEGIN {name}>>>\n{content}\n<<<FILE_END {name}>>>",
            False,
        )
    # Too big — head + tail.
    lines = content.splitlines()
    if len(lines) <= _ATTACH_HEAD_LINES + _ATTACH_TAIL_LINES:
        # Few long lines; fall back to byte-truncate from each end.
        head_chunk = content[: _ATTACH_INLINE_MAX_BYTES // 2]
        tail_chunk = content[-_ATTACH_INLINE_MAX_BYTES // 2 :]
        body = (
            head_chunk
            + f"\n\n…[TRUNCATED {len(content) - len(head_chunk) - len(tail_chunk)} bytes]…\n\n"
            + tail_chunk
        )
    else:
        head = "\n".join(lines[: _ATTACH_HEAD_LINES])
        tail = "\n".join(lines[-_ATTACH_TAIL_LINES :])
        skipped = len(lines) - _ATTACH_HEAD_LINES - _ATTACH_TAIL_LINES
        body = (
            f"{head}\n…[TRUNCATED {skipped} middle lines — full file at the URL above]…\n{tail}"
        )
    return (
        f"<<<FILE_BEGIN {name} (truncated; full size {len(content)} bytes / {len(lines)} lines)>>>\n"
        f"{body}\n<<<FILE_END {name}>>>",
        True,
    )


async def _prepend_attachments(brief: str, attachments: list[dict]) -> str:
    """Prepend a machine-readable [Attached files] block so the agent can find
    the user-uploaded image/PDF/etc.

    For text-like attachments with a fetchable URL, the file content is inlined
    directly into the brief (head+tail if oversize). This makes log/CSV/text
    analysis dumb-model-proof — even an agent that ignores skills sees the data
    in its context. The harvis-image skill still owns the image path.
    """
    if not attachments:
        return brief
    image_like = False
    text_like = False
    any_inlined = False
    listing: list[str] = []
    inline_blocks: list[str] = []

    for i, a in enumerate(attachments, start=1):
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or f"file{i}")
        mime = str(a.get("mime_type") or "application/octet-stream")
        if _is_image_like(name, mime):
            image_like = True
        is_text = _is_text_like(name, mime)
        if is_text:
            text_like = True

        loc_parts: list[str] = []
        if a.get("url"):
            loc_parts.append(f"url={a['url']}")
        if a.get("path"):
            loc_parts.append(f"path={a['path']}")
        if a.get("file_id"):
            loc_parts.append(f"file_id={a['file_id']}")
        loc = " ".join(loc_parts) or "(no location)"
        listing.append(f"{i}. {name} — {mime} — {loc}")

        # Inline text-like attachments so the agent doesn't need to curl.
        if is_text and a.get("url"):
            content = await _download_text_attachment(a["url"])
            if content is not None:
                block, _ = _format_inlined_text(name, content)
                inline_blocks.append(block)
                any_inlined = True

    lines: list[str] = ["[Attached files from the user]"] + listing
    if inline_blocks:
        lines.append("")
        lines.append("[Inlined file contents — answer directly from these; the data is here]")
        lines.extend(inline_blocks)
    lines.append("")
    lines.append("[Task]")
    lines.append(brief)
    lines.append("")
    lines.append("[Execution rules]")
    lines.append("- ALWAYS reply in English unless the user explicitly writes to you in another language.")
    lines.append("- Attached files are part of the task. Inspect them before answering.")
    if image_like:
        # The skills-shared mount only exists in the sandbox/OpenClaw runtime — the engine
        # sidecars mount /data/artifacts and nothing else. Phrase it as an "if present"
        # lookup so a missing skill file is a no-op rather than the start of a hunt.
        lines.append(
            "- At least one attached file is an image. If `/skills-shared/harvis-image/SKILL.md` "
            "exists, read it first. Then inspect the image with your file-read tool — prefer a "
            "local path over any URL listed above."
        )
        # Screenshot-to-code method pack (Build session shape) — additive rules when
        # the brief looks like UI replication. See vision_to_code/method_pack.py.
        try:
            from vision_to_code.method_pack import screenshot_to_code_brief_addon

            addon = screenshot_to_code_brief_addon(brief, has_image=True)
            if addon:
                lines.append(addon.strip())
        except Exception:
            pass
    if text_like and any_inlined:
        lines.append(
            "- THE FILE CONTENT IS ALREADY HERE. The text between `<<<FILE_BEGIN name>>>` and "
            "`<<<FILE_END name>>>` markers under [Inlined file contents] above IS the file. "
            "Treat it as if it were on disk — read it, search it, count it, quote it directly. "
            "Do NOT say you can't find the file, do NOT ask the user to paste it, do NOT try to "
            "`ls` or `curl` for it. The answer comes from the inlined block, not from any tool."
        )
    elif text_like:
        lines.append("- At least one attached file is a text/log/data file. Read `/skills-shared/harvis-file/SKILL.md` first, then use tools to extract the answer.")
    lines.append("- Replies like `Copy that.`, `Standing by.`, `On it.`, or any acknowledgment without tool use or extracted findings are invalid.")
    lines.append("- If the file is unreadable, ambiguous, or the answer cannot be determined confidently after using tools, say that explicitly and explain the blocker in one sentence. Do not guess.")
    return "\n".join(lines)


async def _start_workspace(
    workspace_id: str,
    session_id: str,
    task_brief: str,
    chat_history: list[dict],
    agent_id: str,
    user_id: int,
    pool,
    started_epoch: float,
    model_name: str = "",
    interactive_context: Optional[dict] = None,
    live_web: bool = True,
    parallel: bool = True,
    uniform_model: bool = False,
    repo_path: Optional[str] = None,
    vibecode_session_id: Optional[str] = None,
    workspace_path: Optional[str] = None,
    base_sha: Optional[str] = None,
    vibecode_isolation_mode: str = "session",
    vibecode_permission_mode: str = "ask",
    engine: Optional[str] = None,
    engine_key: Optional[str] = None,
    engine_auth_mode: str = "api_key",
    vibecode_persona_engine: str = "",
    vibecode_review_mode: str = "thread",
    vibecode_review_base: str = "",
    vibecode_reviewer_ids: Optional[list[str]] = None,
    launch_mode: str = "user",
    attachments: Optional[list[dict]] = None,
) -> OpenClawClient:
    """
    Register a workspace in memory, create its queue, and start the background task.
    Returns the OpenClawClient for the /cancel endpoint.
    """
    # Resolve which OpenClaw instance this user routes to
    config = await resolve_openclaw_config(pool, user_id)

    logger.info(
        "workspace launch: user=%s mode=%s url=%s prefix=%r",
        user_id, config.mode, config.url, config.workspace_prefix,
    )

    client = OpenClawClient(
        workspace_id=workspace_id,
        session_id=session_id,
        agent_id=agent_id,
        gateway_url=config.url,
        gateway_token=config.token,
        workspace_prefix=config.workspace_prefix,
    )

    _workspaces[workspace_id] = {
        "client": client,
        "status": "running",
        "task_brief": task_brief,
        "session_id": session_id,
        "chat_history": chat_history,
        "user_id": user_id,
        "started_epoch": started_epoch,
        "agent_id": agent_id,
        "model_name": model_name,
        "interactive_context": interactive_context or None,
        "live_web": live_web,
        "parallel": parallel,
        # P5: force every sub-agent onto the chat-selected model (vs per-role profile).
        "uniform_model": uniform_model,
        # When set, orchestrated runs use clone-local "attached" isolation of this repo.
        "repo_path": repo_path,
        # VibeCode cumulative-session turn: the persistent session workspace + its
        # fixed cumulative-diff baseline, used by the "vibecode-turn" dispatch.
        "vibecode_session_id": vibecode_session_id,
        "workspace_path": workspace_path,
        "base_sha": base_sha,
        "vibecode_isolation_mode": vibecode_isolation_mode,
        "vibecode_permission_mode": vibecode_permission_mode,
        # Phase E1: external code engine (e.g. "opencode") for this run; None = native runner.
        "engine": engine,
        # Phase E2: decrypted per-user CREDENTIAL for cloud engines (codex/claude-code), held
        # in-memory for this run only — NEVER logged/persisted. None for opencode/native.
        "engine_key": engine_key,
        # Phase E4B: which credential the cloud engine injects — 'api_key' (ANTHROPIC_API_KEY)
        # or 'oauth_token' (CLAUDE_CODE_OAUTH_TOKEN, Claude subscription). Never both.
        "engine_auth_mode": engine_auth_mode,
        # Phase E4: "hermes" when this is a Hermes native-engine turn (SOUL persona +
        # Hermes model on the SubAgentRunner); "" for plain native / external engines.
        "vibecode_persona_engine": vibecode_persona_engine,
        "vibecode_review_mode": vibecode_review_mode,
        "vibecode_review_base": vibecode_review_base,
        "vibecode_reviewer_ids": vibecode_reviewer_ids,
        # Launch-path signal: "user" = explicitly user-initiated (pill, vibecode,
        # build, internal integrations — the default); "auto" = auto-detected
        # escalation. Auto runs carry no Tier-3 token and get heavy tools withheld.
        # Fail-CLOSED for unrecognized non-empty values (a bad/typo signal → restricted);
        # absent callers still get the param default "user" (legacy-compatible).
        "launch_mode": launch_mode if launch_mode in ("user", "auto") else "auto",
        # The user's raw attachment refs. _prepend_attachments already described
        # them in the brief; this keeps the refs themselves so image attachments
        # can be sent to the model as real multimodal parts rather than a filename.
        "attachments": attachments or [],
        # Two-mode tracking
        "mode": config.mode,
        "allowed_capabilities": config.allowed_capabilities,
    }

    broadcaster = WorkspaceLiveBroadcaster()
    _workspace_broadcasters[workspace_id] = broadcaster

    # FIX 2 (FK launch race): the workspace_runs row MUST exist before the bg task
    # can emit events — workspace_events.workspace_id FKs workspace_runs.id, so any
    # event racing ahead of the row is dropped, which is what produced "missing first
    # trace events". Create it here, before create_task; the post-hoc _db_create_run
    # calls in the launch handlers become idempotent no-ops (ON CONFLICT DO NOTHING).
    await _db_create_run(pool, workspace_id, user_id, session_id, task_brief)

    task = asyncio.create_task(
        _run_workspace_bg(workspace_id, pool, started_epoch),
        name=f"workspace-{workspace_id}",
    )
    _workspace_tasks[workspace_id] = task

    return client


async def launch_workspace_internal(
    *,
    request: Request,
    user_id: int,
    task_brief: str,
    chat_history: list[dict] | None = None,
    agent_id: str = "main",
    model_name: str = "",
    session_id: str | None = None,
    enable_interactive: bool = True,
    live_web: bool = True,
    attachments: list[dict] | None = None,
    uniform_model: bool = False,
) -> dict:
    """
    Launch a workspace run without JWT (internal integrations).

    Intended for trusted server-side integrations (e.g., Discord bot) that already
    run inside the backend process and can supply an owning user_id.
    """
    workspace_id = str(uuid.uuid4())[:8]
    session_id = session_id or f"ws-{workspace_id}"
    chat_history = chat_history or []
    task_brief = _resolve_task_brief(task_brief, chat_history)
    task_brief = await _prepend_attachments(task_brief, attachments or [])
    _append_debug_log(
        "workspace_router.py:launch_workspace_internal",
        "launch_workspace_attachment_prompt",
        {
            "workspace_id": workspace_id,
            "attachment_count": len(attachments or []),
            "task_preview": task_brief[:400],
        },
        "run_attachment_prompt",
        "H_attachment_act_first",
    )

    # Tier 3 interactive browsing is always on for workspace launches.
    # Keep the arg for backward-compatible callers, but ignore opt-out.
    enable_interactive = True

    pool = getattr(request.app.state, "pg_pool", None)
    started_epoch = time.monotonic()

    interactive_context: Optional[dict] = None
    interactive_enabled = False
    if enable_interactive:
        try:
            cap_token = await _db_enable_interactive(
                pool,
                workspace_id=workspace_id,
                user_id=user_id,
                ttl_seconds=3600,
            )
            interactive_context = {
                "workspace_id": workspace_id,
                "capability_token": cap_token,
            }
            interactive_enabled = True
        except Exception as exc:
            logger.warning(
                "Failed to enable interactive for internal workspace %s: %s",
                workspace_id,
                exc,
            )

    await _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=chat_history,
        agent_id=agent_id,
        user_id=user_id,
        pool=pool,
        started_epoch=started_epoch,
        model_name=model_name,
        live_web=live_web,
        interactive_context=interactive_context,
        uniform_model=uniform_model,
        attachments=attachments or [],
    )

    try:
        await _db_create_run(pool, workspace_id, user_id, session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run (internal) raised unexpectedly: %s", exc)

    logger.info(
        "Workspace launched (internal): id=%s user=%s session=%s agent=%s brief=%r",
        workspace_id, user_id, session_id, agent_id, task_brief,
    )

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
        "interactive_enabled": interactive_enabled,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@workspace_router.post("/suggest")
async def suggest_workspace(
    req: SuggestRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    suggestion = await detect_workspace_task(req.chat_history)
    return suggestion.to_dict()


@workspace_router.get("/providers")
async def list_providers(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Probe all configured LLM providers and return their availability.
    Called by the frontend on mount to populate the workspace model selector.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    providers = []
    providers.append(await _probe_local_ollama())
    providers.append(await _probe_kimi(pool, current_user["id"]))
    providers.append(_probe_nvidia())
    providers.append(await _probe_cloud_ollama())
    return {"providers": providers}


@workspace_router.post("/launch")
async def launch_workspace(
    request: Request,
    req: LaunchRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Launch a new workspace.  Returns workspace_id immediately.

    The OpenClaw task starts as a background asyncio.Task — decoupled from the
    SSE connection.  The frontend connects to /stream/{workspace_id} and receives
    events regardless of when it connects (DB replay + live queue).
    """
    workspace_id = str(uuid.uuid4())[:8]
    session_id = req.session_id or f"ws-{workspace_id}"
    task_brief = _resolve_task_brief(req.task_brief, req.chat_history)
    task_brief = await _prepend_attachments(task_brief, req.attachments or [])
    pool = getattr(request.app.state, "pg_pool", None)

    # Normalize agent_id — accept legacy 'qwen3' as alias for 'cloud-ollama'.
    # This allowlist must list EVERY agent_id _run_workspace_bg dispatches, or the run
    # silently falls back to local Ollama and then dies with a model-not-found naming the
    # engine's model — which reads as "that model doesn't exist" rather than "we ignored
    # your engine". 'claude' and 'kimi-code' were missing for exactly that reason.
    agent_id = req.agent_id
    if agent_id == "qwen3":
        agent_id = "cloud-ollama"
    if agent_id not in ("main", "kimi", "kimi-code", "claude", "nvidia-kimi", "local",
                        "cloud-ollama", "gpt-oss", "orchestrated", "agent-native"):
        logger.warning(
            "workspace launch: unknown agent_id %r — falling back to local Ollama", agent_id,
        )
        agent_id = "local"

    # Attached-repo isolation may only target an ops-mounted allowlisted repo — same
    # gate as the VibeCode session create (closes the systemic attached-repo auth gap).
    if req.repo_path and not _is_allowed_repo(req.repo_path):
        raise HTTPException(status_code=403, detail="repo_path is not in the attached-repos allowlist")

    # Tier 3 interactive browsing is always on for workspace launches.
    # Keep req.enable_interactive for backward-compatible clients.
    enable_interactive = True

    started_epoch = time.monotonic()

    interactive_context: Optional[dict] = None
    interactive_enabled = False
    if enable_interactive:
        try:
            cap_token = await _db_enable_interactive(
                pool,
                workspace_id=workspace_id,
                user_id=current_user["id"],
                ttl_seconds=3600,
            )
            interactive_context = {
                "workspace_id": workspace_id,
                "capability_token": cap_token,
            }
            interactive_enabled = True
        except Exception as exc:
            logger.warning("Failed to enable interactive for workspace %s: %s", workspace_id, exc)

    await _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=req.chat_history,
        agent_id=agent_id,
        user_id=current_user["id"],
        pool=pool,
        started_epoch=started_epoch,
        model_name=req.model_name,
        live_web=req.live_web,
        interactive_context=interactive_context,
        parallel=req.parallel,
        repo_path=req.repo_path,
    )

    try:
        await _db_create_run(pool, workspace_id, current_user["id"], session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run raised unexpectedly: %s", exc)

    logger.info(
        "Workspace launched: id=%s user=%s session=%s agent=%s parallel=%s brief=%r",
        workspace_id, current_user["id"], session_id, agent_id, req.parallel, task_brief,
    )

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
        "interactive_enabled": interactive_enabled,
    }


@workspace_router.post("/interactive/enable")
async def enable_workspace_interactive(
    request: Request,
    req: InteractiveEnableRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Explicitly enable Tier 3 interactive browsing for a workspace."""
    pool = getattr(request.app.state, "pg_pool", None)
    workspace_id = (req.workspace_id or "").strip()
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    ws = _workspaces.get(workspace_id)
    if ws is not None and int(ws.get("user_id", -1)) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Workspace does not belong to current user")
    if ws is None and pool is not None:
        async with pool.acquire() as conn:
            owner = await conn.fetchval("SELECT user_id FROM workspace_runs WHERE id = $1", workspace_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if int(owner) != int(current_user["id"]):
            raise HTTPException(status_code=403, detail="Workspace does not belong to current user")

    cap_token = await _db_enable_interactive(
        pool,
        workspace_id=workspace_id,
        user_id=current_user["id"],
        ttl_seconds=req.ttl_seconds,
    )
    if ws is not None:
        ws["interactive_context"] = {
            "workspace_id": workspace_id,
            "capability_token": cap_token,
        }

    return {"workspace_id": workspace_id, "interactive_enabled": True}


@workspace_router.get("/stream/{workspace_id}")
async def stream_workspace(
    workspace_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    SSE stream of workspace activity.  Two-phase generator:

    Phase 1 — DB replay: All events stored in workspace_events are replayed in
      order.  This handles reconnection (tab reload, Nginx timeout, etc.) — the
      frontend always gets a complete picture regardless of when it connects.

    Phase 2 — Live fan-out: This handler subscribes to the per-workspace
      WorkspaceLiveBroadcaster and receives the same events as the chat bridge
      and other subscribers, in near-real-time.

    If the SSE client disconnects (asyncio.CancelledError), the background task
    is NOT cancelled — sub-agents keep running and events keep accumulating in
    the DB for the next reconnection.
    """
    ws = _workspaces.get(workspace_id)
    pool = getattr(request.app.state, "pg_pool", None)

    # Ownership gate (live path): the in-memory workspace records its owner at
    # launch — only that user may stream it. Same idiom as /interactive/enable.
    if ws is not None and int(ws.get("user_id", -1)) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Workspace does not belong to current user")

    # Persistence: every event lives in workspace_events forever, but the in-memory
    # _workspaces entry is lost on cleanup / a backend restart. Don't 404 those —
    # verify ownership via the DB run row and serve the persisted history (replay
    # only). The LIVE phase (broadcaster) still requires the in-memory ws.
    if ws is None:
        owner = None
        if pool:
            try:
                async with pool.acquire() as conn:
                    owner = await conn.fetchval(
                        "SELECT user_id FROM workspace_runs WHERE id = $1", workspace_id
                    )
            except Exception:
                owner = None
        if owner is None or owner != current_user.get("id"):
            _append_debug_log(
                "workspace_router.py:stream_workspace",
                "stream_workspace_missing_in_memory",
                {"workspace_id": workspace_id, "known_workspaces": list(_workspaces.keys())[:20]},
                "run_workspace_active_follow",
                "H_active_orphan",
            )
            raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    async def event_generator():
        last_seq = -1  # highest seq replayed from DB

        try:
            # ── Phase 1: replay stored events from DB ─────────────────────────
            if pool:
                try:
                    async with pool.acquire() as conn:
                        rows = await conn.fetch(
                            """
                            SELECT seq, event_type, payload
                            FROM workspace_events
                            WHERE workspace_id = $1
                            ORDER BY seq ASC
                            """,
                            workspace_id,
                        )
                    for row in rows:
                        last_seq = row["seq"]
                        raw_payload = row["payload"]
                        # asyncpg returns JSONB as str by default (no global
                        # type codec is registered); tolerate both forms.
                        if isinstance(raw_payload, dict):
                            payload = raw_payload
                        elif isinstance(raw_payload, str):
                            try:
                                parsed = json.loads(raw_payload)
                                payload = parsed if isinstance(parsed, dict) else {}
                            except Exception:
                                payload = {}
                        else:
                            payload = {}
                        event_data = {"type": row["event_type"], **payload}
                        yield f"data: {json.dumps(event_data)}\n\n"
                        if row["event_type"] in ("done", "cancelled", "error"):
                            # Terminal event already in DB — we're fully replayed
                            yield 'data: {"type": "stream_end"}\n\n'
                            return
                except Exception as exc:
                    logger.error("DB: replay workspace_events %s: %s", workspace_id, exc)

            # Replay-only (no in-memory run — persisted history after cleanup /
            # restart): the full DB history has been served, so close cleanly.
            if ws is None:
                yield 'data: {"type": "stream_end"}\n\n'
                return

            # If the workspace is already terminal (DB write may have raced ahead
            # of the status update), close the stream now
            current_status = ws.get("status", "running")
            if current_status in ("done", "cancelled", "error"):
                yield 'data: {"type": "stream_end"}\n\n'
                return

            # ── Phase 2: live events (subscriber queue — full fan-out from broadcaster) ──
            broadcaster = _workspace_broadcasters.get(workspace_id)
            if broadcaster is None:
                yield 'data: {"type": "stream_end"}\n\n'
                return

            live_queue = broadcaster.subscribe()

            try:
                while True:
                    # Check client disconnect (Nginx / browser navigation)
                    if await request.is_disconnected():
                        logger.info(
                            "[workspace:%s] SSE client disconnected — background task continues",
                            workspace_id,
                        )
                        return

                    try:
                        item = await asyncio.wait_for(live_queue.get(), timeout=25)
                    except asyncio.TimeoutError:
                        # Heartbeat SSE comment — keeps Nginx from closing a quiet stream
                        yield ": ping\n\n"
                        # Safety: if task ended without a sentinel, break
                        task = _workspace_tasks.get(workspace_id)
                        if task and task.done():
                            break
                        continue

                    if item is None:
                        # Sentinel: background task has ended
                        break

                    seq_num, event = item

                    # Skip events we already replayed from DB (reconnection case)
                    if seq_num <= last_seq:
                        continue

                    yield event.to_sse()

                    if event.type in ("done", "cancelled", "error"):
                        break

            finally:
                broadcaster.unsubscribe(live_queue)

        except asyncio.CancelledError:
            # SSE stream cancelled by client — intentionally do NOT cancel the
            # background task so sub-agents and long tool calls keep running.
            logger.info("[workspace:%s] SSE stream cancelled by client", workspace_id)
            return

        yield 'data: {"type": "stream_end"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def cancel_workspace_internal(
    workspace_id: str,
    *,
    audit_actor: str = "internal",
) -> dict:
    """Cancel a running workspace from non-HTTP contexts (Discord bot, etc.).

    Same effect as POST /cancel/{workspace_id}: marks status, signals the
    OpenClaw client cancel flag (which schedules ws.close() so the blocked
    async-for unblocks), cancels the background asyncio.Task, and waits up
    to 6s for cleanup so callers can report a truly-idle workspace.

    Returns one of:
      {"status": "cancelled", "workspace_id": ..., "wait_outcome": ...}
      {"status": "not_found", "workspace_id": ...}
      {"status": "already_terminal", "current": "done|cancelled|error", "workspace_id": ...}
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        return {"status": "not_found", "workspace_id": workspace_id}

    current = ws.get("status")
    if current in ("done", "cancelled", "error"):
        return {
            "status": "already_terminal",
            "current": current,
            "workspace_id": workspace_id,
        }

    # Mark state first so any concurrent handler sees the intent immediately.
    _workspaces[workspace_id]["status"] = "cancelled"

    client_cancel_err: Optional[str] = None
    try:
        ws["client"].cancel()
    except Exception as exc:
        client_cancel_err = str(exc)
        logger.warning("cancel_workspace_internal: client.cancel failed: %s", exc)

    task = _workspace_tasks.get(workspace_id)
    task_existed = task is not None
    task_was_done = bool(task.done()) if task else True
    wait_outcome = "no-task"
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=6.0)
            wait_outcome = "completed"
        except asyncio.CancelledError:
            wait_outcome = "cancelled-error"
        except asyncio.TimeoutError:
            wait_outcome = "timeout"
        except Exception as exc:
            wait_outcome = f"error:{exc}"
            logger.warning(
                "cancel_workspace_internal: background task raised during cleanup: %s",
                exc,
            )

    logger.info(
        "Workspace cancelled (internal): id=%s actor=%s outcome=%s",
        workspace_id, audit_actor, wait_outcome,
    )
    return {
        "status": "cancelled",
        "workspace_id": workspace_id,
        "wait_outcome": wait_outcome,
        "task_existed": task_existed,
        "task_was_done": task_was_done,
        "client_cancel_err": client_cancel_err,
    }


@workspace_router.post("/cancel/{workspace_id}")
async def cancel_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Cancel a running workspace. Force-closes the OpenClaw websocket and
    cancels the background task, then waits briefly for cleanup so the
    response only returns once the workspace is truly idle."""
    # Ownership gate: only the launching user may cancel (idiom from
    # /interactive/enable). A missing in-memory ws falls through to the
    # internal handler's not_found → 404 below.
    ws = _workspaces.get(workspace_id)
    if ws is not None and int(ws.get("user_id", -1)) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Workspace does not belong to current user")

    result = await cancel_workspace_internal(
        workspace_id,
        audit_actor=f"user:{current_user.get('id')}",
    )
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    _client_cancel_err = result.get("client_cancel_err")
    _task_existed = result.get("task_existed", False)
    _task_was_done = result.get("task_was_done", True)
    _wait_outcome = result.get("wait_outcome", "n/a")


    return {"workspace_id": workspace_id, "status": result["status"]}


@workspace_router.get("/status/{workspace_id}", response_model=WorkspaceStatus)
async def get_workspace_status(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
    # Ownership gate: task_brief/session_id are private to the launching user.
    if int(ws.get("user_id", -1)) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Workspace does not belong to current user")
    return WorkspaceStatus(
        workspace_id=workspace_id,
        status=ws["status"],
        task_brief=ws["task_brief"],
        session_id=ws["session_id"],
    )


# ── P5 orchestration: agent tree + artifacts (Mission Control / diff review) ──
def _run_row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "parent_run_id": r["parent_run_id"],
        "role": r["role"],
        "status": r["status"],
        "task": r["task_brief"],
        "model_name": r["model_name"],
        "model_provider": r["model_provider"],
        "branch_name": r["branch_name"],
        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
        "duration_ms": r["duration_ms"],
        "tool_calls": r["tool_calls"],
        "prompt_tokens": r["prompt_tokens"],
        "completion_tokens": r["completion_tokens"],
        "summary": r["final_summary"],
        "error": r["error_message"],
    }


@workspace_router.get("/run/{run_id}/tree")
async def get_run_tree(
    run_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Parent run + its sub-agent children (P5 agent tree)."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"run": None, "children": []}
    uid = current_user.get("id")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, parent_run_id, role, status, task_brief, model_name,
                   model_provider, branch_name, started_at, completed_at,
                   duration_ms, tool_calls, final_summary, error_message,
                   prompt_tokens, completion_tokens
            FROM workspace_runs
            WHERE user_id = $1 AND (id = $2 OR parent_run_id = $2)
            ORDER BY started_at ASC
            """,
            uid, run_id,
        )
    parent = next((r for r in rows if r["id"] == run_id), None)
    children = [_run_row_to_dict(r) for r in rows if r["id"] != run_id]
    return {"run": _run_row_to_dict(parent) if parent else None, "children": children}


# Binary artifacts are stored base64 with this prefix — MUST match isolation._B64_SENTINEL.
_ARTIFACT_B64_SENTINEL = "__HARVIS_B64__"
_ARTIFACT_MIME = {
    "html": "text/html", "htm": "text/html", "md": "text/markdown", "markdown": "text/markdown",
    "txt": "text/plain", "log": "text/plain", "csv": "text/csv", "tsv": "text/tab-separated-values",
    "json": "application/json", "yaml": "application/yaml", "yml": "application/yaml", "xml": "application/xml",
    "svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "ico": "image/x-icon", "tiff": "image/tiff", "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "zip": "application/zip", "tar": "application/x-tar", "gz": "application/gzip",
    # A connector that renders video (ComfyUI's SaveVideo/SaveWEBM) produced files that fell
    # through to octet-stream and, worse, to is_binary=False — so the frontend tried to read
    # a megabyte of h264 as text.
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
    "mkv": "video/x-matroska", "ogv": "video/ogg",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/mp4",
    "flac": "audio/flac",
}
_ARTIFACT_CATEGORY = {
    "html": "html", "htm": "html", "pdf": "pdf",
    "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image",
    "bmp": "image", "ico": "image", "tiff": "image", "svg": "image",
    "mp4": "video", "m4v": "video", "webm": "video", "mov": "video", "mkv": "video", "ogv": "video",
    "mp3": "audio", "wav": "audio", "ogg": "audio", "m4a": "audio", "flac": "audio",
    "md": "markdown", "markdown": "markdown", "txt": "text", "log": "text",
    "csv": "data", "tsv": "data", "json": "data", "yaml": "data", "yml": "data", "xml": "data",
    "docx": "office", "pptx": "office", "xlsx": "office", "doc": "office", "ppt": "office", "xls": "office",
    "zip": "archive", "tar": "archive", "gz": "archive", "tgz": "archive", "bz2": "archive", "7z": "archive", "rar": "archive",
}
_ARTIFACT_SECRET_HINTS = (".env", "credential", "secret", ".key", ".pem", "id_rsa", "id_ed25519", "apikey", "api_key")


def _artifact_meta(path) -> dict:
    """Classify an artifact by filename: category (html/pdf/image/video/audio/markdown/text/data/
    office/archive/unknown), mime, and whether its stored content is base64 (binary). svg is an
    image but TEXT."""
    p = (path or "")
    ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
    category = _ARTIFACT_CATEGORY.get(ext, "unknown")
    is_binary = category in ("image", "video", "audio", "pdf", "office", "archive") and ext != "svg"
    return {"category": category, "mime": _ARTIFACT_MIME.get(ext, "application/octet-stream"),
            "is_binary": is_binary, "ext": ext}


def _artifact_is_secret(path) -> bool:
    n = (path or "").lower().rsplit("/", 1)[-1]
    return any(h in n for h in _ARTIFACT_SECRET_HINTS)


@workspace_router.get("/run/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Artifact metadata (diff / changed_files / summary) for a run — ownership-checked."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"artifacts": []}
    uid = current_user.get("id")
    async with pool.acquire() as conn:
        owner = await conn.fetchval("SELECT user_id FROM workspace_runs WHERE id = $1", run_id)
        if owner is None or owner != uid:
            raise HTTPException(status_code=404, detail="Run not found")
        rows = await conn.fetch(
            """
            SELECT id, artifact_type, path,
                   COALESCE(LENGTH(content), OCTET_LENGTH(content_bytes), 0) AS size,
                   created_at
            FROM workspace_artifacts
            WHERE workspace_id = $1
            ORDER BY created_at ASC
            """,
            run_id,
        )
    out = []
    for r in rows:
        meta = _artifact_meta(r["path"]) if r["artifact_type"] == "file" else {"category": r["artifact_type"], "mime": "text/plain", "is_binary": False}
        out.append({
            "id": r["id"],
            "artifact_type": r["artifact_type"],
            "path": r["path"],
            "size": r["size"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "category": meta["category"],
            "mime": meta["mime"],
            "is_binary": meta["is_binary"],
        })
    return {"artifacts": out}


@workspace_router.get("/artifact/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Full artifact content (e.g. the diff), ownership-checked via the owning run."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")
    uid = current_user.get("id")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.id, a.artifact_type, a.path, a.content, a.created_at, r.user_id,
                   (a.content_bytes IS NOT NULL) AS has_bytes
            FROM workspace_artifacts a
            JOIN workspace_runs r ON r.id = a.workspace_id
            WHERE a.id = $1
            """,
            artifact_id,
        )
    if row is None or row["user_id"] != uid:
        raise HTTPException(status_code=404, detail="Artifact not found")
    meta = _artifact_meta(row["path"]) if row["artifact_type"] == "file" else {"category": row["artifact_type"], "mime": "text/plain", "is_binary": False}
    content = row["content"] or ""
    is_b64 = content.startswith(_ARTIFACT_B64_SENTINEL)
    # Don't ship base64 bytes in the JSON content — the frontend fetches /raw for binary preview.
    if is_b64:
        content = ""
    return {
        "id": row["id"],
        "artifact_type": row["artifact_type"],
        "path": row["path"],
        "content": content,
        "category": meta["category"],
        "mime": meta["mime"],
        # E2: raw-bytes artifacts (content_bytes BYTEA) are binary by definition.
        "is_binary": meta["is_binary"] or is_b64 or bool(row["has_bytes"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def _fetch_owned_artifact(pool, artifact_id: str, uid):
    """Fetch an artifact's (path, content, content_bytes) iff the run belongs to uid. Raises 404 otherwise."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.path, a.content, a.content_bytes, r.user_id
            FROM workspace_artifacts a JOIN workspace_runs r ON r.id = a.workspace_id
            WHERE a.id = $1
            """,
            artifact_id,
        )
    if row is None or row["user_id"] != uid:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if _artifact_is_secret(row["path"]):
        raise HTTPException(status_code=403, detail="This file type is not downloadable")
    return row["path"], (row["content"] or ""), row["content_bytes"]


def _artifact_bytes(path, content: str, content_bytes=None) -> tuple:
    """Decode a stored artifact to (bytes, mime). E2 raw-binary artifacts live in
    content_bytes (served verbatim); legacy binary artifacts carry the base64 sentinel."""
    meta = _artifact_meta(path)
    if content_bytes is not None:
        return bytes(content_bytes), (meta["mime"] if meta["category"] != "unknown" else "application/octet-stream")
    if content.startswith(_ARTIFACT_B64_SENTINEL):
        import base64 as _b64
        try:
            data = _b64.b64decode(content[len(_ARTIFACT_B64_SENTINEL):], validate=False)
        except Exception:
            data = b""
        return data, meta["mime"]
    return content.encode("utf-8", "replace"), (meta["mime"] if meta["category"] != "unknown" else "text/plain; charset=utf-8")


@workspace_router.get("/artifact/{artifact_id}/raw")
async def get_artifact_raw(
    artifact_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Serve an artifact's bytes inline with the right Content-Type (for <img>/<iframe>/<embed>
    preview). Ownership-checked; secret-named files refused; HTML served as octet-stream so the
    browser NEVER renders untrusted model HTML at our origin (preview uses the sandboxed iframe)."""
    from fastapi.responses import Response
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")
    path, content, content_bytes = await _fetch_owned_artifact(pool, artifact_id, current_user.get("id"))
    data, mime = _artifact_bytes(path, content, content_bytes)
    # Never serve raw HTML/SVG with an active content-type at our origin (XSS) — force download type.
    if mime in ("text/html", "image/svg+xml"):
        mime = "application/octet-stream"
    return Response(content=data, media_type=mime, headers={"X-Content-Type-Options": "nosniff"})


@workspace_router.get("/artifact/{artifact_id}/download")
async def download_artifact_file(
    artifact_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Download an artifact as an attachment (always allowed for non-secret files)."""
    from fastapi.responses import Response
    import os as _os
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")
    path, content, content_bytes = await _fetch_owned_artifact(pool, artifact_id, current_user.get("id"))
    data, mime = _artifact_bytes(path, content, content_bytes)
    fname = _os.path.basename(path or "artifact") or "artifact"
    fname = "".join(c for c in fname if c.isalnum() or c in "._- ()") or "artifact"
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fname}"', "X-Content-Type-Options": "nosniff"},
    )


@workspace_router.post("/artifact-mcp")
async def artifact_mcp(request: Request, current_user: dict = Depends(get_current_user_optimized)):
    """The brokered file-delivery door for sidecar engines. See `orchestration.artifact_mcp`.

    An auto-launched sidecar runs with ``Write`` withheld, so this is the only way it
    can hand a finished file back. The run it writes to comes from a header Harvis
    wrote at launch — never from the tool arguments — and is then checked against the
    caller's own token, so a leaked token still cannot reach another user's run.
    """
    raw = await request.body()
    if len(raw) > _artifact_mcp.MAX_FILE_BYTES + 64 * 1024:
        return JSONResponse(
            _artifact_mcp.error_response(None, _artifact_mcp.INVALID_REQUEST,
                                         "the request body is too large"),
            status_code=413)
    try:
        message = json.loads(raw or b"{}")
    except ValueError:
        return JSONResponse(
            _artifact_mcp.error_response(None, _artifact_mcp.PARSE_ERROR, "invalid JSON"),
            status_code=400)

    pool = getattr(request.app.state, "pg_pool", None)
    workspace_id = _artifact_mcp.injected_workspace_id(
        request.headers.get(_artifact_mcp.CONTEXT_HEADER))
    if workspace_id and pool is not None:
        async with pool.acquire() as conn:
            owner = await conn.fetchval(
                "SELECT user_id FROM workspace_runs WHERE id = $1", workspace_id)
        if owner is None or owner != current_user.get("id"):
            # Not something the model can fix, and naming the mismatch would confirm a
            # run id it should never have held. As far as it is told, it has no run.
            workspace_id = None

    try:
        response = await _artifact_mcp.handle_jsonrpc(
            message, pool=pool, workspace_id=workspace_id, save_artifact=_db_save_artifact)
    except Exception:
        logger.exception("artifact mcp request failed")
        rid = message.get("id") if isinstance(message, dict) else None
        return JSONResponse(
            _artifact_mcp.error_response(rid, _artifact_mcp.INTERNAL_ERROR, "the request failed"),
            status_code=500)

    if response is None:
        # A notification gets 202 and no body — what an MCP client over HTTP expects
        # for a message it is not waiting on.
        return JSONResponse(None, status_code=202)
    return JSONResponse(response)


@workspace_router.get("/artifacts")
async def list_all_artifacts(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
    limit: int = 200,
):
    """Every FILE artifact the user's orchestrated runs produced — the global
    Artifacts gallery. Joined to the owning run for task context, newest first."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"artifacts": []}
    uid = current_user.get("id")
    limit = max(1, min(int(limit or 200), 500))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.workspace_id, a.path,
                   COALESCE(LENGTH(a.content), OCTET_LENGTH(a.content_bytes), 0) AS size,
                   a.created_at, r.task_brief
            FROM workspace_artifacts a
            JOIN workspace_runs r ON r.id = a.workspace_id
            WHERE r.user_id = $1 AND a.artifact_type = 'file'
              AND r.source IS DISTINCT FROM 'vibecode'
            ORDER BY a.created_at DESC
            LIMIT $2
            """,
            uid, limit,
        )
    return {
        "artifacts": [
            {
                "id": r["id"],
                "workspace_id": r["workspace_id"],
                "path": r["path"],
                "size": r["size"],
                "task_brief": r["task_brief"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    }


@workspace_router.get("/attached-repos")
async def list_attached_repos(
    current_user: dict = Depends(get_current_user_optimized),
):
    """List git repos bind-mounted into the backend. RO repos (HARVIS_ATTACHED_REPOS) for
    clone-mode; writable repos (HARVIS_ATTACHED_REPOS_RW) for opt-in in-place mode. Each
    entry carries `writable` so the UI offers in-place only on writable repos."""
    from .orchestration.isolation import _run_git

    async def _enumerate(env_name: str, writable: bool):
        out_repos = []
        for p in [s.strip() for s in os.getenv(env_name, "").split(",") if s.strip()]:
            if not os.path.isdir(os.path.join(p, ".git")):
                continue
            branch = ""
            try:
                rc, b, _ = await _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=p)
                if rc == 0:
                    branch = b.strip()
            except Exception:
                pass
            out_repos.append({
                "path": p,
                "name": os.path.basename(p.rstrip("/")) or p,
                "branch": branch,
                "writable": writable,
            })
        return out_repos

    repos = await _enumerate("HARVIS_ATTACHED_REPOS", False)
    repos += await _enumerate("HARVIS_ATTACHED_REPOS_RW", True)
    return {"repos": repos}


@workspace_router.get("/fs/browse")
async def browse_filesystem(
    path: str = "",
    rw: bool = False,
    current_user: dict = Depends(get_current_user_optimized),
):
    """List the immediate subdirectories of `path`, bounded to a browse root. With `rw=false`
    (default) it browses the READ-ONLY root (HARVIS_FS_BROWSE_ROOT) → repos clone-only. With
    `rw=true` it browses the READ-WRITE root (HARVIS_FS_BROWSE_ROOT_RW) → repos are flagged
    `rw_capable` (eligible for in-place editing of the REAL files). Each dir is flagged
    `is_repo` when it contains a real `.git`. The path is realpath-contained to the chosen root
    (`../`/symlink escapes rejected), so this only ever reveals the deliberately-mounted tree."""
    root = _browse_root_rw() if rw else _browse_root()
    # The HOST-side path of the browse root (display-only) + whether it's still the default
    # sandbox — drives the "point HARVIS_FS_BROWSE_ROOT_RW_HOST at your projects" empty/default hint.
    host_root = os.getenv(
        "HARVIS_FS_BROWSE_ROOT_RW_HOST" if rw else "HARVIS_FS_BROWSE_ROOT_HOST", ""
    ).strip()
    is_default_root = (not host_root) or host_root in ("./harvis-fs-browse", "harvis-fs-browse")
    if not root or not os.path.isdir(root):
        return {"enabled": False, "rw": rw, "root": "", "path": "", "parent": None,
                "is_repo": False, "rw_capable": False, "entries": [],
                "host_root": host_root, "is_default_root": is_default_root}

    # Resolve the requested path INSIDE the root (default = the root itself). realpath
    # collapses `..` and resolves symlinks; the containment check rejects any escape.
    req = (path or "").strip() or root
    try:
        if not os.path.isabs(req):
            req = os.path.join(root, req)
        p = os.path.realpath(req)
    except Exception:
        raise HTTPException(status_code=400, detail="bad path")
    if not (p == root or p.startswith(root + os.sep)):
        raise HTTPException(status_code=403, detail="path is outside the browse root")
    if not os.path.isdir(p):
        raise HTTPException(status_code=404, detail="not a directory")

    # Display label/path: the RO root reuses the existing helpers; the RW root maps relative
    # to itself (its own label) so chips read sensibly for either root.
    if rw:
        rw_label = (
            os.getenv("HARVIS_FS_BROWSE_ROOT_RW_LABEL", "").strip()
            or os.path.basename(root.rstrip(os.sep))
            or "Workspace"
        )

        def _disp(cp: str) -> str:
            try:
                pp = os.path.realpath(cp)
            except Exception:
                return cp
            if pp == root:
                return rw_label
            if pp.startswith(root + os.sep):
                rel = pp[len(root) + 1:].replace(os.sep, "/")
                return f"{rw_label}/{rel}" if rel else rw_label
            return os.path.basename(pp)

        display_root = rw_label
    else:
        _disp = _browse_display_path
        display_root = _browse_display_label()

    entries: list[dict] = []
    try:
        with os.scandir(p) as it:
            for e in it:
                if e.name.startswith("."):
                    continue  # hide dotdirs (.git, .config, …) from the picker
                try:
                    if e.is_symlink() or not e.is_dir():
                        continue  # never offer symlinks (escape) or files
                except OSError:
                    continue
                child = os.path.join(p, e.name)
                entries.append({
                    "name": e.name,
                    "path": child,
                    "display_path": _disp(child),
                    "is_repo": _dir_is_git_repo(child),  # rejects symlinked .git (mirrors the accept gate)
                    "rw_capable": rw,  # under the RW root ⇒ eligible for in-place editing
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    entries.sort(key=lambda x: (not x["is_repo"], x["name"].lower()))

    return {
        "enabled": True,
        "rw": rw,
        "root": root,
        "path": p,
        "display_root": display_root,
        "display_path": _disp(p),
        "parent": None if p == root else os.path.dirname(p),
        "is_repo": _dir_is_git_repo(p),
        "rw_capable": rw,
        "host_root": host_root,
        "is_default_root": is_default_root,
        "at_root": p == root,
        "entries": entries,
    }


# ─── VibeCode cumulative multi-turn sessions ───────────────────────────────────
# A VibeCode session is a durable, named container holding a THREAD of turns. Each
# turn is a workspace_runs row (session_id = <vibecode_session.id>, source='vibecode')
# running ONE agent on the session's PERSISTENT working clone (clone-mode). Kept
# cleanly separate from owui_chats (the main chat sidebar) and generic runs.

class VibecodeSessionCreate(BaseModel):
    repo_path: Optional[str] = None
    model_name: str = ""
    title: Optional[str] = None
    isolation_mode: str = "session"   # 'session' (clone, default+safe) | 'inplace' (opt-in)
    permission_mode: str = "ask"      # in-place only: plan|ask|auto-accept|full-auto
    engine: str = "native"            # Phase E1: 'native' (OpenClaw runner) | 'opencode' (external CLI; clone-only, flag-gated)
    # Local-folder mode (browser File System Access API): the picked directory's display
    # label. Set ⇒ repo_path is ignored, the workspace is created empty + seeded by the
    # browser (POST /seed), and changed files are written back to the real folder per turn.
    local_folder_name: Optional[str] = None
    # GitHub-clone source: clone owner/repo (optional branch) into the session. Always
    # clone-mode; private repos need a connected GitHub account, public repos clone tokenless.
    github_owner: Optional[str] = None
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None


class VibecodeSeedRequest(BaseModel):
    # The browser-walked folder snapshot: relative path + text content per file.
    files: list[dict] = []


class CodeProjectUpsert(BaseModel):
    """Build Space repo registry entry (code_projects). One row per (user, repo_url):
    which repos coding sessions may target and under what branch rules."""
    repo_url: str
    name: Optional[str] = None
    provider: str = "github"
    default_base_branch: str = "main"
    allowed_base_branches: list[str] = []
    branch_prefix: str = "harvis/code/"


class VibecodeTurnRequest(BaseModel):
    task_brief: str
    model_name: str = ""
    run_mode: str = ""  # per-turn: 'plan' (read-only → draft a plan) | 'auto'/'' (execute)
    attachments: list[dict] = []  # image/file refs ({url|path|file_id, name, mime_type})
    orchestrate: bool = False  # fan the turn out to N task-delegated sub-agents (multi-agent)


class VibecodeReviewRequest(BaseModel):
    """Agent Review Conversation kickoff — everything defaults so `{}` works (the
    frontend posts an empty body). model_name overrides the reviewer/coder model.
    mode='thread' (default) converses in the session thread; mode='github' opens a
    draft PR and the agents converse there as PR comments."""
    model_name: str = ""
    mode: str = "thread"
    base: str = ""  # override the PR base branch (else the session's base_branch, else repo default)
    reviewer_ids: list[str] = []  # custom sub-agent ids to use as reviewers (else the built-in reviewer)


async def _vibecode_session_row(pool, session_id: str, user_id: int):
    if pool is None:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM vibecode_sessions WHERE id = $1 AND user_id = $2",
            session_id, user_id,
        )


# How many prior turns of a Build/Code session get replayed to the agent. The
# per-message and whole-block caps live in conversation_prefix(); this only bounds
# the query. Six turns is twelve messages, which is that function's own turn cap.
_VIBECODE_HISTORY_TURNS = 6

# Hard size budget for the replayed transcript. NOT belt-and-braces: `task_brief` can
# carry an inlined attachment (_ATTACH_INLINE_MAX_BYTES is 80 KB) and a `final_summary`
# already reaches 18 KB in this database — and the Kimi/Ollama workspace lane's
# `_build_context_message` caps message COUNT but not length, so an unbounded history
# would land a quarter-megabyte prompt on a metered endpoint. `conversation_prefix`
# trims again for the lanes that use it; this is the floor under all of them.
_VIBECODE_HISTORY_MAX_PER_MSG = 2000
_VIBECODE_HISTORY_MAX_CHARS = 12000

# The Agent Review lane writes its run row with source='vibecode' and the session's
# id too — deliberately, so the review lands in the session thread. Its task_brief is
# this server-written placeholder rather than anything the user typed, so anything
# reconstructing what the USER asked has to skip it. One constant, matched as a bound
# parameter, so the two readers below cannot drift if the wording ever changes.
_REVIEW_BRIEF_PREFIX = "Agent review of"


async def _vibecode_chat_history(
    pool, session_id: str, user_id: int, exclude_run_id: str = "",
) -> list[dict]:
    """The session's earlier turns, as a user/assistant transcript.

    A Build/Code session's history IS its workspace_runs rows: ``task_brief`` is what
    the user asked and ``final_summary`` is what the agent answered. Every lane is
    one-shot, so without this the turn route handed the runner an empty history,
    ``conversation_prefix`` returned the brief untouched, and a follow-up like "try
    again" reached the model as a sentence about nothing — it would go and review the
    workspace instead of continuing the build it could no longer see.

    A turn that never produced a summary (it failed, or it is still running)
    contributes only its user message. That is the honest record, and it reads
    correctly: the same ask, made twice.

    Two rows are deliberately NOT turns: an Agent Review run (see
    ``_REVIEW_BRIEF_PREFIX`` — its brief is a server-written placeholder, and
    replaying it would put words in the user's mouth), and anything owned by another
    user. Session ids are truncated UUIDs, so the ownership filter costs nothing and
    means a collision can never hand one person another's transcript.
    """
    if pool is None or not session_id:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT task_brief, final_summary
                FROM workspace_runs
                WHERE session_id = $1
                  AND user_id = $2
                  AND source = 'vibecode'
                  AND id <> $3
                  AND task_brief IS NOT NULL
                  AND task_brief NOT LIKE $4
                ORDER BY started_at DESC, id DESC
                LIMIT $5
                """,
                session_id, user_id, exclude_run_id or "",
                _REVIEW_BRIEF_PREFIX + "%", _VIBECODE_HISTORY_TURNS,
            )
    except Exception as exc:
        # Context is an enhancement, never a precondition — the turn still runs.
        logger.warning("vibecode: chat history load failed for %s: %s", session_id, exc)
        return []

    def _clip(text: str) -> str:
        text = text.strip()
        if len(text) <= _VIBECODE_HISTORY_MAX_PER_MSG:
            return text
        return text[:_VIBECODE_HISTORY_MAX_PER_MSG] + " …[truncated]"

    # Walk newest-first (the order the LIMIT already gave us) and spend the budget on
    # the most recent turns, because that is what a follow-up actually refers to. The
    # newest turn is always admitted even if it alone exceeds the budget — clipped, but
    # present, since dropping it would leave "try again" with nothing again.
    msgs: list[dict] = []
    used = 0
    for r in rows:
        pair: list[dict] = []
        reply = (r["final_summary"] or "").strip()
        if reply:
            pair.append({"role": "assistant", "content": _clip(reply)})
        brief = (r["task_brief"] or "").strip()
        if brief:
            pair.append({"role": "user", "content": _clip(brief)})
        if not pair:
            continue
        cost = sum(len(m["content"]) for m in pair)
        if msgs and used + cost > _VIBECODE_HISTORY_MAX_CHARS:
            break
        msgs.extend(pair)
        used += cost
    msgs.reverse()  # newest-first pairs → chronological transcript
    return msgs


def _parse_preflight_col(raw):
    """vibecode_sessions.preflight (JSONB) → dict|None. asyncpg may hand it back as a
    JSON string (no codec) or an already-decoded dict — handle both."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else None
        except Exception:
            return None
    return None


async def _match_code_project(
    pool, uid: int, repo_path: Optional[str],
    github_owner: Optional[str] = None, github_repo: Optional[str] = None,
):
    """Match this session's repo against the user's code_projects registry.
    GitHub-clone sessions match on owner/repo inside the normalized remote; local
    paths match on directory basename == repo-name tail (best-effort — we only have
    a path here, not a remote). Returns (project_id, repo_url) or (None, None)."""
    if pool is None:
        return None, None
    try:
        from .orchestration.preflight import normalize_remote
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, repo_url FROM code_projects WHERE user_id = $1", uid
            )
        for r in rows:
            norm = normalize_remote(r["repo_url"])  # host/owner/repo
            if not norm:
                continue
            if github_owner and github_repo:
                if norm.endswith(f"/{github_owner.lower()}/{github_repo.lower()}"):
                    return r["id"], r["repo_url"]
            elif repo_path:
                name = os.path.basename(repo_path.rstrip("/")).lower()
                if name and norm.rsplit("/", 1)[-1] == name:
                    return r["id"], r["repo_url"]
    except Exception as exc:
        logger.warning("vibecode: code_projects match failed for user=%s: %s", uid, exc)
    return None, None


# ─── Build Space: code_projects registry CRUD ─────────────────────────────────
# The per-user repo REGISTRY (see orchestration/__init__.py DDL): which repos a
# coding session may target + branch rules. UPSERT keyed on (user_id, repo_url).

def _code_project_to_dict(r) -> dict:
    d = dict(r)
    raw = d.get("allowed_base_branches")
    if isinstance(raw, str):
        try:
            d["allowed_base_branches"] = json.loads(raw) or []
        except Exception:
            d["allowed_base_branches"] = []
    elif raw is None:
        d["allowed_base_branches"] = []
    return d


@workspace_router.post("/vibecode/projects")
async def upsert_code_project(
    req: CodeProjectUpsert,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Register (or update) a repo in the user's Build Space registry."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    uid = current_user["id"]
    repo_url = (req.repo_url or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required")
    project_id = str(uuid.uuid4())[:12]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO code_projects
                (id, user_id, name, repo_url, provider, default_base_branch,
                 allowed_base_branches, branch_prefix)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
            ON CONFLICT (user_id, repo_url) DO UPDATE SET
                name                  = EXCLUDED.name,
                provider              = EXCLUDED.provider,
                default_base_branch   = EXCLUDED.default_base_branch,
                allowed_base_branches = EXCLUDED.allowed_base_branches,
                branch_prefix         = EXCLUDED.branch_prefix,
                updated_at            = NOW()
            RETURNING *
            """,
            project_id, uid, (req.name or "").strip() or None, repo_url,
            (req.provider or "github").strip() or "github",
            (req.default_base_branch or "main").strip() or "main",
            json.dumps(req.allowed_base_branches or []),
            (req.branch_prefix or "harvis/code/").strip() or "harvis/code/",
        )
    return {"project": _code_project_to_dict(row)}


@workspace_router.get("/vibecode/projects")
async def list_code_projects(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The user's registered Build Space repos (newest-touched first)."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"projects": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM code_projects WHERE user_id = $1 ORDER BY updated_at DESC",
            current_user["id"],
        )
    return {"projects": [_code_project_to_dict(r) for r in rows]}


@workspace_router.delete("/vibecode/projects/{project_id}")
async def delete_code_project(
    project_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Remove a repo from the user's registry (ownership-scoped hard delete)."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM code_projects WHERE id = $1 AND user_id = $2",
            project_id, current_user["id"],
        )
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": project_id}


@workspace_router.post("/vibecode/sessions")
async def create_vibecode_session(
    req: VibecodeSessionCreate,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Create a VibeCode session. Clone-mode (default, safe): a PERSISTENT throwaway
    clone of a RO attached repo. In-place (opt-in): a session branch ON the real repo
    (RW mount) — requires the RW allowlist, a CLEAN tree, and no other active in-place
    session on that repo. Turns share the one evolving working copy either way."""
    from .orchestration.isolation import (
        _run_git, create_or_attach_session_workspace, create_inplace_session_workspace,
        create_local_folder_session_workspace,
    )
    from .orchestration.preflight import run_preflight
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    session_id = str(uuid.uuid4())[:12]
    repo_path = (req.repo_path or "").strip() or None
    isolation_mode = req.isolation_mode if req.isolation_mode in ("session", "inplace") else "session"
    permission_mode = (
        req.permission_mode if req.permission_mode in ("plan", "ask", "auto-accept", "full-auto") else "ask"
    )
    local_folder_name = (req.local_folder_name or "").strip() or None
    github_owner = (req.github_owner or "").strip() or None
    github_repo = (req.github_repo or "").strip() or None
    github_branch = (req.github_branch or "").strip() or None

    if local_folder_name:
        # Local-folder mode (browser File System Access API): empty git workspace now,
        # seeded by the browser via POST /seed (which sets base_sha). Always clone-style
        # isolation — the real folder is the browser's, not a container path.
        isolation_mode = "session"
        repo_path = None
        info = await create_local_folder_session_workspace(session_id)
        workspace_path = info.get("workspace_path")
        base_sha = None  # set on /seed
        base_branch = None
    elif github_repo:
        # GitHub-clone source: always clone-mode (a remote repo, not a local mount). Use the
        # user's connected token if present (private repos); else a tokenless clone (public).
        isolation_mode = "session"
        token = ""
        try:
            from .repo_manager import _get_github_token
            token = (await _get_github_token(pool, uid)) or ""
        except Exception:
            token = ""  # not connected / decrypt error → public-only tokenless clone
        info = await create_or_attach_session_workspace(
            session_id, None, None,
            github_source={
                "owner": github_owner or "", "repo": github_repo,
                "branch": github_branch or "", "token": token,
            },
        )
        if info.get("error"):
            raise HTTPException(status_code=502, detail=info["error"])
        workspace_path = info.get("workspace_path")
        base_sha = info.get("base_sha")
        repo_path = info.get("repo_path") or workspace_path
        base_branch = github_branch
    elif isolation_mode == "inplace":
        # In-place edits the REAL repo → require the RW allowlist + a clean tree + no other
        # active in-place session on this repo (one working tree per repo can't be shared).
        # NOTE: browse-root ("Open folder…") repos are clone-mode only — _is_allowed_repo_rw
        # honors the explicit RW allowlist alone, so an opened folder can't reach in-place.
        if not repo_path or not _is_allowed_repo_rw(repo_path):
            raise HTTPException(
                status_code=403,
                detail="In-place requires a writable allowlisted repo (HARVIS_ATTACHED_REPOS_RW).",
            )
        async with pool.acquire() as conn:
            clash = await conn.fetchrow(
                "SELECT id FROM vibecode_sessions WHERE repo_path = $1 AND isolation_mode = 'inplace' "
                "AND status = 'active' LIMIT 1",
                repo_path,
            )
        if clash:
            raise HTTPException(
                status_code=409,
                detail="Another in-place session is already active on this repo — delete it first.",
            )
        info = await create_inplace_session_workspace(session_id, repo_path, None)
        if info.get("error"):
            raise HTTPException(status_code=409, detail=info["error"])
        workspace_path = info["workspace_path"]
        base_sha = info["base_sha"]
        base_branch = info["base_branch"]
    else:
        # Clone-mode (default, safe): RO allowlist + a persistent throwaway clone.
        if repo_path and not _is_allowed_repo(repo_path):
            raise HTTPException(status_code=403, detail="repo_path is not in the attached-repos allowlist")
        base_branch = ""
        if repo_path and os.path.isdir(os.path.join(repo_path, ".git")):
            # A git repo → clone-local; capture its current branch as the baseline.
            try:
                rc, b, _ = await _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
                if rc == 0:
                    base_branch = b.strip()
            except Exception:
                pass
        elif repo_path and not _is_dir_under_browse_root(repo_path):
            # Not a git repo AND not a browsable folder → scratch session.
            repo_path = None
        # else: a non-git folder under a browse root → kept; create_or_attach copy-seeds it.
        info = await create_or_attach_session_workspace(session_id, repo_path, base_branch)
        workspace_path = info.get("workspace_path")
        base_sha = info.get("base_sha")
        base_branch = base_branch or None

    # Phase E1/E2/E4: an engine is opt-in, clone-only, flag-gated. Policy: COERCE to
    # native for flag-off / in-place; REJECT an unknown engine; REJECT a cloud engine
    # (codex/claude-code) without a verified per-user API key; REJECT Hermes when no
    # Hermes model is installed. External engines run as sidecars (engine-adapter);
    # Hermes runs the NATIVE SubAgentRunner with a SOUL persona.
    _req_engine = (req.engine or "native")
    if _req_engine != "native" and _req_engine not in (
        EXTERNAL_ENGINE_IDS | NATIVE_ENGINE_IDS | KIMI_ENGINE_IDS | KIMI_CODE_ENGINE_IDS
    ):
        raise HTTPException(status_code=400, detail=f"unknown engine '{_req_engine}'")
    engine_val = "native"
    if _req_engine in KIMI_CODE_ENGINE_IDS and isolation_mode == "session":
        # Kimi Code MEMBERSHIP. Tested BEFORE the `kimi` arm below on purpose: these are set
        # memberships, not prefixes, so order is not load-bearing today — but every other
        # Kimi-aware site in the codebase matches kimi-code first, and breaking that habit
        # here is how a membership run ends up billed to the pay-as-you-go platform.
        # Gate = a VERIFIED key, the same contract capabilities.py reports readiness on.
        from owui_compat.engine_auth import user_has_verified_engine
        if not await user_has_verified_engine(pool, uid, "kimi-code"):
            raise HTTPException(
                status_code=400,
                detail="Kimi Code needs a connected, verified membership key — connect it in Integrations first",
            )
        engine_val = "kimi-code"
    elif _req_engine in KIMI_ENGINE_IDS and isolation_mode == "session":
        # Kimi = the original workspace engine. No sidecar/flag — just a Moonshot key, the same
        # gate the chat lane uses. Reject with a clear message when the key is missing.
        if not await _get_kimi_key(pool, uid):
            raise HTTPException(
                status_code=400,
                detail="Kimi needs a Moonshot API key — add one in Settings (or set MOONSHOT_API_KEY) first",
            )
        engine_val = "kimi"
    elif _req_engine in EXTERNAL_ENGINE_IDS and _engine_enabled(_req_engine) and isolation_mode == "session":
        if _req_engine in CLOUD_ENGINE_IDS:
            from owui_compat.engine_auth import user_has_verified_engine
            if not await user_has_verified_engine(pool, uid, _req_engine):
                raise HTTPException(
                    status_code=400,
                    detail=f"{_req_engine} requires a connected, verified API key — connect it in Integrations first",
                )
        engine_val = _req_engine   # opencode / codex / claude-code / hermes-agent → engine-adapter
    elif _req_engine == "hermes-native" and _hermes_engine_enabled() and isolation_mode == "session":
        # Phase E4 (experimental fallback): reject only when the model probe SUCCEEDS and
        # finds no Hermes model (fail-OPEN on a transient probe error — runtime fails soft).
        _hms = await _installed_hermes_models()
        if _hms is not None and len(_hms) == 0:
            raise HTTPException(
                status_code=400,
                detail="Hermes Native needs an installed Hermes model — pull one (e.g. `ollama pull hermes3:3b`) first",
            )
        engine_val = "hermes-native"

    # ── Build Space Phase 1: preflight + lifecycle ────────────────────────────
    # Capture a persisted preflight report on the prepared working copy BEFORE any
    # AI work. Fail-OPEN: a preflight crash must never break session creation.
    # Local-folder sessions have NO repo until the browser seeds them → skip
    # preflight and keep lifecycle='created' (needs_seed already signals the state).
    work_branch = (info.get("branch_name") if isinstance(info, dict) else None) or base_branch or None
    project_id, expected_remote = await _match_code_project(
        pool, uid, repo_path, github_owner=github_owner, github_repo=github_repo,
    )
    pf = None
    lifecycle = "created"
    if not local_folder_name:
        try:
            pf = await run_preflight(
                workspace_path or repo_path,
                expected_remote=expected_remote,
                base_branch=base_branch or None,
                require_clean=(isolation_mode == "inplace"),
            )
        except Exception as exc:
            logger.warning("vibecode: preflight failed (fail-open) for %s: %s", session_id, exc)
            pf = None
        # BLOCK only where it can't regress today's flows: a REGISTERED repo (the
        # user opted into governance) or in-place (edits the real repo). Unregistered
        # clone-mode repos just record the report.
        if pf and pf.get("blockers") and (expected_remote is not None or isolation_mode == "inplace"):
            if isolation_mode == "inplace":
                # The session branch was already created on the real repo — roll it back
                # (same teardown as the 23505 race path) before refusing.
                from .orchestration.isolation import cleanup_inplace_session
                safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "session"
                try:
                    await cleanup_inplace_session(repo_path, base_branch, f"vibecode/{safe}")
                except Exception:
                    pass
            raise HTTPException(status_code=409, detail=pf["blockers"][0]["message"])
        lifecycle = "blocked" if (pf and pf.get("blockers")) else "ready"
    head_sha = (pf.get("head_sha") if pf else None) or base_sha

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO vibecode_sessions
                    (id, user_id, title, repo_path, base_branch, workspace_path, base_sha,
                     isolation_mode, permission_mode, local_folder_name, engine, source, status,
                     project_id, work_branch, head_sha, lifecycle, preflight)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'vibecode', 'active',
                        $12, $13, $14, $15, $16::jsonb)
                """,
                session_id, uid,
                req.title or local_folder_name or (f"{github_owner}/{github_repo}" if github_repo else None),
                repo_path, base_branch or None,
                workspace_path, base_sha, isolation_mode, permission_mode, local_folder_name, engine_val,
                project_id, work_branch, head_sha, lifecycle,
                json.dumps(pf) if pf else None,
            )
    except Exception as exc:
        # Partial-unique-index (23505) → another in-place session raced us onto this repo.
        # The DB is the real guard against the check-then-create TOCTOU; roll back our branch.
        if getattr(exc, "sqlstate", None) == "23505" and isolation_mode == "inplace":
            from .orchestration.isolation import cleanup_inplace_session
            safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "session"
            await cleanup_inplace_session(repo_path, base_branch, f"vibecode/{safe}")
            raise HTTPException(
                status_code=409,
                detail="Another in-place session is already active on this repo — delete it first.",
            )
        raise
    logger.info(
        "vibecode: created %s session %s (user=%s, repo=%s, perm=%s)",
        isolation_mode, session_id, uid, repo_path, permission_mode,
    )
    display_title = req.title or local_folder_name or (f"{github_owner}/{github_repo}" if github_repo else None)
    return {
        "id": session_id,
        "title": display_title,
        "repo_path": repo_path,
        "repo_display_path": local_folder_name or _session_repo_display(repo_path, display_title),
        "base_branch": base_branch or None,
        "workspace_path": workspace_path,
        "isolation_mode": isolation_mode,
        "permission_mode": permission_mode,
        "local_folder_name": local_folder_name,
        # Local-folder sessions must be seeded by the browser before the first turn.
        "needs_seed": bool(local_folder_name),
        "status": "active",
        # Build Space Phase 1: session state machine + preflight report.
        "work_branch": work_branch,
        "head_sha": head_sha,
        "lifecycle": lifecycle,
        "preflight": pf,
    }


@workspace_router.get("/vibecode/sessions")
async def list_vibecode_sessions(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The user's VibeCode sessions (newest first) for the sidebar list."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"sessions": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, emoji, repo_path, status, lifecycle, created_at, updated_at,
                   review_enabled, review_status
            FROM vibecode_sessions
            WHERE user_id = $1 AND status != 'deleted'
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            current_user["id"],
        )
    return {"sessions": [dict(r) for r in rows]}


@workspace_router.get("/vibecode/session/{session_id}")
async def get_vibecode_session(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """A session + its ordered thread of turns (workspace_runs, source='vibecode')."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    async with pool.acquire() as conn:
        turns = await conn.fetch(
            """
            SELECT r.id, r.task_brief, r.status, r.started_at, r.completed_at,
                   r.duration_ms, r.tool_calls, r.final_summary, r.error_message,
                   r.model_name, r.prompt_tokens, r.completion_tokens, r.context_window,
                   r.usage_detail, r.attachments, r.analysis_md,
                   (SELECT COUNT(*) FROM workspace_runs c WHERE c.parent_run_id = r.id)
                     AS child_count,
                   -- The files the workspace held as of this turn. The chat card lists
                   -- them under the reply so "what did it actually create?" is answerable
                   -- without opening a panel — the question that sent a user hunting after
                   -- a turn wrote one index.html and said nothing about it.
                   (SELECT a.content FROM workspace_artifacts a
                     WHERE a.workspace_id = r.id AND a.artifact_type = 'changed_files'
                     ORDER BY a.created_at DESC LIMIT 1) AS changed_files
            FROM workspace_runs r
            WHERE r.session_id = $1 AND r.source = 'vibecode'
            ORDER BY r.started_at ASC
            """,
            session_id,
        )
    s = dict(sess)
    rp = s.get("repo_path")
    local_folder_name = s.get("local_folder_name")
    return {
        "session": {
            "id": s["id"], "title": s.get("title"), "emoji": s.get("emoji"),
            "repo_path": rp,
            "repo_display_path": local_folder_name or _session_repo_display(rp, s.get("title")),
            "base_branch": s.get("base_branch"),
            "status": s.get("status"),
            "isolation_mode": s.get("isolation_mode") or "session",
            "permission_mode": s.get("permission_mode") or "ask",
            # Which Build engine this session runs (native | opencode | codex | claude-code |
            # hermes-*). Stored at create; surfaced so the thread can label "Built with X".
            "engine": s.get("engine") or "native",
            "local_folder_name": local_folder_name,
            # No base_sha yet ⇒ the browser still needs to seed this local-folder session.
            "needs_seed": bool(local_folder_name) and not s.get("base_sha"),
            # Build Space Phase 1: session state machine + persisted preflight report.
            "work_branch": s.get("work_branch"),
            "head_sha": s.get("head_sha"),
            "lifecycle": s.get("lifecycle") or "created",
            "preflight": _parse_preflight_col(s.get("preflight")),
            # Agent Review Conversation (opt-in): drives the PrDrawer gate + chips.
            "review_enabled": bool(s.get("review_enabled")),
            "review_status": s.get("review_status") or "off",
        },
        "turns": [_vibecode_turn_to_dict(t) for t in turns],
    }


def _vibecode_turn_to_dict(t) -> dict:
    """Row → dict, decoding the JSONB `attachments` (asyncpg hands it back as a str) into a
    list so the chat thread can render the user's images inline."""
    d = dict(t)
    raw = d.get("attachments")
    if isinstance(raw, str):
        try:
            d["attachments"] = json.loads(raw) or []
        except Exception:
            d["attachments"] = []
    elif raw is None:
        d["attachments"] = []
    # Same asyncpg JSONB-as-str treatment for the split usage record. None stays None:
    # "we have no trustworthy occupancy number" is a state the meter renders honestly,
    # and an empty dict would look like a measured zero.
    ud = d.get("usage_detail")
    if isinstance(ud, str):
        try:
            d["usage_detail"] = json.loads(ud) or None
        except Exception:
            d["usage_detail"] = None
    # `changed_files` arrives as the stored newline-joined blob; hand the UI a list.
    # Cumulative vs the session baseline, NOT per-turn — the card labels it accordingly.
    cf = d.get("changed_files")
    d["changed_files"] = (
        [ln for ln in cf.splitlines() if ln.strip()] if isinstance(cf, str) else []
    )
    return d


@workspace_router.post("/vibecode/session/{session_id}/seed")
async def seed_vibecode_local_folder(
    session_id: str,
    req: VibecodeSeedRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Seed a LOCAL-FOLDER session with the browser-walked folder snapshot. Writes the
    files into the session workspace, commits the fixed baseline (``base_sha``), and stores
    it on the session row. Idempotent-ish: re-seeding before the first turn just resets the
    baseline. Returns ``{base_sha, written}``."""
    from .orchestration.isolation import seed_local_folder_workspace
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    s = dict(sess)
    if not s.get("local_folder_name"):
        raise HTTPException(status_code=400, detail="Not a local-folder session")
    wp = s.get("workspace_path")
    if not wp or not os.path.isdir(os.path.join(wp, ".git")):
        raise HTTPException(status_code=409, detail="Session workspace is missing")
    if s.get("base_sha"):
        # Already seeded (turns may have edited the tree) — don't clobber it.
        return {"base_sha": s.get("base_sha"), "written": 0, "reused": True}

    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "session"
    result = await seed_local_folder_workspace(wp, req.files or [], f"vibecode-{safe}")
    base_sha = result.get("base_sha")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE vibecode_sessions SET base_sha = $2, updated_at = NOW() WHERE id = $1",
            session_id, base_sha,
        )
    logger.info(
        "vibecode: seeded local-folder session %s (user=%s, %d files)",
        session_id, uid, result.get("written", 0),
    )
    return {"base_sha": base_sha, "written": result.get("written", 0)}


@workspace_router.get("/vibecode/session/{session_id}/writeback")
async def get_vibecode_local_folder_writeback(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Files the agent changed/deleted vs the baseline — the browser writes these BACK into
    the user's real folder (local-folder mode). Returns ``{changed: [{path, content}],
    deleted: [path]}``."""
    from .orchestration.isolation import collect_local_folder_writeback
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    s = dict(sess)
    if not s.get("local_folder_name"):
        raise HTTPException(status_code=400, detail="Not a local-folder session")
    wp = s.get("workspace_path")
    if not wp or not os.path.isdir(os.path.join(wp, ".git")):
        return {"changed": [], "deleted": []}
    return await collect_local_folder_writeback(wp, s.get("base_sha"))


@workspace_router.post("/vibecode/session/{session_id}/turn")
async def start_vibecode_turn(
    session_id: str,
    req: VibecodeTurnRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Send a follow-up message: spawn a turn run bound to the session, operating on
    the session's PERSISTENT working clone. Returns {workspace_id} → the caller
    streams it via /api/workspace/stream/{id}."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    task_brief = (req.task_brief or "").strip()
    if not task_brief:
        raise HTTPException(status_code=400, detail="task_brief is required")
    # A local-folder session has no baseline until the browser seeds it — refuse turns
    # until then (the agent would otherwise run on an empty tree).
    if dict(sess).get("local_folder_name") and not dict(sess).get("base_sha"):
        raise HTTPException(
            status_code=409,
            detail="This folder hasn't finished loading yet — try again in a moment.",
        )
    # The user's ORIGINAL message (task_brief) is what the chat thread renders. The AGENT
    # gets a SEPARATE assembled brief that folds in attachment refs + execution rules — that
    # scaffolding must never leak into the user's bubble.
    agent_brief = await _prepend_attachments(task_brief, req.attachments or [])

    s = dict(sess)
    workspace_id = str(uuid.uuid4())[:8]
    started_epoch = time.monotonic()

    # Per-turn run mode = the permission pyramid rung chosen in the composer:
    # plan (read-only → fills the Plan panel) · ask · auto-accept · full-auto. Falls back
    # to the session's stored permission_mode if absent/unknown.
    _turn_mode = (req.run_mode or "").strip().lower()
    turn_permission = (
        _turn_mode
        if _turn_mode in ("plan", "ask", "auto-accept", "full-auto")
        else (s.get("permission_mode") or "ask")
    )

    # ── The lane must match the model, or the turn 404s in a way nobody can read. ──
    # `engine` is stored on the session at CREATION and the dispatch below reads it from
    # that row, but the model is chosen per turn in the composer. Those two disagreed
    # silently: picking Claude inside a session created as `native` sent
    # `anthropic/claude-sonnet-5` to Ollama, which answered `404 Not Found` for a model it
    # has never heard of, and the chat showed that raw URL as the run's error.
    #
    # Changing the model is a deliberate act, so it moves the session's lane with it —
    # you can switch a Build chat from local to Claude mid-conversation. When the lane the
    # model needs is not available at all, refuse HERE with a sentence that names the
    # engine, instead of letting the wrong lane fail with a hostname.
    _req_model = (req.model_name or "").strip()
    if _req_model:
        _want_engine = _engine_for_model(_req_model)
        _have_engine = s.get("engine") or "native"
        if _want_engine != _have_engine:
            if not _engine_runnable(_want_engine):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{_req_model} runs on the {_want_engine} engine, which is not "
                        "connected. Connect it under Integrations, or pick a model this "
                        "session can run."
                    ),
                )
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE vibecode_sessions SET engine = $2, updated_at = NOW() "
                        "WHERE id = $1",
                        session_id,
                        _want_engine,
                    )
                s = {**s, "engine": _want_engine}
                logger.info(
                    "vibecode: session %s engine %s -> %s (model %s)",
                    session_id, _have_engine, _want_engine, _req_model,
                )
            except Exception as exc:
                # Fail loud rather than run the turn down the old lane: that is exactly
                # the silent mismatch this block exists to end.
                logger.error("vibecode: engine switch failed for %s: %s", session_id, exc)
                raise HTTPException(
                    status_code=500,
                    detail="Could not switch this session to the engine that model needs.",
                )

    # Create the turn row NOW with the ORIGINAL text + attachments (for display), BEFORE
    # spawning the bg task — run_vibecode_turn's _db_create_run is ON CONFLICT DO NOTHING,
    # so this original wins; the agent still receives the assembled agent_brief below.
    try:
        await _db_create_run(pool, workspace_id, uid, session_id, task_brief)
        await _db_set_run_source(pool, workspace_id, "vibecode")
        await _db_set_run_attachments(pool, workspace_id, req.attachments or [])
        async with pool.acquire() as conn:
            await conn.execute(
                # Build Space lifecycle: a turn is now executing. The bg-task finally
                # block flips it back to 'ready' on any terminal status.
                "UPDATE vibecode_sessions SET lifecycle = 'running', updated_at = NOW() WHERE id = $1",
                session_id,
            )
    except Exception as exc:
        logger.error("vibecode: turn bookkeeping failed for %s: %s", workspace_id, exc)

    # The session's earlier turns. Loaded HERE rather than sent by the browser: the
    # rows are already the authoritative transcript, they cannot be spoofed by a
    # client, and every existing session gains context without a frontend release.
    # The row created just above is this turn — exclude it or the brief repeats.
    turn_history = await _vibecode_chat_history(pool, session_id, uid, workspace_id)

    if req.orchestrate:
        # MULTI-AGENT turn: fan out to N task-delegated sub-agents (the LLM planner
        # decides 3–10, naming each after its job). Runs through the SAME orchestrator
        # as Agent Studio, but SESSION-SCOPED — session_id = this vibecode session, so
        # the run surfaces in THIS session's Background tasks (and nowhere else). The
        # parent row is already source='vibecode' (set above) → it lives in the session
        # thread with child_count sub-agents; each sub-agent works on its own clone of
        # the session's repo (real diffs), collected as per-agent artifacts. (Isolated
        # clones → the orchestrate turn does NOT advance the session's cumulative diff;
        # review per-agent diffs via Open run.)
        await _start_workspace(
            workspace_id=workspace_id,
            session_id=session_id,
            task_brief=task_brief,  # clean brief → the planner decomposes it
            chat_history=turn_history,
            agent_id="orchestrated",
            user_id=uid,
            pool=pool,
            started_epoch=started_epoch,
            model_name=req.model_name or s.get("model_name") or "",
            live_web=False,
            parallel=True,
            # DEFAULT: every sub-agent runs on the SESSION's model (the one the user is
            # working with), not the heterogeneous pool — `uniform_model=True` + that
            # model_name. (Per-agent custom models = a future opt-in via Customize.)
            uniform_model=True,
            # Clone source for the sub-agents: the session's source repo, else its
            # persistent workspace (a git repo), else scratch (empty-dir + difflib).
            repo_path=s.get("repo_path") or s.get("workspace_path") or None,
            vibecode_session_id=session_id,
        )
    else:
        # Phase E1: route to an EXTERNAL engine when the session selected one AND it's
        # enabled AND clone-mode (never in-place — we can't gate an external CLI's
        # actions). Otherwise the native `vibecode-turn` runner (unchanged path). The
        # `engine` is read from the authoritative session ROW, so reload/resume is consistent.
        _engine = s.get("engine") or "native"
        _is_session = (s.get("isolation_mode") or "session") == "session"
        # opencode / codex / claude-code / hermes-agent → engine-adapter sidecar. Each is
        # gated by its own flag (hermes-agent has HARVIS_OWUI_HERMES_AGENT_ENGINE; the rest
        # share the external-engines flag) via _engine_enabled().
        _use_engine = (
            _engine in EXTERNAL_ENGINE_IDS
            and _engine_enabled(_engine)
            and _is_session
        )
        # Phase E4 (experimental): hermes-native is a NATIVE engine — it runs the
        # vibecode-turn SubAgentRunner (NOT the sidecar), specialized with a SOUL persona +
        # a local Hermes model. agent_id stays "vibecode-turn"; we thread a persona flag.
        _use_hermes = (
            _engine == "hermes-native"
            and _hermes_engine_enabled()
            and _is_session
        )
        # Kimi = the original workspace engine. NOT a sidecar and NOT vibecode-turn — it routes
        # to agent_id="kimi" (the existing stream_kimi_workspace lane). Gated only on a Moonshot
        # key, resolved inside that lane; no flag, no clone-mode requirement beyond session.
        _use_kimi = _engine in KIMI_ENGINE_IDS and _is_session
        # Kimi Code MEMBERSHIP → the engine-adapter sidecar, like claude-code, so the CLI runs
        # in the session's working CLONE. (The chat lane's kimi-code branch runs in a scratch
        # dir with no repo — right for chat, useless for a Build turn.) Not folded into
        # _use_engine because it is deliberately NOT in EXTERNAL_ENGINE_IDS: its gate is a
        # verified key, not the external-engines flag. See KIMI_CODE_ENGINE_IDS above.
        _use_kimi_code = _engine in KIMI_CODE_ENGINE_IDS and _is_session
        # Cloud engines need the user's verified key, decrypted here at turn start and
        # held in-memory for this run only. If it was disconnected since session-create,
        # the adapter fails soft (emits a "connect your key" error) so the user sees why.
        _engine_key = None
        _engine_auth_mode = "api_key"  # E4B: 'api_key' | 'oauth_token' (Claude subscription)
        if _use_kimi_code or (_use_engine and _engine in CLOUD_ENGINE_IDS):
            from owui_compat.engine_auth import get_verified_engine_auth
            _auth = await get_verified_engine_auth(pool, uid, _engine)
            if _auth:
                _engine_key, _engine_auth_mode = _auth
        await _start_workspace(
            workspace_id=workspace_id,
            session_id=session_id,  # the turn run's session_id == the vibecode session id
            task_brief=agent_brief,
            chat_history=turn_history,
            agent_id=(
                "kimi" if _use_kimi
                else ("engine-adapter" if (_use_engine or _use_kimi_code) else "vibecode-turn")
            ),
            user_id=uid,
            pool=pool,
            started_epoch=started_epoch,
            model_name=req.model_name or s.get("model_name") or "",
            live_web=False,
            parallel=False,
            repo_path=s.get("repo_path"),
            vibecode_session_id=session_id,
            workspace_path=s.get("workspace_path"),
            base_sha=s.get("base_sha"),
            vibecode_isolation_mode=s.get("isolation_mode") or "session",
            vibecode_permission_mode=turn_permission,
            engine=_engine if (_use_engine or _use_kimi_code) else None,
            engine_key=_engine_key,
            engine_auth_mode=_engine_auth_mode,
            vibecode_persona_engine="hermes-native" if _use_hermes else "",
            attachments=req.attachments or [],
        )

    logger.info(
        "vibecode: turn %s on session %s (user=%s, orchestrate=%s)",
        workspace_id, session_id, uid, req.orchestrate,
    )
    return {"workspace_id": workspace_id, "session_id": session_id, "status": "running"}


@workspace_router.post("/vibecode/session/{session_id}/review")
async def start_vibecode_review(
    session_id: str,
    req: VibecodeReviewRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """OPT-IN Agent Review Conversation: turn review mode ON for this session and run
    a coder ↔ reviewer dialogue over its ACCUMULATED diff as a background run (same
    streaming as a turn — the caller streams /api/workspace/stream/{workspace_id}).
    Sets review_enabled=TRUE + review_status='pending'; the loop lands on 'agreed'
    (reviewer APPROVED) or 'needs_human' (round cap / error). Ownership-scoped.
    Sessions that never call this stay review_enabled=FALSE → zero behavior change."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    s = dict(sess)
    wp = s.get("workspace_path")
    if not wp or not os.path.isdir(wp):
        raise HTTPException(status_code=404, detail="The session workspace is no longer available.")
    if req.mode == "github" and not s.get("repo_path"):
        raise HTTPException(
            status_code=400,
            detail="Review-on-GitHub needs a GitHub-connected repo session — start one with a GitHub repo.",
        )
    if s.get("local_folder_name") and not s.get("base_sha"):
        raise HTTPException(
            status_code=409,
            detail="This folder hasn't finished loading yet — try again in a moment.",
        )

    workspace_id = str(uuid.uuid4())[:8]
    started_epoch = time.monotonic()
    task_brief = "Agent review of this session's accumulated changes"
    try:
        await _db_create_run(pool, workspace_id, uid, session_id, task_brief)
        await _db_set_run_source(pool, workspace_id, "vibecode")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE vibecode_sessions SET review_enabled = TRUE, review_status = 'pending', "
                "lifecycle = 'running', updated_at = NOW() WHERE id = $1",
                session_id,
            )
    except Exception as exc:
        logger.error("vibecode: review bookkeeping failed for %s: %s", workspace_id, exc)

    await _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        # The reviewer judges the diff AGAINST the session's original task — give it
        # the most recent real turn brief when one exists.
        task_brief=await _latest_vibecode_turn_brief(pool, session_id) or task_brief,
        chat_history=[],
        agent_id="vibecode-review",
        user_id=uid,
        pool=pool,
        started_epoch=started_epoch,
        model_name=req.model_name or "",
        live_web=False,
        parallel=False,
        repo_path=s.get("repo_path"),
        vibecode_session_id=session_id,
        workspace_path=wp,
        base_sha=s.get("base_sha"),
        vibecode_isolation_mode=s.get("isolation_mode") or "session",
        vibecode_permission_mode=s.get("permission_mode") or "ask",
        vibecode_review_mode=req.mode if req.mode in ("thread", "github") else "thread",
        vibecode_review_base=(req.base or s.get("base_branch") or ""),
        vibecode_reviewer_ids=[r for r in (req.reviewer_ids or []) if r] or None,
    )
    logger.info("vibecode: review %s on session %s (user=%s, mode=%s, base=%s)",
                workspace_id, session_id, uid, req.mode, req.base or s.get("base_branch") or "(default)")
    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "review_status": "pending",
    }


async def _latest_vibecode_turn_brief(pool, session_id: str) -> str:
    """The most recent REAL turn's task_brief (skipping review runs' placeholder) —
    the review prompt's 'what was the agent asked to do'. Best-effort."""
    if pool is None:
        return ""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT task_brief FROM workspace_runs WHERE session_id = $1 "
                "AND source = 'vibecode' AND task_brief IS NOT NULL "
                "AND task_brief NOT LIKE $2 "
                "ORDER BY started_at DESC LIMIT 1",
                session_id, _REVIEW_BRIEF_PREFIX + "%",
            )
        return (row or "").strip()
    except Exception as exc:
        logger.warning("vibecode: latest-turn-brief lookup failed for %s: %s", session_id, exc)
        return ""


@workspace_router.delete("/vibecode/session/{session_id}")
async def delete_vibecode_session(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Delete a VibeCode session: tear down its workspace (the ONLY teardown point),
    release its in-memory turn lock, and soft-delete the row. Clone-mode → rmtree the
    throwaway clone; in-place → restore the base branch + delete the session branch
    (NEVER the real repo). Human-only, ownership-scoped."""
    from .orchestration.isolation import cleanup_session_workspace, cleanup_inplace_session
    from .orchestration.session_turn import release_session_lock, _lock_for
    from .orchestration.risk import _PENDING_ACTIONS, resolve_action
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    s = dict(sess)

    # 1. Mark deleted FIRST so the list hides it immediately.
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE vibecode_sessions SET status = 'deleted', updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2",
            session_id, uid,
        )
    # 2. Unblock any turn paused on the approval gate (deny its pending action) so it
    #    resumes + releases the per-session lock instead of holding the working tree.
    try:
        async with pool.acquire() as conn:
            running = await conn.fetch(
                "SELECT id FROM workspace_runs WHERE session_id = $1 AND status = 'running'",
                session_id,
            )
        for r in running:
            for aid in [a for a in list(_PENDING_ACTIONS) if a.startswith(f"{r['id']}-")]:
                resolve_action(aid, False)
        # Durable mirror: close out any surviving pending rows for this session so
        # the DB fallback never resurfaces them after the session is gone.
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspace_pending_approvals SET resolved = TRUE, decision = 'denied' "
                "WHERE session_id = $1 AND NOT resolved",
                session_id,
            )
    except Exception as exc:
        logger.warning("vibecode: delete %s pending-deny failed: %s", session_id, exc)
    # 3. Take the per-session lock (bounded) so cleanup can't run while a turn is mid-write
    #    on the SHARED working copy (critical for in-place: it's the user's real repo).
    lock = _lock_for(session_id)
    got = False
    try:
        await asyncio.wait_for(lock.acquire(), timeout=30)
        got = True
    except asyncio.TimeoutError:
        logger.warning("vibecode: delete %s cleaning up without lock (turn still active)", session_id)
    try:
        if s.get("isolation_mode") == "inplace":
            safe = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "session"
            await cleanup_inplace_session(s.get("repo_path"), s.get("base_branch"), f"vibecode/{safe}")
        elif s.get("workspace_path"):
            await cleanup_session_workspace(s["workspace_path"])
    finally:
        if got:
            lock.release()
    release_session_lock(session_id)
    logger.info("vibecode: deleted session %s (user=%s)", session_id, uid)
    return {"ok": True, "status": "deleted"}


class VibecodeUpdateRequest(BaseModel):
    title: Optional[str] = None
    permission_mode: Optional[str] = None  # change the in-place ladder rung mid-session


@workspace_router.patch("/vibecode/session/{session_id}")
async def update_vibecode_session(
    session_id: str,
    req: VibecodeUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Update a VibeCode session: rename (title) and/or change the permission ladder rung
    (permission_mode) — the composer mode pill PATCHes this mid-session. Ownership-scoped."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sets, vals = [], []
    if req.title is not None:
        t = req.title.strip()[:140]
        if not t:
            raise HTTPException(status_code=400, detail="title cannot be blank")
        sets.append(f"title = ${len(vals) + 3}")
        vals.append(t)
    if req.permission_mode is not None:
        if req.permission_mode not in ("plan", "ask", "auto-accept", "full-auto"):
            raise HTTPException(status_code=400, detail="invalid permission_mode")
        sets.append(f"permission_mode = ${len(vals) + 3}")
        vals.append(req.permission_mode)
    if not sets:
        return {"id": session_id}
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE vibecode_sessions SET {', '.join(sets)}, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2",
            session_id, uid, *vals,
        )
    return {"id": session_id, "title": req.title, "permission_mode": req.permission_mode}


def _vibecode_fallback_title(task_brief: str) -> str:
    """Deterministic, non-blank title from the first turn's brief (~6 words)."""
    words = " ".join((task_brief or "").split())
    if not words:
        return "Coding session"
    short = words[:56]
    return (short.rsplit(" ", 1)[0] if len(words) > 56 else short) or "Coding session"


@workspace_router.post("/vibecode/session/{session_id}/autoname")
async def autoname_vibecode_session(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Generate a concise title + emoji for a VibeCode session from its FIRST turn's
    task_brief (open-notebook autoname pattern). Deterministic fallback — never blank."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    async with pool.acquire() as conn:
        first = await conn.fetchrow(
            "SELECT task_brief FROM workspace_runs WHERE session_id = $1 AND source = 'vibecode' "
            "ORDER BY started_at ASC LIMIT 1",
            session_id,
        )
    brief = ((first["task_brief"] if first else "") or "")
    fallback = _vibecode_fallback_title(brief)

    gen_title, gen_emoji = None, None
    if brief.strip():
        prompt = (
            "You are titling a short coding session from the user's request below. Produce:\n"
            "1. title — a concise 3-6 word descriptive title for the task (like a PR / branch "
            "title, NOT a sentence).\n"
            "2. emoji — one emoji that fits the task.\n"
            'Respond with ONLY a compact JSON object: {"title": "...", "emoji": "..."}. '
            "No prose, no markdown, no code fences.\n\n"
            f"Request: {brief[:600]}"
        )
        try:
            from notebooks.rag_chat import FALLBACK_MODELS
        except Exception:
            FALLBACK_MODELS = []
        autoname_models = ["granite4.1:8b", "llama3.1:8b", "gemma4:e4b"]
        autoname_models += [m for m in FALLBACK_MODELS if m not in autoname_models]
        for model in autoname_models:
            try:
                async with _httpx.AsyncClient(timeout=60.0) as c:
                    r = await c.post(
                        f"{_LOCAL_OLLAMA_URL.rstrip('/')}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False,
                              "options": {"temperature": 0.4, "num_predict": 400, "num_ctx": 4096}},
                    )
                if r.status_code != 200:
                    continue
                text = (r.json().get("response") or "").strip()
                m = re.search(r"\{.*\}", text, re.DOTALL)
                if not m:
                    continue
                obj = json.loads(m.group(0))
                gen_title = ((obj.get("title") or "").strip().strip('"').strip())[:140] or None
                gen_emoji = ((obj.get("emoji") or "").strip())[:8] or None
                if gen_title or gen_emoji:
                    logger.info(
                        "vibecode autoname %s: model=%s title=%r emoji=%r",
                        session_id, model, gen_title, gen_emoji,
                    )
                    break
            except Exception as exc:
                logger.debug("vibecode autoname model %s failed: %s", model, exc)
                continue

    final_title = gen_title or fallback
    final_emoji = gen_emoji or "\U0001F9E9"  # 🧩
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE vibecode_sessions SET title = $2, emoji = $3, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $4",
            session_id, final_title, final_emoji, uid,
        )
    return {"id": session_id, "title": final_title, "emoji": final_emoji}


def _parse_github_remote(url: str):
    """(owner, repo) from a github https/ssh remote url, or (None, None)."""
    import re
    if not url:
        return None, None
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    return (m.group(1), m.group(2)) if m else (None, None)


@workspace_router.get("/run/{run_id}/repo")
async def get_run_repo(
    run_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The attached repo for a run (for the diff-row `repo · branch` header + Create-PR
    gating). Returns {repo: null} if the run had no attached repo. `has_github` tells the
    UI whether a PR can be opened (the source needs a GitHub origin)."""
    from .orchestration.isolation import _run_git
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        return {"repo": None}
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT repo_path FROM workspace_runs WHERE id = $1 AND user_id = $2", run_id, uid
        )
    repo_path = run["repo_path"] if run else None
    if not repo_path or not os.path.isdir(os.path.join(repo_path, ".git")):
        return {"repo": None}
    branch, has_github = "", False
    try:
        _rc, b, _e = await _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
        branch = b.strip()
        _rc2, o, _e2 = await _run_git(["git", "config", "--get", "remote.origin.url"], cwd=repo_path)
        owner, repo = _parse_github_remote(o.strip())
        has_github = bool(owner)
    except Exception:
        pass
    return {"repo": {
        "name": os.path.basename(repo_path.rstrip("/")) or repo_path,
        "branch": branch,
        "path": repo_path,
        "has_github": has_github,
    }}


async def _open_pr_from_diff(
    pool, uid: int, repo_path: str, diff_text: str, head: str,
    title: Optional[str], body: Optional[str], source_label: str,
    base_branch: Optional[str] = None,
) -> dict:
    """Shared HUMAN-ONLY PR path: resolve the source repo's GitHub origin + the user's
    token, fresh clone-local, apply `diff_text` onto a feature branch, push, open the
    PR. Refuses main/master as head. Raises HTTPException on any failure. Used by both
    the run-level and the VibeCode-session create-pr endpoints.

    `base_branch` is the PR target (e.g. "main"). Pass it explicitly for session clones,
    whose checked-out branch is the session branch (never pushed) — deriving base from
    HEAD there sends GitHub a non-existent base and 422s. Falls back to HEAD when None."""
    import tempfile, shutil
    from .repo_manager import _get_github_token
    from .orchestration.isolation import _run_git

    if not diff_text.strip() or diff_text.strip() == "(no changes)":
        raise HTTPException(status_code=400, detail="No diff to open a PR for.")
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise HTTPException(status_code=404, detail="The source repo is no longer available.")
    if head in ("main", "master"):
        raise HTTPException(status_code=400, detail="Refusing to use main/master as the PR head branch.")

    _rc, origin, _e = await _run_git(["git", "config", "--get", "remote.origin.url"], cwd=repo_path)
    owner, repo = _parse_github_remote(origin.strip())
    if not owner:
        raise HTTPException(status_code=400, detail=f"The source repo has no GitHub origin to open a PR against (origin={origin.strip()!r}).")
    if base_branch and base_branch.strip():
        base = base_branch.strip()
    else:
        _rc, base, _e = await _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
        base = base.strip() or "main"
    gh_token = await _get_github_token(pool, uid)
    if not gh_token:
        raise HTTPException(status_code=400, detail="No GitHub token connected for your account — connect GitHub first.")

    work = tempfile.mkdtemp(prefix="harvis-pr-")
    clone_dir = os.path.join(work, "repo")
    try:
        rc, _o, err = await _run_git(
            ["git", "clone", "--local", "--no-hardlinks", repo_path, clone_dir], cwd=work
        )
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"clone failed: {(err or _o)[:200]}")
        await _run_git(["git", "checkout", base], cwd=clone_dir)
        await _run_git(["git", "checkout", "-B", head], cwd=clone_dir)
        await _run_git(["git", "config", "user.name", "Harvis"], cwd=clone_dir)
        await _run_git(["git", "config", "user.email", "agent@harvis.local"], cwd=clone_dir)

        patch_path = os.path.join(work, "change.diff")
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        rc, _o, err = await _run_git(["git", "apply", "--whitespace=nowarn", patch_path], cwd=clone_dir)
        if rc != 0:
            rc, _o, err = await _run_git(["git", "apply", "--3way", patch_path], cwd=clone_dir)
            if rc != 0:
                raise HTTPException(status_code=409, detail=f"Could not apply the diff onto '{base}' (source may have moved): {err[:200]}")
        await _run_git(["git", "add", "-A"], cwd=clone_dir)
        rc, _o, _e = await _run_git(["git", "diff", "--cached", "--quiet"], cwd=clone_dir)
        if rc == 0:
            raise HTTPException(status_code=400, detail="The diff produced no changes against the current base.")
        msg = (title or f"Harvis: {source_label}").strip()
        rc, _o, err = await _run_git(["git", "commit", "-m", msg], cwd=clone_dir)
        if rc != 0:
            raise HTTPException(status_code=500, detail=f"commit failed: {err[:200]}")

        push_url = f"https://x-access-token:{gh_token}@github.com/{owner}/{repo}.git"
        rc, _o, err = await _run_git(
            ["git", "push", "--force-with-lease", push_url, f"{head}:{head}"], cwd=clone_dir
        )
        if rc != 0:
            if gh_token:
                err = (err or "").replace(gh_token, "***")  # never echo the token in the error
            raise HTTPException(status_code=502, detail=f"push failed: {err[:200]}")

        async with _httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"},
                json={
                    "title": msg,
                    "body": body or f"Opened by Harvis from {source_label}.",
                    "head": head,
                    "base": base,
                },
            )
        if resp.status_code in (200, 201):
            pr = resp.json()
            return {
                "status": "ok", "pr_url": pr.get("html_url"), "pr_number": pr.get("number"),
                "branch": head, "base": base, "owner": owner, "repo": repo,
            }
        raise HTTPException(status_code=502, detail=f"PR creation failed ({resp.status_code}): {resp.text[:200]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


class CreatePrRequest(BaseModel):
    artifact_id: Optional[str] = None  # which diff artifact (default: first diff on the run)
    branch: Optional[str] = None       # PR head branch (default: harvis/<run_id>)
    title: Optional[str] = None
    body: Optional[str] = None


@workspace_router.post("/run/{run_id}/create-pr")
async def create_pr_for_run(
    run_id: str,
    req: CreatePrRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """HUMAN-ONLY: open a GitHub PR from an attached-repo run's diff. Resolves the
    source repo's GitHub origin + the user's token, re-clones, applies the saved diff
    to a fresh feature branch, pushes, opens the PR. NEVER agent-triggered (only the UI
    button calls this). Refuses main/master as the PR head branch."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        raise HTTPException(status_code=500, detail="Database not available")

    # The run's attached repo + the chosen diff artifact (the clone is torn down at run
    # end, so the PR re-applies the SAVED diff). Then the shared PR path takes over.
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT repo_path FROM workspace_runs WHERE id = $1 AND user_id = $2", run_id, uid
        )
        if not run or not run["repo_path"]:
            raise HTTPException(status_code=404, detail="This run has no attached repo to open a PR for.")
        repo_path = run["repo_path"]
        if req.artifact_id:
            art = await conn.fetchrow(
                "SELECT content FROM workspace_artifacts WHERE id = $1 AND workspace_id = $2 AND artifact_type = 'diff'",
                req.artifact_id, run_id,
            )
        else:
            art = await conn.fetchrow(
                "SELECT content FROM workspace_artifacts WHERE workspace_id = $1 AND artifact_type = 'diff' ORDER BY created_at LIMIT 1",
                run_id,
            )
    diff_text = (art["content"] if art else "") or ""
    head = (req.branch or f"harvis/{run_id}").strip()
    return await _open_pr_from_diff(
        pool, uid, repo_path, diff_text, head, req.title, req.body,
        source_label=f"orchestrated run `{run_id}`",
    )


async def _resolve_run_action(
    request: Request, current_user: dict, run_id: str, action_id: str, approved: bool,
    scope: str = "once",
):
    """Resolve a gated in-place action (HUMAN-only — the acknowledge-popup). Ownership-
    scoped; resumes the paused agent turn via the in-memory pending-actions registry,
    with the durable workspace_pending_approvals row as the restart-survivable fallback.
    scope='session' (approve only) additionally records the action's pattern so matching
    commands auto-approve for the REST of the session (no re-prompt)."""
    from .orchestration.risk import (
        _PENDING_ACTIONS, add_session_approval, get_pending_row,
        mark_pending_resolved, resolve_action,
    )
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        # Fail closed — never skip the ownership check when the DB is unavailable.
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM workspace_runs WHERE id = $1 AND user_id = $2", run_id, uid
        )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    # action_id is namespaced by run_id (f"{run_id}-{step}-{seq}") — defense-in-depth.
    if not action_id.startswith(f"{run_id}-"):
        raise HTTPException(status_code=400, detail="action_id does not belong to this run")
    scope = scope if scope in ("once", "session") else "once"
    # Grab the in-memory meta BEFORE resolving (await_action_decision pops the entry).
    entry_exists = action_id in _PENDING_ACTIONS
    meta = (_PENDING_ACTIONS.get(action_id) or {}).get("meta") or {}
    db_row = None
    if not entry_exists:
        # Restart-survivable path: the awaiting coroutine is gone, but the durable row
        # lets us still record the decision (and a 'session' scope, so a re-run of the
        # same command auto-approves) instead of a silent 404.
        db_row = await get_pending_row(pool, action_id)
        if not db_row or db_row.get("resolved"):
            raise HTTPException(status_code=404, detail="No pending action with that id (expired or already resolved)")
    if approved and scope == "session":
        sess_id = meta.get("session_id") or (db_row or {}).get("session_id")
        tool = meta.get("tool") or (db_row or {}).get("tool")
        args = meta.get("args") or (db_row or {}).get("args") or {}
        if sess_id and tool:
            await add_session_approval(pool, sess_id, tool, args)
    decision = "approved-session" if (approved and scope == "session") else ("approved" if approved else "denied")
    # Record the decision BEFORE waking the paused runner so a richer scope
    # ('approved-session') isn't raced out by the runner's own 'approved' mark.
    await mark_pending_resolved(pool, action_id, decision)
    resumed = resolve_action(action_id, approved) if entry_exists else False
    return {"ok": True, "approved": approved, "scope": scope, "resumed": resumed}


@workspace_router.get("/run/{run_id}/pending-action")
async def get_pending_action(
    run_id: str, request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The gated action (if any) awaiting approval for this run — polled by the in-place
    UI to raise the acknowledge-popup. Reload-safe (the pending entry lives until resolved),
    and RESTART-safe: when the in-memory registry is empty, the durable
    workspace_pending_approvals row is returned (tagged stale:true — the paused turn
    itself did not survive the restart, but the request is not silently lost)."""
    from .orchestration.risk import get_pending_for_run, get_pending_for_run_db
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        # Fail closed — never skip the ownership check when the DB is unavailable.
        raise HTTPException(status_code=503, detail="Database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM workspace_runs WHERE id = $1 AND user_id = $2", run_id, uid
        )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    pending = get_pending_for_run(run_id)
    if pending is None:
        pending = await get_pending_for_run_db(pool, run_id)
    return {"pending": pending}


@workspace_router.post("/run/{run_id}/action/{action_id}/approve")
async def approve_run_action(
    run_id: str, action_id: str, request: Request,
    scope: str = "once",
    current_user: dict = Depends(get_current_user_optimized),
):
    """Approve a gated in-place action → the paused agent turn resumes + dispatches it.
    ?scope=session additionally whitelists the action's pattern for the whole session."""
    return await _resolve_run_action(request, current_user, run_id, action_id, True, scope=scope)


@workspace_router.post("/run/{run_id}/action/{action_id}/deny")
async def deny_run_action(
    run_id: str, action_id: str, request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Deny a gated in-place action → the turn skips it and continues."""
    return await _resolve_run_action(request, current_user, run_id, action_id, False)


@workspace_router.get("/vibecode/session/{session_id}/diff")
async def get_vibecode_session_diff(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The session's LIVE ACCUMULATED diff (working tree vs the fixed base_sha) — the
    union of every turn's edits. `files` is the status-classified change list (M/A/D/R —
    so DELETED files render even though the unified diff is their only trace). `has_github`
    gates the Create-PR button (the source needs a GitHub origin)."""
    from .orchestration.isolation import (
        WorkspaceIsolationManager, SESSION_WORKSPACE_ROOT, _run_git,
    )
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    s = dict(sess)
    wp = s.get("workspace_path")
    if not wp or not os.path.isdir(os.path.join(wp, ".git")):
        return {"diff": "", "files": [], "has_github": False, "repo": None}
    iso = WorkspaceIsolationManager(
        root=SESSION_WORKSPACE_ROOT, isolation_mode="session",
        repo_config={"base_sha": s.get("base_sha")},
    )
    diff = await iso.collect_diff(wp)
    try:
        files = await iso.collect_changed_files_status(wp)
    except Exception as exc:
        logger.warning("vibecode: changed-files status failed (%s): %s", session_id, exc)
        files = []
    has_github = False
    rp = s.get("repo_path")
    if rp and os.path.isdir(os.path.join(rp, ".git")):
        try:
            _rc, o, _e = await _run_git(["git", "config", "--get", "remote.origin.url"], cwd=rp)
            owner, _r = _parse_github_remote(o.strip())
            has_github = bool(owner)
        except Exception:
            pass
    return {
        "diff": diff or "",
        "files": files,
        "has_github": has_github,
        "repo": os.path.basename(rp.rstrip("/")) if rp else None,
    }


# ── Read-only workspace browse (Build Space Phase 2) ──────────────────────────
_BROWSE_MAX_ENTRIES = 5000
_BROWSE_MAX_FILE_BYTES = 512 * 1024


def _vibecode_browse_root(sess: dict) -> str | None:
    """The session's on-disk workspace root (realpath) — or None if it's gone."""
    wp = (sess or {}).get("workspace_path")
    if not wp or not os.path.isdir(wp):
        return None
    return os.path.realpath(wp)


@workspace_router.get("/vibecode/session/{session_id}/files")
async def list_vibecode_session_files(
    session_id: str,
    request: Request,
    subpath: str = "",
    current_user: dict = Depends(get_current_user_optimized),
):
    """READ-ONLY tree of the session's workspace (ownership-scoped). `subpath` narrows
    the walk to a sub-directory. `.git` is hidden; entries are capped (`truncated`
    signals the cap). Paths are relative to the workspace root."""
    from .orchestration.isolation import validate_agent_path
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    root = _vibecode_browse_root(dict(sess))
    if not root:
        return {"entries": [], "truncated": False}
    rel = (subpath or "").strip().strip("/")
    base = os.path.realpath(os.path.join(root, rel)) if rel else root
    if not validate_agent_path(root, base):
        raise HTTPException(status_code=400, detail="Path escapes the session workspace")
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="Not a directory in this workspace")
    entries: list[dict] = []
    truncated = False
    for droot, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for d in dirs:
            entries.append({"path": os.path.relpath(os.path.join(droot, d), root), "type": "dir"})
        for fn in sorted(files):
            fp = os.path.join(droot, fn)
            try:
                size = os.path.getsize(fp)
            except OSError:
                size = 0
            entries.append({"path": os.path.relpath(fp, root), "type": "file", "size": size})
        if len(entries) >= _BROWSE_MAX_ENTRIES:
            truncated = True
            break
    return {"entries": entries[:_BROWSE_MAX_ENTRIES], "truncated": truncated}


@workspace_router.get("/vibecode/session/{session_id}/file")
async def get_vibecode_session_file(
    session_id: str,
    request: Request,
    path: str = "",
    current_user: dict = Depends(get_current_user_optimized),
):
    """READ-ONLY content of ONE workspace file (ownership-scoped, realpath-contained).
    Text capped at 512KB (`truncated`); binary files return content:'' + binary:true;
    secret-named files (.env / keys) return content:'' + secret:true — same deny-list
    as artifacts (browse must never exfiltrate credentials)."""
    from .orchestration.isolation import validate_agent_path
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    root = _vibecode_browse_root(dict(sess))
    if not root:
        raise HTTPException(status_code=404, detail="The session workspace is no longer available.")
    rel = (path or "").strip().strip("/")
    if not rel:
        raise HTTPException(status_code=400, detail="path is required")
    if rel == ".git" or rel.startswith(".git/") or "/.git/" in rel:
        raise HTTPException(status_code=400, detail="Path escapes the session workspace")
    if not validate_agent_path(root, rel):
        raise HTTPException(status_code=400, detail="Path escapes the session workspace")
    fp = os.path.realpath(os.path.join(root, rel))
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="File not found in this workspace")
    size = os.path.getsize(fp)
    if _artifact_is_secret(rel):
        return {"path": rel, "content": "", "truncated": False, "binary": False,
                "secret": True, "size": size}
    with open(fp, "rb") as fh:
        raw = fh.read(_BROWSE_MAX_FILE_BYTES + 1)
    if b"\x00" in raw[:8192]:
        return {"path": rel, "content": "", "truncated": False, "binary": True, "size": size}
    truncated = len(raw) > _BROWSE_MAX_FILE_BYTES
    content = raw[:_BROWSE_MAX_FILE_BYTES].decode("utf-8", errors="replace")
    return {"path": rel, "content": content, "truncated": truncated, "binary": False, "size": size}


class VibecodeCreatePrRequest(BaseModel):
    branch: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    base: Optional[str] = None  # PR target/base branch (drawer selector); falls back to the session's base_branch
    # Explicit HUMAN bypass of the agent-review gate: a review_enabled session whose
    # review_status isn't 'agreed' refuses Create-PR unless this is true. The human
    # override is always allowed; review_enabled=FALSE sessions ignore it entirely.
    override: bool = False


# ── Run & Preview ─────────────────────────────────────────────────────────────
# Code it in Harvis, run it in Harvis. The session's workspace is bind-mounted into
# the same isolated sandbox the Repo Runner uses — no GitHub, no clone, no copy.
#
# The preview is served from a SEPARATE ORIGIN (a 127.0.0.1 host port docker assigns)
# and never proxied through Harvis's own origin. That is deliberate and load-bearing:
# `auth_optimized` accepts the JWT from an `access_token` cookie, so a same-origin
# preview would let model-written JavaScript call Harvis's API as the signed-in user.
# The cost of a separate origin is that the iframe only embeds when the browser is on
# the Docker host — the UI says so rather than showing a silent blank frame.


def _vibecode_run_stack(root: str) -> dict:
    """Recompute the run plan from what is ON DISK right now. Never cached: the agent
    may have written package.json (or the first index.html) since the last look."""
    from owui_compat import fab_repo
    return fab_repo.detect_stack(root)


def _vibecode_install_cmd(stack: dict) -> str | None:
    """The install step, or None when there is genuinely nothing to install. A hand-
    written page has no manifest, and running `npm install` on it only produces a
    confusing failure."""
    plan = stack.get("run_plan") or {}
    if plan.get("framework") == "static":
        return None
    return stack.get("install") or None


@workspace_router.get("/vibecode/session/{session_id}/preview")
async def get_vibecode_preview(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """What Run would do, and what it is doing. Everything the Preview tab renders."""
    from owui_compat import workspace_sandbox
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    root = _vibecode_browse_root(dict(sess))
    enabled = workspace_sandbox.run_enabled()
    out: dict = {
        "enabled": enabled,
        "reason": "" if enabled else (
            "Running your session's code isn't enabled on this deployment. It executes "
            "code in a container, so it stays off until an operator sets "
            "HARVIS_VIBECODE_RUN_ENABLED=true and the isolated sandbox network is up."
        ),
        "plan": None,
        "preview": workspace_sandbox.get_manager().state(session_id),
    }
    if not root:
        out["reason"] = out["reason"] or "This session has no workspace directory on disk."
        return out
    stack = _vibecode_run_stack(root)
    plan = stack.get("run_plan") or {}
    out["plan"] = {
        "stack": stack.get("stack"),
        "framework": plan.get("framework"),
        "web": bool(plan.get("web")),
        "dev_cmd": plan.get("dev_cmd"),
        "install": _vibecode_install_cmd(stack),
        "port": plan.get("port"),
        "blocked_reason": (stack.get("requirements") or {}).get("blocked_reason"),
    }
    return out


@workspace_router.post("/vibecode/session/{session_id}/run")
async def run_vibecode_preview(
    session_id: str,
    payload: dict,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Start this session's app in the sandbox and publish a live preview.

    Approval-gated per run (``approved: true``) because it executes code the model
    wrote. Launches in the background; the client polls ``/preview``."""
    from owui_compat import workspace_sandbox
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if not workspace_sandbox.run_enabled():
        raise HTTPException(
            status_code=403,
            detail="Running your session's code isn't enabled on this deployment "
                   "(HARVIS_VIBECODE_RUN_ENABLED).",
        )
    if not bool((payload or {}).get("approved")):
        raise HTTPException(status_code=403, detail="Running the app needs your explicit approval.")
    root = _vibecode_browse_root(dict(sess))
    if not root:
        raise HTTPException(status_code=400, detail="This session has no workspace directory on disk.")

    stack = _vibecode_run_stack(root)
    plan = stack.get("run_plan") or {}
    req = stack.get("requirements") or {}
    if req.get("multi_service"):
        services = [s.get("name") for s in (req.get("services") or [])
                    if isinstance(s, dict) and s.get("name")]
        raise HTTPException(
            status_code=400,
            detail="This looks like a multi-service app (needs %s). The sandbox runs one "
                   "process; start it as a single web app, or run it outside Harvis."
                   % (", ".join(services) or "external services"),
        )
    if not plan.get("web") or not plan.get("dev_cmd"):
        raise HTTPException(
            status_code=400,
            detail=req.get("blocked_reason")
            or "Nothing here serves a web page yet — write an index.html (or a dev script) first.",
        )

    mgr = workspace_sandbox.get_manager()
    cur = mgr.state(session_id)
    if cur and cur.get("status") in ("installing", "starting", "running"):
        return {"ok": True, "preview": cur}  # already up or coming up — don't double-launch

    ready = await mgr.probe()
    if not ready.get("ready"):
        raise HTTPException(status_code=503, detail=f"Preview sandbox not ready: {ready.get('reason')}")

    fw = plan.get("framework") or "app"

    async def _persist(status: str, fields: dict) -> None:
        # The manager's own box table IS the state the /preview route reads, and it is
        # already updated before this fires — so this only needs to leave a trail.
        logger.info("[vibe-preview:%s] %s (%s)", session_id, status,
                    (fields or {}).get("error") or fw)

    asyncio.create_task(mgr.run(
        session_id, root, _vibecode_install_cmd(stack), plan["dev_cmd"],
        plan.get("env") or {}, fw, _persist,
    ))
    logger.info("vibecode: preview launching for session %s (fw=%s)", session_id, fw)
    return {"ok": True, "preview": {"status": "starting", "framework": fw,
                                    "port": plan.get("port"), "host_port": 0,
                                    "error": "", "log_tail": ""}}


@workspace_router.post("/vibecode/session/{session_id}/stop")
async def stop_vibecode_preview(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Tear down this session's preview container."""
    from owui_compat import workspace_sandbox
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    stopped = await workspace_sandbox.get_manager().stop(session_id)
    return {"ok": True, "stopped": stopped}


@workspace_router.post("/vibecode/session/{session_id}/create-pr")
async def create_pr_for_vibecode_session(
    session_id: str,
    req: VibecodeCreatePrRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """HUMAN-ONLY: open ONE GitHub PR from a session's ACCUMULATED diff (all turns).
    Uses the LIVE session working-tree diff (not a saved artifact — the session clone
    persists). Refuses main/master; NEVER agent-triggered (only the UI button)."""
    from .orchestration.isolation import WorkspaceIsolationManager, SESSION_WORKSPACE_ROOT
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        raise HTTPException(status_code=500, detail="Database not available")
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    s = dict(sess)
    # ── Agent-review PR gate (opt-in) ── review_enabled sessions wait for the
    # agents' agreement before a PR can open; the HUMAN override always wins.
    # review_enabled=FALSE (the default) ⇒ this block is a no-op — zero change.
    _review_status = (s.get("review_status") or "off").strip().lower()
    if s.get("review_enabled") and _review_status not in ("agreed", "off") and not req.override:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The agents haven't agreed on this change yet (review status: "
                f"{_review_status}). Run a review — `/harvis-code review` on Discord or "
                "the Run agent review button in the PR drawer — until the reviewer "
                "approves, or pass override=true to open the PR anyway (your call)."
            ),
        )
    repo_path = s.get("repo_path")
    wp = s.get("workspace_path")
    if not repo_path:
        raise HTTPException(status_code=400, detail="This session has no attached repo to open a PR for.")
    if not wp or not os.path.isdir(os.path.join(wp, ".git")):
        raise HTTPException(status_code=404, detail="The session workspace is no longer available.")
    iso = WorkspaceIsolationManager(
        root=SESSION_WORKSPACE_ROOT, isolation_mode="session",
        repo_config={"base_sha": s.get("base_sha")},
    )
    diff_text = await iso.collect_diff(wp)
    head = (req.branch or f"harvis/vibecode/{session_id}").strip()
    result = await _open_pr_from_diff(
        pool, uid, repo_path, diff_text, head, req.title, req.body,
        source_label=f"VibeCode session `{session_id}`",
        base_branch=(req.base or s.get("base_branch")),
    )
    # Phase 4: persist the PR record. UPSERT by (session_id, head_branch) — a
    # re-create for the same session+branch UPDATES the existing row (url/number/
    # status) instead of duplicating. FAIL-OPEN: the PR already exists on GitHub;
    # a bookkeeping failure must never turn that success into an error.
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO code_pull_requests
                    (id, session_id, provider, pr_url, pr_number, base_branch, head_branch, title, status)
                VALUES ($1, $2, 'github', $3, $4, $5, $6, $7, 'open')
                ON CONFLICT (session_id, head_branch) DO UPDATE SET
                    pr_url      = EXCLUDED.pr_url,
                    pr_number   = EXCLUDED.pr_number,
                    base_branch = EXCLUDED.base_branch,
                    title       = EXCLUDED.title,
                    status      = 'open',
                    updated_at  = NOW()
                """,
                uuid.uuid4().hex, session_id,
                result.get("pr_url"), result.get("pr_number"),
                result.get("base"), result.get("branch"),
                (req.title or f"Harvis: VibeCode session `{session_id}`").strip(),
            )
    except Exception as exc:
        logger.warning("code_pull_requests upsert failed (fail-open): %s", exc)
    return result


@workspace_router.get("/vibecode/session/{session_id}/changes")
async def list_vibecode_session_changes(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Per-file audit trail of the session's TRACKED AI edits (code_file_changes
    rows written by the apply_patch tool). Ownership-scoped; newest first."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        raise HTTPException(status_code=500, detail="Database not available")
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, session_id, run_id, file_path, change_type, patch_id, "
            "before_sha, after_sha, created_at FROM code_file_changes "
            "WHERE session_id = $1 ORDER BY created_at DESC LIMIT 500",
            session_id,
        )
    return {"changes": [
        {**dict(r), "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]}


@workspace_router.get("/vibecode/session/{session_id}/pull-requests")
async def list_vibecode_session_pull_requests(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The session's persisted PR records (code_pull_requests). Ownership-scoped;
    most recently updated first."""
    pool = getattr(request.app.state, "pg_pool", None)
    uid = current_user["id"]
    if pool is None:
        raise HTTPException(status_code=500, detail="Database not available")
    sess = await _vibecode_session_row(pool, session_id, uid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, session_id, provider, pr_url, pr_number, base_branch, "
            "head_branch, title, status, created_at, updated_at "
            "FROM code_pull_requests WHERE session_id = $1 "
            "ORDER BY updated_at DESC LIMIT 100",
            session_id,
        )
    return {"pull_requests": [
        {
            **dict(r),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]}


@workspace_router.get("/history")
async def list_workspace_history(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"runs": []}
    # ?top_level=1 → only parent/launched runs (the VibeCode session list; sub-agent
    # child runs have their events under the parent, so they aren't streamable alone).
    top_level = request.query_params.get("top_level") in ("1", "true", "yes")
    # ?session_id=<chat_id> → scope the list to ONE chat's runs (the process rail is
    # per-chat: a chat-launched run's session_id IS the OWUI chat_id). Persistent because
    # the rows are DB-backed — reopening the chat re-shows its runs + statuses.
    sess = request.query_params.get("session_id")
    # ?run_id=<id> → ONE run, looked up by an id the caller already holds. RunView asks
    # this to learn whether the run it is streaming has finished on the server, and that
    # answer is the ONLY thing that stops its "Working…" indicator when the live stream
    # never delivers a terminal event (a view mounted after the run ended, a replay that
    # raced, a severed reconnect). The vibecode exclusion below keeps Build turns out of
    # the Agent Studio LIST — but a lookup by explicit id is not a list, and applying it
    # there returned nothing for every Build turn, so that guard was dead on the one
    # surface that renders inside the Build thread. Ownership is still enforced.
    run_id = request.query_params.get("run_id")
    params: list = [current_user["id"]]
    if run_id:
        where = "WHERE r.user_id = $1 AND r.id = $2"
        params.append(run_id)
    else:
        # Exclude VibeCode session turns — they live in their own surface (the VibeCode
        # thread), not the generic Agent Studio history / Neural Map. IS DISTINCT FROM
        # keeps NULL-source rows (all generic/orchestrated runs).
        where = "WHERE r.user_id = $1 AND r.source IS DISTINCT FROM 'vibecode'" + (
            " AND r.parent_run_id IS NULL" if top_level else ""
        )
        if sess:
            where += f" AND r.session_id = ${len(params) + 1}"
            params.append(sess)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT r.id, r.session_id, r.task_brief, r.status, r.parent_run_id,
                       r.started_at, r.completed_at, r.duration_ms,
                       r.event_count, r.tool_calls, r.final_summary, r.error_message,
                       r.model_name, r.prompt_tokens, r.completion_tokens,
                       r.context_window,
                       (SELECT COUNT(*) FROM workspace_runs c WHERE c.parent_run_id = r.id)
                         AS child_count
                FROM workspace_runs r
                {where}
                ORDER BY r.started_at DESC
                LIMIT 50
                """,
                *params,
            )
        runs = [dict(r) for r in rows]
        for run in runs:
            for key in ("started_at", "completed_at"):
                if run.get(key) is not None:
                    run[key] = run[key].isoformat()
        return {"runs": runs}
    except Exception as exc:
        logger.error("DB: failed to fetch workspace history for user %s: %s", current_user["id"], exc)
        return {"runs": []}


@workspace_router.post("/run/{source_id}/rerun")
async def rerun_workspace(
    source_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Re-launch a previous workspace run using its stored task_brief.
    Creates a fresh workspace_id + session_id and starts a new background task.
    """
    pool = getattr(request.app.state, "pg_pool", None)

    task_brief: Optional[str] = None
    agent_id = "main"

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT task_brief FROM workspace_runs WHERE id = $1 AND user_id = $2",
                    source_id, current_user["id"],
                )
            if row:
                task_brief = row["task_brief"]
        except Exception as exc:
            logger.error("DB: failed to fetch task_brief for rerun %s: %s", source_id, exc)

    if not task_brief:
        ws = _workspaces.get(source_id)
        if ws and ws.get("user_id") == current_user["id"]:
            task_brief = ws["task_brief"]
            agent_id = ws.get("agent_id", "main")

    if not task_brief:
        raise HTTPException(status_code=404, detail="Workspace run not found")

    workspace_id = str(uuid.uuid4())[:8]
    session_id = f"ws-{workspace_id}"
    started_epoch = time.monotonic()

    await _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=[],
        agent_id=agent_id,
        user_id=current_user["id"],
        pool=pool,
        started_epoch=started_epoch,
    )

    try:
        await _db_create_run(pool, workspace_id, current_user["id"], session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run (rerun) raised unexpectedly: %s", exc)

    logger.info(
        "Workspace rerun: source=%s new=%s user=%s brief=%r",
        source_id, workspace_id, current_user["id"], task_brief,
    )
    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
    }


@workspace_router.get("/usage/summary")
async def usage_summary(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Return token usage and cost aggregates from proxy_usage_log.

    Response:
      today    — totals for the current calendar day (UTC)
      by_model — per-model totals for the last 30 days, ordered by cost desc
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {
            "today": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0},
            "by_model": [],
        }
    try:
        async with pool.acquire() as conn:
            by_model = await conn.fetch("""
                SELECT model,
                       SUM(tokens_in)::int  AS tokens_in,
                       SUM(tokens_out)::int AS tokens_out,
                       SUM(cost_usd)        AS cost_usd
                FROM proxy_usage_log
                WHERE ts >= NOW() - INTERVAL '30 days'
                GROUP BY model ORDER BY cost_usd DESC
            """)
            today = await conn.fetchrow("""
                SELECT COALESCE(SUM(tokens_in),0)::int  AS tokens_in,
                       COALESCE(SUM(tokens_out),0)::int AS tokens_out,
                       COALESCE(SUM(cost_usd),0)        AS cost_usd
                FROM proxy_usage_log WHERE ts >= CURRENT_DATE
            """)
        return {
            "today": dict(today),
            "by_model": [dict(r) for r in by_model],
        }
    except Exception as exc:
        logger.error("DB: failed to fetch usage summary: %s", exc)
        return {
            "today": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0},
            "by_model": [],
        }


@workspace_router.get("/run/{workspace_id}/events")
async def get_workspace_events(
    workspace_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"events": []}
    try:
        async with pool.acquire() as conn:
            run = await conn.fetchrow(
                "SELECT user_id FROM workspace_runs WHERE id = $1",
                workspace_id,
            )
            if run is None or run["user_id"] != current_user["id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            rows = await conn.fetch(
                """
                SELECT id, workspace_id, seq, event_type, payload, ts
                FROM workspace_events
                WHERE workspace_id = $1
                ORDER BY seq ASC
                """,
                workspace_id,
            )
        events = []
        for r in rows:
            row_dict = dict(r)
            row_dict["ts"] = row_dict["ts"].isoformat() if row_dict.get("ts") else None
            events.append(row_dict)
        return {"events": events}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("DB: failed to fetch events for workspace %s: %s", workspace_id, exc)
        return {"events": []}


@workspace_router.get("/active")
async def get_active_workspace(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Return the latest running workspace for the current user (if any).

    Used for external triggers (e.g., Discord) so the UI can attach to a run that
    started outside the browser.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"active": None}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, session_id, task_brief, status, started_at
                FROM workspace_runs
                WHERE user_id = $1
                  AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 10
                """,
                current_user["id"],
            )
        if not rows:
            return {"active": None}
        for row in rows:
            d = dict(row)
            in_memory = d["id"] in _workspaces
            _append_debug_log(
                "workspace_router.py:get_active_workspace",
                "active_workspace_candidate",
                {
                    "workspace_id": d["id"],
                    "session_id": d.get("session_id"),
                    "status": d.get("status"),
                    "in_memory": in_memory,
                },
                "run_workspace_active_follow",
                "H_active_orphan",
            )
            if not in_memory:
                await _db_mark_run_orphaned(
                    pool,
                    d["id"],
                    "Workspace was left in running state but no live in-memory task exists.",
                )
                continue
            d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
            session_id = d.get("session_id") or ""
            d["source"] = "discord" if session_id.startswith("discord-") else "web"
            return {"active": d}
        return {"active": None}
    except Exception as exc:
        logger.error("DB: failed to fetch active workspace: %s", exc)
        return {"active": None}


@workspace_router.get("/active-runs")
async def get_active_runs(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Every workspace run still live for this user, as ``{id, session_id}``.

    The sidebar polls this so a chat whose agent is still working keeps its spinner
    while the user reads a different chat. ``/active`` cannot serve that: it returns
    at most ONE run, and it marks every candidate it walks past as orphaned on the
    way. Polling that endpoint would quietly kill the very runs this is meant to
    report, so this one is strictly read-only.

    ``session_id`` IS the chat id -- that is the join the caller needs.

    A row with no entry in ``_workspaces`` is a leftover from a backend restart, not a
    live run; it is dropped here so the sidebar stops spinning on it. Writing that fact
    back to the DB stays ``/active``'s job -- a poll should not mutate.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"runs": []}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, session_id, source
                FROM workspace_runs
                WHERE user_id = $1
                  AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 50
                """,
                current_user["id"],
            )
    except Exception as exc:
        logger.error("DB: failed to fetch active runs: %s", exc)
        return {"runs": []}
    # `session_id` is the OWUI chat id ONLY when the request carried one; the bridge
    # falls back to a synthetic `owui-<workspace_id>` (and Discord launches use
    # `discord-…`). Those are not chats the sidebar can key on, and marking them would
    # write rows into its localStorage that no chat will ever come along and clear.
    synthetic = ("owui-", "discord-", "sess-")
    return {
        "runs": [
            # `source` says WHICH list owns this id: 'vibecode' means the session_id is a
            # Build session (the Code sidebar's list), anything else means it is an OWUI
            # chat id. Without it the sidebar was already writing activity entries keyed on
            # Build ids that no chat row would ever render or clear.
            {"id": r["id"], "session_id": r["session_id"], "source": r["source"] or ""}
            for r in rows
            if r["id"] in _workspaces
            and r["session_id"]
            and not r["session_id"].startswith(synthetic)
        ]
    }


@workspace_router.get("/active-discord")
async def get_active_discord_session(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Is a Discord-launched (#harvis-code) session actively running for this user?

    A session gets ``discord_channel_id`` set when it's started via ``/harvis-code start``
    (the run's own ``session_id`` is a normal vibecode id, so the ``discord-`` prefix
    heuristic in ``/active`` can't detect it). Powers the Build header's
    "Discord session online" chip → click jumps the user into the live session so the
    web UI mirrors what's happening in Discord.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"active": None}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r.id AS run_id, r.session_id, r.task_brief, r.started_at,
                       s.title, s.discord_channel_id
                FROM workspace_runs r
                JOIN vibecode_sessions s ON s.id = r.session_id
                WHERE r.user_id = $1
                  AND r.status = 'running'
                  AND s.discord_channel_id IS NOT NULL
                ORDER BY r.started_at DESC
                LIMIT 1
                """,
                current_user["id"],
            )
        if not row:
            return {"active": None}
        d = dict(row)
        d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
        return {"active": d}
    except Exception as exc:
        logger.error("DB: failed to fetch active discord session: %s", exc)
        return {"active": None}


@workspace_router.get("/active-review")
async def get_active_review(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The user's currently-running agent review (coder↔reviewer), if any. Powers the main-Chat
    "Agent review live" chip + the review side panel that MIRRORS the review conversation into
    the Chat app. Identified by the session's `review_status='pending'` + a running run.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"active": None}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r.id AS run_id, r.session_id, r.task_brief, r.started_at,
                       s.title, s.review_status
                FROM workspace_runs r
                JOIN vibecode_sessions s ON s.id = r.session_id
                WHERE r.user_id = $1
                  AND r.status = 'running'
                  AND s.review_status = 'pending'
                ORDER BY r.started_at DESC
                LIMIT 1
                """,
                current_user["id"],
            )
        if not row:
            return {"active": None}
        d = dict(row)
        d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
        return {"active": d}
    except Exception as exc:
        logger.error("DB: failed to fetch active review: %s", exc)
        return {"active": None}


# ── Shared workspace model (Discord ↔ Build sync) ────────────────────────────
# The per-user openclaw_llm_config row (UNIQUE(user_id)) is the single lever both
# Discord's /set-model and the Build model picker write. Last-write-wins by
# updated_at: whichever surface changed the model most recently takes over. These
# endpoints let the Build UI READ the shared model (reflect a Discord change) and
# WRITE it (so a Build pick shows up in Discord) — the reverse was already wired.

class WorkspaceModelRequest(BaseModel):
    model_id: str = ""


@workspace_router.get("/workspace-model")
async def get_workspace_model(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Return the current shared model + its updated_at epoch (0 if unset)."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"model_id": "", "updated_at": 0}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT model_id, EXTRACT(EPOCH FROM updated_at) AS epoch "
                "FROM openclaw_llm_config WHERE user_id = $1 "
                "ORDER BY updated_at DESC LIMIT 1",
                current_user["id"],
            )
        if not row:
            return {"model_id": "", "updated_at": 0}
        return {"model_id": row["model_id"] or "", "updated_at": float(row["epoch"] or 0)}
    except Exception as exc:
        logger.error("DB: failed to read shared workspace model: %s", exc)
        return {"model_id": "", "updated_at": 0}


@workspace_router.post("/workspace-model")
async def set_workspace_model_endpoint(
    req: WorkspaceModelRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Point the shared model at the Build picker's selection — the SAME per-user
    openclaw_llm_config row Discord /set-model writes (bumps updated_at=NOW() so it
    wins). ON CONFLICT only touches model_id + updated_at, preserving provider_url /
    provider_type / engine on an existing row. Returns the new updated_at epoch so the
    caller can avoid re-adopting its own write on the next poll.

    ``last_local_model_id`` mirrors what Discord's /set-model records: a LOCAL pick is
    remembered there, a cloud pick leaves it untouched (COALESCE on NULL). That column
    is what every local-only consumer falls back to while a cloud model is selected —
    without it, picking Claude in Build left workspace detection and autonaming pointed
    at a tag Ollama can't serve, and switching back to local had nothing to restore.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    m = (req.model_id or "").strip()
    if pool is None or not m:
        return {"ok": False, "updated_at": 0}
    ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
    try:
        from owui_compat.cloud_chat import is_cloud_chat_model
        _is_cloud = is_cloud_chat_model(m)
    except Exception:
        logger.warning("workspace-model: cloud detection unavailable, treating %r as local", m)
        _is_cloud = False
    _last_local = None if _is_cloud else m
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO openclaw_llm_config
                    (user_id, provider_url, model_id, provider_type, is_active, last_local_model_id)
                VALUES ($1, $2, $3, 'ollama', TRUE, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    model_id = EXCLUDED.model_id,
                    last_local_model_id = COALESCE($4, openclaw_llm_config.last_local_model_id),
                    updated_at = NOW()
                RETURNING EXTRACT(EPOCH FROM updated_at) AS epoch
                """,
                current_user["id"], ollama_url, m, _last_local,
            )
        return {"ok": True, "model_id": m, "updated_at": float(row["epoch"] or 0) if row else 0}
    except Exception as exc:
        logger.error("DB: failed to set shared workspace model: %s", exc)
        return {"ok": False, "updated_at": 0}


# ── BYO OpenClaw config endpoints ────────────────────────────────────────────

class BYOConfigSaveRequest(BaseModel):
    mode: str = "bundled"         # "bundled" or "byo"
    byo_url: Optional[str] = None
    byo_token: Optional[str] = None


class BYOConfigVerifyRequest(BaseModel):
    url: str
    token: Optional[str] = None


@workspace_router.get("/config/openclaw")
async def get_openclaw_mode_config(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Get the current user's OpenClaw mode configuration."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        return {
            "mode": "bundled",
            "byo_url": None,
            "byo_verified_at": None,
            "byo_last_error": None,
            "byo_token_saved": False,
        }

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT mode, byo_url, byo_verified_at, byo_last_error,
                       (byo_token_encrypted IS NOT NULL AND length(byo_token_encrypted) > 0) AS byo_token_saved
                FROM user_openclaw_config
                WHERE user_id = $1
                """,
                current_user["id"],
            )
    except Exception as exc:
        logger.error("get_openclaw_mode_config: DB error for user %s: %s", current_user["id"], exc)
        return {
            "mode": "bundled",
            "byo_url": None,
            "byo_verified_at": None,
            "byo_last_error": None,
            "byo_token_saved": False,
        }

    if not row:
        return {
            "mode": "bundled",
            "byo_url": None,
            "byo_verified_at": None,
            "byo_last_error": None,
            "byo_token_saved": False,
        }

    return {
        "mode": row["mode"],
        "byo_url": row["byo_url"],
        "byo_verified_at": row["byo_verified_at"].isoformat() if row["byo_verified_at"] else None,
        "byo_last_error": row["byo_last_error"],
        "byo_token_saved": bool(row["byo_token_saved"]),
    }


@workspace_router.post("/config/openclaw")
async def save_openclaw_mode_config(
    req: BYOConfigSaveRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Save the user's OpenClaw mode configuration."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    if req.mode not in ("bundled", "byo"):
        raise HTTPException(status_code=400, detail="mode must be 'bundled' or 'byo'")

    byo_url = (req.byo_url or "").strip() or None
    byo_token = (req.byo_token or "").strip()

    if req.mode == "byo" and not byo_url:
        raise HTTPException(status_code=400, detail="BYO mode requires a gateway URL")

    # Encrypt the BYO token if provided
    encrypted_token = None
    if byo_token:
        from main import encrypt_api_key
        encrypted_token = encrypt_api_key(byo_token)

    try:
        async with pool.acquire() as conn:
            existing_has_token = bool(
                await conn.fetchval(
                    """
                    SELECT (byo_token_encrypted IS NOT NULL AND length(byo_token_encrypted) > 0)
                    FROM user_openclaw_config
                    WHERE user_id = $1
                    """,
                    current_user["id"],
                )
            )
            if req.mode == "byo" and not encrypted_token and not existing_has_token:
                raise HTTPException(
                    status_code=400,
                    detail="Gateway token is required the first time you configure BYO mode",
                )

            await conn.execute(
                """
                INSERT INTO user_openclaw_config (user_id, mode, byo_url, byo_token_encrypted)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    byo_url = COALESCE(EXCLUDED.byo_url, user_openclaw_config.byo_url),
                    byo_token_encrypted = COALESCE(EXCLUDED.byo_token_encrypted, user_openclaw_config.byo_token_encrypted),
                    updated_at = NOW()
                """,
                current_user["id"],
                req.mode,
                byo_url,
                encrypted_token,
            )
            row = await conn.fetchrow(
                """
                SELECT mode, byo_url, byo_verified_at, byo_last_error,
                       (byo_token_encrypted IS NOT NULL AND length(byo_token_encrypted) > 0) AS byo_token_saved
                FROM user_openclaw_config
                WHERE user_id = $1
                """,
                current_user["id"],
            )
        return {
            "ok": True,
            "mode": row["mode"] if row else req.mode,
            "byo_url": row["byo_url"] if row else byo_url,
            "byo_verified_at": row["byo_verified_at"].isoformat() if row and row["byo_verified_at"] else None,
            "byo_last_error": row["byo_last_error"] if row else None,
            "byo_token_saved": bool(row["byo_token_saved"]) if row else bool(encrypted_token),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("save_openclaw_mode_config: DB error for user %s: %s", current_user["id"], exc)
        raise HTTPException(status_code=500, detail="Failed to save configuration")


@workspace_router.post("/config/byo/verify")
async def verify_byo_config(
    req: BYOConfigVerifyRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Attempt to connect to the user's OpenClaw and verify auth + protocol.
    Returns ok=true on success, ok=false with error/hint on failure.
    On success, stores verified timestamp (and token if provided).
    """
    import websockets as _ws

    if not req.url.startswith(("ws://", "wss://")):
        return {"ok": False, "error": "URL must start with ws:// or wss://", "hint": "Use ws://localhost:18789 or similar."}

    token = (req.token or "").strip()
    if not token:
        pool = getattr(request.app.state, "pg_pool", None)
        if pool:
            try:
                async with pool.acquire() as conn:
                    enc = await conn.fetchval(
                        """
                        SELECT byo_token_encrypted
                        FROM user_openclaw_config
                        WHERE user_id = $1
                        """,
                        current_user["id"],
                    )
                if enc:
                    from main import decrypt_api_key
                    token = decrypt_api_key(enc) or ""
            except Exception as exc:
                logger.error("verify_byo_config: failed loading saved token for user %s: %s", current_user["id"], exc)
        if not token:
            return {
                "ok": False,
                "error": "No gateway token provided",
                "hint": "Enter your OpenClaw gateway token or save one first.",
            }

    try:
        ws = await _ws.connect(
            req.url,
            ping_interval=10,
            ping_timeout=5,
            open_timeout=10,
        )

        # Read the challenge
        import json as _json
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        challenge = _json.loads(raw)
        if not (challenge.get("type") == "event" and challenge.get("event") == "connect.challenge"):
            await ws.close()
            return {"ok": False, "error": "Unexpected response from server", "hint": "This endpoint does not appear to be an OpenClaw gateway."}

        nonce = challenge.get("payload", {}).get("nonce", "")
        if not nonce:
            await ws.close()
            return {"ok": False, "error": "Missing challenge nonce", "hint": "Gateway challenge payload was invalid."}

        req_id = "verify-connect"
        await ws.send(_json.dumps({
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": PROTOCOL_VERSION,
                "maxProtocol": PROTOCOL_VERSION,
                "client": {
                    "id": _CLIENT_ID,
                    "version": "1.0.0",
                    "platform": "linux",
                    "mode": _CLIENT_MODE,
                },
                "caps": ["tool-events"],
                "role": "operator",
                "scopes": _CLIENT_SCOPES,
                "auth": {"token": token},
                "device": _build_device_params(nonce, token),
            },
        }))
        ack_raw = await asyncio.wait_for(ws.recv(), timeout=10)
        ack = _json.loads(ack_raw)
        if ack.get("type") != "res" or not ack.get("ok"):
            await ws.close()
            err_msg = (
                (ack.get("error") or {}).get("message")
                or "Gateway rejected connect/auth handshake"
            )
            await _set_byo_error(request, current_user["id"], str(err_msg)[:500])
            return {
                "ok": False,
                "error": f"Authentication failed: {err_msg}",
                "hint": "Check your gateway token and ensure OpenClaw allows operator access.",
            }

        # Gateway auth + protocol handshake succeeded.
        await ws.close()

        # Update verification timestamp in DB
        pool = getattr(request.app.state, "pg_pool", None)
        if pool:
            from main import encrypt_api_key
            encrypted_token = encrypt_api_key(token)
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO user_openclaw_config (user_id, mode, byo_url, byo_token_encrypted, byo_verified_at, byo_last_error)
                        VALUES ($1, 'byo', $2, $3, NOW(), NULL)
                        ON CONFLICT (user_id) DO UPDATE SET
                            byo_url = EXCLUDED.byo_url,
                            byo_token_encrypted = EXCLUDED.byo_token_encrypted,
                            byo_verified_at = NOW(),
                            byo_last_error = NULL,
                            updated_at = NOW()
                        """,
                        current_user["id"],
                        req.url,
                        encrypted_token,
                    )
            except Exception as exc:
                logger.error("verify_byo_config: DB update failed for user %s: %s", current_user["id"], exc)

        return {"ok": True, "message": "OpenClaw reachable, auth handshake verified", "byo_token_saved": True}

    except asyncio.TimeoutError:
        await _set_byo_error(request, current_user["id"], "Connection timed out")
        return {
            "ok": False,
            "error": "Connection timed out",
            "hint": "Check firewall and port forwarding. WSL users may need to bind to 0.0.0.0.",
        }
    except ConnectionRefusedError:
        await _set_byo_error(request, current_user["id"], "Connection refused")
        return {
            "ok": False,
            "error": "Connection refused",
            "hint": "OpenClaw is not running at that URL. Check `openclaw gateway status`.",
        }
    except Exception as exc:
        error_msg = str(exc)[:500]
        await _set_byo_error(request, current_user["id"], error_msg)
        return {
            "ok": False,
            "error": error_msg,
            "hint": _verification_hint(exc),
        }


def _verification_hint(exc: Exception) -> str:
    msg = str(exc).lower()
    if "connection refused" in msg or "econnrefused" in msg:
        return "OpenClaw is not running at that URL. Check `openclaw gateway status`."
    if "timeout" in msg:
        return "Connection timed out. Check firewall and port forwarding."
    if "401" in msg or "unauthorized" in msg or "invalid token" in msg:
        return "Gateway token is invalid. Regenerate it and paste the new value."
    if "handshake" in msg:
        return "Protocol version mismatch. Update OpenClaw to a compatible version."
    return "See OpenClaw logs for details."


async def _set_byo_error(request, user_id: int, error: str) -> None:
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_openclaw_config
                SET byo_last_error = $2, updated_at = NOW()
                WHERE user_id = $1
                """,
                user_id,
                error[:500],
            )
    except Exception:
        pass

