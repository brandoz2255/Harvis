# Neural Map — knowledge-graph design (v1 / v1.5 / v2)

Status: v1 shipping (2026-06-11, branch `harvis1.1`) · v1.5 scoped-not-built · v2 idea-only
Owner surfaces: `front_end/owui/src/lib/agent-studio/GlobalMap.svelte` (registry key `global-map`,
label **Neural Map**, nested under **Brain**).

## Vision

An Obsidian-graph-view-style map of everything Harvis does for you: sessions, agent runs, and —
project-scoped, on demand — memories and notebook knowledge. Small dots, thin links, organic
force layout. The principle locked with the user:

> **Default sparse and readable; drill into a project for the rich web; never auto-overlap the
> two unless the user asks.** Graph density scales with scope; memory is opt-in.

## v1 — sessions + runs, account-wide (THIS BUILD)

- **Session = hub node.** Each chat session is a hub dot (radius grows log-ish with run count).
- **Run = spoke node**, edged to its session hub. Status-colored (running=pulsing blue, done=blue,
  error=red, cancelled=amber); radius scales with `tool_calls`.
- **Edges are required** — the Obsidian look depends on links. A no-edge render means
  session→run linking didn't wire (verification gate).
- Runs with no `session_id` float free (no fake hub, no edge).
- **No memory nodes in the account-wide view, EVER — by design**, not a limitation. Memory is
  project-scoped and opt-in (v1.5).
- Data: `GET /api/workspace/history` (existing; fields `id, session_id, task_brief, status,
  duration_ms, tool_calls, …`). **Window caveat:** history is LIMIT 20, so "account-wide" =
  last-20-runs-wide. A `?limit=` backend param is an explicit non-goal of this frontend build;
  add it later if the graph needs more depth.
- Layout: static `d3-force` simulation (forceLink/manyBody/collide + weak centering), ticked to
  convergence synchronously, positions fed into the existing SvelteFlow canvas
  (`WorkflowCanvas`/`WorkflowFlow`) with a new `neural` dot-node type. Deterministic-enough;
  fitView-once keeps it jump-free.
- Clicks: run dot → `/harvis/agent-studio/run/{id}`; session hub → `/c/{session_id}`
  (`discord-*` hubs inert).

## v1.5 — project-scoped memory layer (SCOPED, NOT BUILT)

When the user is inside a project, a memory layer unlocks: a Memory hub + memory-entry nodes for
**that project only**, linked in. **Opt-in cross-link** — memory edges do NOT auto-wire; the user
pulls them in via a toggle/expand. One project's memory web must not bleed into another's or into
the account-wide view.

### The blocking finding (resolved 2026-06-10 — do not re-derive)

Memory is **global per-user and untagged** today:

- Storage: `harvis_user_memory(user_id, content, source, metadata)` —
  `python_back_end/plugins/memory/builtin/provider.py` (INSERT at ~:74). `metadata` is free-form
  JSONB; **nothing writes a project/workspace/session association into it**.
- The manual route `POST /api/memory` (`plugins/memory/routes.py:69-78`) ACCEPTS `metadata`, but
  the UI (`MemoryPanel.svelte`) calls `addMemory(token, content, 'manual')` with none.
- The one session-aware path exists but is dead: `plugins/messaging/dispatcher.py:376-380` calls
  `provider.extract_from_session(user_id, session_id, messages=[final_summary])` after workspace
  runs — and the builtin provider does not implement it, so it falls to the base-class **no-op
  returning []** (`plugins/memory/provider.py:88-98`). No memory is ever written from sessions.

→ "Show only this project's memory" is **not possible yet**. Do NOT fake project-scoping by
heuristically guessing which global entries "belong" to a project — that mislabels.

### Prerequisite backend task (small, well-defined — its own change)

1. **Tag at write time**: builtin provider implements `extract_from_session` →
   `remember(..., source='session', metadata={'session_id': <id>})`; the plumbing already passes
   `session_id` in. Manual path: UI includes `metadata.session_id` (current chat) on
   `POST /api/memory` — the body already accepts it.
2. **Filter at read time**: `session_id`/project filter on `GET /api/memory`
   (`metadata->>'session_id'`; promote to a real column + index if volume grows).
3. **UI**: per-project opt-in toggle that pulls the memory layer into the project's Neural Map.
   Never wired into the account-wide view.

v1 ships independently of all of this — the sessions+runs graph doesn't touch memory.

## v2 — Open-Notebook tie-in (IDEA, documented per user request)

Harvis has a **real** Open Notebook backend (`python_back_end/notebooks/router.py`, prefix
`/api/notebooks`): notebook CRUD; sources (PDF/text/URL/YouTube/audio/…) with chunking + vector
embeddings + processing-status; notes; LLM transformations (summarize/key-points/outline/…);
RAG chat over sources; podcast generation — orchestrated via LangGraph
(`python_back_end/open_notebook/`).

**The idea:** a project links a notebook; the notebook's sources and notes become graph nodes
edged into that project's Neural Map — alongside (and cross-linkable with) the v1.5 memory layer.
The graph becomes the visual index of what the project *knows*: sessions ↔ runs ↔ memories ↔
notebook sources/notes.

Open questions to resolve before building:
- **Project ⇄ notebook association model** — same unknown as memory scoping: what is "a project"
  in data terms (a session? a folder of chats? a new entity)? Notebooks have ids; the link table
  doesn't exist yet.
- **Node-count limits / clustering** — a notebook can have hundreds of chunks; graph nodes should
  be sources/notes (not chunks), with expand-on-demand.
- **Edge semantics** — containment-only (notebook→source) first; similarity edges (vector
  proximity between memory ↔ source chunks) are a later, gated enhancement.
- Reuse: same `sessionsToGraph`-style adapter + `neural` node type; only the data assembly grows.

## Rollout & risks

- v1 rides the existing SvelteFlow canvas — no new heavy deps (`d3-force` resolves to the copy
  already in node_modules via vega).
- The renamed surface keeps registry key `global-map` (the `$workspaceControlsTab` bridge and the
  existing route keep working); `/harvis/agent-studio/neural-map` is an alias.
- d3-force layouts are stable but not bit-identical across refetches; fitView runs once per mount
  so there's no visible jump.
- ChatControls (the dock) is the gated file — the Neural Map nesting there ships behind the
  workspace-run regression gate; the full-page surface + Brain card ship regardless.
