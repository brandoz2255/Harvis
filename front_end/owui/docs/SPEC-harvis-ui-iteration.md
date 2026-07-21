# Harvis — Next UI Iteration Design Spec

**Goal.** A calm, spacious, trustworthy, local-first, developer-focused workspace that is powerful without clutter. The visual language is **Claude's calm shell + Manus's task/preview workspace + Harvis's local-first safety/status language**. Warm/Airy paper by default; Midnight supported as a calm dark. Not a neon cyber dashboard; not dense by default; no copied Claude/Manus branding.

**Framework reality.** The live frontend is **Svelte (owui fork)**, token-driven, three themes. Everything below translates into Svelte components + theme tokens — never React-only, never raw hex in components. The React prototype at `front_end/harvis-ui-prototype` (localhost:5180) is a visual reference for Home + the sidebar/drawer only; this spec is the source of truth for the Svelte implementation.

All paths are under `front_end/owui/` unless noted.

---

## Design principles

- **Calm over clutter.** One primary action per region; one accent element per region. The main area shows the task and its result — advanced controls live in drawers, rare tools behind a "More" flyout.
- **Warm/paper first.** Design and verify Warm, then Airy (warm off-white), then Midnight (calm warm-dark). The default is Warm.
- **The result is the hero.** In Build, the preview/artifact is prominent; logs/terminal are summarized, not the default surface.
- **Truthful, local-first states.** Local-only / unverified / blocked / needs-approval states are always visible via pills, dots, and banners. Never a fabricated number, never a green dot that wasn't checked.
- **Real data or nothing.** Every card, count, and pill is fed by an existing store/API. Empty sections collapse; missing providers show an honest, actionable empty state.
- **Approval-gated danger.** Local commit only after approval; push / deploy / public share never happen automatically and never appear as one-click affordances.
- **Reuse before rebuild.** RailCard, portal-flyout, the theme registry, skeletons, chip recipes, and the Build cockpit components already exist. This spec re-composes them.

## Theme & token rules

- **Surfaces** = `gray-*` ramp (semantic roles: gray-800 raised · gray-850 panel · gray-900 shell · gray-950 deepest). **Accent** = `blue-*`, re-hued per theme (cyan Midnight / indigo Airy / coral Warm) via the `themes.ts` registry (`applyThemeById`). **Status** = stock `green/amber/red/cyan`, theme-invariant, used only for status. **Serif** only in Warm, only on reading surfaces, via `--theme-font-body`.
- **No raw hex in components.** Reference palette values live in `src/tailwind.css` `@theme` and `src/lib/themes.ts` maps + `app.html` FOUC loader — never as component classes.
- **Glass vs solid.** Subtle translucency for *chrome only*: composer, right controls drawer, account menu, appearance submenu, preview toolbar, publish modal overlay. **Solid** surfaces for content that must stay legible: code, logs, diffs, long text, test output.
- **Elevation is border-first:** hairline `border-gray-100 dark:border-gray-850`, hover shifts border/bg, at most `shadow-sm`→`shadow-lg` on floating cards. No glows, no neon, no purple gradients.

## Global interaction rules

- Main area stays clean; advanced controls go into drawers.
- **Every action maps to a trace event** (`/api/harvis/*` trace lane → `workspace_events`). New surfaces are read-only consumers or route through existing traced endpoints.
- Dangerous actions require approval (existing `authorize_action` gate). Local commit allowed post-approval; push/deploy/public-share never automatic.
- Any blocked/unverified/local-only state is visible. Never fabricate data. Missing provider → honest empty state.

---

## 1. Home screen

