# Masterprompt: OpenClaw Workspace Upgrade — GitHub Repo Mounting, IDE Integration, Broader Access

## Context

You are working on **Harvis**, an open-source AI assistant platform. The repo lives at the working directory root. Harvis has an agent backend called **OpenClaw** — a Node.js WebSocket gateway (port 18789) that gives LLMs tools: shell access, file read/write, browser automation, etc.

**Current architecture:**
```
User (Discord / Web UI)
  → Harvis Backend (Python FastAPI, port 8000)
    → OpenClaw Gateway (ws://openclaw:18789)
      → Local Ollama (http://ollama:11434) via backend model proxy
    ← tool results / final answer
  → response back to user
```

OpenClaw runs in Docker, has NO direct internet access. All LLM inference and web access goes through the Harvis backend's proxy endpoints. OpenClaw authenticates to the backend with a shared `OPENCLAW_GATEWAY_TOKEN`.

**What we want to achieve (3 goals):**
1. **GitHub repo mounting** — Users sign in with GitHub OAuth, pick a repo, and OpenClaw clones/pulls it into its workspace so it can read/write real project code
2. **Workspace-first routing** — Make OpenClaw workspace the default for most messages (not just complex ones)
3. **IDE integration** — Expose OpenClaw as an MCP server so Cursor / VS Code can use it as a coding agent

---

## Goal 1: GitHub OAuth → Repo Clone into OpenClaw Workspace

### What already exists

- **GitHub OAuth flow** is fully implemented in `python_back_end/vibecoding/auth_github.py`
  - Routes: `GET /api/vibecode/github/start` → GitHub authorize → `GET /api/vibecode/github/callback`
  - Stores encrypted `access_token` in `github_tokens` table (keyed by `user_id`)
  - Status check: `GET /api/vibecode/github/status`
  - Disconnect: `POST /api/vibecode/github/disconnect`
  - Uses `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `FERNET_KEY` env vars
  - Token encrypted with Fernet cipher derived from `FERNET_KEY`
  - OAuth scope is `repo` (read/write access to repositories)

- **GitHub proxy** exists in `python_back_end/workspace/github_proxy.py` for OpenClaw → GitHub PR creation (bot account only, allowlisted repos)

- **OpenClaw workspace directory** inside the container: `/home/node/.openclaw/workspace/`
  - Currently contains heartbeat scripts, test files, etc.
  - OpenClaw's `exec`, `read`, `write`, `edit` tools operate on this filesystem

- **Docker volume**: `openclaw-data:/home/node/.openclaw` persists across restarts

### What to build

#### 1a. Backend endpoint: `POST /api/workspace/clone-repo`

Location: Add to `python_back_end/workspace/workspace_router.py` (or a new `python_back_end/workspace/repo_manager.py`)

**Flow:**
1. Authenticated user calls `POST /api/workspace/clone-repo` with `{"owner": "...", "repo": "...", "branch": "main"}`
2. Backend fetches the user's GitHub token from `github_tokens` table, decrypts it
3. Backend calls OpenClaw via WebSocket to run a `git clone` inside the container:
   ```
   chat.send → "exec: git clone https://x-access-token:{token}@github.com/{owner}/{repo}.git /home/node/projects/{owner}/{repo}"
   ```
   - Or better: use the backend's own `httpx` to clone via GitHub API tarball and extract into OpenClaw's volume (avoids putting the token in OpenClaw's shell history)
4. Return `{"status": "cloned", "path": "/home/node/projects/{owner}/{repo}"}`

**Alternative (safer, preferred):** Don't send the GitHub token into OpenClaw at all. Instead:
- Backend downloads the repo tarball: `GET https://api.github.com/repos/{owner}/{repo}/tarball/{branch}` with the user's token
- Backend extracts it to the shared Docker volume that OpenClaw can read
- For pushing changes back, OpenClaw calls the existing GitHub proxy (`/github/pulls`) or a new `POST /api/workspace/push-changes` endpoint where the backend does the git push with the token server-side

**Volume mount change needed in `docker-compose.yaml`:**
```yaml
# Add to the openclaw service volumes:
- openclaw-projects:/home/node/projects

# Add to the backend service volumes:
- openclaw-projects:/data/openclaw-projects

# Add to volumes section:
openclaw-projects: {}
```

This gives both containers access to the same directory — backend writes repos there, OpenClaw reads/writes code.

#### 1b. Backend endpoint: `GET /api/workspace/repos`

List repos the user has cloned into the workspace:
```json
[
  {"owner": "brandoz2255", "repo": "Harvis", "branch": "main", "path": "/home/node/projects/brandoz2255/Harvis", "last_synced": "..."},
  ...
]
```

