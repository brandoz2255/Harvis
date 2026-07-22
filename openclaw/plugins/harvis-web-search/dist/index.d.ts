/**
 * Harvis Web Search — OpenClaw tool plugin.
 *
 * Registers a `web_search` MCP tool that wraps Harvis's working
 * DuckDuckGo-backed `/api/tools/search` proxy. This solves the architectural
 * gap where models would only invoke schema-registered tools, never
 * prose-described curl paths in the WEB ACCESS hint.
 *
 * Backend endpoint: POST http://backend:8000/api/tools/search
 *   - Auth:    Bearer <OPENCLAW_GATEWAY_TOKEN>
 *   - Headers: X-OpenClaw-SessionKey (any non-empty), X-Live-Web: true
 *   - Body:    {"query": "<q>", "max_results": <int>}
 *   - Returns: {"query", "results": [{title, url, snippet, source}], "policy"}
 *
 * Tracked architectural fix: project_openclaw_b7_blocked memory entry
 * (now unblocked once this ships and works end-to-end).
 */
declare const _default: import("openclaw/plugin-sdk/tool-plugin").DefinedToolPluginEntry;
export default _default;