**Layout.** Three columns: soft left sidebar · centered column · optional right drawer (opt-in). Center, top→bottom, on generous vertical air:
1. **Status pill** — small, centered, real provider readiness (green "All systems ready" / amber "N need attention"); becomes the blue live-run chip when a workspace run is active.
2. **Headline** — "What do you want Harvis to do?" (`text-3xl font-medium`, `--theme-font-body`), with the themed `HarvisMascot`.
3. **Composer** — large rounded, glassy chrome; `+` menu, mic, Deep Research toggle, engine/model pill, Send. The centerpiece.
4. **Quick task chips** (below composer): Chat · Build feature · Research · Run repo · Connect tool · Generate image · Cookbook helper. Selecting one sets task-type + reveals guided setup chips (§Prompt setup).
5. **Provider/tool connection strip** — only when real capability data exists (icons of connected/available providers). Collapses when empty.
6. **Alert banner** — only on a real error/needs-setup capability; calm amber, "Fix in Providers →", dismissible per session.
7. **Recent-work grid** — 1–2 col, Manus-style soft cards: recent chats, recent builds, artifacts, provider issues. Only real rows; empty groups collapse.

**Guided setup chips** (after a task type is chosen): Web app · Dashboard · Plugin · Discord integration · Provider · UI redesign · Backend API · Add GitHub repo · Add screenshot · Add design reference · Import Figma · Use Cookbook recipe · Attach file. Rendered as quiet pill chips above/below the composer; each seeds context, none fabricates.

**Components.** Headline + mascot; `Composer` (glassy); `QuickChips` (new); `SetupChips` (new); `ConnectionStrip` (new, gated on real data); `AlertBanner` (new); `WorkCard` grid.

**Visual style.** Off-white/warm canvas, soft gray sidebar, rounded cards, hairline borders, gentle shadow on the composer only, calm type, restrained accent (New chat row, Send, active pill, live chip — one accent per region). Chips are neutral with a soft `--accent-weak` hover.

**Interaction.** Chip click sets task-type (chat/build/research/run-repo/connect/image/cookbook) and routes: Chat→stay; Build feature/Run repo→Build workspace; Connect tool→Providers; Generate image→image lane; Cookbook→recipe picker. Composer submit routes by task-type. Reduced-motion honored on the live-chip ping.

**Data sources.** `$chats` (`apis/chats` `getChatList`); `getWorkspaceHistory(limit)` + `getActiveWorkspace()` (`apis/agent-runs`); `getAllArtifacts(limit)`; capabilities via `lib/integrations/registry.ts` normalized by `lib/integrations/status.ts` (`NormStatus` + `NORM_META`).

**Svelte components likely affected.** `components/chat/Placeholder.svelte` (rebuilt as the launcher), `ChatPlaceholder.svelte` (copy unified), `Suggestions.svelte` (empty-state fix → quick chips), `MessageInput.svelte` (unchanged, hosted), `components/layout/Sidebar.svelte` (see below), new `chat/QuickChips.svelte` + `chat/SetupChips.svelte` + `chat/ConnectionStrip.svelte` + `chat/AlertBanner.svelte`.

**Acceptance criteria.**
- Headline reads "What do you want Harvis to do?"; composer is the centered centerpiece; quick chips present and route correctly.
- Setup chips appear after a task type is chosen and seed context without fabricating data.
- Connection strip and alert banner render only on real capability data; empty groups collapse.
- Status pill reflects live readiness / flips to the live-run chip; no fixed-height holes.
- Re-skins cleanly across Warm/Airy/Midnight with zero component color edits; no raw hex.

### Sidebar (Home + everywhere)

**Layout** (top→bottom): logo mark + wordmark (both tint to accent) · ModeSwitcher (Chat|Notebook|Code, real segmented pill) · **New chat** (the one accent row) + search · **Starred/Pinned** · **Projects** (under Pinned, above Recents) · **Recent chats** · **Recent build runs** · bottom cluster **Cookbook · Providers · Skills · Settings** · **More** flyout (Neural Map, Model Comparison, Artifacts, Schedules, Agent Studio as overflow) · footer: "Local stack ready" status + account trigger (→ menu → Appearance submenu).

> Note: the prototype currently promotes Schedules/Agent Studio to rows and drops "New build"; final sidebar order is a live tuning decision — keep it calm, not overloaded with monitoring data.

**Row recipe.** One recipe everywhere: `group flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850`. Active nav destination = soft accent wash (`bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium`), route-matched. Chat rows keep neutral active. Section labels = `text-[0.625rem] uppercase tracking-wider text-gray-400`. Sidebar icons are monochrome (`--text-muted`), not accent-colored.

