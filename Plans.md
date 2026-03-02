# Harvis Agentic Expansion Plans

## Overview

OpenClaw is the agent runtime backend for Harvis. Beyond vibe coding, the goal is to give Harvis
a full suite of named agent backends — each scoped, secure, and routable by the Kimi K2.5 planner.
Users talk to Harvis naturally; Harvis routes to the right agent; results surface back in chat as
rich UI (cards, maps, documents, spoken summaries).

---

## Agent Backends to Build

### 1. DevOps / K8s Ops Agent — `/api/agent/devops`
**Trigger phrases**: "is everything healthy", "check logs", "what's broken", "deploy staging"

**What it does**:
- Runs kubectl commands, parses pod/service/node status
- Tail and analyze container logs, spot anomalies
- Trigger deployments, monitor rollout, report back verbally via TTS
- Cluster health summaries on demand

**Security model (CRITICAL — no master node access)**:
- OpenClaw does NOT get kubeconfig or direct cluster access
- A lightweight **K8s proxy service** sits between OpenClaw and the cluster
- Proxy exposes only safe read-only endpoints: pod status, logs, events, resource usage
- Write operations (deploy, restart) require an explicit allowlist and are rate-limited
- OpenClaw calls the proxy over internal Docker network only — never touches kube API directly
- Proxy validates every command against an allowlist before forwarding to kube API
- Harvis backend acts as the second gate — orchestrator approves the tool call before OpenClaw executes

```
Harvis Backend (orchestrator)
  → approves tool call
    → OpenClaw tool: k8s_proxy(command)
      → K8s Proxy Service (internal only)
        → Kubernetes API (read-only or allowlisted writes)
```

**Allowed proxy commands**:
- `get_pods`, `get_services`, `get_nodes` (read)
- `get_logs(pod, tail=100)` (read)
- `get_events` (read)
- `restart_pod(pod)` (write, allowlisted)
- `scale_deployment(name, replicas)` (write, requires confirmation)

---

### 2. Research Agent — `/api/agent/research`
**Trigger phrases**: "research", "write me a paper on", "deep dive", "academic summary of"

**What it does**:
- Multi-step academic-style research (~5 minutes of autonomous work)
- Sub-agents each tackle a different angle of the topic in parallel
- Synthesizes findings into a structured report
- Exports a formatted DOCX or PDF with:
  - Abstract
  - Introduction
  - Methodology / Background
  - Key Findings (with citations from local RAG or provided sources)
  - Analysis
  - Conclusion
  - References section

**Flow**:
1. Planner (Kimi K2.5) breaks topic into 3-5 research angles
2. Parallel sub-agents each research one angle using `local_rag` + `read_docs`
3. Writer agent (Kimi K2.5) synthesizes into full paper structure
4. `create_docx` / `create_pdf` tool generates formatted output
5. Chat UI shows download card + inline summary

**Output in chat**: Document card with download link + spoken abstract via TTS

---

### 3. Code Agent — `/api/agent/code` (Vibe Coding, already partially built)
**Trigger phrases**: "fix this bug", "refactor", "write a function for", "add a feature"

**What it does**:
- Reads repo context, writes/modifies code, runs tests, opens PR
- Multi-agent: planner → coder → tester → reviewer
- PR opened under harvisai-dulc3-cmd with co-author trailer (see Co-Authoring section)

**Allowed tools**: `repo_read`, `repo_write`, `run_code`, `run_tests`

---

### 4. Document Agent — `/api/agent/docs`
**Trigger phrases**: "write a report", "generate a changelog", "export as PDF", "summarize this week"

**What it does**:
- Reads git log, tickets, notes and composes structured documents
- Weekly/sprint summaries, changelogs, release notes
- Exports DOCX or PDF, surfaces download card in chat

**Allowed tools**: `repo_read`, `create_docx`, `create_pdf`

---

### 5. File & Data Agent — `/api/agent/files`
**Trigger phrases**: "organize", "rename", "convert", "analyze this CSV"

**What it does**:
- File system operations: organize, rename, bulk transform
- CSV/data analysis with structured output (tables in chat)
- Generate charts or formatted summaries from data files

**Allowed tools**: `run_code`, `create_docx`, shell (restricted to workspace dir only)

---

### 6. Google Maps / Trip Planning Agent — `/api/agent/maps`
**Trigger phrases**: "plan a trip", "find locations near", "route from X to Y", "restaurants in"

**What it does**:
- Takes a user request (e.g. "plan a weekend trip to Big Bear")
- Queries Google Maps API via Harvis backend proxy (OpenClaw never hits Maps directly)
- Returns structured location data: name, lat/lng, description, category, hours
- Chat UI renders: embedded map + location cards with details
- Can chain: find hotels → find restaurants → build itinerary → export as DOCX

**Security**: OpenClaw calls `/api/tools/maps` on Harvis backend → backend calls Google Maps API
OpenClaw never has the Maps API key. Key stays in Harvis backend env only.

