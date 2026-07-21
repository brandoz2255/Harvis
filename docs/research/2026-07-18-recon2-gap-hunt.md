# Recon #2 — systematic gap hunt (2026-07-18)

## Executive summary

Nothing we shipped today is broken — the settings refactor, honesty gates, skeleton kit, and splash fix all passed adversarial verification, with two adjacent findings: the Models workspace page can now skeleton-shimmer **forever** on any `/groups` API failure (a pre-existing hang the skeleton made *less* honest than the spinner it replaced), and the Change Password form sits ungated against a route that doesn't exist, one component away from the gates we just added. The systemic picture is worse than the polish-level view we had this morning. **265 frontend API functions with real UI call sites have no backing route** — 13 of them reachable from core chat UI by every user (Share chat, Clone chat, password change, `/` prompt menu, Personalization memories, "Set status", changelog modal). Two findings are outright data-loss risks: the orchestration model pool can be silently **wiped** by a toggle after a transient load failure (`Customize.svelte:28-47`), and GitHub "disconnect" reports success even when the credential is still live server-side. The dominant dishonesty pattern is "error rendered as confident empty state" — Knowledge, Projects, Dev Console, Skills, Sub-agents all tell a user with a dead backend that they have nothing, and the Dev Console (whose whole job is reporting system health) is the worst offender. On accessibility, the two mascots run an unconditional never-idle rAF loop (WCAG 2.2.2 failure + battery cost on the 8GB laptop target), and one Escape press inside any dropdown-in-modal closes the whole modal app-wide. The good news: the fix patterns for almost everything already exist in-repo (`SkillsManager.svelte`'s `loadError`, `HelmetHangerMockViewer.svelte:55`'s motion gate, `common/Modal.svelte`'s focus trap) — this is mostly propagation work, not invention.

## Regressions / breakage in today's work

Verification ran three scopes; **no regressions**. Detail:

- **Settings refactor (12 tabs) — PASS.** Token-count + line-diff comparison found zero dropped handlers, bindings, or labels. One deliberate behavior change verified correct: `Interface.svelte:185-194` stops unconditionally clobbering the user's default model on every interface save (guard properly initialized at `Interface.svelte:286-290`). All 10 new descriptions match their handlers; mobile stacking and `highContrastMode` intact.
- **Honesty gates (8) — PASS, one inconsistency.** All 8 gates still `false` and gating (`DataControls.svelte:47-52` → disabled at 221/244/282/304/326/352; `Account.svelte:28-29` → 407/436/465 + handler guards at 93/467), and their backend claims re-verified against `router.py`. **FINDING (medium):** `Account/UpdatePassword.svelte:14` → `POST /api/v1/auths/update/password` (`lib/apis/auths/index.ts:445`) — router.py only implements signin/signup/signout (lines 100-158). Live form, dead endpoint, in the very tab that just got honesty gates. Pre-existing but philosophically inconsistent.
- **Skeleton kit — one FAIL, rest PASS.** **FINDING (highest in scope):** `workspace/Models.svelte:279` — `await getGroups(...)` uncaught; `getGroups` throws on API failure (`lib/apis/groups/index.ts:63-65`) or returns `null` → `groups.map` TypeError (`Models.svelte:284`); `loaded = true` (line 287) never reached → **infinite shimmer** impersonating incoming content. Knowledge/Notes/Cookbook/build-page/SkillsManager all resolve correctly; reduced-motion + `aria-busy`/`sr-only` verified on every consumer; no in-flight action indicators lost.
- **Splash fix — PASS.** All 8 theme ids covered; app.html loader maps verified value-for-value against `themes.ts` (hex-for-hex). The old bug (`html.harvis-dark` matching a class never set) is genuinely closed. Two non-regression nits: Midnight one-step shade change #00030b → `dark:bg-gray-900` at load; `her` pre-hydration missing its `light` base class — egg-only, pre-existing.

## Dead / missing backend routes

Already handled (excluded): today's nine (`updateUserProfile`, `createAPIKey`, `getAPIKey`, `importChats`, `getAllChats` export-all, `getSharedChatList`, `archiveAllChats`, `deleteAllChats`, `searchFiles`).

**Raw scale:** 265 unbacked frontend fns with UI call sites (+42 with no caller = dead frontend code). New findings:

### Tier 1 — reachable from core chat UI by every user