Store metadata in a new `workspace_repos` table:
```sql
CREATE TABLE IF NOT EXISTS workspace_repos (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    owner VARCHAR(255) NOT NULL,
    repo VARCHAR(255) NOT NULL,
    branch VARCHAR(255) DEFAULT 'main',
    local_path VARCHAR(500) NOT NULL,
    last_synced TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, owner, repo)
);
```

#### 1c. Backend endpoint: `POST /api/workspace/sync-repo`

Pull latest changes for an already-cloned repo. Backend does `git pull` on the shared volume using the user's decrypted GitHub token.

#### 1d. Backend endpoint: `POST /api/workspace/push-changes`

When OpenClaw has made code changes:
1. Backend receives `{"owner": "...", "repo": "...", "branch": "harvis/feature-name", "commit_message": "..."}`
2. Backend uses the user's GitHub token to:
   - Create a new branch if needed
   - Commit changes
   - Push to GitHub
   - Optionally create a PR via the existing github_proxy
3. The token NEVER enters OpenClaw — all git auth happens in the backend

#### 1e. Frontend: Repo picker component

Add a component (likely in `front_end/newjfrontend/components/workspace/`) that:
1. Shows GitHub connection status (uses existing `/api/vibecode/github/status`)
2. If not connected, shows "Connect GitHub" button (redirects to `/api/vibecode/github/start`)
3. Once connected, fetches user's repos from `GET https://api.github.com/user/repos` (proxied through backend for token safety)
4. User picks a repo → calls `POST /api/workspace/clone-repo`
5. Shows cloned repos with sync/push buttons

#### 1f. Update OpenClaw agent instructions

Update `openclaw/config/AGENT.md` to tell the agent about project directories:
```markdown
## Project Files

User projects are cloned to `/home/node/projects/{owner}/{repo}/`.
Use `read`, `write`, `edit`, and `exec` tools to work with these files.

When you finish making changes, tell the user what you changed so they
can push via the Harvis UI. Do NOT run `git push` yourself.
```

### Security considerations
- GitHub tokens NEVER enter the OpenClaw container. All git operations that need auth go through the backend
- OpenClaw can `read`/`write`/`exec` on `/home/node/projects/` but cannot push to GitHub directly
- The shared volume (`openclaw-projects`) should be owned by uid 1000 (node user in OpenClaw) and also writable by uid 1001 (appuser in backend). Use a shared GID or init container to set permissions
- Token decryption reuses the existing Fernet cipher from `auth_github.py`

---

## Goal 2: Workspace-First Routing (Use OpenClaw More)

### Current problem

Two aggressive filters prevent most messages from reaching the OpenClaw workspace:

**Filter 1** — `_is_obviously_simple()` in `python_back_end/integrations/discord_workspace_bot.py` (line ~151):
```python
def _is_obviously_simple(text: str) -> bool:
    if len(text) > 300:
        return False
    if _WORKSPACE_SIGNALS.search(text):
        return False
    if len(text) < 200:  # ← anything under 200 chars with no signals = fast path
        return True
    return False
```

**Filter 2** — `task_detector.py` (line ~59):
```
Only set should_suggest = true if confidence >= 0.7.
```

Messages like "make me a react component for a login page" (48 chars, no regex match) get the fast path — a direct Ollama call with no tools, no file access, no workspace.

### Changes needed

#### 2a. Add `DISCORD_PREFER_WORKSPACE` env var

In `discord_workspace_bot.py`, add a mode that sends everything to workspace unless it's a one-word greeting:

```python
_PREFER_WORKSPACE = os.getenv("DISCORD_PREFER_WORKSPACE", "false").lower() == "true"
```

Then in `on_message`, before the existing filter logic:
```python
if _PREFER_WORKSPACE:
    # Only fast-path ultra-short greetings (< 20 chars, no signals)
    use_fast_path = len(content) < 20 and not _WORKSPACE_SIGNALS.search(content)
else:
    # existing filter logic...
```

#### 2b. Lower confidence threshold

In `python_back_end/workspace/task_detector.py`, change the system prompt:
```
Only set should_suggest = true if confidence >= 0.4.
```

Also bias the prompt toward workspace for coding:
```
Workspaces are STRONGLY preferred when the user mentions anything about code,
programming, components, functions, APIs, or technical implementation — even
if the request seems simple. Err on the side of suggesting a workspace.
```

#### 2c. Expand `_WORKSPACE_SIGNALS` regex

