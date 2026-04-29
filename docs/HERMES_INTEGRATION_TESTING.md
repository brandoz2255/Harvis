# Hermes Integration — Hands-on Testing Guide

How to test the work in commits `97cf594..e807f4e` against the real
HARVIS stack (not the isolated smoke tests run during development).

The branch ships in two waves:

1. **Storage + sidecar foundation** (`97cf594..9b48cee`, 8 commits) — messaging
   gateway, ACP adapter, plugin hooks + manifest loader, memory/MCP/cron/SOUL
   storage layers. None of this *changes agent behavior* on its own.
2. **Behavioral wiring + CRUD routes** (`aa24ef2..e807f4e`, 5 commits) — the
   storage layers actually plug into the agent prompt + lifespan now, and you
   can manage them via REST.

After Wave 2, the agent really does see your SOUL.md + recalled memories in
its task brief, the cron tick fires due jobs in the background, and on_session_end
runs your memory provider's extract_from_session.

---

## Tier 0 — Prerequisites

You need the full HARVIS stack up: `docker compose up -d backend pgsql ollama openclaw`.
The backend bind-mounts `python_back_end/plugins/` from the host, so
new code is picked up on backend restart — no rebuild needed.

If you've never set the messaging gateway secret:

```bash
# Append to .env
echo "MESSAGING_GATEWAY_TOKEN=$(openssl rand -hex 32)" >> .env
```

---

## Tier 1 — Smoke (5 min, no real credentials needed)

Goal: prove migrations apply cleanly and the backend boots with the new
plugins loaded.

### 1.1 Apply migrations

```bash
docker compose exec -T pgsql psql -U pguser -d database \
  < python_back_end/migrations/011_messaging_platforms.sql
docker compose exec -T pgsql psql -U pguser -d database \
  < python_back_end/migrations/012_user_memory.sql
docker compose exec -T pgsql psql -U pguser -d database \
  < python_back_end/migrations/013_mcp_servers.sql
docker compose exec -T pgsql psql -U pguser -d database \
  < python_back_end/migrations/014_cron_jobs.sql
docker compose exec -T pgsql psql -U pguser -d database \
  < python_back_end/migrations/015_user_soul.sql
```

Or run them all via the existing migration runner:

```bash
docker compose exec backend python /app/run_migrations.py
```

Then confirm the 7 new tables exist:

```bash
docker compose exec -T pgsql psql -U pguser -d database -tA -c \
  "SELECT tablename FROM pg_tables WHERE tablename IN
   ('messaging_platforms','messaging_audit','harvis_user_memory',
    'mcp_servers','mcp_oauth_tokens','cron_jobs','user_soul')
   ORDER BY tablename"
```

Expected output (7 rows):
```
cron_jobs
harvis_user_memory
mcp_oauth_tokens
mcp_servers
messaging_audit
messaging_platforms
user_soul
```

### 1.2 Restart the backend & watch the boot log

```bash
docker compose restart backend
docker compose logs -f backend | head -200
```

Look for these lines (in order):
```
✅ Discord workspace bot started (legacy path)    # if DISCORD_BOT_TOKEN is set
🔌 plugins discovered: 1 (statuses: {'disabled': 1})
                       ^ the audit_log plugin — disabled by default
```

If you see `Plugin loader failed:` instead, capture the traceback —
that's a real bug.

### 1.3 Backend `/api/messaging/platforms` route is live

```bash
# This will 401 — that's correct (it requires user JWT).
curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:9000/api/messaging/platforms
# Expected: 401
```

```bash
# Service-to-service inbound route should reject without the gateway token.
curl -sS -X POST http://localhost:9000/api/messaging/inbound \
  -H "Content-Type: application/json" -d '{}'
# Expected: 401 invalid gateway token (or 503 if MESSAGING_GATEWAY_TOKEN unset)
```

---

## Tier 2 — Per-phase functional tests

### Phase 1 (messaging gateway) — stub round-trip

The fastest end-to-end test. No real Slack/Discord credentials needed.

```bash
# In .env
echo "MESSAGING_STUB_ENABLED=true" >> .env
echo "MESSAGING_STUB_TOKEN=$(openssl rand -hex 16)" >> .env
echo "MESSAGING_ENABLED_PLATFORMS=stub" >> .env

# Bring up the gateway sidecar
docker compose up -d --build harvis-messaging-gateway

# Wait for it to register the stub
docker compose logs harvis-messaging-gateway --tail 20

# Map a platform identity to a real harvis user (replace user_id with a real one)
docker compose exec -T pgsql psql -U pguser -d database -c \
  "INSERT INTO messaging_platforms (user_id, platform, identifier, enabled)
   VALUES (2, 'stub', 'stub-user', TRUE) ON CONFLICT DO NOTHING"

# Inject a test message
STUB_TOKEN=$(grep ^MESSAGING_STUB_TOKEN .env | cut -d= -f2)
curl -sS -X POST http://127.0.0.1:18800/inject \
  -H "X-Stub-Token: $STUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello from stub","sender_id":"stub-user"}'
```