| # | Frontend fn | Method+Path | Call sites | Backend status | Symptom |
|---|---|---|---|---|---|
| 1 | `shareChatById` (+3 siblings) | POST `/api/v1/chats/{id}/share` | `ShareChatModal.svelte:30`, chat menu `layout/Navbar/Menu.svelte:376` | NO ROUTE | Share produces nothing; entire `/s/[id]` public page (`routes/s/[id]/+page.svelte:89`) dead |
| 2 | `cloneChatById` | POST `/api/v1/chats/{id}/clone` | `Sidebar/ChatItem.svelte:142` | NO ROUTE | Sidebar ⋯ → Clone → 404 toast |
| 3 | `updateUserPassword` | POST `/api/v1/auths/update/password` | `Settings/Account/UpdatePassword.svelte:16` | NO ROUTE | Password change always fails (see verification finding above) |
| 4 | `getPrompts` | GET `/api/v1/prompts/` | `MessageInput/Commands/Prompts.svelte:39` (`.catch(() => null)`) | NO ROUTE (zero `/api/v1/prompts/*`) | `/` in composer: prompt menu silently empty |
| 5 | `getMemories` + 4 CRUD fns | `/api/v1/memories/*` | `ManageModal.svelte:309/302/75`, `AddMemoryModal.svelte:21` | NO ROUTE | Personalization→Manage: empty + error toasts on every action |
| 6 | `getAllArchivedChats`, `unarchiveAllChats` | GET `/api/v1/chats/all/archived`, POST `/api/v1/chats/unarchive/all` | `ArchivedChatsModal.svelte:101/120` | NO ROUTE (list itself works, router.py:502) | Export All + Unarchive All broken in archived-chats modal |
| 7 | `updateUserStatus` | POST `/api/v1/users/user/status/update` | `Sidebar/UserMenu.svelte:195` → `UserStatusModal.svelte:29` | NO ROUTE | "Set status" → 404 toast |
| 8 | `exportChatStats`, `exportSingleChatStats` | GET `/api/v1/chats/stats/export[/{id}]` | `routes/+layout.svelte:845` + `?sync=true` deep-link (`:1100-1106`) | NO ROUTE | Sync-stats export fails |
| 9 | `deleteOAuthSession` | DELETE `/api/v1/auths/oauth/sessions/{id}` | `MessageInput/IntegrationsMenu.svelte:397` | NO ROUTE | Composer integrations disconnect → 404 |
| 10 | `getChangelog` | GET `/api/changelog` | `ChangelogModal.svelte:23`; auto-opens for admins on version bump (`(app)/+layout.svelte:411-412`) | NO ROUTE | "What's new" opens empty after every version change |
| 11 | `getGravatarUrl` | GET `/api/v1/utils/gravatar` | `Settings/Account/UserProfileImage.svelte:145` | NO ROUTE | "Use Gravatar" button fails |
| 12 | `updateUserInfo` | POST `/api/v1/users/user/info/update` | `chat/Settings/Interface.svelte:127` | NO ROUTE | "User location" errors after geolocation grant |
| 13 | `getUsage` | GET `/api/usage` | `Sidebar/UserMenu.svelte:103/121` | NO ROUTE | Silent — usage row never renders |

### Tier 2 — whole admin/workspace surfaces (~150 fns)

- **`/admin`** (UserMenu:353): practically every tab dead — analytics (9 fns), Users, Evaluations, Functions (13 fns), Connections (no `/ollama` or `/openai` routes exist at all), Models manage, Documents/WebSearch, Images, Pipelines, Database, CodeExecution. Only the Audio tab works (`main.py:5090+`).
- **`/workspace` Library** (UserMenu:402): Prompts tab 100% dead; Tools CRUD dead (stub GETs only, `stubs.py:50-54`); Knowledge `create`/`update`/`file add-update-remove`/`reset` missing → Create-KB + file upload broken (list/get/delete exist, `knowledge.py:378-416`).
- **`/playground`** (UserMenu:613): nonfunctional — `imageGenerations` (`playground/Images.svelte:84`) + missing `/openai`/`/ollama` passthroughs.

### Swallowed-route shadowing bugs (today-style class)

- `deleteAllFiles` DELETE `/api/v1/files/all` (`Documents.svelte:296`) is swallowed by DELETE `/api/v1/files/{file_id}` (`main.py:5346`) with `file_id="all"` — harmless today (404), classic shadowing time bomb.
- `searchKnowledgeFiles` GET `/api/v1/knowledge/search/files` swallowed by GET `/api/v1/knowledge/{kb_id}/files` (`knowledge.py:408`, `kb_id="search"`) → **`#` composer command file-suggestions silently wrong/empty** (`Commands/Knowledge.svelte:117`). This one is live.

