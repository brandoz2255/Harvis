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

### Discord Integration (replaces Instagram — official API, no ban risk)
**Goal**: Message Harvis / OpenClaw from Discord on mobile — DMs or a private server channel.

**Why Discord instead of Instagram**:
- Official bot API — no reverse-engineering, no ban risk, no Meta rate-limit headaches
- OpenClaw has a native Discord channel driver (configured in `openclaw.json`)
- Pairing is built-in: DM the bot → it shows a code in terminal → `openclaw pairing approve discord <code>`
- Supports DMs and private channels; full markdown + file attachment responses

**Bot token**: stored in `k8s-manifests/overlays/prod/openclaw-secret.yaml` under `discord-bot-token`
(gitignored — apply with `kubectl apply -f openclaw-secret.yaml`)

**Architecture** (two paths — use whichever fits the task):

```
Path A — OpenClaw native Discord channel (agent tasks):
  You (Discord DM / channel mention)
    → OpenClaw Discord channel driver (ws://harvis-ai-openclaw:18789)
      → agent runs tool loop (exec, write, RAG search, etc.)
        → response sent back as Discord message

Path B — Harvis backend bridge (chat + voice context):
  You (Discord DM)
    → discord.py listener in Harvis Python backend
      → /api/chat (carries full chat history + JWT session)
        → response sent back as Discord message reply
```

Path A = pure agent tasks ("run this script", "search the codebase").
Path B = full Harvis conversational context (history, TTS pipeline, persona).

---

### Discord Implementation Phases

#### Phase 1 — OpenClaw native Discord channel ✅ DONE
OpenClaw supports Discord natively via its `channels` config block.

**What was done**:
**Files changed**:
- `k8s-manifests/overlays/prod/openclaw-secret.yaml` — `discord-bot-token`, `discord-allowed-user-id` added (gitignored ✓)
- `k8s-manifests/overlays/prod/openclaw.yaml` — three changes:
  1. ConfigMap `openclaw.json`: `channels.discord` block added with token + allowedUserIds
  2. Deployment: `DISCORD_BOT_TOKEN` env var mounted from secret
  3. NetworkPolicy: egress rule added for outbound TCP 443 to non-RFC-1918 IPs (Discord/Cloudflare gateway)

**To activate** (apply the updated secret + config, then roll the pod):
```bash
# 1. Re-apply the secret with the new discord fields
kubectl apply -f k8s-manifests/overlays/prod/openclaw-secret.yaml

# 2. Re-apply the openclaw manifest (ConfigMap + NetworkPolicy + Deployment update)
kubectl apply -f k8s-manifests/overlays/prod/openclaw.yaml

# 3. Restart the pod so it picks up the new env var and config
kubectl rollout restart deployment/harvis-ai-openclaw -n ai-agents
kubectl rollout status deployment/harvis-ai-openclaw -n ai-agents
```

**To pair** (one-time, after pod is running):
```bash
# 4. DM the bot in Discord or mention it in your private server
#    OpenClaw will print a pairing code in the pod logs:
kubectl -n ai-agents logs -f deployment/harvis-ai-openclaw | grep -i "pairing\|discord"

# 5. Approve the pairing (replace <code> with what you see in logs):
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- \
  node openclaw.mjs pairing approve discord <code>
```

After pairing, DMs / mentions to the bot go directly to the `main` agent (qwen3:4b local).
Switch models in Discord by starting your message with `@kimi` or `@gpt-oss` if OpenClaw supports agent targeting in channel messages.

---

#### Phase 2 — Harvis backend Discord bridge (full conversational context)
A `discord.py` listener in the Python backend that forwards messages through `/api/chat`,
carrying the user's JWT session and full chat history so Harvis has persona + memory.

**What to do**:
1. Add `discord.py` to `python_back_end/requirements.txt`
2. Create `python_back_end/discord_bridge.py`:
   - `on_message`: receive DM or channel mention
   - Look up user session by Discord user ID (stored in a small `discord_sessions` DB table)
   - Forward to `/api/chat` with full history
   - Split long responses at 2000 chars (Discord limit), send as threaded replies
3. Launch bridge as a background asyncio task in `main.py` startup
4. Add `DISCORD_BOT_TOKEN` to the Harvis backend secret (same token, different pod)

**DB table needed**:
```sql
CREATE TABLE IF NOT EXISTS discord_sessions (
    discord_user_id TEXT PRIMARY KEY,
    harvis_user_id  INTEGER REFERENCES users(id),
    session_token   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

**Credentials needed** (already in secret):
- `DISCORD_BOT_TOKEN` — already in `openclaw-secret.yaml`
- `DISCORD_ALLOWED_USER_IDS` — comma-separated list of your Discord user ID(s)
  (enable Developer Mode → right-click your avatar → Copy User ID)

---

#### Phase 3 — Rich Discord responses
- Code blocks for code output (``` fenced)
- Embeds for search results and structured data
- File attachments for generated DOCX/PDF
- Slash commands: `/harvis <task>`, `/workspace <brief>`, `/research <topic>`

---

### Implementation Order (Discord phases)

1. **Phase 1** — OpenClaw native channel: ~1 hour, zero new Python code, just config + secret mount
2. **Phase 2** — Harvis backend bridge: ~half day, full conversational context + history
3. **Phase 3** — Rich responses + slash commands: polish, no new infra needed

**Telegram already works** — Discord is the second mobile channel.

---

## Maintenance / Pending Updates

- **OpenClaw v2026.3.2 available** (current deploy: v2026.2.23) — update the image tag in
  `k8s-manifests/overlays/prod/openclaw.yaml` (`image: dulc3/openclaw:latest`) and rebuild/push.
  Run: `kubectl rollout restart deployment/harvis-ai-openclaw -n ai-agents` after image push.

---

## Implementation Order (Suggested)

1. **Co-authoring** — quick env var + commit message change, immediate value
2. ~~**Discord Phase 1**~~ ✅ DONE — secret, `openclaw.json` channel config, NetworkPolicy 443 egress, env var mount
3. **Research Agent** — high value, uses existing tools (`local_rag`, `create_docx`), no new infra
4. **Document Agent** — very similar to research, quick add-on
5. **Discord Phase 2** — Harvis backend bridge with full chat history and persona (do later)
6. **Maps Agent** — needs Google Maps API key + proxy endpoint + chat UI map component
7. **Discord Phase 3** — rich responses, slash commands (do later)
8. **File Agent** — needs sandboxed shell scope, slightly more security work
9. **DevOps Agent** — needs K8s proxy service built first, most complex but coolest feature