You should get back a JSON response with `ok: true` and a `reply` field
containing the workspace's final summary (real workspace dispatch this
time, not a mock).

### Phase 1C — real Slack

```bash
# In .env
echo "SLACK_BOT_TOKEN=xoxb-your-bot-token" >> .env
echo "SLACK_APP_TOKEN=xapp-your-app-token" >> .env
echo "MESSAGING_ENABLED_PLATFORMS=slack" >> .env  # or "stub,slack"

docker compose restart harvis-messaging-gateway

# In Slack: DM the bot OR @mention it in a channel
# Expected: it runs the workspace and replies in-thread.
```

Then map your Slack user_id to a HARVIS user:

```sql
INSERT INTO messaging_platforms (user_id, platform, identifier, enabled)
VALUES (<your_harvis_user_id>, 'slack', 'U01234ABCDE', TRUE);
```

(`U01234ABCDE` is your Slack user ID — find it in Profile → More → Copy member ID.)

### Phase 1D — real Discord

```bash
# DISCORD_BOT_TOKEN is already set if you've been using the legacy bot
# Add to .env:
echo "MESSAGING_ENABLED_PLATFORMS=discord" >> .env  # or "slack,discord"
echo "DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=false" >> .env

docker compose restart backend harvis-messaging-gateway

# Map your Discord ID to a HARVIS user:
docker compose exec -T pgsql psql -U pguser -d database -c \
  "INSERT INTO messaging_platforms (user_id, platform, identifier, enabled)
   VALUES (<harvis_user_id>, 'discord', '<discord_user_id>', TRUE)"

# In Discord: DM the bot or @mention it.
```

If you see duplicate replies, the legacy bot didn't actually disable —
double-check `DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=false` is being read
(`docker compose exec backend env | grep DISCORD_WORKSPACE_BOT`).

### Phase 2 (ACP) — from an editor

This is the most involved test because it requires an ACP-aware editor
(Zed, or a VS Code extension that speaks ACP). Lightweight version:

```bash
# Build the adapter
docker build -t harvis-acp-adapter:local plugins/acp-adapter/

# Quick handshake check (proves the binary boots and the SDK can talk to it)
docker run --rm \
  -v /tmp/acp_handshake_test.py:/tmp/test.py:ro \
  --entrypoint python \
  -e MESSAGING_GATEWAY_TOKEN=test \
  harvis-acp-adapter:local /tmp/test.py
```

For real editor integration, point the editor at:
```
command: docker
args: ["run", "--rm", "-i", "--network=host",
       "-e", "MESSAGING_GATEWAY_TOKEN=<your token>",
       "-e", "HARVIS_BACKEND_URL=http://localhost:9000",
       "-e", "HARVIS_USER_ID=<your harvis user id>",
       "harvis-acp-adapter:local"]
```

Each editor's ACP integration is different — consult the editor's
docs for the agent-registration shape.

### Phase 3 + 3B — plugin hooks + auto-discovery

```bash
# Enable the example audit_log plugin
echo "HARVIS_PLUGINS_ENABLED=observability/audit_log" >> .env

docker compose restart backend
docker compose logs backend | grep -E "plugin|audit"
```

Expected log lines:
```
plugin observability/audit_log loaded (v0.1.0) — registered 1 hook(s): pre_gateway_dispatch
🔌 plugins discovered: 1 (statuses: {'loaded': 1})
```

Now send a message through any messaging platform (or via the stub
adapter from Phase 1). You should see in the backend log:
```
audit user=<id> platform=stub chat=<chat_id> text='hello from stub'
```

That proves `pre_gateway_dispatch` fires per inbound and the loaded
plugin's handler runs.

### Phase 4 — memory provider

The provider doesn't have HTTP routes yet — exercise it from a Python
shell against the real backend's pool. Easiest path:

```bash
docker compose exec backend python -c "
import asyncio, os
import asyncpg
from plugins.memory.manager import get_manager

async def main():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2)
    mgr = get_manager()
    p = await mgr.activate('builtin', config={'pool': pool})

    e = await p.remember(2, 'I prefer dark mode', source='manual')
    print('remembered:', e)

    out = await p.recall(2, query='dark', limit=10)
    print('recalled:', [(m.content, m.created_at) for m in out])

    await pool.close()

asyncio.run(main())
"
```

Expected: the inserted memory comes back with a populated `created_at`.

### Phase 5 — MCP storage