**Components.** `Sidebar.svelte`, `Sidebar/ModeSwitcher.svelte`, `Sidebar/ChatItem.svelte` + `ChatItemSkeleton.svelte`, `Sidebar/VibeCodeNav.svelte` (build-run rows), `Sidebar/SidebarMore.svelte`, `Sidebar/UserMenu.svelte` + Appearance submenu.

**Acceptance.** All sections reachable in chat mode; one row/active recipe; active pill re-hues per theme; no raw hex; account menu carries the Appearance submenu generated from `themes.ts`.

---

## 2. Build workspace

**Layout (Manus split).** `BuildHeader` strip on top; below it a paneforge `PaneGroup` split: **left = agent task trace**, **right = preview/artifact result** (the hero). A resizer between. The right panel is prominent by default.

- **Header (`BuildHeader.svelte`):** repo · base→work branch chip · HEAD SHA · clean/dirty dot · a calm lifecycle status chip (preflight → planning → running → awaiting-approval).
- **Left (agent trace):** task summary · plan steps with checkmarks + short explanations (`PlanPanel.svelte` / `RunView.svelte`) · generated-artifact card (`RunArtifacts.svelte`) · terminal *summaries* (collapsed one-liners: `command · exit · duration`, from `BackgroundTaskCard.svelte` / `ShellTab.svelte`) · test/build status (soft card) · changed files with muted +/- (`WorkspaceFileRail.svelte`) · final delivery · **suggested follow-ups** (§8).
- **Right (preview/result):** the `WorkspaceMainPanel.svelte` tabbed surface with a preview toolbar (§3). Preview/Browser is the default hero; Diff, Code, Logs, Files, Database, Settings, Artifacts as tabs (`BrowserPanel.svelte` for preview).
- **Top toolbar (above preview):** Preview · Code · Logs · Database · Files · Settings · GitHub · Share · Publish · close (§3).

**Visual style.** Calm paper; the trace is a quiet column of soft cards, the preview a large soft card with a browser-frame header. Logs/diffs/test-output render on **solid** surfaces (legibility). One accent per region; muted status dots.

**Interaction.** Steps stream via the existing run SSE store (`runStream.ts`); status dots animate (done=green, active=build-cyan pulse w/ motion-reduce, pending=faint). Commit/PR/push live behind the drawer/right-rail as **approval-gated** buttons; the toolbar's Share/Publish opens the publish drawer (§6). Preview toolbar controls act on the preview iframe/route only.

**Data sources.** `apis/agent-runs` (`getWorkspaceHistory`, run detail, `RunView` events), `vibecode_sessions`, `workspace_events`, `workspace_jobs` (terminal_output/exit_code), `workspace_artifacts`, `getPendingAction`/`resolveAction` (approvals), `getIntegrationsStatus` (providers).

**Svelte components likely affected.** `routes/(app)/harvis/vibecode/+page.svelte` (the cockpit), `agent-studio/build/{BuildHeader,WorkspacePanel,WorkspaceMainPanel,WorkspaceFileRail,WorkspaceRightRail,ShellTab,BrowserPanel,PrDrawer,BackgroundTaskCard}.svelte`, `agent-studio/{PlanPanel,RunView,RunProgressCard,RunArtifacts,BuildActions}.svelte`.

**Acceptance criteria.**
- Header shows repo · base→work branch · SHA · clean/dirty · lifecycle status.
- Left = trace (plan/steps/terminal-summaries/tests/changed-files/final delivery/follow-ups); right = preview/artifact as the hero.
- Toolbar present with the listed tabs + Share/Publish/close; logs/diffs/tests on solid surfaces.
- Commit/PR/push are approval-gated and never one-click; no fabricated telemetry.
- Re-skins across the three themes; no raw hex.

---

## 3. Preview toolbar

**Layout.** A slim translucent bar atop the right preview panel. Left: tab group (Preview · Code · Logs · Database · Files · Settings · More). Right: GitHub · Share · Publish · close. A second inline row (inside Preview) hosts preview controls.

**Preview controls (inside Preview tab):** desktop/mobile viewport toggle · route/path selector (dropdown of known routes) · refresh · open-external · edit · fullscreen.

