# Handoff — owui UI overhaul (2026-07-17, EOD)

> Continues `2026-07-17-eod-launcher-prototype-tomorrow-list.md`. That day was the isolated
> React **prototype** (`front_end/harvis-ui-prototype`, :5180). **This** session took that
> direction and shipped it into the **real** owui app + several new surfaces. All local,
> **nothing pushed** (standing rule: no push until user verifies E2E, then ASK).

## Goal

Bring the prototype's calm launcher look into the real Harvis frontend (`front_end/owui`,
forked OpenWebUI SvelteKit), unify the sidebars, and build out Skills management — all on the
**blue** default accent, token-only (Warm/Airy/Midnight inherit), Fable-5 subagents for the build.

## Standing constraints (unchanged)

- Work on `harvis1.1` in the MAIN tree `/home/user/Harvis` (session cwd is
  a STALE worktree — edit via main-tree absolute paths only).
- **Blue = default accent** (user-locked). Token-only; no raw hex in components; no coral/violet/sky.
- **Use Fable-5 subagents for build work** (`model:'fable'` in Workflow) — build→verify.
- **No push until user verifies E2E**, then ASK first. Nothing pushed all session.
- Deploy: owui = `npm --prefix front_end/owui run build` → `docker restart nginx-proxy`;
  notebook = `docker compose -f docker-compose.yaml up -d --no-deps --force-recreate --build open-notebook-ui`
  (the `--no-deps` is REQUIRED — a plain `up` reconciles the whole project because docker-compose.yaml
  has uncommitted drift, and hit a zombie-ollama recreate).
- Test model = gemma/qwen local. Verify live at `:9000` via the claude-in-chrome extension
  (flaky this session — dropped/froze several times; recovered on retry).

## What shipped this session (all built, deployed, E2E-eyeballed unless noted)

1. **Launcher merged into the owui home** — `chat/Placeholder.svelte`: mascot hero + greeting,
   **connect-tools shadow tray** (6 brand marks, attached under the composer), **explore-ideas**
   chip row (6 longer prototype ideas + scroll arrow), **capabilities carousel** pinned to the
   bottom via a full-height grid. Faithful re-copy of the prototype after a first approximation was
   rejected ("just copy the prototype"). Glow re-centered behind the mascot.
2. **Chat / Notebook / Build sidebars → one blue recipe** — `layout/Sidebar*`: blue "New…" rows,
   blue active mode pill, blue live-dots, route-active blue-tint / list-selection neutral,
   one hover shade, `rounded-xl`, `gap-3`.
3. **Notebook theme → blue + adapts per theme** — `front_end/open-notebook/src/app/globals.css`
   + theme-script/ThemeProvider: `:root`/`.dark` = owui light/Midnight blue; `data-nb-theme="warm|airy"`
   variants. (Gotcha that cost a rebuild: a `*/` inside a CSS comment — `gray-*/blue-*` — closed the
   comment early and broke the Next build.)
4. **Sidebar bottom-nav cluster** — Cookbook · Providers · **Customize** · Settings · More; fade-mask
   on long names (no more "…"); "Local stack ready" removed; **More flyout opens upward**; Customize
   took the Skills pill's spot and opens the Skills manager in Settings.
5. **Chat identity** — assistant messages show the **HARVIS wordmark** (reuses `.harvis-wordmark`),
   real model on hover. (Multi-model compare columns all read HARVIS — flagged.)
6. **Skills manager** — `chat/Settings/Skills/{SkillsManager,SkillDetail}.svelte`, in Settings →
   Customize → Skills: real table (Skill/Last updated/Author + governance pills), search, Add menu
   ("Create with Harvis" / Write instructions / Upload .md|.json), in-panel detail (enable toggle,
   3-dot audit/verdict/export/delete, SKILL.md Rendered|Source viewer). Governance fail-closed.
