# Handoff — OpenWebUI frontend on Harvis backend (owui_compat facade)

**Date:** 2026-05-31
**Branch:** `claude/serene-driscoll-79137f` (fast-forwarded to `feat/hermes-integration` tip `11f9fd1`)
**Plan:** `~/.claude/plans/noble-noodling-pnueli.md` (top section, APPROVED)

## Goal
Run a forked **OpenWebUI v0.9.5** frontend against Harvis's **existing** FastAPI backend (not OWUI's own), so OWUI replaces `newjfrontend`. Decisions: streaming = **Option A** (patch frontend to HTTP-SSE, no Socket.IO); newjfrontend = **replace** (don't preserve it as a constraint); fork lives at **`front_end/owui/`** (monorepo subdir).

## State — DONE + statically verified
**Backend facade** (all in worktree, on bind-mounted/COPY'd paths):
- `workspace/model_proxy.py`: extracted `execute_chat_completion(request, body)`; `proxy_chat_completions` is now a 3-line shim (verified no `authorization`/`request.` refs in moved code).
- `main.py`: native `/api/models` → `/api/models/native`; facade registered via DI factory after auth helpers (~line 2403); `owui_chats` CREATE TABLE in lifespan (after `workspace_web_caps`).
- New `python_back_end/owui_compat/` (7 files): config, schemas, translate, persistence (owui_chats JSONB CRUD), chat_completion (in-process model_proxy reuse), router (factory), __init__.
- Verified: all files `ast.parse` OK; `owui_compat` imports clean in a venv (fastapi+jose); factory registers **18 routes**; `Dockerfile COPY . .` (line 95) bakes owui_compat into the image on rebuild.

**OWUI fork**:
- Vendored v0.9.5 into `front_end/owui/` (copied from /tmp/owui-recon, `.git` stripped).
- Streaming patch applied to `front_end/owui/src/lib/components/chat/Chat.svelte`: import `chatCompletion` (replaces `generateOpenAIChatCompletion`); `sendMessageSocket` now does `const [res, controller] = await chatCompletion(...)`, consumes `res.body` via `createOpenAITextStream`, reshapes each chunk into the `data` shape and calls the existing `chatCompletionEventHandler(data, responseMessage, _chatId)`; stop via `generationController.abort()`. NOT yet build-verified.

## Remaining (tasks #46–#48)
1. **Branding → Harvis** (#46): `constants.ts` APP_NAME, `app.html` title, `static/` assets, `manifest.json`, `opensearch.xml`, scripted i18n replace (~64 `translation.json`), About/General links, `harvis-dark` theme.
2. **Build** (#47): `cd front_end/owui && npm install && npm run build` — first real compile-check of the Svelte patch + branding; fix any errors.
3. **Nginx + E2E** (#48): serve `front_end/owui/build` at Nginx root (replaces newjfrontend); get worktree changes into the build context; coordinated backend rebuild (interrupts live stack — user-gated) + full E2E (boot/config no-socket, signup→admin, models, SSE stream, persist+reload).

## Key facts / gotchas
- Live stack is up (2 days) from the **main repo**; backend bind-mounts `main.py`/`workspace/`/etc. but **NOT** `owui_compat` (new dir) → needs image rebuild to appear in the container.
- OWUI v0.9.5 normal chat is Socket.IO-push; `chatCompletionEventHandler` consumes OpenAI-chunk-shaped `data`, which is why Option A (feed it from `createOpenAITextStream`) is clean.
- `main` is 30+ commits behind `feat/hermes-integration` (model_proxy 502 vs 1854 lines) — build on hermes.
- Nothing committed/pushed (per standing rule). No live-stack changes made.

## Failed/avoided approaches
- Stacking `@app.get("/api/models")` + `/native` decorators — the early app-level route would shadow the late facade route. Removed the bare decorator; facade owns `/api/models`.
