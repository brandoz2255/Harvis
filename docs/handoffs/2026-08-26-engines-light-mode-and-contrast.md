# Handoff — the Engines tab logos were invisible in light mode, and half its text failed contrast

**Date:** 2026-08-26
**Branch:** `test/fresh-clone-2026-08-23` @ `eb7a3f67` (main checkout)
**State:** implemented, built, deployed to the dev box, verified in both themes — **uncommitted**
**Surface:** `/harvis/integrations` (the Engines tab) and every panel it mounts

---

## 1. What was actually wrong

The report was "the logos need more colour in light mode." That turned out to be three separate
defects that happened to land on the same page. None of them were a colour-choice problem.

**1. Six vendored marks ship as solid `fill="#FFFFFF"` and were rendered through `<img>`.**
`openai`, `ollama`, `github`, `mcp`, `opencode` and `hermes` in `static/integrations/` are
single-path white glyphs. In dark mode they sit on a dark tile and read fine. In light mode the
tile is `bg-emerald-50` / `bg-slate-100` / `bg-gray-100` — white on near-white, so the mark was
simply not there. **An `<img>` cannot be recoloured**, so no amount of tint work on the tile could
have fixed it.

**2. Six free-tier providers had no `TILE_TINT` row at all.**
`TILE_TINT` in `status.ts` is what the Engines page actually paints with (`tileTint()`, consumed by
`ControlCard` and `FeaturedProviderCard`). It had no entry for `groq`, `cerebras`, `gemini`,
`nvidia`, `mistral`, `openrouter` or `harvis`, so all seven fell through to the grey fallback — in
**both** themes. This didn't look broken, it looked deliberate, which is why it survived so long.

**3. `BRAND_TONE` was written dark-only.**
The map in `catalog.ts` (used by `IntegrationDetailModal` and `FreeKeysGuide`, both live) hardcoded
a `bg-[#0e1320]` chip and `-400` icon steps. On a white modal that is a black square holding a
washed-out icon.

Separately, a contrast sweep of the same surface found 38 instances of text below the WCAG floor.
`text-gray-400` (#9ca3af) on white is ≈2.5:1 against a 4.5:1 requirement for body text.

## 2. What changed

| File | Change |
|---|---|
| `lib/integrations/BrandGlyph.svelte` | Split the vendored marks into `MONO_LOGOS` (the six white ones) and `COLOR_LOGOS` (`claude`, `discord`, `openclaw` — these carry their own brand colour or their own dark ground and read on both). Mono marks now render as a `<span>` painted through `-webkit-mask-image`/`mask-image` with `background-color: currentColor`, so the SVG file stays the source of truth and only the colour comes from the tile. |
| `lib/integrations/status.ts` | Added the seven missing `TILE_TINT` rows, each approximated to the vendor's own hue, with a comment saying that every `brandKey` in the catalog needs a row here because the fallback fails silently. |
| `lib/integrations/catalog.ts` | `BRAND_TONE` and `LOGO_TILE` rewritten light-first with `dark:` variants. `bg-[#0e1320] border-white/10` is gone as an unconditional value. |
| 11 files across `lib/integrations/` + `routes/(app)/harvis/integrations/+page.svelte` | 38 contrast fixes: bare `text-gray-400` → `text-gray-500 dark:text-gray-400`; the seven `text-gray-400 dark:text-gray-500` pairs (weak in *both* themes) flipped; one `placeholder:text-gray-400`. `ControlCard`'s chevron went from `gray-300`/`gray-600` to `gray-400`/`gray-500` so the affordance is visible before hover. |

Total: 14 files, +136/−78.

**Why a CSS mask and not a recoloured copy of each SVG:** the vendored files are the vendors'
official marks. Forking them into tinted duplicates means every future logo update has to be
applied twice and the two drift. The mask keeps one file and moves the colour decision into the
tint system, where it already belonged.

## 3. Verified

Built in the main checkout, `docker compose restart nginx`, then checked live — not inferred from
the build exiting 0, which on this repo is [not evidence](2026-08-23-video-artifacts-and-the-verification-sweep.md).

- Build genuinely ran: 22 files emitted, zero `SIGKILL` / heap / "already present" markers.
- New strings present in the bundle: `brand-mask` ×3, `text-lime-700 dark:text-lime-400` ×4,
  `bg-violet-50 dark:bg-violet-500/10` ×2, `placeholder:text-gray-500` ×8. Old
  `bg-[#0e1320] border-white/10` → 0 hits.
- Mask CSS shipped as `_app/immutable/assets/BrandGlyph.Bs4ShIGG.css`.
- Live DOM probe: 5 masked elements, real computed colours — openai emerald
  `oklch(0.596 0.145 163.225)`, hermes violet, mcp amber, ollama slate — all 20px.
- Light-mode screenshots: every tile carries its brand hue (Claude orange, Codex CLI emerald, Kimi
  purple, OpenClaw lobster, Hermes violet, Groq orange, Cerebras amber, Gemini sky, NVIDIA lime,
  Mistral rose, OpenRouter violet, MCP amber, SSH teal, Ollama slate, GitHub dark-grey, Discord
  indigo). Zooms confirm the masked marks render as the correct shapes, not blocks.
- Dark mode reloaded and compared: unchanged. Ollama and GitHub marks are still white there.
- Free Keys guide modal in light mode: all six providers brand-tinted, previously all on `#0e1320`.

**Not verified:** the test VM (192.168.4.201) has not received this change — it is still at
`eb7a3f67` from the previous deploy.

## 4. Found while working, not fixed

- **594 bare `text-gray-400` across 127 files app-wide** — the same defect class, outside the
  Engines tab. Heaviest: `ConnectorsPanel` 34, `vibecode` 29, `CadExplorer` 24, `PluginsPanel` 23,
  `knowledge` 18, `Cookbook` 15, `McpWizard` 15. Deliberately left alone: `lib/cad/*` holds live
  uncommitted work and a blind regex sweep across it would be reckless.
- **`IntegrationCard.svelte` and `IntegrationRow.svelte` are dead code** — nothing imports either.
  They still carry `text-amber-500/80` on white (≈2.2:1). They got the contrast pass anyway because
  the sweep was path-scoped; deleting them is the better fix.
- **`TILE_TINT` (`status.ts`) and `BRAND_TONE` (`catalog.ts`) are two tint systems for the same
  brands.** They cannot simply be merged: `status.ts` already imports from `catalog.ts`, so
  unifying them means inverting that dependency. Left as-is with a comment on each pointing at the
  other.
