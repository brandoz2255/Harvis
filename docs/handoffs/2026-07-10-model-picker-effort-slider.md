# Handoff — Model picker, real-time catalog, per-model effort slider (2026-07-10)

**Branch:** `harvis1.1` (main tree `/home/ommblitz/Projects/Recent-EX/Harvis`). **Nothing committed or pushed** —
all changes are local/uncommitted, on top of the unpushed Exec-Core v0/v1 work. Hold per user rule (no push until
they verify E2E).

**Deploy loop:** backend files are bind-mounted → `docker restart harvis-backend`. Frontend → `npm run build` in
`front_end/owui` (`NODE_OPTIONS=--max-old-space-size=8192`) → `docker restart nginx-proxy`. Access at
`http://localhost:9000`. Test user = user 2 (`cisco`), has a verified Claude **subscription oauth** credential.

## Goal
Give Harvis a real-time Claude model catalog + a Cursor-style chat model picker with per-model reasoning-effort
control, plus fix the Integrations "Connected vs Unavailable" honesty bug. Driven by the user iterating on the
composer UI over several turns.

## SHIPPED this session (all live-verified in the browser)

1. **Integrations status fix** — Claude Code card was falsely "Unavailable" despite a verified credential. Now the
   card reflects usability (Connected) while the Build selector stays honest (only offers build-ready engines).
   Files: `owui_compat/integrations_status.py`, `owui_compat/capabilities.py`,
   `front_end/owui/.../integrations/status.ts`, `.../harvis/integrations/+page.svelte`.

2. **Real-time Claude catalog** — `owui_compat/cloud_chat.py` fetches Claude models LIVE from Anthropic
   `GET /v1/models` (subscription OAuth works via `Authorization: Bearer`; API keys via `x-api-key`), cached per
   `"<uid>:<mode>"` (300s positive / 60s negative TTL, decrypts only on miss, authoritative auth_mode). Merged with
   `_CLAUDE_META` (name/ctx/price/max_thinking). Dynamic prefix routing (`is_cloud_chat_model`/`_provider_of` use the
   `anthropic/` prefix). Static fallback if the fetch fails. Default model = `anthropic/claude-sonnet-5`. The 4
   flagship (`_CLAUDE_PRIMARY` = opus-4-8, sonnet-5, fable-5, haiku-4-5) carry `meta.primary`.

3. **Per-model profiles** — new `owui_compat/model_profiles.py`: `owui_model_profiles` table (PK user_id,model_id) +
   `GET/PUT/DELETE /api/owui/model-profiles` (registered in `owui_compat/router.py`). PUT is a **partial merge**
   (effort-only save preserves budget/name). Validation: effort∈{low,med,high,max}, budget 0..200000, name≤60,
   model_id must be cloud + ≤128 chars. `cloud_chat.cloud_chat_model_entries` overlays profiles (name override +
   `meta.profile_effort`/`profile_thinking_budget`); `proxy_cloud_chat` uses profile effort as the default.

4. **Cursor-style composer picker** (`front_end/owui/.../chat/MessageInput.svelte` — the dropdown users actually see,
   NOT the navbar Selector): search field, an **Auto toggle** (wired to `chatMode`), the **4 flagship Claude models
   only** by default, a persisted **"Show all Claude models"** toggle (`settings.showAllCloudModels`), and a model
   Edit modal (`ModelSelector/ModelProfileEditor.svelte`). API client: `lib/apis/model-profiles/index.ts`.

5. **Effort slider** (`ModelSelector/EffortSlider.svelte`) — the Cursor "Effort" panel: **Faster ⟷ Smarter** textured
   slider + white draggable thumb, 4 stops. Rendered as a **Dropdown popover ABOVE** the composer effort button
   (`side="top"`, no modal, no dimming). The composer's old "💡 Auto" lightbulb pill was replaced by a compact button
   showing just the current model's level (e.g. "Max") — whatever the slider lands on = the button label. Shown only
   for effort-capable Claude models. Drag → saves profile effort (partial) → label updates live.

6. **Verify fixes** (from a Fable-5 adversarial pass): reverted the broken navbar picker changes
   (`ModelSelector/ModelItem.svelte` + `Selector.svelte` are back to STOCK — their Edit modal was destroyed on click);
   removed a **credential-preview log leak** in `main.py` `encrypt/decrypt_api_key` (was logging plaintext key
   preview + length at INFO — also the source of the earlier `Failed to decrypt` log noise); model_id length cap;
   negative cache; display-name clobber guard (`nameTouched` in ModelProfileEditor).