**Visual style.** Chrome translucency (glass) allowed here; hairline bottom border; small icon buttons (44px hit area); pill toggles; one accent for the active tab.

**Interaction.** Tab switch swaps the main-panel surface (no reload). Viewport toggle reflows the preview frame. Route selector navigates the preview iframe. Open-external respects the local-first rule (opens the local preview URL only). Fullscreen expands the preview pane. GitHub opens the repo context; Share/Publish open the publish drawer (§6).

**Data sources.** Preview URL + route list from the run's dev-server metadata (`workspace_events` / job state); tab availability from run capabilities (hide tabs with no data).

**Svelte components likely affected.** New `agent-studio/build/PreviewToolbar.svelte`; `WorkspaceMainPanel.svelte` (tab host), `BrowserPanel.svelte` (preview frame).

**Acceptance criteria.**
- Toolbar shows the tab set + GitHub/Share/Publish/close; inactive-data tabs hidden, not faked.
- Preview controls (desktop/mobile, route, refresh, external, edit, fullscreen) all functional against the preview frame.
- Chrome is translucent; the preview content surface stays solid; icons have ≥44px hit area and labels.

---

## 4. Chat / Build controls drawer

**Layout.** A floating rounded right-side card (translucent chrome), soft background, large padding, close button, simple collapsible sections (`RailCard`). No dense technical rows by default. One shared `ControlsDrawerShell` serves mobile (bottom-sheet `Drawer.svelte`), desktop (in-pane), and the Build dock. Titled "Chat controls" / "Build controls" via a `context` prop.

**Chat controls sections:** Model/Engine · Artifacts · Content · Skills · Providers · Style & behavior · Advanced (collapsed).
**Build controls sections:** Engine · Repo/Branch · Preview · Artifacts · Tests · Changed files · Providers · Commit/PR (approval-gated) · Advanced (collapsed).

**Visual style.** Calm soft card, hairline border, `shadow-sm`; section headers `text-sm font-medium`; rows quiet; skill chips in the sky-tinted ON recipe; provider rows = dot + name + status pill. Translucent chrome; content rows solid.

**Interaction.** Knobs button toggles `showControls`; Escape/close returns focus to trigger. Two top-level pills max (Controls | Activity). Skills toggles only what the approval gate permits. Provider rows poll only while the drawer is open (7s). The artifact full-view has a back control. Commit/PR buttons carry a "Requires approval" lock and route through `authorize_action`.

**Data sources.** `selectedModels`/`$models`; `getAllArtifacts`; attached files + `SourcesPanel` citations; skill data (session); `getIntegrationsStatus`; settings store (chatBubble/widescreen/textScale); run repo/branch/tests from run state.

**Svelte components likely affected.** `components/chat/ChatControls.svelte`, new `ChatControls/ControlsDrawerShell.svelte`, `ChatControls/{OverviewPanel,ArtifactsPanel,SourcesPanel,ViewPanel}.svelte`, `Controls/Controls.svelte` (+ `Valves.svelte`, re-homed), `common/{RailCard,Drawer}.svelte`, `routes/(app)/harvis/vibecode/+page.svelte` (mounts the shell as "Build controls").

**Acceptance criteria.**
- One shell serves mobile + desktop + build dock; the mobile/desktop duplication in `ChatControls.svelte` is gone.
- Chat drawer shows Model/Artifacts/Content/Skills/Providers/Style/Advanced; Build drawer shows Engine/Repo-Branch/Preview/Artifacts/Tests/Changed-files/Providers/Commit-PR/Advanced.
- System prompt/Temperature/Valves reachable again; provider rows poll only while open.
- Commit/PR gated; no push/deploy one-click anywhere in the shell.

---

## 5. Provider empty states

**Layout (Manus database-empty style).** A calm centered card inside the relevant surface: icon · concise title · one-sentence explanation · a single primary CTA. No dense rows, no fake status.

**Examples (only when the provider is genuinely absent):**
- "No Discord provider connected" → *Configure Discord provider*
- "No ComfyUI image provider" → *Add ComfyUI*
- "No Floci local AWS sandbox" → *Add Floci / LocalStack*
- "No database connected" → *Ask Harvis to add a local database*
- "No printer connected" → *Add printer profile*