7. **Skills Browse + multi-source import** — `chat/Settings/Skills/{SkillsBrowse,SkillsBrowseSection}.svelte`:
   [Collections | From GitHub or URL]. 5 real GitHub seeds (Anthropic/Block/HuggingFace/Microsoft/NVIDIA)
   browsed **client-side** (api.github.com + raw only, CORS-open, no backend); URL-paste import; preview
   with real file list + scripts warning; **install-as-draft** (SKILL.md text only, meta.source provenance,
   backend strips audit → can't arrive "supported"). skills.sh = honest link-out (no public API).
8. **Settings shell reskin** — `chat/SettingsModal.svelte`: ~1150×88vh desktop window, rail darkest vs
   lighter content + hairline, quiet-gray active nav, independent scroll, desktop close X. Fixes
   "too dark / not filling".
9. **Icon contract** — `front_end/owui/ICONS.md` (Heroicons baseline · 24×24 · 1.5 stroke · currentColor;
   Lucide/Tabler normalized; Carbon rules for custom). Bonus: `ChatItemSkeleton.svelte` cold-load skeleton.

## Gotchas learned (reuse)

- Escape inside the Settings modal: window-level handlers must use **capture phase + stopPropagation**
  (or element-level stopPropagation) or `Modal.svelte`'s own window Escape closes the WHOLE modal.
- Notebook rebuild: use `--no-deps`; watch `*/` in CSS comments; DNS to docker.io (UDP 53) is flaky
  on this network — retries recover.
- Prototype launcher pills use `.pill`, not `.chip` (`.chip` = WorkCard's 32px square).

## Open follow-ups / flags

- Imports arrive `enabled` (draft = unaudited, not toggled Off — needs a backend create field to change).
- `github.com/<o>/<r>/raw/` URL variant unparsed (honest error shown).
- Shared `Dropdown.svelte` still closes the modal on Escape (pre-existing, app-wide).
- Multi-model compare columns all read "HARVIS".
- `Folder.svelte` chat-mode section-label parity; agent-studio inline-SVG → icon-component normalization.
- The separate **composer/header token restyle** (retire sky/violet in the Build cockpit) is still open
  (`docs/research/2026-07-17-build-restyle-research.md`).
- "Harvis Code settings page" (classify-run / switch-engines toggles from the reference) — deferred:
  those backend flags don't exist yet; don't fabricate controls.

## Main UI launcher — functional TODOs (PARKED for tomorrow, 2026-07-17)

User verdict: the launcher **looks good but isn't functional enough** — the merged pieces are
currently visual-only. Parked; work these tomorrow. All live in `chat/Placeholder.svelte`.

1. **Connect-tools tray is a flag, not a button.** The "Connect your tools to Harvis" strip + the
   6 brand chips are decorative. Make it actionable → the tray (or each brand chip) should link to
   the tools/integrations surface (`/harvis/integrations`), ideally each chip → that provider's
   connect flow. Right now clicking does nothing.
2. **Capabilities carousel is a flag with no redirect.** The bottom capability cards don't link
   anywhere. Give each a real destination — the Harvis GitHub repo / a publicity/landing page /
   docs, or the relevant Harvis surface per capability. (User: "we can change to our github repo or
   publicity or whatever.")
3. **Explore-ideas needs to branch + auto-prompt.** Today each chip just sets `prompt` to a fixed
   string. Wanted: clicking an idea **branches down** into sub-options based on the choice, then
   composes a real prompt that is **auto-pasted (and ideally auto-sent) into the chat composer** so
   the user gets a result — an interactive prompt-builder, not a static seed.

## NEXT STEPS (user-listed — resume here)

Per the tomorrow list, with updated status:
1. Settings / Notebook / Build **functionality** pass — Settings UI now reskinned (done); Build cockpit
   composer/header restyle still open; Notebook themed.
2. Fix the Settings UI — largely addressed by the shell reskin; sweep remaining tabs.
3. **New mascot** (themeable HarvisMark variant; pick from 2–3 sketches).
4. Loading **skeletons** + workspace polish — `ChatItemSkeleton` started; generalize; fix `app.html`
   splash `harvis-dark` flash.
5. Deploy test (full cache-busted pass, all 3 themes on :9000).
6. **Push** — gated: ASK first; `harvis1.1` ~25+ commits ahead.
7. Main website (static landing, reuse Warm-paper + new mascot).
8. Adaptive Space (resume ringed-HUD `b0963d3a`).
9. `install.sh` help/UX pass.

## Reference docs

- Plans: `docs/plans/2026-07-17-proto-merge-sidebars-plan.md`, `docs/research/2026-07-17-build-restyle-research.md`
- Obsidian: `notes-vault/code/harvis/2026-07-17-prototype-merge-sidebar-restyle.md` (4 update sections),
  `notes-vault/projects/Harvis UI polish pass.md` (Log)
- Memory: `project_skills_manager_settings`, `project_proto_merge_sidebars_shipped`,
  `project_build_restyle_research`, `reference_harvis_icon_system`