Also earlier this session: diagnosed OpenClaw "Error" (= `.env` `OPENCLAW_URL=ws://192.168.20.58:18789` points at an
intentional remote box that's firewalled on :18789 — remote-side fix, NOT a Harvis bug) + the "no verified
credential" chat error (stale pre-verification timing; subscription chat works). See memory
`project_openclaw_remote_and_cred_timing.md`.

## Earlier this session — COMMITTED locally (harvis1.1 is **23 commits ahead of origin/harvis1.1**, all unpushed)
The model-picker work below sits on TOP of a large committed stack. Don't lose these:
- **Build-narrator chat-mode fix** (`bbca517c`) — a regular-chat build result is now a simple "Created X" + auto-preview,
  NOT a repo/PR narrative. Fixes the "acting like Build in normal chat" report. `workspace/build_narrator.py` (COMMITTED,
  not in-flight).
- **Exec Core v1 — the "Judgment Layer"** (Phases A–I), committed checkpoints:
  B=`fbc9771b` (honest trace events artifact/search_trace/final_message) · C1+C2=`94c47ed1` (skill-audit governance:
  verdict-gated injection + audit UI) · D=`860ce786` (offer-time tool policy + heavy-tool withholding on auto-runs) ·
  E1=`c16cceb1` (background job runtime) · E2=`e45cf1a2` (job persistence + reconnect + process artifacts) ·
  E2-reattach-fix=`b9c725ac` · F=`1d40607a` (run→skill extraction, verdict-gated draft) · G/H/I=`f3f88728` (honest
  readiness + provider catalog). Full detail + invariants: memory `project_execution_core_v1_plan.md`.
- Builds on **Exec Core v0** (Phases 0–5, `e2f36dab`→`ebf8d885`), repo-runner adaptive runtime (`ae3f73d0`), and
  Adaptive Space (`b0963d3a` and earlier) — all committed locally in prior sessions.
- **OPEN from Exec Core v1**: verify the Phase-D cloud-Claude `--disallowedTools` flag spelling on a connected account;
  BYO-mode auto-runs still reach github/kubectl/exec (verify_capability is token-based, orthogonal to launch_mode); D's
  full auto-escalation path not E2E-tested; Fable maxed at E2 so E2-fix/F/G/H/I were built + reviewed SOLO.

## Files in flight (uncommitted, main tree)
- Backend: `owui_compat/{cloud_chat,model_profiles,router,integrations_status,capabilities}.py`, `main.py`
  (credential-log fix).
- Frontend NEW: `ModelSelector/EffortSlider.svelte`, `ModelSelector/ModelProfileEditor.svelte`,
  `lib/apis/model-profiles/index.ts`.
- Frontend EDITED: `chat/MessageInput.svelte`, `integrations/status.ts`, `harvis/integrations/+page.svelte`.
- Frontend REVERTED to stock: `ModelSelector/ModelItem.svelte`, `ModelSelector/Selector.svelte`.
- ⚠ **Orphaned:** `ModelSelector/EffortBar.svelte` (old segmented-pips component, no longer imported) — delete on cleanup.

## RESOLVED next session (2026-07-10, later) — all three pending items closed
1. ✅ **"Show all Claude models" moved to Settings → Interface** (Switch after "Web Search in Chat", same persisted
   `settings.showAllCloudModels`); the in-dropdown row + `hasLegacyClaude`/`toggleShowAllClaude` removed from
   MessageInput. Verified live: toggle round-trips (on → legacy Claude models appear in the picker).
2. ✅→❌ **Auto model routing: built, verified, then REMOVED at the user's request.** A tier router
   (`owui_compat/auto_model.py`: light→keep-local/Haiku, standard→Sonnet 5, heavy→Opus 4.8, Fable structurally
   excluded, OpenAI untouched, credential-gated) passed all 8 routing cases — then the user chose strictly
   **selection-based** model choice. The router file was deleted, the hook removed (a NOTE comment marks the spot in
   `chat_completion.py::run_chat_completion`), and the Auto toggle removed from the picker dropdown. The mode pill
   next to Send (Auto/Chat/Agent → workspace escalation) is untouched. Also deleted the orphaned `EffortBar.svelte`.
3. ✅ **E2E verified** — and it caught a REAL bug: on the subscription chat path, `claude -p` was WRITING the HTML to
   the sidecar's /tmp (user can never see it; no preview). FIX: `_proxy_claude_cli` now passes
   `--disallowedTools "Bash,Edit,Write,MultiEdit,NotebookEdit"` — chat answers come INLINE, the artifact preview
   auto-opens. Re-tested live: Sonnet 5 (subscription) → conversational reply + full HTML + rendered preview panel.
   **Bonus: this VERIFIED the `--disallowedTools` flag spelling against the real sidecar CLI** (`--disallowedTools,
   --disallowed-tools` in `claude --help`) — closing the open Phase-D question.

## Sandbox file preview (2026-07-10, later) — SHIPPED + live-verified
User ask: "the AI should show what it made; make the path clickable to pull up the preview — but the
file is dockerized, not on my machine, so 'open in a browser' makes no sense; keep it in the container
but accurate + functional." Delivered:
- **Subscription chat now runs in a PER-USER / PER-RUN sandbox dir** in the sidecar
  (`/tmp/harvis-chat/u<uid>/<run_id>`, `cloud_chat._proxy_claude_cli` — threaded `user_id`,
  `--allowedTools "Read,Write,Edit,MultiEdit"` (no Bash/web), `--append-system-prompt` telling it it's
  a dockerized sandbox: save files with a short name + state the FULL path, Harvis previews it, NEVER
  say "open in a browser"). A preview footer lists any created files it didn't already name.
- **`owui_compat/chat_files.py`** (NEW) — `GET /api/owui/chat-file?path=…` reads a file back OUT of the
  sidecar (via `docker exec head -c`), STRICTLY sandboxed: path must resolve (server-side normpath)
  under the REQUESTER's own `/tmp/harvis-chat/u<their-id>/` (verified: own OK; cross-user / `..` traversal /
  escape all 404), 2 MB cap, text/renderable only (images → data URL). Registered in router.py.
