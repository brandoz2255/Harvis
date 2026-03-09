# Harvis Agentic Expansion Plans

## Overview

OpenClaw is the agent runtime backend for Harvis. Beyond vibe coding, the goal is to give Harvis
a full suite of named agent backends — each scoped, secure, and routable by the Kimi K2.5 planner.
Users talk to Harvis naturally; Harvis routes to the right agent; results surface back in chat as
rich UI (cards, maps, documents, spoken summaries).

---

## ✅ Completed Work

### OpenClaw Stability Fixes (March 2026)

| Commit | Fix |
|--------|-----|
| `86f202b` | ✅ Raised sub-agent timeouts — `agents.defaults.timeoutSeconds: 600`, `subagents.runTimeoutSeconds: 600`, `subagents.announceTimeoutMs: 180000` |
| `f9220e3` | ✅ Fixed skill invocation — reads `/skills/<name>/SKILL.md`, not exec skill name |
| `3e7fc91` | ✅ Removed invalid `systemPrompt` key from `agents.list` |
| `3da7960` | ✅ `commands.bash=true` — exec tool unblocked |
| `3da7960` | ✅ SSRF allowlist — internal backend URLs whitelisted |
| `3da7960` | ✅ `harvis-soul` skill added (`always: true`) — personality anchor + tool truth |
| `fix(openclaw)` | ✅ `runTimeoutSeconds` moved under `agents.defaults.subagents` (correct schema path) |
| `fix(model-proxy)` | ✅ httpx timeouts raised to 600s (non-streaming + streaming) — stops proxy dropping slow local Kimi calls |

### Skills Library

| Skill | Status | Purpose |
|-------|--------|---------|
| `harvis-soul` | ✅ always-on | Personality, tool truth, anti-hallucination |
| `harvis-agent` | ✅ live | General Harvis agent behavior |
| `harvis-github` | ✅ live | PR workflow, co-author trailer, repo allowlist |
| `harvis-rag` | ✅ live | pgvector RAG search |
| `harvis-research` | ✅ live | Research + web-fetch proxy |
| `harvis-document` | ✅ live | DOCX/PDF document generation |
| `harvis-vibecoding` | ✅ live | Full tool guide: read/edit/write/apply_patch/exec/process/memory/subagents/image/git/PR |

### Discord Integration

| Phase | Status |
|-------|--------|
| Phase 1 — OpenClaw native Discord channel | ✅ DONE — secret, config, NetworkPolicy 443 egress, env var mount |
| Exec approval wall | ✅ FIXED — `elevatedDefault: "full"` |

### PR #57 — python-docx + kubectl proxy (merged March 2026)

| Item | Status |
|------|--------|
| Init container installs `python-docx` into `/python-extra` volume | ✅ MERGED |
| `PYTHONPATH=/python-extra` on OpenClaw main container | ✅ MERGED |
| `workspace/kubectl_proxy.py` — FastAPI router with auth, allowlist, secret redaction, 30s timeout | ✅ MERGED |
| `main.py` registers `kubectl_proxy_router` | ✅ MERGED |
| Duplicate dead-code `kubectl_proxy.py` removed | ✅ CLEANED |

### Harvis Planner Agent

| Item | Status |
|------|--------|
| `harvis_planner.md` — dedicated system prompt for web app agent | ✅ CREATED |
| `harvis-vibecoding` skill — full tool guide for coding tasks | ✅ LIVE |
| `harvis-planner` agent added to `openclaw.yaml` with dedicated system prompt | ✅ LIVE |

---

## 🔜 What's Next

### 1. Apply PR #57 K8s Changes + Verify

After merging PR #57, apply the kubectl RBAC manifest and verify both features:

```bash
# Apply RBAC for kubectl reader ServiceAccount
kubectl apply -f k8s-manifests/services/harvis-kubectl-rbac.yaml

# Argo sync (or via GUI)
argocd app sync harvis-ai --force

# Verify python-docx
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- \
  python3 -c "import sys; sys.path.insert(0,'/python-extra'); import docx; print('python-docx OK')"

# Verify kubectl proxy health
kubectl -n ai-agents exec deployment/harvis-ai-merged-ollama-backend -- \
  curl -s http://localhost:8000/kubectl/health
```

Then test from Discord: "create a short test document as docx" and "what pods are running?"

### 2. Discord kubectl ServiceAccount + RBAC

The `k8s-manifests/services/harvis-kubectl-rbac.yaml` was planned in Harvis.md.
Harvis needs to create this file and the OpenClaw pod needs `serviceAccountName: harvis-kubectl-reader`.
See new `Harvis.md` for the task.

### 3. Research Agent Web-Fetch Proxy

Backend endpoint `POST /api/tools/web-fetch` — sanitizes content before it reaches OpenClaw LLM.
Required before Research Agent can safely browse the web.

Security model: URL validation → fetch → strip HTML/scripts → truncate 8k tokens → audit log.

### 4. Harvis Planner Agent (Non-Discord)

✅ `harvis_planner.md` created — dedicated system prompt for the web app agent.
The planner agent uses Kimi K2.5 and has disciplined skill-read-before-act workflow.
Reduces hallucination vs Discord (Discord accumulates bad chat history).