**Output in chat**: Interactive map embed + swipeable location cards

---

## Planner Routing Table

The Kimi K2.5 planner routes user messages to the right agent backend:

| Keywords / Intent | Routed To |
|-------------------|-----------|
| deploy, logs, pods, cluster, healthy, broken | `/api/agent/devops` |
| research, paper, academic, deep dive, explain | `/api/agent/research` |
| fix, build, refactor, PR, commit, code | `/api/agent/code` |
| report, changelog, export, summarize, PDF | `/api/agent/docs` |
| organize, rename, files, CSV, data | `/api/agent/files` |
| trip, locations, map, route, restaurants, hotels | `/api/agent/maps` |

---

## UI Plans

### OpenClaw Workspace Panel (Phase 1 — already planned)
- Wire existing `OpenClawWorkspace.tsx` into main jfrontend chat
- Live sub-agent status sidebar: shows which agents are running, done, failed
- Real-time event log per agent

### Rich Result Cards in Chat (Phase 3 — already planned)
- Location cards + map embed for Maps agent
- Document download cards for Research/Docs agent
- Code diff preview for Code agent PR results
- Table rendering for File/Data agent

---

## Co-Authoring System

**Goal**: Every PR/commit Harvis makes also shows your GitHub contribution — no personal token needed.

**How it works — Git `Co-authored-by` trailer**:
GitHub recognizes this commit message footer and credits both authors:
```
feat: add trip planning agent

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>
```
This shows up on GitHub as two green contribution squares — one for harvisai-dulc3-cmd, one for you.
Your token is never used. Harvis just includes your name + noreply email in the commit message.

**Implementation**:
- Add `HARVIS_COAUTHOR_TRAILER` env var to backend:
  ```
  HARVIS_COAUTHOR_TRAILER=Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>
  ```
- Harvis backend appends the trailer to every commit message before OpenClaw commits
- All PRs opened by harvisai-dulc3-cmd will show you as co-author automatically

**Your noreply email** (from git log): `124217011+brandoz2255@users.noreply.github.com`
GitHub noreply emails keep your real email private and still register contributions.

---

## Security Principles (Applies to All Agents)

1. **OpenClaw never holds API keys** — all external API calls proxied through Harvis backend
2. **Per-agent tool allowlists** — each agent type only gets the tools it needs
3. **Orchestrator approval gate** — Harvis backend inspects every tool call before execution
4. **No outbound internet from OpenClaw pod** — all external calls go through backend proxy
5. **K8s ops require proxy** — OpenClaw never touches kube API directly
6. **Rate limiting** on all write operations
7. **All agent activity logged** to `workspace_events` table for audit trail

---

## Mobile Access — Messaging Channels

### Instagram DM Integration
**Goal**: Message Harvis from Instagram when away from home, just like Telegram.

**Approach**: `instagrapi` (Python, unofficial Instagram private API)
- Instagram has no official bot API for personal accounts — instagrapi reverse-engineers the private API
- Simulates a real user session logging in and polling DMs
- **Ban risk for this setup: very low** — private account, single user, low message volume. Instagram
  targets spam/mass-message bots. A personal bot with one user is invisible to their detection.

**Architecture**:
```
You (Instagram DM)
  → instagrapi listener (polls for new DMs)
    → Harvis backend /api/chat
      → Response sent back as Instagram DM reply
```

**Implementation**:
- Add `instagrapi` to Python backend requirements
- Background polling loop checks for new DMs every ~10-15 seconds
- On new DM: forward to `/api/chat`, send response back as DM reply
- Instagram credentials stored in K8s secret (separate from openclaw secret)
- Session persistence: save instagrapi session to disk to avoid repeated logins (reduces ban risk)

**OpenClaw channel option**: OpenClaw has a `channels` system in its config (currently `channels: {}`).
If OpenClaw ever adds an Instagram channel driver, this could be handled natively. For now,
the instagrapi Python approach in the Harvis backend is the practical path.

**Telegram already works** — Instagram would be a second mobile channel alongside it.

**Credentials needed**:
- `INSTAGRAM_USERNAME` — the Harvis Instagram account username
- `INSTAGRAM_PASSWORD` — password for the account
- Keep it a private account, only follow yourself

---

## Implementation Order (Suggested)

1. **Co-authoring** — quick env var + commit message change, immediate value
2. **Research Agent** — high value, uses existing tools (`local_rag`, `create_docx`), no new infra
3. **Document Agent** — very similar to research, quick add-on
4. **Maps Agent** — needs Google Maps API key + proxy endpoint + chat UI map component
5. **Instagram DM** — add instagrapi listener, wire to /api/chat, low effort high value for mobile
6. **File Agent** — needs sandboxed shell scope, slightly more security work
7. **DevOps Agent** — needs K8s proxy service built first, most complex but coolest feature
