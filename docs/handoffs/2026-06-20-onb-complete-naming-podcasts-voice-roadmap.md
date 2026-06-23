# Handoff — Open Notebook completed (naming v2, podcasts) + ops fixes + post-onb roadmap

**Date:** 2026-06-20 · **Branch:** `harvis1.1` (everything below UNCOMMITTED, not pushed — standing rule)
**Verify env:** Pop!_OS laptop at `http://localhost:9000` (NOT the Windows rig)
**View Open Notebook via** `:9000/harvis/notebooks` (iframe inside the Harvis shell) — NOT the bare `/onb/...` zoom (user dislikes that).

---

## Goal
Finish the **Open Notebook** surface (vendored `lfnovo/open-notebook` Next app at `front_end/open-notebook`, served `:9000/onb`, backed by the Python `onb_compat` facade at `/onb-api`). Then verify the main Harvis chat still works, audit onb for completeness, and capture the next-phase roadmap (podcast voice fix → VibeCode → background workspace → UI).

## End state
**Open Notebook is functionally COMPLETE + browser-verified.** The only real open item is **podcast voice quality** (see roadmap). Everything is uncommitted on `harvis1.1`.

---

## What shipped this session

### A. The four remaining onb features (built + verified live)
1. **Autoname** — "+ New Notebook" creates instantly (no name prompt) and drops into the empty notebook. When the first source finishes ingesting, the AI generates a **broad-scope title + emoji + 3-5 sentence synopsis** in one Ollama call (`POST /onb-api/notebooks/{id}/autoname`, granite4.1:8b→llama3.1:8b→gemma4:e4b fallback). The synopsis is persisted to `notebooks.description` (reused existing column, no schema change).
2. **Inline citation + URL-sync** — clicking a chat citation chip opens the source **inline in the left column** (not an overlay) with the cited passage **highlighted**; state lives in the URL (`?source=&highlight=&claim=`), surviving refresh/back/deep-link.
3. **Ask & Search** — `POST /onb-api/search` (cross-notebook pgvector cosine, parent-grouped, ILIKE fallback) + `POST /onb-api/search/ask` (`StreamingResponse` SSE: strategy → per-search answers → synthesis). Verified: 7 scored results; Strategy + 2 Individual Answers + Final Answer.
4. **Podcasts** — NEW `onb_compat/podcasts.py` (2nd `/onb-api` router, registered in `main.py`): built-in episode/speaker/language profiles (no amber "setup" banner; profile CRUD = 501), generate → `standalone_podcasts` row + BackgroundTask → `PodcastGenerator` → `tts-service` → audio; list/delete/retry; tts-audio proxy. **Verified: 3 episodes completed with real 24 MB / ~250 s .wav that plays in the UI.**

### B. Naming v2 + synopsis + chat overview card
- Autoname now produces a **broad descriptive title** (NotebookLM-style, e.g. "The Evolution of Personal Transportation: From the Bicycle to the Automobile…", not a 2-4-word label; cap 140, `num_predict` 400) PLUS the synopsis.
- It **re-evaluates as sources are added** so the name/scope broadens to cover all of them. Loop-guarded by a **localStorage `onb:autoname:<id>` = {count,title}** marker: only re-names when the ready-source count grew, survives remount, freezes once the user renames manually. Verified: bicycle → "…Bicycles to Modern Mobility" 🚲, +automobile → broadened to "…Bicycle to the Automobile…" 🚲🚗; exactly 2 autoname calls (no loop), GPU idle after.
- **Chat overview card** replaces the empty-state "Start a conversation…": big emoji + AI title + "N sources · date" + synopsis paragraph (shown when `contextType==='notebook' && sourceCount>0`).

