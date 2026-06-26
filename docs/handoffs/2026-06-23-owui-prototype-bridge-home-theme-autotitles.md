# Handoff: OWUI prototype → production UI bridge — home, near-black theme, auto-titles (2026-06-23)

## Goal
The user reviewed a standalone React/Vite **UI prototype** (`front_end/harvis-ui-prototype/`,
served by Vite on **:5180**) and wants its look bridged onto the **real OWUI Svelte app**
(live at **:9000**, `front_end/owui`). The prototype is a whole visual system — near-black
background, cyan accent, clean sidebar, animated single-robot mascot, quirky randomized
greeting — not just the home.

## Workflow rule (LOCKED by the user — follow tomorrow)
Bridge **one feature at a time**. Before each feature, STOP and describe exactly what
you'll do; the user replies **merge-with-X** or **overwrite**. Do NOT bulk-implement.
Reviews stay ≤3 agents [[feedback_lean_reviews]].

## SHIPPED + VERIFIED on :9000 today (UNCOMMITTED on `harvis1.1` — NO push)

### 0. Prototype home polish (`:5180`, React) — the source of the bridge
- Installed the **UI UX Pro Max** skill at `~/.claude/skills/ui-ux-pro-max/` (real
  `data` + `scripts`, incl. the Design System Generator; symlinks were broken on first
  copy → re-installed with `cp -rL` to dereference).
- `App.tsx`: randomized quirky greeting (`GREETINGS[]` + `pickGreeting()`, some use the
  account name); compact centered pill starters; `HarvisMascot.tsx` = React port of the
  single animated robot (rAF bob / antenna / look-cycle / wave + click easter-egg).
- `styles.css`: gradient-sheen headline + fade-rise entrance + `prefers-reduced-motion`.

### 1. Chat home → real `Placeholder.svelte` (Feature 1, user chose MERGE on both forks)
- **Greeting**: quirky randomized set wired to the real `$user.name` (`_greetings[]` +
  `pickGreeting`), rendered in a **Harvis-blue gradient sheen** headline.
- **Subtitle**: "Ask anything, build, research, or plan." restored under the greeting.
- **Starter pills** (merged ABOVE the existing model suggestion prompts, gated on
  `enable_harvis_studio`): *Build something* → `/harvis/vibecode`, *Analyze files* →
  `/harvis/notebooks`, *Research topic* → `/harvis/notebooks`, *Plan a project* → seeds
  the composer (`prompt = 'Help me plan a project.'`).
- Mascot was already the single animated `HarvisMascot.svelte` — unchanged.

### 2. Near-black color scheme + UI background — `tailwind.css`
- Re-tuned the harvis-dark `--color-gray-*` ramp: dark end pulled toward the prototype's
  `#06080d` shell. `gray-800: oklch(0.2…)`, `850: 0.14`, `900: 0.095`, `950: 0.055`
  (hue nudged 255→260). Light/mid grays (text + light mode) unchanged → only dark mode
  (Harvis default) goes near-black. Whole app reads like the prototype now.

### 3. Sidebar polish (user: "merge — keep chat list, auto-named chats, no blue dots")
- **Blue dots removed**: deleted the `{#if unread}…bg-sky-500…` dot in `ChatItem.svelte`.
- **Auto-generated chat names**: see findings below — DONE + verified.

## Files changed (all uncommitted on `harvis1.1`)
```
M front_end/owui/src/tailwind.css                                      (near-black ramp)
M front_end/owui/src/lib/components/chat/Placeholder.svelte            (greeting+subtitle+pills+sheen)
M front_end/owui/src/lib/components/chat/Chat.svelte                   (auto-title client wire)
M front_end/owui/src/lib/components/layout/Sidebar/ChatItem.svelte     (blue dot removed)
M python_back_end/owui_compat/router.py                                (LLM title endpoint)
?? front_end/harvis-ui-prototype/                                      (the React prototype, untracked)
```

## Key findings (gotchas — also memory-pinned)
1. **`background-clip: text` is stripped by the production CSS minifier** — both
   hand-written CSS and Tailwind's `bg-clip-text` get dropped (computed
   `webkitBackgroundClip: "border-box"` → gradient fills the box, transparent text =
   invisible). FIX: put clip + gradient in an **inline `style`** (never minified); keep
   only the keyframe in `<style>`. Used a Harvis-blue gradient (reads on light + dark).
   [[reference_owui_bg_clip_text_minifier]]
2. **Auto-title needed THREE coupled fixes** (the facade is socket-less, so OWUI's
   server-side `background_tasks.title_generation` socket-push path is dead):
   (a) wire the **client** path in `Chat.svelte` `chatCompletedHandler` — on a new chat's
   first exchange call `generateTitle()` → `chatTitle.set` + `updateChatById(id,{title})`;
   (b) the facade `owui_title` endpoint MUST return `content = json.dumps({"title": …})`
   — `generateTitle` parses a `{...}` block and returns `null` for plain text;
   (c) the LLM call is a direct non-stream Ollama `POST /api/generate` with **NO num_ctx**
   (a mismatch vs the loaded `OLLAMA_CONTEXT_LENGTH=24576` forces a reload → ReadTimeout),
   60s timeout (fire-after-response), `think:false`, strip `<think>`, hard fallback.
   [[reference_owui_autotitle_facade]]

## Verification done
- :9000 home: near-black, gradient greeting ("Ready when you are."/"Yes, cisco?" etc.),
  subtitle, the 4 intent pills, single animated robot. Blue dots gone from chat list.
- Title endpoint returns real titles (e.g. `{"title":"Banana Bread Recipe"}`, 2.8s warm);
  `generateTitle` parses it; the wire fires on completion (the `/api/generate` call lands
  right after a chat completes) and the persist path sticks (manual replication confirmed,
  "Simple one word greeting" auto-titled in the list).

## PENDING / next steps (tomorrow)
1. **Sidebar nav structure merge** (the big remaining piece; user chose merge-keep-list):
   add the prototype's **Chat / Build / Knowledge / Agents** nav rows + a **System group**
   (Models / Cookbook / Integrations / Settings) + a **"Local stack ready"** footer, while
   KEEPING OWUI's New Chat / Search / full chat history. Touches `Sidebar.svelte`
   (load-bearing — has the mode switcher + pins + chat list); go carefully.
2. **Model name → into the composer "Auto" pill + always-auto** (user instruction): move
   the model indicator off the home into the Auto-pill slot in `MessageInput.svelte`, and
   lock the mode to Auto.
3. **Minor**: accent cyan (`#38bdf8` vs current blue), home radial glow.
4. **Verify** the banana-bread chat auto-titled on completion (model was still generating
   when the session ended — 9B on the 8GB GPU is slow).

## Standing rules
Branch `harvis1.1`; everything above is **uncommitted, NO push** until the user verifies
end-to-end [[feedback_no_push_until_verified]]. Deploy flow: backend (owui_compat is
bind-mounted) → `docker restart harvis-backend`; OWUI frontend → `npm run build` in
`front_end/owui` → `docker restart nginx-proxy` (nginx serves `front_end/owui/build`).
Edits land in **MAIN** `front_end/owui`, not the worktree.