- **Frontend**: `Messages/SandboxPreview.svelte` (NEW, a Modal that fetches + renders: HTML/SVG in a
  sandboxed `<iframe srcdoc sandbox="allow-scripts">`, images inline, else `<pre>`). `ContentRenderer.svelte`
  linkifies `/tmp/harvis-chat/u\d+/…` paths (a **MutationObserver** — afterUpdate misses the codespan which
  a child renders async) and intercepts the click in the **capture phase** (so it previews instead of the
  codespan's copy-on-click). Fast-path guard skips the DOM walk when no sandbox path is present.
- Verified live: Sonnet 5 (subscription) → concise reply + clickable path → click opens the rendered
  Summit Rentals page, footer "rendered from the sandbox — not saved to your machine".
- **Update:** the click now opens the preview in the **right-side Artifacts rail** (not a centered modal)
  by pushing the fetched content into `artifactContents` + `showArtifacts` (same panel as inline HTML
  previews); the `SandboxPreview.svelte` modal is kept only as the mobile fallback. `ContentRenderer`
  imports `artifactContents`; `buildSandboxArtifact()` maps html→iframe / svg→svg / image→img / text→pre.

## Image generation (local) — PLAN ONLY, not started
Design doc: `docs/plans/image-generation-v0.md`. Recommendation: ComfyUI primary + A1111 fallback behind
one `ImageProvider` interface; v0 reuses jobs (E1) + artifacts (E2) + trace + provider readiness + skill
extraction (F) + today's right-rail preview. **Blocked:** no provider installed (`:8188`/`:7860` closed;
GPU = RTX 5070 Laptop 8 GB). User chose "just plan for now" — provider-install decision deferred.

## Remaining open items
- BYO-mode auto-runs still reach github/kubectl/exec via token-based verify_capability (Exec Core v1 residual).
- Phase D's full auto-escalation path: partially observed live (detector → OpenClaw + Auto chips on the run card);
  the local-model run itself was slow/flaky (qwen3.5-9b empty-response retries) — engine quality, not the lane.
- Roadmap next (user's plan): stabilize chat/engine behavior → Dev Console v0 → Discord v0 hardening.

## Verify status
Effort slider, catalog, profiles, 4-model limit, and the Integrations fix are all live-verified in the browser +
against the DB. The Fable-5 adversarial pass ran; its real findings are fixed (see #6). No further adversarial pass
run after the effort-slider popover refactor — worth one before the eventual commit.
