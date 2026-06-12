# Harvis Frontend — Current-State Assessment & Overhaul Scope

**Target:** `front_end/newjfrontend/` (Next.js app-router · Radix+CVA · Tailwind v4 OKLCH always-dark · Zustand · Vercel AI SDK · Monaco/xterm · React Flow)
**Date:** 2026-05-29
**Source:** 3-angle recon (UX surfaces, state/API wiring, design-system/subsystems).

---

## 1. Current-state assessment

**Verdict: functionally rich and visually polished, but architecturally scattered.** The product works and looks good; the problems are *clarity* (UX), *consistency* (design tokens), and *sprawl* (monolith components + duplicated state/fetching). The overhaul is **clarity + foundation hardening**, not an architectural rewrite.

Three axes:

| Axis | State | Headline issues |
|---|---|---|
| **UX** | Polished, multimodal, good bones | Workspace event viz is dense; reasoning panel buried; input buttons cramped; settings fragmented across 3 routes; VL-model gating happens *after* failure |
| **State / data layer** | Works, but 3 retry strategies + 2 SSE codepaths + per-store error state | **Auth-header gaps** (`/api/web-search`, `/api/openclaw/*` unauthenticated) — security + correctness; no central API client / user context |
| **Design system / components** | Solid Radix+Tailwind base | 14 hard-coded color tokens bypass CSS vars; 6 monolith files (DocumentGenerator **4846 LOC**, WorkspacePanel 1913, VoiceLibrary 998); dual full/compact UI duplication; 2 research renderers; likely-dead `MCPPluginManager` |

---

## 2. Keep — do NOT break what works

- **Chat ⟷ workspace split-view** + resizable + minimize affordance
- **Streaming / progressive message rendering** (Vercel AI SDK + memoized conversion)
- **Plugin system** (floating bubbles idle + full-page active)
- **Multimodal input** (voice, files, images, screenshare in one bar)
- **Dark OKLCH theme + Radix primitives + Geist + Lucide**
- **Sidebar** (sessions/recents/starred/artifacts, collapsible)
- **Agent graph** (React Flow, already well sub-divided)

---

## 3. Overhaul scope — phased by impact × effort

### Phase 1 — High-impact UX + the cheap security win (user-visible)
1. **Auth-header gaps** 🔴 — add Bearer to `/api/web-search`; audit/secure `/api/openclaw/*`. Security + correctness, small change. (Do regardless.)
2. **Settings consolidation** — collapse `/profile` + `/settings` + `/settings/openclaw` into one tabbed hub (General · API Keys · Workspace · Corpus · Security); `/profile` keeps name/email/avatar only.
3. **Workspace event visualization** — group events by phase (Init → Thinking → Execution → Results), collapse/expand, icons per event type, summary-first. (Core to Harvis's agent UX.)
4. **Reasoning panel** — always-visible "reasoned for Ns" affordance; inline expand instead of buried in the bubble. (Core "show thinking" value.)
5. **Input bar polish** — larger/clearer button roles, tooltips, focus state; **gate image/screenshare on a vision model** (disable + tooltip, not error-after-attempt).
6. **Model selector** — friendly names + size/status, refresh indicator, stop the 30s blind refresh.

### Phase 2 — Foundation (less visible, enables everything)
7. **Design tokens** — kill the 14 hard-coded `bg-[oklch|#...]`; extract `lib/designTokens.ts`; add a lint rule. Pick one research renderer (`ResearchBlock`), retire `research-chain`.
8. **Centralized API client + auth middleware** — one `ApiClient` (auto-inject Bearer, unified retry/timeout) replacing the 3 scattered strategies; **systematically closes the Phase-1 auth gaps**.
9. **One SSE abstraction** — merge `openclawStore.attachToWorkspaceStream` + `useApiWithRetry` getReader codepaths; add drop/recovery handling.
10. **Global user/error context** — single source for token+user; unified loading/error (toast/boundary) instead of per-store prop-drilling.

### Phase 3 — Refactor / de-sprawl (defer unless it blocks)
11. Split monoliths: `DocumentGenerator` (4846), `WorkspacePanel` (1913), `VoiceLibrary` (998), `MonacoVibeFileTree` (784), `VibeContainerCodeEditor` (712), `VibeCodeMiniIDE` (671) → focused sub-components.
12. Dedupe full/compact UI (shared state hook + `mode` prop).
13. Consolidate the 3 media players into one `useMediaPlayer` + `MediaPlayerControls`.
14. Resolve `MCPPluginManager` (complete or remove).
15. Mobile: safe-area + input-button reflow; empty-state context.

---

## 4. Scope reality

Full overhaul ≈ several sprints (recon estimated 3–4 for UX + ~10–15 days refactor). **Recommended first pass = Phase 1** (user-visible wins + the security fix) — high value, contained, doesn't require the foundation rewrite. Phase 2 hardens the base and is the right second pass. Phase 3 is maintainability, deferrable.

**Cross-link:** the `/api/openclaw/*` + `/api/web-search` auth gaps also appear in the engineering report's open items — fixing them here closes a real security loose end.

---

*Generated 2026-05-29 from frontend recon. Companion docs: engineering-troubleshooting-report, model-testing-and-difficulties.*