Add more coding-related patterns:
```python
_WORKSPACE_SIGNALS = re.compile(
    r"(https?://|\.com\b|\.org\b|\.io\b|\.dev\b|\.net\b"
    r"|screenshot|screen\s*shot|browse|open\s+.*website"
    r"|write\s+(?:a\s+)?(?:file|code|script|program|function|component|page|api)"
    r"|create\s+(?:a\s+)?(?:file|repo|project|pr|pull\s*request|component|endpoint|route)"
    r"|make\s+(?:a\s+)?(?:component|page|api|endpoint|function|class|module)"
    r"|implement|add\s+(?:a\s+)?(?:feature|button|form|modal|table)"
    r"|run\s+(?:a\s+)?(?:command|script|test|code)"
    r"|search\s+(?:the\s+)?(?:web|internet|google)"
    r"|download|upload|install|deploy|build|compile"
    r"|fix\s+(?:the\s+)?(?:bug|error|issue|code)"
    r"|debug|refactor|merge|commit|push|pull"
    r"|read\s+(?:the\s+)?file|edit\s+(?:the\s+)?file"
    r"|research\s|analyze\s+(?:the\s+)?(?:code|repo|log)"
    r"|react|nextjs|next\.js|fastapi|python|typescript|javascript"
    r"|component|endpoint|router|schema|migration|dockerfile)",
    re.IGNORECASE,
)
```

#### 2d. Add env var to docker-compose.yaml

```yaml
# In backend environment:
DISCORD_PREFER_WORKSPACE: "${DISCORD_PREFER_WORKSPACE:-true}"
```

---

## Goal 3: MCP Server for Cursor / VS Code Integration

### What already exists

- MCP scaffold at `python_back_end/mcp/` with `server/app.py` (FastAPI-based, JSON-RPC `/mcp/invoke`)
- MCP tool registry pattern in `python_back_end/mcp/server/registry.py`
- Existing tools: `os_ops`, `network`, `notifications`
- OpenClaw is already exposed on `127.0.0.1:18789` from docker-compose:
  ```yaml
  ports:
    - "127.0.0.1:18789:18789"
  ```
- Full WebSocket client in `python_back_end/workspace/openclaw_client.py` handles connection, auth, challenge-response, chat streaming

### What to build

#### 3a. MCP-compliant server that wraps OpenClaw

Create `python_back_end/mcp/server/tools/openclaw_workspace.py`:

This should expose OpenClaw's capabilities as MCP tools that Cursor/VS Code can discover and call:

| MCP Tool | Maps to | Description |
|----------|---------|-------------|
| `openclaw_exec` | OpenClaw `exec` tool | Run a shell command in the OpenClaw workspace |
| `openclaw_read` | OpenClaw `read` tool | Read a file from the workspace |
| `openclaw_write` | OpenClaw `write` tool | Write/create a file in the workspace |
| `openclaw_edit` | OpenClaw `edit` tool | String-replace edit on a file |
| `openclaw_chat` | OpenClaw `chat.send` | Send a natural language task to the OpenClaw agent |
| `openclaw_search` | Backend `/api/tools/search` | Web search through the proxy |
| `openclaw_web_fetch` | Backend `/api/tools/web-fetch` | Fetch a URL through the proxy |
| `list_repos` | Backend `/api/workspace/repos` | List cloned GitHub repos |
| `clone_repo` | Backend `/api/workspace/clone-repo` | Clone a GitHub repo |

**Implementation approach:**
- Each MCP tool function sends a WebSocket message to OpenClaw (reuse `OpenClawClient` from `workspace/openclaw_client.py`)
- Or for simpler tools, call the backend's own endpoints internally
- The MCP server runs as a sidecar process or as part of the backend (add routes to `main.py`)

#### 3b. MCP server config for Cursor

Create `openclaw/cursor-mcp-config.json`:
```json
{
  "mcpServers": {
    "harvis-openclaw": {
      "url": "http://localhost:8000/mcp/invoke",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer ${OPENCLAW_GATEWAY_TOKEN}"
      }
    }
  }
}
```

User adds this to their Cursor settings (`~/.cursor/mcp.json` or project `.cursor/mcp.json`).

#### 3c. Alternative: stdio MCP bridge

For VS Code extensions that prefer stdio transport, create a thin Node.js or Python script:

`openclaw/mcp-stdio-bridge.py`:
```python
# Reads JSON-RPC from stdin, forwards to http://localhost:8000/mcp/invoke, writes response to stdout
# This lets VS Code MCP extensions that use stdio transport talk to the HTTP MCP server
```

#### 3d. Expose the MCP server in docker-compose

The MCP endpoints should be part of the existing backend (port 8000), NOT a separate service. The backend already has:
- Auth (JWT + OPENCLAW_GATEWAY_TOKEN)
- Access to OpenClaw via WebSocket
- Access to the shared project volume

Add to `main.py`:
```python
from mcp.server.app import app as mcp_app
app.mount("/mcp", mcp_app)
```

Or better — register the MCP tools as FastAPI routes directly so they share the same auth middleware.

---

## Broader Internet Access (Supporting Change)

### Current rate limits (env vars in docker-compose backend environment)

