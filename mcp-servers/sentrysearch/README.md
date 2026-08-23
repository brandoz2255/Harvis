# SentrySearch (Harvis) — optional video MCP

**Not** Sentry.io error monitoring. Local **video** search (Apache-2.0 upstream:
https://github.com/ssrajadh/sentrysearch).

## Placement

- Compose profile: `sentrysearch` (`docker compose --profile sentrysearch up`)
- Catalog card: Plugins storefront directory entry (`sentrysearch-video`)
- Default: **OFF** (~450–600 MB when a real image is wired)
- OpenClaw: **do not** install upstream skill (Gemini + egress)

## Product gate

Build the real MCP server only after an explicit “yes, I want video search.”
