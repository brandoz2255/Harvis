# audit_log

Minimal example plugin for Harvis's Phase 3B plugin loader. Adapted shape
from `NousResearch/hermes-agent`'s `plugins/observability/langfuse/`.

## What it does

Registers a `pre_gateway_dispatch` handler that logs the user_id,
platform, chat_id, and a text preview for every inbound messaging
dispatch. Observer-only — never returns a skip/rewrite directive.

## Enable

Set in the backend environment:

```bash
HARVIS_PLUGINS_ENABLED=observability/audit_log
```

Multiple plugins are comma-separated. `*` loads everything discovered.

## Disable

Remove `observability/audit_log` from `HARVIS_PLUGINS_ENABLED` (or unset
the variable entirely — empty disables all plugins by default).
