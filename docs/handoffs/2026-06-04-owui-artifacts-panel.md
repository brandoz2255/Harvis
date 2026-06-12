# Handoff: OWUI Artifacts panel + dock polish (2026-06-04)

## Goal
Two UI adjustments the user asked for on the OWUI-on-Harvis right-rail dock (live at :9000), then a follow-on:
1. Thicken the gap between the main chat and the docked report panel ("a little small, want it a small bit thicker").
2. Rename the **Activity** tab → **Artifacts** ("fits better there").
3. (Follow-on) Repurpose that tab from a run-activity FEED into an actual **Artifacts** panel — "files or things made for the user to go back to per session, not activities." User chose **"Both, combined"**: research reports + generated files + OWUI code/HTML/SVG artifacts.

## State — SHIPPED + deployed to :9000 (build → rsync → restart nginx-proxy), NOT committed
- **Divider thickened.** `ChatControls.svelte` PaneResizer class: hairline `border-l` → `w-2.5 shrink-0` (10px gutter) + slightly more visible border. It's the single chat↔dock boundary, so the research Report panel inherits it. Verified live.
- **Activity → Artifacts rename.** Label changed in 4 spots, internal routing key `'activity'` KEPT (so the `$workspaceControlsTab` bridge + WorkspaceRunCard "View activity" still work):
  - `ChatControls.svelte` mobile tab (~373) + desktop tab (~560)
  - `WorkspaceActivity.svelte` header (~58) — now orphaned, see below
  - `lib/agent-studio/surfaces.ts` (~23) surface label
- **Artifacts panel rebuilt** — the run-activity feed is GONE from the tab. New `lib/components/chat/SessionArtifacts.svelte`:
  - **Research reports**: in the dock (history present) → scoped to the current chat by extracting `<details type="research_run" researchid=… query=…>` markers from `history.messages`, enriched via `GET /api/research/library`. On the full-page surface (no history) → shows the WHOLE library. Click in dock → docks the report (`dockedResearchId`/`researchDockView='report'`/`workspaceControlsTab='research'`/`showControls`). Click on full-page → `openReportInNewTab` (no dock there).
  - **Code/HTML/SVG artifacts**: read straight from the `$artifactContents` store (OWUI already aggregates them per-chat). Click → opens native `Artifacts.svelte` viewer (`artifactCode.set`+`showArtifacts.set(true)`).
  - Empty state: "No artifacts in this session yet. Research reports and things you create will collect here."
- Wired into both ChatControls dock branches (mobile ~432, desktop ~624) as `<SessionArtifacts {history} />` + the surface registry. `WorkspaceActivity.svelte` is now orphaned (kept on disk, easy to restore if a run-list view is wanted elsewhere).
- Added `fetchLibrary(token)` + `ResearchLibraryItem` type + `openReportInNewTab` import usage to `lib/apis/research/index.ts`.

## Verified
- Dock Artifacts tab → correct empty state, run feed gone (screenshot).
- Full-page `/harvis/agent-studio/activity` → renders the real research library as clickable report cards (knicks 3src, mechanical keyboards 2src, lakers 6src, espresso 2src) (screenshot).
- Build compiled clean (1m15s) both deploys; nginx restarted; :9000 healthy.

## Known interaction / NOT done
- **Landing-persistence gap (pre-existing) undercuts the per-session dock.** `SELECT ... FROM owui_chats WHERE chat::text LIKE '%research_run%'` returns ZERO rows — every research the user ran came from the home/landing screen, and that path never persists the assistant message (the `research_run` marker) into a chat. So those reports live only in `/library` (→ show on the full-page surface) and a chat's Artifacts dock is empty for home-screen research. Fix = make landing-originated research persist its marker (research from WITHIN an existing chat already persists fine). This is the highest-value next step — it's what makes the per-session dock actually fill in.
- **"Generated files" (3rd source of "Both, combined") deferred.** Agent-written scripts + `create_docx`/`create_pdf` docs need a backend per-session retrieval endpoint. There IS an `artifacts` DB table (`artifacts_schema.sql`, `file_path` → /data/artifacts) but the current OpenClaw flow doesn't populate it per-session/per-chat. Reports + code/HTML/SVG artifacts (themselves downloadable files) are live; this is the remaining piece.
- User said **"leave it here for now"** on both of the above.

## Files in flight (all MAIN repo `front_end/owui/src/`, uncommitted)
- NEW `lib/components/chat/SessionArtifacts.svelte`
- `lib/components/chat/ChatControls.svelte` (resizer width + tab labels + dock branches + import)
- `lib/components/chat/WorkspaceActivity.svelte` (header label only — now orphaned)
- `lib/agent-studio/surfaces.ts` (import + label + component → SessionArtifacts)
- `lib/apis/research/index.ts` (fetchLibrary + type)

## Uncommitted pile — REMINDER
Nothing is committed (standing rule: commit/push only when the user asks). The pile is now LARGE: Cookbook + Deep Research backends, the whole Agent Studio redesign (Brain/Global Map/Model Comparison/Tuning/dock-router/run-view), and today's Artifacts work. User was offered a local checkpoint commit (no push) on `harvis1.1`; deferred. Consider proposing again.

## Next steps (when resumed)
1. Fix landing-persistence so home-screen research persists its `research_run` marker → per-session Artifacts dock fills in. (Investigate `Chat.svelte` `researchHandler` called from `Placeholder` vs from an existing chat — the new-chat create/save path isn't firing for the research-first case.)
2. Wire the "generated files" source (backend endpoint for per-session generated docs/scripts + frontend list rows).
3. Optional: local checkpoint commit of the pile on `harvis1.1` (no push).
4. Optional polish: per-query source counts; demo a live in-chat research end-to-end.