Next: wire the web app chat UI to send requests to `agent_id: "planner"` instead of `main`.

### 5. Document Agent — DOCX end-to-end

With python-docx now installed (PR #57), test `create_docx` tool end-to-end:
- Research → outline → `create_docx` → download card in chat UI

### 6. Maps Agent — `/api/agent/maps`

Backend proxy: `POST /api/tools/maps` → Google Maps API (key stays in backend).
Frontend: `MapCard.tsx` with embedded map + location cards.

### 7. Discord Phase 2 — Harvis Backend Bridge

`discord.py` listener in Python backend → forwards to `/api/chat` with full history + JWT.
Gives Discord full Harvis persona + memory (not just raw OpenClaw).

### 8. Rich Discord Responses (Phase 3)

Code blocks, file attachments (DOCX/PDF), slash commands: `/harvis`, `/research`, `/workspace`.

---

## Agent Backends to Build

### 1. DevOps / K8s Ops Agent — `/api/agent/devops`
**Trigger phrases**: "is everything healthy", "check logs", "what's broken", "deploy staging"

**What it does**:
- Runs kubectl commands via `workspace/kubectl_proxy.py` (already built ✅)
- Tail and analyze container logs, spot anomalies
- Trigger deployments, monitor rollout, report back verbally via TTS
- Cluster health summaries on demand

**Security model**: OpenClaw → `POST /kubectl/exec` on Harvis backend → kubectl (read-only).
Backend validates token + allowlist before running any command.

---

### 2. Research Agent — `/api/agent/research`
**Trigger phrases**: "research", "write me a paper on", "deep dive", "academic summary of"

**Flow**:
1. Planner (Kimi K2.5) breaks topic into 3-5 research angles
2. Parallel sub-agents each research one angle using `local_rag` + web-fetch proxy
3. Writer agent synthesizes into full paper structure
4. `create_docx` / `create_pdf` generates formatted output (python-docx now installed ✅)
5. Chat UI shows download card + inline summary

---

### 3. Code Agent — `/api/agent/code` (Vibe Coding — mostly built ✅)
**Uses**: `harvis-vibecoding` skill + `harvis-github` skill
**Flow**: planner → coder → tester → PR opened via harvis-github skill

---

### 4. Document Agent — `/api/agent/docs`
**Uses**: `harvis-document` skill (live ✅) + python-docx init container (live ✅)
**Output**: DOCX/PDF download card in chat

---

### 5. Maps Agent — `/api/agent/maps`
**Backend proxy needed**: `POST /api/tools/maps`
**Frontend card needed**: `MapCard.tsx`

---

## Web Research Security Model

OpenClaw never fetches external URLs directly — all go through the Harvis backend proxy:

```
OpenClaw exec: curl POST http://harvis-ai-merged-backend:8000/api/tools/web-fetch
  → Backend: validate URL (blocklist, no RFC-1918)
  → Backend: fetch, extract main text, strip scripts/hidden divs
  → Backend: truncate to 8k tokens
  → Backend: audit log
  → Return: clean plain text only
```

---

## UI Plans

### OpenClaw Workspace Panel
- Wire `OpenClawWorkspace.tsx` into main jfrontend chat
- Live sub-agent status sidebar

### Rich Result Cards
- `ResearchCard.tsx` — summary + download for DOCX/PDF
- `DocumentCard.tsx` — file preview + download
- `MapCard.tsx` — embedded Google Map + location cards

---

## Co-Authoring System

Every PR Harvis opens includes:
```
Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>
```

---

## Implementation Order (Updated)

1. ~~**Co-authoring**~~ ✅ Done — always included
2. ~~**Discord Phase 1**~~ ✅ Done
3. ~~**Exec approval wall**~~ ✅ Done
4. ~~**OpenClaw stability fixes**~~ ✅ Done
5. ~~**harvis-vibecoding skill**~~ ✅ Done
6. ~~**Fix create_docx (python-docx)**~~ ✅ Done (PR #57)
7. ~~**kubectl proxy backend**~~ ✅ Done (PR #57)
8. **Apply PR #57 K8s (RBAC + ServiceAccount)** — Harvis task, see Harvis.md
9. **Harvis planner agent wired to web UI** — send `agent_id: "planner"` from chat
10. **Research Agent web-fetch proxy** — backend endpoint + SKILL.md update
11. **Document Agent end-to-end** — test create_docx + download card UI
12. **Maps Agent** — backend proxy + MapCard.tsx
13. **Discord Phase 2** — backend bridge with full chat history
14. **Discord Phase 3** — rich responses, slash commands
15. **File Agent** — sandboxed shell scope
16. **DevOps Agent (full)** — K8s proxy + cluster health summaries

---

## Security Principles (All Agents)

1. OpenClaw never holds API keys — all external calls proxied through Harvis backend
2. Per-agent tool allowlists — each agent gets only what it needs
3. Orchestrator approval gate — Harvis backend inspects every tool call
4. No outbound internet from OpenClaw except Discord gateway (TCP 443)
5. kubectl access via read-only ServiceAccount only
6. Rate limiting on all write operations
7. All agent activity logged for audit trail