```bash
docker compose exec backend python -c "
import asyncio, os
import asyncpg
from plugins.mcp.server_registry import McpServerRegistry
from plugins.mcp.types import AuthMethod, McpServerConfig, Transport

async def main():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2)
    reg = McpServerRegistry(pool)

    cfg = McpServerConfig(
        user_id=2, server_name='filesystem',
        transport=Transport.STDIO,
        command='npx', args=['-y','@modelcontextprotocol/server-filesystem','/tmp'],
        auth_method=AuthMethod.NONE,
    )
    saved = await reg.upsert(cfg)
    print('saved:', saved)
    print('list:', await reg.list_for_user(2))
    await pool.close()

asyncio.run(main())
"
```

### Phase 6 — cron

```bash
docker compose exec backend python -c "
import asyncio, os
import asyncpg
from plugins.cron.store import PgCronJobStore
from plugins.cron.types import ScheduleType

async def main():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2)
    store = PgCronJobStore(pool)

    job = await store.create(
        user_id=2, name='daily summary',
        schedule_type=ScheduleType.CRON, schedule_expr='0 9 * * *',
        prompt='Summarize my agenda for today.',
        delivery='discord:<channel_id>',
    )
    print('created:', job.id, 'next_run_at:', job.next_run_at)

    due = await store.find_due(now=job.next_run_at)
    print('due now (forwarded):', [j.name for j in due])
    await pool.close()

asyncio.run(main())
"
```

The job is persisted but **nothing fires it yet** — the tick runtime is
deferred. To fire it manually:

```bash
docker compose exec backend python -c "
import asyncio, os
import asyncpg
from plugins.cron.store import PgCronJobStore
from plugins.cron.scheduler import CronScheduler

async def fake_dispatch(job):
    print(f'WOULD DISPATCH: {job.name} -> {job.delivery} :: {job.prompt}')
    return True, None

async def main():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2)
    sched = CronScheduler(PgCronJobStore(pool), dispatch=fake_dispatch)
    n = await sched.tick()
    print(f'dispatched {n} job(s)')
    await pool.close()

asyncio.run(main())
"
```

### Phase 7 — SOUL.md

```bash
docker compose exec backend python -c "
import asyncio, os
import asyncpg
from plugins.soul.loader import save_soul, load_soul, load_soul_with_default

async def main():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'], min_size=1, max_size=2)

    await save_soul(pool, 2, '# My Soul\n\nI prefer concrete examples.')
    print('saved.')
    print('load:', await load_soul(pool, 2))
    print('default-fallback:', (await load_soul_with_default(pool, 2))[:60])
    await pool.close()

asyncio.run(main())
"
```

---

## Tier 3 — Real-world cutover

This is when you flip your team's actual messaging traffic to the new
gateway and start using the ACP adapter daily.

### Cutover checklist

- [ ] All migrations applied to production pgsql
- [ ] `MESSAGING_GATEWAY_TOKEN` set, rotated from any prior value
- [ ] Real Slack tokens (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`) configured
- [ ] All real platform user IDs mapped in `messaging_platforms`
- [ ] `MESSAGING_ENABLED_PLATFORMS=slack,discord` in production env
- [ ] `DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=false` to retire the
      in-process bot
- [ ] One full "user @-mentions bot in production channel" test passes
      with no duplicate replies
- [ ] Backend log monitored for 1 hour — no `plugin loader failed` or
      adapter crash entries
- [ ] If using the audit_log plugin, the per-message audit lines are
      flowing into wherever you're aggregating logs

### Rollback

Each phase is independently reversible without code change:

| Phase | Rollback |
|-------|----------|
| 1 | Remove `MESSAGING_ENABLED_PLATFORMS`, set `DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=true`, restart backend |
| 3 | Unset `HARVIS_PLUGINS_ENABLED` |
| Everything else | Storage layers — having the tables present is harmless if nothing reads them |

To drop the new tables entirely:
```sql
DROP TABLE IF EXISTS messaging_audit, messaging_platforms,
                     harvis_user_memory,
                     mcp_oauth_tokens, mcp_servers,
                     cron_jobs,
                     user_soul CASCADE;
```

---

## Tier 4 — REST endpoints (commits aa24ef2..e807f4e)

After Wave 2, the storage layers are reachable via REST under the standard
JWT-auth flow. Use a real bearer token (the same one your frontend gets back
from `/api/auth/login`).

```bash
# Replace with your actual JWT
TOKEN=eyJ...

# === SOUL.md ===
# Get current SOUL (returns DEFAULT_SOUL_MD with is_default=true if you've never set one)
curl -sS http://localhost:9000/api/soul -H "Authorization: Bearer $TOKEN"

# Save your persona
curl -sS -X PUT http://localhost:9000/api/soul \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "# Identity\n\nI am Brando. Prefer terse direct answers."}'

# Seed default if not set (idempotent — second call returns seeded:false)
curl -sS -X POST http://localhost:9000/api/soul/seed-default -H "Authorization: Bearer $TOKEN"

# Wipe
curl -sS -X DELETE http://localhost:9000/api/soul -H "Authorization: Bearer $TOKEN"

# === Memory ===
# Save a fact
curl -sS -X POST http://localhost:9000/api/memory \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "I deploy to k8s with FluxCD on Mondays", "source": "manual"}'

# List recent
curl -sS http://localhost:9000/api/memory?limit=20 -H "Authorization: Bearer $TOKEN"

# Search
curl -sS "http://localhost:9000/api/memory?query=deploy" -H "Authorization: Bearer $TOKEN"

# Diagnostic — which provider is active?
curl -sS http://localhost:9000/api/memory/provider -H "Authorization: Bearer $TOKEN"

# Wipe
curl -sS -X DELETE http://localhost:9000/api/memory -H "Authorization: Bearer $TOKEN"

# === Cron ===
# Schedule a daily 9am summary (delivery format mirrors messaging — "discord:<channel_id>" etc.)
curl -sS -X POST http://localhost:9000/api/cron \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "morning brief",
    "schedule_type": "cron",
    "schedule_expr": "0 9 * * *",
    "prompt": "Summarize my agenda for today.",
    "delivery": "discord:1234567890"
  }'