### Tier 3 — flag-hidden or latent (list)

Channels (24 fns, gated by `enable_channels=False`, `config.py:65`); Notes (10 fns, gated); Calendar + vanilla `/automations` — **flags absent from config.py, pages still route by direct URL and are fully broken there** (Agent Studio Automations is fine — uses `/api/cron`, `Automations.svelte:15`); `stopTask`/`stopTasksByChatId` latent — stub `stubs.py:86` returns no task ids so `Chat.svelte:1687-1696`/`:2958` never fires them, bites the moment real ids are emitted; `formatPythonCode`, `generateMoACompletion`, `uploadDir`, `unloadModel`/`pullModel` (`ModelSelector/Selector.svelte:422/277`); 42 caller-less fns = cleanup candidates.

**Clean/cleared:** `downloadChatAsPDF` (client-side jsPDF), audio speech (real caller uses `/api/v1/audio/speech`, `main.py:5159`), CodeBlock pyodide path, MemoryPanel, `getKbStatus`, `getGithubStartUrl`, `applySkillSync`, `/api/models`. Inverse direction (backend routes with no frontend caller): no confirmed dead backend surface — UNVERIFIED beyond static scan; would need a runtime route dump.

## Silent failures & dishonest states

### Data-loss / false-success (worst class)

- **Orchestration model pool silent wipe** — `lib/agent-studio/Customize.svelte:28-47`. `loadPool` `.catch(() => null)` still sets `poolLoaded = true` with `poolActive=false, poolModels=[]`; `savePool` PUTs with `.catch(() => {})`, no `res.ok` check. Transient GET failure → user toggles switch → PUT `{active:false, models:[]}` **overwrites the real server-side pool**. Zero feedback either way.
- **GitHub "disconnected" lie** — `lib/integrations/ConnectionPanel.svelte:140-147`: `try { await disconnectGithub(); } catch (_) {}` then unconditionally `gh = { connected: false }`. Credential may still be live server-side — security-flavored.
- **Skill/plugin delete removes row even on failed DELETE** — `SkillsPanel.svelte:70-73`, `PluginsPanel.svelte:197-201`; toggle similarly swallows failure (SkillsPanel:66-69, PluginsPanel:190-196) — switch flickers back unexplained.
- **Connector toggle/detach silent no-ops** — `ConnectorsPanel.svelte:173-186`, `McpShop.svelte:218-237`. Refetch restores truth; lower impact.

### Error rendered as confident empty state

- **Dev Console goes silently empty** — `routes/(app)/harvis/console/+page.svelte:23-41`: every fetch → `null` → zero providers/jobs/runs, no banner. The one page that must never lie about backend reachability does.
- **Knowledge**: `knowledge/+page.svelte:201-208` `catch { kbs = []; }` → "No knowledge bases yet" (:719-722).
- **Projects**: `projects/+page.svelte:40` `.catch(() => [])` → "No projects yet" (:109-119); failed per-project counts render as "0 chats" (:46-48, :138).
- **Integrations panel shows stale as live** — `integrations/+page.svelte:119-131`: null returns (`apis/integrations/index.ts:6-17`, `integrations/registry.ts:40-60`) freeze `live` at last value while the page claims 7s polling; no staleness indicator.
- **Skills/Plugins panels**: `SkillsPanel.svelte:34` → "No skills yet" (:326); same `PluginsPanel.svelte:139`. (`SkillsManager.svelte:46-56` + 427-431 does it RIGHT — the fix pattern exists in-repo.)
- **Sub-agents**: `SubAgents.svelte:55-63` → "No sub-agents yet" (:314). **Webhooks**: `WebhooksModal.svelte:34-42` → "No webhooks yet" (:157). **MCP count**: `apis/integrations/index.ts:86-95` → dead endpoint reads as "0 connectors" (`ConnectionPanel.svelte:150-154`).

### Stuck state

- **KB indexing poll never terminates on failure** — `knowledge/+page.svelte:210-228` + `apis/knowledge/index.ts:34-40`: the `n > 100` bail-out and `clearInterval` are inside `if (s)`; a failing status endpoint means the interval fires every 3s forever and the card shows "indexing" indefinitely. UNVERIFIED whether `/api/owui/kb/{id}/status` can actually 401 mid-session; the logic hole is confirmed regardless.