**Visual style.** Soft card, hairline border, muted icon chip (`--accent-weak`), calm title (`text-sm font-medium`), one-line `text-xs text-gray-500`, one pill CTA. Never alarmist.

**Interaction.** CTA routes to the connect flow (Providers page / provider wizard) or seeds a Harvis task ("add local database"). Empty state renders only when `status.ts` reports the capability missing/needs-setup; a connected provider shows its real status row instead.

**Data sources.** `lib/integrations/registry.ts` + `status.ts` (`NormStatus`/`NORM_META`), capability planner/provider catalog.

**Svelte components likely affected.** New `integrations/ProviderEmptyState.svelte`; consumed by Home connection strip, Build Database/Providers tabs, and the drawer Providers section; `routes/(app)/harvis/integrations` for the connect flows.

**Acceptance criteria.**
- Empty state shows icon + title + one-sentence explanation + one CTA; appears only for genuinely-missing providers.
- CTA routes to a real connect flow or seeds a task; never fabricates a "connected" state.
- Calm styling, token-driven, all three themes.

---

## 6. Publish / share flow

**Layout (small focused popover/drawer).** Status row (Not published / Local only / Published) · Visibility dropdown · Destination · primary action (Publish now / Export / Share) · an **approval warning** whenever the action leaves the local machine.

**Visual style.** Translucent chrome overlay; compact; one accent on the primary action; a clear amber "leaves your machine — requires approval" note when relevant.

**Interaction.** **Harvis never auto-pushes or auto-deploys.** Publish/share/export that leaves local requires explicit approval through `authorize_action`; local-only export writes to disk without leaving the machine. Default status = "Local only." The primary button is disabled until visibility/destination are chosen and (for off-machine) approval is granted.

**Data sources.** Run/artifact publish state, `code_pull_requests` (PR path via `PrDrawer`/`_open_pr_from_diff`), export targets; approval via the pending-action queue.

**Svelte components likely affected.** New `agent-studio/build/PublishDrawer.svelte`; `agent-studio/build/PrDrawer.svelte` (PR path), `agent-studio/BuildActions.svelte`.

**Acceptance criteria.**
- Shows status/visibility/destination/action + approval warning for off-machine actions.
- No auto-push/auto-deploy; off-machine actions blocked until approved; local export works without approval.
- Default "Local only"; token-driven; three themes.

---

## 7. Completion modal

**Layout.** Centered success card over a **blurred/dimmed** background: success icon · title · result URL/path · copy button · open/visit button · share actions · optional follow-up actions.

**Examples:** "Your build is ready" · "Your Discord integration is connected" · "Your image is generated" · "Your local app is running" · "Your export is ready."

**Visual style.** Translucent scrim (40–60% dim), solid centered card, one accent on the primary open/visit button, calm success-green icon chip. No confetti-neon.

**Interaction.** Appears on a major completion (build ready / provider connected / image generated / app running / export ready). Copy copies the path/URL; Open respects local-first (opens local URL/file); Share routes through the publish drawer (approval-gated if off-machine). Escape/click-scrim dismisses to the task-completed section (§8). Focus trapped in the modal; returns to trigger on close.

**Data sources.** Completion event from the run trace (`final_message`/artifact/job-complete); result path/URL from artifact or dev-server metadata.

**Svelte components likely affected.** New `agent-studio/CompletionModal.svelte`; reuses `common/Modal.svelte` scrim + focus-trap.

**Acceptance criteria.**
- Blurred scrim + centered card with icon/title/result/copy/open/share/follow-ups.
- Open respects local-first; Share is approval-gated when off-machine; focus trapped, Escape closes.
- Fires only on real completions with a real result; three themes.

---

## 8. Task completed / follow-up section

**Layout.** After a task finishes, in the trace column: "Task completed" · a light rating prompt · **suggested follow-ups** · the final step collapsed · composer ready for the next instruction.

**Harvis follow-ups (contextual, real):** Add tests · Improve UI spacing · Connect Discord · Add database · Save as skill · Create local commit · Open PR drawer · Export artifact.