### C. UI polish (notebooks hub)
- **Title truncation fix** — long auto-titles were overflowing into neighbor cards. Root cause: the title's wrapper is a child of `CardHeader` which is a CSS **grid** (grid items default `min-width:auto`, can't shrink). Fix: `min-w-0` on the grid item + name in its own `truncate` span with the emoji as a non-shrinking sibling.
- **Cube cards** — 3-col grid → `xl:grid-cols-4`, `min-h-[260px]` flex cards, date/counts pinned to the bottom (`mt-auto`), synopsis `line-clamp-4`. Squarish tiles instead of thin rectangles.
- **Removed the notebook-detail header band** — the top title + full synopsis + timestamps duplicated the chat overview card; removed the `NotebookHeader` mount + import from `[id]/page.tsx`. (Archive/Delete still available via each hub card's ⋯ menu.)

### D. Ops / verification fixes
- **Killed an Ollama runaway** — a stuck "Music video - Wikipedia" source ingestion (78 K chars, 0 chunks, ~8 min) pegged the GPU at 96% and hammered `/api/embeddings`. Marked the source `error`, restarted backend, unloaded the pinned model → GPU 96%→6%, embeddings → 0.
- **Main Harvis chat regression check** — passed. `qwen3.5-9b` (the prior default) returns **`400 Bad Request`** from the laptop Ollama (model-specific, not the chat path). Unloaded it, switched to **gemma4:12b** (rig 5080) → chat streams correctly; clicked "Set as default" ("Default model updated" toast) — but it **did not persist across a later reload** (open follow-up).

### E. Fixes found *during* verification (all in onb)
1. **Ask/source-chat SSE 404** — `search.ts` + `source-chat.ts` raw `fetch` hardcoded `/api/...` (skipped the `/onb` basePath) + read `auth-storage` not `localStorage.token`. Fixed: `${await getApiUrl()}/api/...` + prefer `localStorage.token`. *Pattern: every raw fetch in vendored onb must prefix `getApiUrl()` + use `localStorage.token`.*
2. **Search NaN 500** — degenerate-embedding cosine can be NaN/Inf → FastAPI strict-JSON rejects. Fixed: `math.isfinite` guard → 0.0 in `_search_user_chunks`.
3. **`standalone_podcasts` table missing** — migrations 006+007 were never applied to this DB; applied (idempotent).
4. **Podcast froze the whole backend loop** — `open_notebook/podcast/script.py:_call_llm` used blocking `requests.post`. Fixed: `await asyncio.to_thread(lambda: requests.post(...))`. **GOTCHA: `open_notebook/` was baked into the image, NOT bind-mounted** (unlike every other `python_back_end` subdir) → host edit invisible until I added `./python_back_end/open_notebook:/app/open_notebook:ro` to `docker-compose.yaml` backend volumes. Probes 2-8 ms during generation (was 30 s-timeout).
5. **Podcast audio_url unreachable** — facade emitted `/onb-api/podcasts/tts-audio/X`; `resolvePodcastAssetUrl` does `getApiUrl()`(/onb)+path → `/onb/onb-api/...` (404). Fixed: emit `/api/podcasts/tts-audio/X` → `/onb/api/...` → nginx rewrite → proxy. `_episode_to_onb` rewrites on list so existing rows are corrected too.
6. **Autoname quality** — feed source **content excerpts** (`content_text[:240]` per `source[:6]`), not just titles; generic "Pasted text" went from "Text Extraction Repository" → "Tomato Cultivation Guide 🍅".

---

## Files touched (all uncommitted)
**Whole NEW untracked dirs:** `front_end/open-notebook/` (the vendored app + all our edits) · `python_back_end/onb_compat/` (`router.py` + NEW `podcasts.py`).
**Modified (tracked):**
- `docker-compose.yaml` — added `./python_back_end/open_notebook:/app/open_notebook:ro` to the backend volumes.
- `python_back_end/open_notebook/podcast/script.py` — `_call_llm` `requests.post` → `asyncio.to_thread`.
- `python_back_end/main.py` — registers `onb_compat.podcasts` router (in the new onb_compat block).

**Key onb files edited this session (inside the untracked dirs):**
- Backend `onb_compat/router.py`: autoname v2 (broad title + emoji + synopsis, content-aware, persist to description) · Ask `/search` + `/search/ask` (+`StreamingResponse`, `IngestionService` imports) · NaN guard · Settings/Models slice (prior).
- Backend `onb_compat/podcasts.py`: NEW — full podcast facade; audio_url `/api/...` prefix fix.
- Frontend `[id]/page.tsx`: autoname re-name effect (localStorage guard) · openSource URL-sync · `notebook` prop threading · header band removed.
- Frontend `components/source/ChatPanel.tsx`: overview card + `onOpenSource` citation branch + `notebook`/`sourceCount` props.
- Frontend `components/ChatColumn.tsx`: thread `notebook`/`sourceCount`/`onOpenSource`.
- Frontend `notebooks/components/NotebookCard.tsx`: title truncation fix + cube-card layout.
- Frontend `notebooks/components/NotebookList.tsx`: 4-col grid.
- Frontend `lib/api/{notebooks,search,source-chat,podcasts}.ts`: basePath/token fixes + autoname return type.

DB migrations applied to the live DB (idempotent): `migrations/006_create_standalone_podcasts.sql` + `007_alter_standalone_podcasts_add_speakers.sql`.

---

## Deploy commands (this stack)
- **Backend** (bind-mounted): `docker restart harvis-backend`. For a docker-compose VOLUME change: `docker compose up -d --no-deps backend`.
- **Open Notebook frontend** (baked into image): `docker compose build open-notebook-ui && docker compose up -d --no-deps open-notebook-ui`.
- Syntax-check Python before restart; check logs for `✅ onb_compat facade mounted` + `✅ onb_compat podcasts mounted`.

---

## Completeness audit (2026-06-20) — onb is COMPLETE
3-agent audit (frontend api/*.ts ↔ onb_compat backend). Every UI-exposed surface works: Notebooks (hub + detail + autoname v2 + overview card + citation + cube cards), Sources, Notes, notebook Chat (sessions + RAG + citations), Transformations, Insights, Settings, Models, Ask & Search, Podcasts (16 routes in `podcasts.py`).
**Not gaps:** Credentials → 501 by design (local-Ollama only). **Latent/unwired** (client method exists but imported by NO page → 0 user impact): source-level chat `/sources/{id}/chat/*` (`source-chat.ts` is dead code), embeddings-rebuild `/embed` + `/embeddings/rebuild`, source `downloadFile`. Implement only if surfaced.

---

## Open items / next-phase roadmap (user-sequenced)
See memory `project_post_onb_roadmap.md`.
1. **🎙️ Podcast VOICE fix (user's #1) — "rip it out and adjust for a better voice."** Pipeline works but the voice is robotic: the `tts-service` container reports `engine_type: speecht5` (its `/health`). The facade asks for `voice_model='chatterbox'` (`podcasts.py:53`, `open_notebook/podcast/audio.py:17` TTS_PROVIDER) but the running engine is SpeechT5, and both speakers map to one `'__default__'` voice. **The real lever is the tts-service engine.** Options cheap→best: tune `PODCAST_TTS_CFG_SCALE`/`TEMPERATURE` (`audio.py:19-20`) → wire up real Chatterbox → **rip/replace** the engine (Kokoro-82M / XTTS-v2 / Piper) → Host vs Guest distinct voices (needs unlocking the 501 speaker-profile CRUD + a voice picker). This service also powers the main app's TTS (S4) + the native podcast route — fixing the engine fixes everything.
2. **💻 VibeCode IDE revival** — backend exists (PTY `/ws/vibecoding/terminal` + editor + AI assistant); `/harvis/vibecode` page is a ~19-line stub. See memory `project_vibecode_stranded`.
3. **⚙️ Background-task agent workspace** — finish the orchestration/scheduled-run surface (`project_p5_orchestration_spike`, `project_first_push_next` — Automations Phase 2/3).
4. **🎨 More UI** — TBD.

### Smaller open follow-ups
- **gemma4:12b default didn't persist** across reload (reverts to qwen3.5-9b which 400s) — investigate the OWUI default-model persistence + why qwen3.5-9b returns 400 from the laptop Ollama (likely `num_ctx=24576` too large for that model, or a param-shape mismatch).
- Multi-source autoname emoji can be 2 glyphs (🚲🚗) — model returns both; cap `[:8]`. Reads intentional; clamp to one only if asked.
- `NotebookHeader.tsx` is now dead (unused) — safe to delete later.

## Standing rules
Branch `harvis1.1`; **no push/commit until the user says go** (onb is large untracked + the harvis1.1 pile is ~15 ahead unpushed). Build/verify on the laptop `:9000`. View onb via `/harvis/notebooks`. Never fabricate (Drive = honest "not available"). iframe sandbox never `allow-same-origin`; SSRF private-IP blocking always on.