### Minor degradation

Pinned notes vanish on error (`Sidebar.svelte:365`, `Notes.svelte:550,620`, `NoteEditor.svelte:1099`); live chips silently absent (`(app)/+layout.svelte:274,287`) — arguably acceptable; `getWorkspaceHistory` `[]`-on-error feeds the Dev Console finding.

**Checked and CLEAN:** Channels (except WebhooksModal), SkillsManager, Adaptive (`ResourceBoard:88`, `RepoRunnerSurface` renders `runErr`/`err`), Admin (only benign `Images.svelte:162`), Chat.svelte's five empty catches (parsing/speechSynthesis guards), notes editor, ModelEditor (deliberate fallback), home, calendar, playground.

## Accessibility & polish

### Motion (worst a11y class)

- **M1/M2 — both mascots run an unconditional, never-idle rAF loop** — `HarvisMascot.svelte:68-85`, `HarvisClawMascot.svelte:70-92` (+2s CYCLE at :53-57: idle → look → wave, forever). No `prefers-reduced-motion` check in either file. Surfaces: chat home (`Placeholder.svelte:197`), run cockpit (`RunView.svelte:230-234`), every workspace run card (`WorkspaceRunCard.svelte:489-493`). WCAG 2.2.2 failure + perpetual 60fps loop even off-screen (battery, 8GB laptop target). **Finished runs keep bobbing/waving** — `RunView.svelte:232` / `WorkspaceRunCard.svelte:491` map done → `'idle'`, and idle isn't idle. (Pulse dots are correctly gated — the "animates over finished content" complaint is specifically the mascot.)
- 89 Tailwind animation-class uses across 64 files vs exactly **1** `motion-safe:`/`motion-reduce:`; no global reduced-motion rule in `app.css`. Infinite offenders: `WorkspaceRunCard.svelte:483-486` ring pulse + `:497` ping for a run's whole duration; `app.css:205-244` shimmer; CallOverlay/VoiceRecording visualizers; ~14 more files with unguarded `@keyframes`.
- **Done well:** the entire Adaptive suite guards motion (`AdaptiveCore.svelte:249`, `AdaptiveSpaceShell.svelte:724,759`, `HelmetHangerMockViewer.svelte:55` gates its rAF); `Placeholder.svelte:172` gates the carousel — ironically 25 lines above the ungated mascot; `common/Skeleton.svelte:33`.

### Keyboard + focus