```yaml
OPENCLAW_WEB_RATE_MAX_SEARCH: "10"      # 10 searches per 60s
OPENCLAW_WEB_RATE_MAX_FETCH: "20"       # 20 fetches per 60s
OPENCLAW_WEB_RATE_MAX_SEARCH_LIVE: "30" # with X-Live-Web header
OPENCLAW_WEB_RATE_MAX_FETCH_LIVE: "60"  # with X-Live-Web header
```

### Changes to make

Bump the defaults and enable live web by default for workspace tasks:

```yaml
# In backend environment section of docker-compose.yaml:
OPENCLAW_WEB_RATE_MAX_SEARCH: "30"
OPENCLAW_WEB_RATE_MAX_FETCH: "60"
OPENCLAW_WEB_RATE_MAX_SEARCH_LIVE: "60"
OPENCLAW_WEB_RATE_MAX_FETCH_LIVE: "120"
OPENCLAW_WEB_RATE_WINDOW_S: "60"
```

The workspace launch already sends `live_web: True` by default (see `LaunchRequest` in `workspace_router.py` line 226), so workspace tasks already get the relaxed rate limits and domain bypass. This is correct — just bump the numbers.

---

## File-by-file change map

| File | Action | What |
|------|--------|------|
| `docker-compose.yaml` | EDIT | Add `openclaw-projects` shared volume to both `openclaw` and `backend` services. Add env vars `DISCORD_PREFER_WORKSPACE`, bump rate limits |
| `python_back_end/workspace/repo_manager.py` | CREATE | New file: `clone-repo`, `sync-repo`, `push-changes`, `list-repos` endpoints + `workspace_repos` table |
| `python_back_end/workspace/workspace_router.py` | EDIT | Import and include repo_manager router, or add the endpoints here |
| `python_back_end/main.py` | EDIT | Register new repo_manager router, mount MCP server |
| `python_back_end/integrations/discord_workspace_bot.py` | EDIT | Add `DISCORD_PREFER_WORKSPACE` env var and workspace-first logic |
| `python_back_end/workspace/task_detector.py` | EDIT | Lower confidence threshold to 0.4, bias prompt toward coding tasks |
| `python_back_end/mcp/server/tools/openclaw_workspace.py` | CREATE | MCP tool definitions that wrap OpenClaw capabilities |
| `python_back_end/mcp/server/app.py` | EDIT | Register openclaw_workspace tools |
| `openclaw/config/AGENT.md` | EDIT | Add section about `/home/node/projects/` directory for user repos |
| `openclaw/cursor-mcp-config.json` | CREATE | Cursor MCP server configuration file |
| `front_end/newjfrontend/components/workspace/RepoManager.tsx` | CREATE | UI for GitHub connect + repo picker + clone/sync/push |
| `front_end/newjfrontend/app/api/` (or direct backend calls) | EDIT | Add frontend API calls for repo management |

---

## Environment variables to add to `.env`

```bash
# GitHub OAuth (may already be set from vibecoding)
GITHUB_CLIENT_ID=your_github_oauth_app_client_id
GITHUB_CLIENT_SECRET=your_github_oauth_app_client_secret
FERNET_KEY=your_fernet_key_for_token_encryption

# Workspace routing
DISCORD_PREFER_WORKSPACE=true

# Relaxed rate limits for web access
OPENCLAW_WEB_RATE_MAX_SEARCH=30
OPENCLAW_WEB_RATE_MAX_FETCH=60
```

---

## Implementation order

1. **Shared volume** — Add `openclaw-projects` volume to docker-compose, verify both containers can read/write
2. **Repo manager backend** — Create `repo_manager.py` with clone/sync/push/list endpoints
3. **Workspace routing** — Apply the `DISCORD_PREFER_WORKSPACE` and detector changes
4. **AGENT.md update** — Tell OpenClaw about `/home/node/projects/`
5. **Frontend repo picker** — Build the React component
6. **MCP server** — Expose OpenClaw tools as MCP endpoints
7. **Cursor config** — Create the `.cursor/mcp.json` config

Steps 1-4 can be done together. Steps 5-7 can follow.

---

## Critical rules

- **GitHub tokens NEVER enter the OpenClaw container.** All authenticated git operations (clone with auth, push, PR creation) happen in the Python backend. OpenClaw only reads/writes files on the shared volume.
- **OpenClaw's network isolation stays intact.** It still cannot reach the internet directly. Web access goes through backend proxy endpoints.
- **The `openclaw-internal` Docker network stays `internal: true`.** No change to network topology.
- **All new endpoints must be authenticated** — JWT for user-facing endpoints, `OPENCLAW_GATEWAY_TOKEN` for OpenClaw-facing endpoints.
- **Never expose raw GitHub tokens in API responses, logs, or OpenClaw shell history.**
- **The existing GitHub OAuth app registration may need the callback URL updated** if deploying to a new domain. Current callback: `{OAUTH_REDIRECT_BASE}/api/vibecode/github/callback`