# List your jobs
curl -sS http://localhost:9000/api/cron -H "Authorization: Bearer $TOKEN"

# Pause a job (replace <id> with the uuid from create's response)
curl -sS -X PUT "http://localhost:9000/api/cron/<id>/status?status=paused" -H "Authorization: Bearer $TOKEN"

# Delete
curl -sS -X DELETE "http://localhost:9000/api/cron/<id>" -H "Authorization: Bearer $TOKEN"
```

Schedule formats:
- `cron` → standard 5-field cron expression (e.g. `0 9 * * *`)
- `interval` → `<N><s|m|h|d>` (e.g. `30m`, `2h`, `7d`)
- `once` → ISO-8601 datetime (e.g. `2026-12-31T15:00:00+00:00`)

Cross-user isolation is enforced — requesting another user's job by id returns 404.

## Tier 5 — Confirming Wave 2 changed agent behavior

After saving a SOUL.md and a memory:

```bash
# Save persona
curl -sS -X PUT http://localhost:9000/api/soul \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "# I prefer Lisp. Always answer in three sentences or fewer."}'

# Save a fact
curl -sS -X POST http://localhost:9000/api/memory \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "I work on the Hermes integration project"}'
```

Then send a message via Discord/Slack/stub: `"what am I working on?"`

Inspect the actual brief the agent saw:
```bash
docker compose exec -T pgsql psql -U pguser -d database -c \
  "SELECT LEFT(task_brief, 800) FROM workspace_runs ORDER BY started_at DESC LIMIT 1"
```

Expected leading content:
```
USER PERSONA / CONSTRAINTS (from their SOUL.md — keep in mind throughout):
# I prefer Lisp. Always answer in three sentences or fewer.

RECENT FACTS THE USER HAS SHARED (from their memory — incorporate when relevant):
• I work on the Hermes integration project

---

USER MESSAGE: what am I working on?
```

If you see that structure, **the wiring is doing its job.** What the agent says
next is the model's problem, not the integration's.

To verify on_session_end fires after the run completes:
```bash
docker compose logs backend | grep -E "on_session_end|extract_from_session|notify-terminal"
```

To verify cron tick is alive (when `HARVIS_CRON_ENABLED=true`):
```bash
docker compose logs backend | grep "cron tick"
```

You should see `⏰ cron tick loop started (interval=60.0s)` at startup, then
`cron tick dispatched N job(s)` whenever something fires.

## What's NOT wired yet (honest list)

- **MCP OAuth runtime** — token storage (`mcp_oauth_tokens` table) and
  `PgTokenStorage` are ready; the `harvis-mcp` service hasn't been
  taught to consume them yet.
- **Path B (SOUL at identity slot #1)** — Path A injects SOUL into the
  task brief preamble. Path B would refactor `openclaw_client.py:_load_identity_bundle`
  to pull per-user SOUL into the SYSTEM IDENTITY slot directly.
  Path A delivers the behavior; Path B is a cleaner placement at the
  cost of plumbing `user_id`+`pool` through 3 pre-session-dirty files.
- **Live progress message edits** in Slack/Discord — the bridge
  exposes an `on_update` hook in `wait_for_terminal()` but the adapters
  send only the final reply right now.

These remain real follow-ups, scoped in `docs/HERMES_INTEGRATION_DEFERRED.md`.