- **K1 — Escape inside any Dropdown-in-Modal closes the whole modal, app-wide** — `Dropdown.svelte:131-136` doesn't stopPropagation; `Modal.svelte:42-52`'s `isTopModal()` only counts `.modal` elements, and dropdown content is portaled to body as a plain div (`Dropdown.svelte:30-38`). Both handlers fire on one Escape. The known Settings quirk, confirmed and generalized.
- **K2** — Dropdown has zero focus management (no trap, no focus-on-open, no return-to-trigger).
- **K3** — six custom overlays bypass `common/Modal` with zero keyboard support: `GitHubRepoModal.svelte:127`, `PrDrawer.svelte:214` (a form you can't Escape and that traps nothing), `ConnectorsPanel`, `PluginsPanel`, notebook add-source dialog, `DeepResearchModal.svelte:133`.
- **K4** — only 16 clickable non-interactive divs found — the codebase mostly uses real buttons.
- **Done well:** `common/Modal.svelte` is genuinely solid (focus-trap, `role="dialog"` + `aria-modal`, scroll lock, top-modal Escape check).

### Names, semantics, contrast

- **~9 surfaces share one unlabeled ellipsis-menu pattern** (verified `workspace/Tools.svelte:538`; recurs at `Prompts.svelte:486`, `Skills.svelte:483`, `admin/Functions.svelte:554`, `admin/Settings/Models.svelte:717`, `Feedbacks.svelte:514`, `notes/Notes.svelte:555,625`, `automations/+page.svelte:383`) — one aria-label fixes nine surfaces. Plus `chat/Navbar.svelte:242-249` (high-traffic), `SearchInput.svelte:289-293`, `DeepResearchModal.svelte:143`, `CallOverlay.svelte:1047`, notebook close-X (`[id]/+page.svelte:577`), `playground/Chat.svelte:362`. UNVERIFIED (flagged, not read): automations dropdown triggers, `common/Folder.svelte:156`, `FilesModal.svelte`. Done well: 224 labeled buttons + house Tooltip pattern covers most toolbars.
- **Semantics:** chat home has no heading at all (`Placeholder.svelte:199` — styled div); `AdaptiveSpaceShell.svelte` skips h1→h3 (:420/:477 → :532+); `aria-busy` in only 7 files, none in RunView/ThoughtStream (UNVERIFIED whether live-region is the right pattern — needs a screen-reader pass); 295 of 410 inputs have neither `id` nor `aria-label` (upper bound — scan didn't detect wrapping `<label>`). Done well: `common/Switch.svelte` via bits-ui; `highContrastMode` setting exists and drives focus outlines.
- **Contrast (candidates — measure per Midnight/Airy/Warm before filing, since `--color-gray-*` is re-tinted per theme):** `dark:text-gray-600` visible small text computes to 2.35:1 at Tailwind defaults (66 uses; `HotkeyHint.svelte:33`, `FileNav.svelte:1321`, `RepoRunnerSurface.svelte:308` at 2.60:1 on `#070b14`); `text-gray-400` small text in light mode computes to 2.54:1; `gray-500` + dark bg + tiny type computes to 3.67:1 — the pair to sweep across 312 `text-[10px|11px]` matches (worst files: `vibecode/+page.svelte` ×25, `PrDrawer.svelte` ×15). `AdaptiveSpaceShell.svelte:381`'s 8.5px uppercase micro-type is a readability problem independent of contrast.

## What this changes about the plan

The earlier recon's order (mascot instrument #1, command palette #2) **changes in three ways**:

1. **Two cheap finish-today's-work fixes jump to the very top**: the Models.svelte skeleton hang and the UpdatePassword honesty gate. Both are S-effort, both are loose ends of work we just shipped, and leaving them makes today's honesty story incomplete.
2. **Mascot stays #1 among features, but its scope now includes a11y**: the reduced-motion gate and the "finished runs stop waving" fix (M1/M2) are 3-line changes in the same two files the mascot instrument work will touch anyway. Doing the instrument without them ships a WCAG 2.2.2 failure to more surfaces. The in-repo pattern is `HelmetHangerMockViewer.svelte:55`.
3. **Command palette drops below three newly-found broken things**: the orchestration-pool silent wipe (data loss), the K1 Dropdown-Escape swallow (destroys modal state app-wide, S-effort), and the error-as-empty-state sweep (the SkillsManager `loadError` pattern already exists — this is propagation, high honesty payoff). A nice-to-have does not outrank a toggle that can wipe server config.

The Tier-1 dead routes are the biggest *volume* of brokenness but don't all need implementation — the right first move is the same honesty-gate treatment we applied today (gate Share/Clone/status/changelog/etc. with "Not available in this deployment"), then decide which to actually build (Share + Clone are the strongest candidates — core chat features every user will try). Tier-2 admin/workspace surfaces need a product decision (implement vs. hide the nav entries), not a fix ticket.

## Ranked fix list

| # | Fix | Impact | Effort | Files |
|---|---|---|---|---|
| 1 | Catch `getGroups` failure; add `loadError` branch (SkillsManager pattern) so the skeleton can't shimmer forever | Workspace Models page hangs on any API blip, skeleton impersonates content | S | `workspace/Models.svelte:279-287`, cf. `apis/groups/index.ts:63-65` |
| 2 | Honesty-gate the Change Password form like the rest of Account | Live form, dead endpoint, in the tab we just gated | S | `chat/Settings/Account/UpdatePassword.svelte:14-16` |
| 3 | Fix orchestration pool: don't set `poolLoaded=true` on failed load; check `res.ok` on PUT; toast on failure | Silent server-config **wipe** via toggle after transient failure | S | `lib/agent-studio/Customize.svelte:28-47` |
| 4 | Dropdown Escape: stopPropagation or mark portal as a modal layer for `isTopModal` | One Escape destroys modal state, every Dropdown-in-Modal app-wide | S | `common/Dropdown.svelte:131-136`, `common/Modal.svelte:49-52` |
| 5 | Mascot: reduced-motion gate + stop CYCLE/rAF on finished runs (fold into mascot-instrument work) | WCAG 2.2.2 on chat home, run cockpit, every run card; perpetual 60fps on 8GB target | S | `HarvisMascot.svelte:68-85`, `HarvisClawMascot.svelte:53-92`, `RunView.svelte:232`, `WorkspaceRunCard.svelte:491`; pattern: `HelmetHangerMockViewer.svelte:55` |
| 6 | Error-as-empty-state sweep: propagate the `loadError` pattern to Console, Knowledge, Projects, Skills/Plugins panels, SubAgents, Webhooks, MCP count | Dead backend reads as "you have nothing" across 8 surfaces; Dev Console lies about system health | M | `console/+page.svelte:23-41`, `knowledge/+page.svelte:201-208`, `projects/+page.svelte:40`, `SkillsPanel.svelte:34`, `PluginsPanel.svelte:139`, `SubAgents.svelte:55-63`, `WebhooksModal.svelte:34-42`, `ConnectionPanel.svelte:150-154`; pattern: `SkillsManager.svelte:46-56,427-431` |
| 7 | KB poll: move the bail-out/clearInterval outside `if (s)`; surface an error status | Card stuck "indexing" forever + eternal 3s polling on endpoint failure | S | `knowledge/+page.svelte:210-228`, `apis/knowledge/index.ts:34-40` |
| 8 | False-success fixes: skill/plugin delete-toggle check response; GitHub disconnect only flips UI on success | Rows vanish then reappear; "disconnected" while credential still live (security-flavored) | S | `SkillsPanel.svelte:66-73`, `PluginsPanel.svelte:190-201`, `ConnectionPanel.svelte:140-147` |
| 9 | Honesty-gate the Tier-1 dead-route UI (Share, Clone, Set-status, memories, prompts menu, changelog, Gravatar, user-info, archived export/unarchive-all, OAuth disconnect, stats export) | 13 core-UI features currently fail with 404s or silent emptiness for every user | M | `ShareChatModal.svelte:30`, `ChatItem.svelte:142`, `UserMenu.svelte:195`, `ManageModal.svelte`, `Commands/Prompts.svelte:39`, `ChangelogModal.svelte:23`, `UserProfileImage.svelte:145`, `Interface.svelte:127`, `ArchivedChatsModal.svelte:101,120`, `IntegrationsMenu.svelte:397`, `+layout.svelte:845` |
| 10 | Implement Share + Clone chat backend routes (the two Tier-1s worth building, not gating) | Core chat features every user will reach for; unblocks the `/s/[id]` page | M | `python_back_end/owui_compat/router.py` (+ `routes/s/[id]/+page.svelte:89`) |
| 11 | aria-label the shared ellipsis-menu pattern + Navbar/SearchInput/close-X buttons | ~12 unlabeled controls, 9 fixed by one pattern change | S | `workspace/Tools.svelte:538` et al. (9 surfaces), `chat/Navbar.svelte:242-249`, `SearchInput.svelte:289-293`, `DeepResearchModal.svelte:143` |
| 12 | Fix the live swallowed route: `searchKnowledgeFiles` vs `/{kb_id}/files`; reorder/rename `deleteAllFiles` shadow | `#` composer file-suggestions silently wrong today; files/all is a time bomb | S | `knowledge.py:408`, `main.py:5346`, `Commands/Knowledge.svelte:117`, `Documents.svelte:296` |
| 13 | Route the six custom overlays through `common/Modal` (or add Escape + trap + `role="dialog"`), PrDrawer first | No keyboard exit from a PR-creation form; five more overlays same | M | `PrDrawer.svelte:214`, `GitHubRepoModal.svelte:127`, `DeepResearchModal.svelte:133`, `ConnectorsPanel`, `PluginsPanel`, notebook `[id]/+page.svelte:577` |
| 14 | Integrations panel staleness indicator when the 7s poll fails | Panel presents frozen data as live | S | `integrations/+page.svelte:119-131`, `apis/integrations/index.ts:6-17` |
| 15 | Contrast sweep: `dark:text-gray-600` visible text + `gray-500`-on-dark tiny type, measured per theme (Midnight/Airy/Warm) | ~2.35:1 computed on hint/meta text; 312 tiny-muted-text sites | M | `HotkeyHint.svelte:33`, `FileNav.svelte:1321`, `RepoRunnerSurface.svelte:308`, `vibecode/+page.svelte`, `PrDrawer.svelte` |

Deferred for a product decision (not fix tickets): Tier-2 `/admin`/`/workspace`/`/playground` surfaces — implement or hide the nav; Tier-3 flag-gated Channels/Notes/Calendar (add the missing `config.py` flags so direct-URL access doesn't hit broken pages); the 42 caller-less dead frontend fns (cleanup pass); heading/label semantics pass (fold into the next design-system sweep).