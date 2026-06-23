# Handoff — OWUI mode pill + Open Notebook nav into the sidebar + de-dup + rich Add-sources modal (2026-06-19)

**Branch:** `harvis1.1` · **All work UNCOMMITTED, NOT pushed** (standing rule: hold until the user says go).
**Verify surface:** Pop!_OS laptop at **`:9000`** (NOT the Windows rig). Driven live via the Claude-in-Chrome
browser MCP. Obsidian log: `notes-vault/code/harvis/2026-06-19-owui-mode-pill-notebook-nav-add-sources.md`;
running project note: `notes-vault/projects/mode-tabs-sidebar.md`.

## Goal
Continue OWUI-on-Harvis UI polish: organize the surfaces (Chat/Notebook/Code), pull Open Notebook's nav into
the Harvis chrome, de-clutter the sidebar, and bring the upstream open-notebook "rich Add-sources" modal into
our vendored fork.

## State — SHIPPED + browser-verified today (4 items)
1. **Mode pill = expand/collapse segmented control.** Active segment = icon+label (`grow`); inactive collapse
   to icon-only (~half width); animated. Also fixes the "Notebook" wrap. File: owui
   `src/lib/components/layout/Sidebar/ModeSwitcher.svelte`.
2. **Open Notebook nav moved into the Harvis left sidebar + full-width iframe.** Removed open-notebook's own
   right `AppSidebar`; new `Sidebar/NotebookNav.svelte` mirrors the nav and drives the iframe via a `?onb=`
   query param read by `notebooks/+page.svelte`. Pinned items hidden in Notebook mode.
3. **Sidebar redundancy de-dup.** Removed `vibecode` + `open-notebook` pins (dup the pill); hoisted
   `DEFAULT_PINNED_ITEMS` to new `Sidebar/pinned.ts` (Sidebar + UserMenu shared it); fixed the `workspace`
   label mismatch (UserMenu "Workspace" → "Library").
4. **Rich Add-sources modal built in the vendored fork.** New `AddSourceModal.tsx` (web search + drop zone +
   Upload/Websites/Drive/Copied text + N/50 capacity), wired to `onb_compat` (`useFileUpload`/`useCreateSource`);
   Drive = honest "not available yet". `SourcesColumn.tsx` "+ Add Source" now opens it directly. Verified
   Copied-text ingest E2E + capacity tick + Drive-unavailable + × close; no console errors.

## Files in flight (uncommitted on `harvis1.1`)
- **owui** (`front_end/owui`): `Sidebar/ModeSwitcher.svelte` · NEW `Sidebar/NotebookNav.svelte` ·
  NEW `Sidebar/pinned.ts` · `Sidebar.svelte` · `Sidebar/UserMenu.svelte` ·
  `routes/(app)/harvis/notebooks/+page.svelte`
- **open-notebook** (`front_end/open-notebook`): `components/layout/AppShell.tsx` ·
  NEW `components/sources/AddSourceModal.tsx` · `app/(dashboard)/notebooks/components/SourcesColumn.tsx`
- (Plus the long prior uncommitted pile from earlier OWUI/onb/citations sessions — see `git status`.)

## Deploy commands (both already applied; re-run if you re-edit)
- **owui:** `cd front_end/owui && npm run build && docker restart nginx-proxy`
- **open-notebook:** `cd <repo> && docker compose build open-notebook-ui && docker compose up -d --no-deps open-notebook-ui`
  (Next.js image rebuild + recreate `harvis-open-notebook`; ~few min; also type-checks the new TSX.)

## OPEN QUESTION — RESOLVED (2026-06-19)
**Add-sources modal title:** user said keep **"Add sources"**. Plus a polish pass landed + verified:
modal width forced to **600px via inline `style`** (Tailwind **v4** important is a suffix `w-[…]!`, not the
v3 prefix `!w-[…]` — the class never generated; inline style is version-proof), clean single-color title
(dropped the white+blue split), removed dotted underlines, restructured capacity footer; and the
Sources-column button is now a **full-width outline "Add sources" bar**. No open questions remain on the modal.

## Failed attempts / gotchas (so they aren't re-hit)
- **Add-sources diagnosis pivot:** the relay assumed the rich modal already existed in our fork ("just wire
  it"). It does NOT — it's the OFFICIAL `lfnovo/open_notebook` modal (running at `:8502`/`:8503`). Proof: its
  strings ("drop your files"/"Copied text"/"Upload files"/"Audio and Video Overviews") are **0 files** in
  `front_end/open-notebook`; our button opened the plain 3-step `AddSourceDialog` wizard. So it was a build.
  Don't try to redirect to a non-existent component again.
- **There are TWO official open-notebook containers running** (`open-notebook` :8502, `on-view-open_notebook-1`
  :8503, both `lfnovo/open_notebook:v1-latest`) kept for reference. Our fork (`open-notebook-ui`, :9000/onb)
  is an OLDER snapshot — porting upstream components risks version skew (why we built fresh).
- **Svelte `{#if}` indentation:** `Sidebar.svelte` uses tabs; Edit matches kept failing on guessed tab counts.
  Use `awk '{gsub(/\t/,"»");print NR": "$0}'` to reveal exact indentation before an Edit.
- **open-notebook has no local node_modules** — can't `tsc` locally; the Docker build is the type-check.

## Next steps (suggested order)
1. **Title decision** (above) → apply → rebuild open-notebook → quick re-verify.
2. **Optional modal polish** the user may want once they look: Websites/Upload paths (I verified Copied text +
   Drive live; Upload uses the existing `useFileUpload` path but the OS file-picker isn't browser-automatable;
   web search inside the modal is the same `SourceWebSearch` already proven in the column).
3. **Deferred de-dup items** (only if the user wants them): collapsed icon-rail mode-gate; remove the dead
   `/onb` branch in `Sidebar.svelte::navMenuItem`.
4. **Eventually: the push.** Large verified pile on `harvis1.1` — when the user says go, review `git status`,
   group commits sensibly, push. Until then, keep holding.

## Standing rules
`harvis1.1`; no push until user-verified; build/verify on the laptop (:9000); Harvis theme tokens only;
never fabricate (Drive = honest unavailable); the onb embed stays an iframe (not made native).
