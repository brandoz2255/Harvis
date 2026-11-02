# Harvis Bundled Container Pulse

## Purpose

Periodic health check for the shared bundled OpenClaw container. Runs every
4 hours during active hours. Reports aggregate stats — never reads
individual user session files (cross-user privacy).

## CRITICAL RESPONSE CONTRACT

If none of the checks below produce actionable output, reply with exactly
`HEARTBEAT_OK` and nothing else. The gateway drops this reply and
stays silent. This prevents heartbeat spam.

Only produce a real response when a check actually finds something
worth reporting.

## Checks (run in order)

### Check 1 — Container health

Run: `exec df -h /home/node/.openclaw | tail -1 | awk '{print $5}'`

If usage > 80%, report:

```
Container disk at N%. Consider pruning old workspace sessions.
```

### Check 2 — Workspace session count

Run: `exec find /home/node/workspaces/bundled -maxdepth 2 -mindepth 2 -type d 2>/dev/null | wc -l`

Report the count if > 0:

```
Active bundled workspaces: N
```

### Check 3 — Stale session cleanup check

Run: `exec find /home/node/workspaces/bundled -maxdepth 3 -type d -mtime +7 2>/dev/null | wc -l`

If > 10 stale sessions:

```
N workspace directories older than 7 days. Consider cleanup.
```

## Decision tree

1. Run Check 1. Usage > 80% -> mark reported
2. Run Check 2. Count > 0 -> mark reported
3. Run Check 3. Stale > 10 -> mark reported
4. NONE reported -> reply exactly `HEARTBEAT_OK`
5. At least one reported -> brief summary

## Rules

- Do NOT ask the user questions. Scheduled task.
- Do NOT read individual user workspace files. Privacy boundary.
- Do NOT post empty or "nothing to report" messages.
- Do NOT print credentials or tokens.
- Do NOT run destructive commands. Checks only read state.
- Keep responses under 1800 characters.