**Visual style.** Quiet completed banner (success-green dot), follow-ups as pill chips, collapsed final step with a chevron, composer re-focused. Calm, not celebratory-loud.

**Interaction.** Follow-up chips seed the next action: "Create local commit" → approval-gated commit; "Open PR drawer" → publish/PR drawer; "Save as skill" → the gated skill-creator (AI drafts SKILL.md → artifact preview → Save-as-skill through the human-gated audit); "Export artifact" → publish drawer (local export). Rating is optional and non-blocking.

**Data sources.** Run completion state; artifact/skill/commit availability from run capabilities; `authorize_action` for gated follow-ups.

**Svelte components likely affected.** New `agent-studio/TaskCompleted.svelte`; `RunView.svelte` (hosts it), composer re-focus in `vibecode/+page.svelte`; skill-creator ties to the skills store + audit.

**Acceptance criteria.**
- Shows completed state + optional rating + contextual follow-ups + collapsed final step + re-focused composer.
- Each follow-up routes correctly; gated ones (commit/PR/skill/export-off-machine) go through approval; rating is non-blocking.
- Only real, applicable follow-ups shown; three themes.

---

## Phased implementation plan

1. **Phase 1 — Home + sidebar.** Rebuild `Placeholder.svelte` into the launcher (headline, composer, quick chips, setup chips, connection strip gated on real data, alert banner, recent-work grid); finalize the sectioned sidebar + Appearance submenu; add the `blue-*` accent re-hue to the theme maps so Warm/Airy accents work. *(Home is already partly realized in the prototype.)*
2. **Phase 2 — Build workspace shell + preview toolbar.** `BuildHeader` lifecycle strip; the trace-left / preview-right split; `PreviewToolbar.svelte` with tabs + preview controls; preview/result as hero; logs/diffs/tests on solid surfaces.
3. **Phase 3 — Right controls drawer.** Extract `ControlsDrawerShell`; Chat + Build section sets; revive Controls.svelte content; provider polling; artifact back-view; mount in the Build dock as "Build controls".
4. **Phase 4 — Provider empty states.** `ProviderEmptyState.svelte` fed by `status.ts`; wire into Home strip, Build Database/Providers, and the drawer; connect flows.
5. **Phase 5 — Publish/share + completion flows.** `PublishDrawer.svelte` (approval-gated, local-first), `CompletionModal.svelte`, `TaskCompleted.svelte` follow-ups; all gated actions through `authorize_action`.
6. **Phase 6 — Polish across Midnight/Airy/Warm.** Three-theme sweep: accent re-hue, OLED legibility, Warm serif on reading surfaces (blocked on choosing + self-hosting a body serif), glass-vs-solid audit, reduced-motion, contrast, no-raw-hex grep, keyboard/focus.

Per phase: verify the three-theme gates before moving on; every new surface is a read-only consumer or routes through existing traced endpoints; no push/deploy affordance ever ships un-gated.

---

## Grounding sources (study before building — don't invent)

- **Claude.ai** — the calm shell: soft sidebar, warm paper canvas, centered greeting, small status pill, simple alert, recent cards with subtle borders, floating right controls drawer, large padding, quiet section labels, Appearance submenu on the account menu. (Shell / Chat / Notebook.)
- **Manus** — the task/preview workspace: home launcher (huge centered question, large composer, tool icons, connect-tools strip, quick chips, empty space); prompt setup chips; build split (agent trace left / generated result right); database empty-state; publish popover; success modal; task-completed + follow-ups. (Build / data surfaces.)
- **Refero MCP** (`https://api.refero.design/mcp`, 135K+ real screens / 10K+ flows; 4 tools: search/detail × screens/flows) — when connected in an interactive session, search real analogues per surface and translate into Harvis tokens instead of inventing. Pairs with the `harvis-ui-craft` house-style skill. Setup: `claude mcp add --transport http refero https://api.refero.design/mcp --header "Authorization: Bearer <token>"` (browser sign-in on first call).

Never copy Claude/Manus branding — borrow interaction *shapes*, express them in Harvis tokens with the robot mascot + wordmark.
