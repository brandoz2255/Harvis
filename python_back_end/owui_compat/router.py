"""OpenWebUI-compatibility facade router.

Speaks OpenWebUI's HTTP contract and translates to Harvis-native logic
in-process. Built as a factory (``create_owui_router``) that receives the Harvis
callables it reuses (dependency injection), so this package never imports
``main`` — avoiding circular imports and keeping it unit-testable.

All routes are ADDITIVE (new paths Harvis didn't expose) except ``GET
/api/models``, which the facade owns in OWUI shape (Harvis's native ``{models:
[...]}`` route was moved to ``/api/models/native`` in main.py). Register the
router via ``app.include_router(create_owui_router(deps))`` AFTER main.py's auth
helpers are defined.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt

from . import config as owui_config
from . import persistence
from .chat_completion import run_chat_completion
from .schemas import (
    OwuiChatNewBody,
    OwuiChatUpdateBody,
    OwuiSigninBody,
    OwuiSignupBody,
)
from .stubs import register_stub_routes
from .knowledge import register_knowledge_routes
from .skills import register_skill_routes
from .connections import register_connection_routes
from .integrations_status import register_integrations_status_routes
from .capabilities import register_capabilities_routes
from .engine_auth import register_engine_auth_routes
from .user_settings import register_user_settings_routes
from .orchestration_pool import register_orchestration_pool_routes
from .translate import harvis_models_to_owui, harvis_user_to_owui

logger = logging.getLogger(__name__)


@dataclass
class OwuiDeps:
    """Harvis callables/constants the facade reuses (injected by main.py)."""

    get_current_user: Callable          # FastAPI dependency → UserResponse
    list_models: Callable               # async (request, user) → {"models": [...]}
    signup_with_connection: Callable    # async (SignupRequest, conn) → TokenResponse
    signup_request_cls: type            # main.SignupRequest
    verify_password: Callable           # (plain, hashed) → bool
    create_access_token: Callable       # (data, expires_delta) → jwt str
    access_token_expire_minutes: int
    secret_key: str
    algorithm: str


def _now() -> int:
    return int(time.time())


def create_owui_router(deps: OwuiDeps) -> APIRouter:
    router = APIRouter()
    get_current_user = deps.get_current_user

    def _require_pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=500, detail="Database unavailable")
        return pool

    def _login_cookie(resp: JSONResponse, token: str) -> JSONResponse:
        resp.set_cookie(
            "access_token", token, httponly=True, samesite="lax", secure=False
        )
        return resp

    # ── boot ──────────────────────────────────────────────────────────────
    @router.get("/api/config")
    async def owui_get_config():
        return owui_config.build_config()

    @router.get("/api/version")
    async def owui_version():
        return {"version": owui_config.HARVIS_OWUI_VERSION}

    # ── auth ──────────────────────────────────────────────────────────────
    @router.post("/api/v1/auths/signin")
    async def owui_signin(payload: OwuiSigninBody, request: Request):
        pool = _require_pool(request)
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id, username, email, avatar, password FROM users WHERE email = $1",
                payload.email,
            )
        if not user or not deps.verify_password(payload.password, user["password"]):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        token = deps.create_access_token(
            {"sub": str(user["id"])},
            expires_delta=timedelta(minutes=deps.access_token_expire_minutes),
        )
        owui_user = harvis_user_to_owui(
            dict(user), token, expires_at=_now() + deps.access_token_expire_minutes * 60
        )
        return _login_cookie(JSONResponse(content=owui_user), token)

    @router.post("/api/v1/auths/signup")
    async def owui_signup(payload: OwuiSignupBody, request: Request):
        pool = _require_pool(request)
        signup_req = deps.signup_request_cls(
            username=payload.name, email=payload.email, password=payload.password
        )
        async with pool.acquire() as conn:
            token_resp = await deps.signup_with_connection(signup_req, conn)
            user = await conn.fetchrow(
                "SELECT id, username, email, avatar FROM users WHERE email = $1",
                payload.email,
            )
        token = token_resp.access_token
        owui_user = harvis_user_to_owui(
            dict(user), token, expires_at=_now() + deps.access_token_expire_minutes * 60
        )
        return _login_cookie(JSONResponse(content=owui_user), token)

    @router.get("/api/v1/auths/")
    async def owui_session(request: Request, user=Depends(get_current_user)):
        # Echo the real token + its exp so OWUI's 15s expiry poll is accurate.
        token = request.cookies.get("access_token")
        if token is None:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if auth and auth.startswith("Bearer "):
                token = auth[len("Bearer ") :]
        expires_at = None
        if token:
            try:
                claims = jwt.decode(token, deps.secret_key, algorithms=[deps.algorithm])
                expires_at = claims.get("exp")
            except JWTError:
                expires_at = None
        return harvis_user_to_owui(
            {"id": user.id, "username": user.username, "email": user.email, "avatar": user.avatar},
            token or "",
            expires_at=expires_at or (_now() + deps.access_token_expire_minutes * 60),
        )

    @router.post("/api/v1/auths/signout")
    async def owui_signout():
        resp = JSONResponse(content={})
        resp.delete_cookie("access_token")
        return resp

    # ── models ────────────────────────────────────────────────────────────
    async def _owui_models(request: Request, user):
        native = await deps.list_models(request, user)
        data = harvis_models_to_owui(native)
        # Phase E4B: surface the Hermes-Agent chat model when its engine flag is on AND the
        # sidecar API server is reachable (fail-closed). Additive — never replaces a model.
        try:
            from .hermes_chat import hermes_chat_model_entry
            _hm = await hermes_chat_model_entry()
            if _hm and not any((m or {}).get("id") == _hm["id"] for m in data):
                data.append(_hm)
        except Exception:
            pass
        # Phase F: per-user cloud chat models (Claude now, GPT later). Appear only when this user
        # has a VERIFIED cloud credential in Integrations. Fail-closed; never decrypts the secret.
        try:
            from .cloud_chat import cloud_chat_model_entries
            pool = getattr(request.app.state, "pg_pool", None)
            uid = getattr(user, "id", None)
            for _cm in await cloud_chat_model_entries(pool, uid):
                # Dedup by (id, owned_by) so a same-id native model can't silently drop a cloud
                # entry (cloud ids are anthropic/-prefixed, so this is belt-and-suspenders).
                if _cm and not any(
                    (m or {}).get("id") == _cm["id"] and (m or {}).get("owned_by") == _cm.get("owned_by")
                    for m in data
                ):
                    data.append(_cm)
        except Exception:
            pass
        return {"data": data}

    @router.get("/api/models")
    async def owui_models(request: Request, user=Depends(get_current_user)):
        return await _owui_models(request, user)

    @router.get("/api/models/base")
    async def owui_models_base(request: Request, user=Depends(get_current_user)):
        return await _owui_models(request, user)

    # ── chat completions ────────────────────────────────────────────────────
    @router.post("/api/chat/completions")
    async def owui_chat_completions(request: Request, user=Depends(get_current_user)):
        owui_body = await request.json()
        # Auto-detect workspace tasks → launch a run + return a WorkspaceRunCard
        # marker (the OWUI card attaches to /api/workspace/stream/{id}). Falls
        # through to a normal chat completion when it's not a workspace task.
        from .workspace_bridge import maybe_handle_workspace

        ws = await maybe_handle_workspace(request, owui_body, user)
        if ws is not None:
            return ws
        return await run_chat_completion(request, owui_body, user_id=user.id)

    # ── workspace approval gate (P1.5, opt-in) — resolve a parked run ────────
    @router.post("/api/owui/workspace/{workspace_id}/approve")
    async def owui_ws_approve(workspace_id: str, request: Request, user=Depends(get_current_user)):
        from .workspace_bridge import resolve_workspace_approval

        return await resolve_workspace_approval(request, workspace_id, True)

    @router.post("/api/owui/workspace/{workspace_id}/deny")
    async def owui_ws_deny(workspace_id: str, request: Request, user=Depends(get_current_user)):
        from .workspace_bridge import resolve_workspace_approval

        return await resolve_workspace_approval(request, workspace_id, False)

    @router.post("/api/chat/completed")
    async def owui_chat_completed(request: Request, user=Depends(get_current_user)):
        return {}

    @router.post("/api/chat/actions/{action_id}")
    async def owui_chat_actions(action_id: str, request: Request, user=Depends(get_current_user)):
        return {}

    @router.post("/api/v1/tasks/title/completions")
    async def owui_title(request: Request, user=Depends(get_current_user)):
        # Auto-generate a concise chat title from the conversation via the LLM
        # (a direct, isolated non-stream Ollama call — NOT the heavy chat
        # pipeline). Falls back to a trimmed first-message heuristic on ANY
        # error so chat creation never breaks. OWUI sends `messages` as a
        # STRING (rendered) for task-gen, but a list in some paths — handle both.
        import json
        import os
        import re

        import httpx

        try:
            body = await request.json()
        except Exception:
            body = {}
        msgs = body.get("messages")
        first_user = ""
        parts = []
        if isinstance(msgs, str):
            parts.append(msgs)
            first_user = msgs
        elif isinstance(msgs, list):
            for m in msgs:
                if isinstance(m, dict) and m.get("content") and m.get("role") in ("user", "assistant"):
                    c = str(m["content"])
                    parts.append(f"{m['role']}: {c}")
                    if not first_user and m.get("role") == "user":
                        first_user = c
        transcript = "\n".join(parts).strip()
        # Clean fallback = first words of the user's actual message (no "user:" prefix).
        fallback = " ".join((first_user or transcript).split()[:6]) or "New Chat"
        # OWUI's generateTitle() parses a {"title": "..."} JSON block out of the
        # content (plain text → it returns null and the title never applies), so
        # every return wraps the title in that JSON envelope.
        if not transcript:
            return {"choices": [{"message": {"content": json.dumps({"title": fallback})}}]}

        # Task-gen (title / tags / follow-ups) ALWAYS uses a small LOCAL model — NOT
        # body['model'], which can live on a remote GPU host (e.g. gemma4:12b on the
        # rig) that ollama:11434 lacks → /api/generate 404 → fallback to first message.
        model = os.getenv("HARVIS_TITLE_MODEL", "llama3.1:8b")
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        prompt = (
            "You name chat conversations. Reply with ONLY a concise, descriptive "
            "title of 3-5 words — no quotes, no 'Title:' prefix, no trailing "
            "punctuation. Summarize what the conversation is about.\n\n"
            "Conversation:\n" + transcript[:4000] + "\n\nTitle:"
        )
        title = fallback
        try:
            # Generous timeout: the model may need a one-time reload; this call is
            # fire-after-response, so the user never waits on it. NO num_ctx → reuse
            # the already-loaded context (OLLAMA_CONTEXT_LENGTH), avoiding a reload
            # — a mismatched num_ctx forces a reload and times the call out.
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as hc:
                r = await hc.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "think": False,
                        "options": {"temperature": 0.3, "num_predict": 48},
                    },
                )
                r.raise_for_status()
                raw = (r.json().get("response") or "").strip()
            # Strip any leaked <think>…</think> reasoning, then take the title line.
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            cleaned = (raw.splitlines() or [""])[0].strip().strip("\"'`").strip()
            if cleaned.lower().startswith("title:"):
                cleaned = cleaned[6:].strip().strip("\"'`").strip()
            cleaned = cleaned.rstrip(".!,").strip()
            if len(cleaned) > 60:
                cleaned = cleaned[:60].rstrip()
            if cleaned:
                title = cleaned
        except Exception:
            logger.warning("owui_compat: title generation fell back to heuristic", exc_info=True)
        return {"choices": [{"message": {"content": json.dumps({"title": title})}}]}

    # Tag / follow-up / emoji task-gen. The OWUI frontend fires these after each
    # response; wire them to a direct, isolated Ollama call (same pattern as the
    # title endpoint) so the affordances actually populate. Autocomplete + queries
    # stay no-ops (as-you-type autocomplete is noisy; queries only matter when web
    # search is enabled, which it isn't here).
    async def _task_gen(request: Request, prompt_tmpl: str, num_predict: int = 64,
                        temperature: float = 0.3) -> str:
        import os
        import re

        import httpx

        try:
            body = await request.json()
        except Exception:
            body = {}
        msgs = body.get("messages")
        parts = []
        if isinstance(msgs, str):
            parts.append(msgs)
        elif isinstance(msgs, list):
            for m in msgs:
                if isinstance(m, dict) and m.get("content") and m.get("role") in ("user", "assistant"):
                    parts.append(f"{m['role']}: {str(m['content'])}")
        transcript = "\n".join(parts).strip()
        if not transcript:
            return ""
        # Task-gen (title / tags / follow-ups) ALWAYS uses a small LOCAL model — NOT
        # body['model'], which can live on a remote GPU host (e.g. gemma4:12b on the
        # rig) that ollama:11434 lacks → /api/generate 404 → fallback to first message.
        model = os.getenv("HARVIS_TITLE_MODEL", "llama3.1:8b")
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        prompt = prompt_tmpl.replace("{transcript}", transcript[:4000])
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as hc:
                r = await hc.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False, "think": False,
                          "options": {"temperature": temperature, "num_predict": num_predict}},
                )
                r.raise_for_status()
                raw = (r.json().get("response") or "").strip()
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
        except Exception:
            logger.warning("owui_compat: task-gen failed", exc_info=True)
            return ""

    @router.post("/api/v1/tasks/tags/completions")
    async def owui_tags(request: Request, user=Depends(get_current_user)):
        import json
        import re

        raw = await _task_gen(
            request,
            "Generate 1-3 broad, lowercase tags for the main themes of this conversation. "
            'Reply with ONLY a JSON object exactly like {"tags": ["tag1", "tag2"]} and nothing else.'
            "\n\nConversation:\n{transcript}\n\nJSON:",
            num_predict=64,
        )
        if raw:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    if isinstance(obj.get("tags"), list) and obj["tags"]:
                        tags = [str(t).strip().lower() for t in obj["tags"] if str(t).strip()][:4]
                        return {"choices": [{"message": {"content": json.dumps({"tags": tags})}}]}
                except Exception:
                    pass
        return {"choices": [{"message": {"content": '{"tags": []}'}}]}

    @router.post("/api/v1/tasks/follow_ups/completions")
    async def owui_follow_ups(request: Request, user=Depends(get_current_user)):
        import json
        import re

        raw = await _task_gen(
            request,
            "Suggest 3 short, natural follow-up questions the user might ask next, based on this "
            'conversation. Reply with ONLY a JSON object exactly like {"follow_ups": ["q1?", "q2?", "q3?"]} '
            "and nothing else.\n\nConversation:\n{transcript}\n\nJSON:",
            num_predict=128,
        )
        if raw:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    if isinstance(obj.get("follow_ups"), list) and obj["follow_ups"]:
                        fu = [str(q).strip() for q in obj["follow_ups"] if str(q).strip()][:3]
                        return {"choices": [{"message": {"content": json.dumps({"follow_ups": fu})}}]}
                except Exception:
                    pass
        return {"choices": [{"message": {"content": '{"follow_ups": []}'}}]}

    @router.post("/api/v1/tasks/emoji/completions")
    async def owui_emoji(request: Request, user=Depends(get_current_user)):
        import re

        raw = await _task_gen(
            request,
            "Reply with ONLY a single emoji that best represents the topic of this conversation. "
            "No words, no explanation — just one emoji.\n\nConversation:\n{transcript}\n\nEmoji:",
            num_predict=8,
            temperature=0.5,
        )
        emoji = ""
        if raw:
            m = re.search(r"[\U0001F000-\U0001FAFF☀-➿←-⇿⬀-⯿]", raw)
            if m:
                emoji = m.group(0)
        return {"choices": [{"message": {"content": emoji}}]}

    @router.post("/api/v1/tasks/auto/completions")
    async def owui_auto_completion(request: Request, user=Depends(get_current_user)):
        # As-you-type autocomplete intentionally left off (noisy + per-keystroke cost).
        return {"choices": [{"message": {"content": ""}}]}

    @router.post("/api/v1/tasks/queries/completions")
    async def owui_queries(request: Request, user=Depends(get_current_user)):
        # Auto web-search queries only matter when web search is enabled (off here).
        return {"choices": [{"message": {"content": '{"queries": []}'}}]}

    # ── chat persistence ──────────────────────────────────────────────────
    # NOTE: static sub-paths declared BEFORE /{chat_id} so they aren't captured.
    @router.post("/api/v1/chats/new")
    async def owui_chat_new(payload: OwuiChatNewBody, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.create_chat(pool, user.id, payload.chat, payload.folder_id)

    @router.get("/api/v1/chats/")
    async def owui_chat_list(request: Request, user=Depends(get_current_user), page: int = 1):
        pool = _require_pool(request)
        page = max(1, page)
        return await persistence.list_chats(pool, user.id, limit=60, offset=(page - 1) * 60)

    @router.get("/api/v1/chats/all/tags")
    async def owui_chat_all_tags(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_all_tags(pool, user.id)

    @router.get("/api/v1/chats/pinned")
    async def owui_chat_pinned(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_pinned_chats(pool, user.id)

    @router.get("/api/v1/chats/archived")
    async def owui_chat_archived(request: Request, user=Depends(get_current_user), page: int = 1):
        pool = _require_pool(request)
        page = max(1, page)
        return await persistence.list_archived_chats(pool, user.id, limit=60, offset=(page - 1) * 60)

    @router.get("/api/v1/chats/search")
    async def owui_chat_search(
        request: Request, user=Depends(get_current_user), text: str = "", page: int = 1
    ):
        pool = _require_pool(request)
        page = max(1, page)
        if not (text or "").strip():
            return []
        return await persistence.search_chats(pool, user.id, text, limit=60, offset=(page - 1) * 60)

    @router.post("/api/v1/chats/tags")
    async def owui_chat_list_by_tag(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        name = (body.get("name") or body.get("tag_name") or "").strip()
        if not name:
            return []
        return await persistence.list_chats_by_tag(pool, user.id, name)

    # ── Folders = Projects ────────────────────────────────────────────────
    # A folder owns chats (owui_chats.folder_id) + project settings
    # (data.system_prompt = custom instructions, injected per chat). The
    # frontend folders API client (lib/apis/folders) defines this exact contract.
    @router.post("/api/v1/folders/")
    async def owui_folder_create(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        form = await request.json()
        return await persistence.create_folder(pool, user.id, form)

    @router.get("/api/v1/folders/")
    async def owui_folder_list(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_folders(pool, user.id)

    # chats-in-a-folder listing (declared before /chats/{chat_id}; static
    # 'folder' segment keeps it distinct from the parameterized chat route).
    @router.get("/api/v1/chats/folder/{folder_id}/list")
    async def owui_chats_in_folder_list(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_chats_by_folder(pool, user.id, folder_id)

    @router.get("/api/v1/chats/folder/{folder_id}")
    async def owui_chats_in_folder(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_chats_by_folder(pool, user.id, folder_id)

    @router.post("/api/v1/chats/{chat_id}/folder")
    async def owui_chat_set_folder(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        chat = await persistence.update_chat_folder_id(pool, user.id, chat_id, body.get("folder_id"))
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.post("/api/v1/chats/{chat_id}/pin")
    async def owui_chat_toggle_pin(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        chat = await persistence.toggle_chat_pinned(pool, user.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.get("/api/v1/chats/{chat_id}/pinned")
    async def owui_chat_pin_status(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        chat = await persistence.get_chat(pool, user.id, chat_id)
        return bool(chat and chat.get("pinned"))

    @router.post("/api/v1/chats/{chat_id}/archive")
    async def owui_chat_toggle_archive(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        chat = await persistence.toggle_chat_archived(pool, user.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    # ── per-chat tags (real; supersede the stubs in stubs.py) ─────────────────
    @router.get("/api/v1/chats/{chat_id}/tags")
    async def owui_chat_tags_get(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.get_chat_tags(pool, user.id, chat_id)

    @router.post("/api/v1/chats/{chat_id}/tags")
    async def owui_chat_tags_add(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        name = (body.get("name") or body.get("tag_name") or "").strip()
        return await persistence.add_chat_tag(pool, user.id, chat_id, name)

    @router.delete("/api/v1/chats/{chat_id}/tags/all")
    async def owui_chat_tags_clear(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.clear_chat_tags(pool, user.id, chat_id)

    @router.delete("/api/v1/chats/{chat_id}/tags")
    async def owui_chat_tags_delete(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        name = (body.get("name") or body.get("tag_name") or "").strip()
        return await persistence.remove_chat_tag(pool, user.id, chat_id, name)

    @router.get("/api/v1/folders/{folder_id}")
    async def owui_folder_get(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        folder = await persistence.get_folder(pool, user.id, folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update")
    async def owui_folder_update(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        form = await request.json()
        folder = await persistence.update_folder(pool, user.id, folder_id, form)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update/expanded")
    async def owui_folder_expanded(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        folder = await persistence.update_folder_expanded(pool, user.id, folder_id, bool(body.get("is_expanded")))
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update/parent")
    async def owui_folder_parent(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        folder = await persistence.update_folder_parent(pool, user.id, folder_id, body.get("parent_id"))
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update/items")
    async def owui_folder_items(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        folder = await persistence.update_folder_items(pool, user.id, folder_id, body.get("items") or {})
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.delete("/api/v1/folders/{folder_id}")
    async def owui_folder_delete(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        delete_contents = (request.query_params.get("delete_contents") or "").lower() == "true"
        return await persistence.delete_folder(pool, user.id, folder_id, delete_contents)

    # ── model comparison runs (Agent Studio Comparison surface → Analytics) ──
    @router.post("/api/owui/comparisons")
    async def owui_comparison_save(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        n = await persistence.save_comparison(
            pool, user.id,
            str(body.get("run_id") or ""),
            str(body.get("prompt") or ""),
            body.get("results") or [],
        )
        return {"saved": n}

    @router.post("/api/owui/comparisons/judge")
    async def owui_comparison_judge(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        n = await persistence.save_comparison_judge(
            pool, user.id,
            str(body.get("run_id") or ""),
            str(body.get("judge_model") or ""),
            body.get("scores") or {},
        )
        return {"updated": n}

    @router.get("/api/owui/comparisons")
    async def owui_comparison_list(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        try:
            limit = int(request.query_params.get("limit", 300))
        except (TypeError, ValueError):
            limit = 300
        runs = await persistence.list_comparisons(pool, user.id, limit=max(1, min(limit, 1000)))
        stats = await persistence.comparison_stats(pool, user.id)
        return {"runs": runs, "stats": stats}

    # Stub v1 routes (settings, tools, tags, profile images, …) — must be
    # registered before parameterized chat routes where paths overlap.
    register_stub_routes(router, get_current_user)
    register_knowledge_routes(router, get_current_user)
    register_skill_routes(router, get_current_user)
    register_connection_routes(router, get_current_user)
    register_integrations_status_routes(router, get_current_user)
    register_capabilities_routes(router, get_current_user)
    register_engine_auth_routes(router, get_current_user)
    register_user_settings_routes(router, get_current_user)
    register_orchestration_pool_routes(router, get_current_user)

    @router.get("/api/v1/chats/{chat_id}")
    async def owui_chat_get(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        chat = await persistence.get_chat(pool, user.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.post("/api/v1/chats/{chat_id}")
    async def owui_chat_update(
        chat_id: str, payload: OwuiChatUpdateBody, request: Request, user=Depends(get_current_user)
    ):
        pool = _require_pool(request)
        chat = await persistence.update_chat(pool, user.id, chat_id, payload.chat)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.delete("/api/v1/chats/{chat_id}")
    async def owui_chat_delete(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        await persistence.delete_chat(pool, user.id, chat_id)
        return True

    return router
