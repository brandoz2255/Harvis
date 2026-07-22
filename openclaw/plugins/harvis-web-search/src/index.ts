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

import { Type } from "typebox";
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

const BACKEND_URL = process.env.HARVIS_BACKEND_URL ?? "http://backend:8000";
const PROXY_PATH = "/api/tools/search";

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  source?: string;
}

interface ProxyResponse {
  query: string;
  results: SearchResult[];
  policy?: { tier?: string };
}

export default defineToolPlugin({
  id: "harvis-web-search",
  name: "Harvis Web Search",
  description:
    "Web search via Harvis's DDG-backed proxy. Use when you need to verify a " +
    "fact, look up current information, or are uncertain about an answer.",
  tools: (tool) => [
    tool({
      name: "web_search",
      label: "Web Search",
      description:
        "Search the public web. Returns ranked results with titles, URLs, and " +
        "snippets. Use this freely on factual or scenario questions where " +
        "your training data is uncertain.",
      parameters: Type.Object({
        query: Type.String({
          description: "Search query. Be specific — include key terms.",
          minLength: 1,
          maxLength: 500,
        }),
        count: Type.Optional(
          Type.Integer({
            description: "Number of results to return (1-10). Default: 5.",
            minimum: 1,
            maximum: 10,
            default: 5,
          }),
        ),
      }),
      async execute({ query, count = 5 }, _config, context) {
        context.signal?.throwIfAborted();

        const token = process.env.OPENCLAW_GATEWAY_TOKEN;
        if (!token) {
          return {
            error: "missing_token",
            message:
              "OPENCLAW_GATEWAY_TOKEN env var is not set inside the OpenClaw " +
              "container. The Harvis backend rejects requests without it.",
            results: [],
          };
        }

        const url = `${BACKEND_URL}${PROXY_PATH}`;
        let response: Response;
        try {
          response = await fetch(url, {
            method: "POST",
            signal: context.signal,
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              "X-OpenClaw-SessionKey": `plugin:harvis-web-search:${context.toolCallId}`,
              "X-Live-Web": "true",
            },
            body: JSON.stringify({ query, max_results: count }),
          });
        } catch (err) {
          return {
            error: "fetch_failed",
            message: `Network error reaching ${url}: ${(err as Error).message}`,
            results: [],
          };
        }

        if (!response.ok) {
          const body = await response.text().catch(() => "");
          return {
            error: "proxy_error",
            status: response.status,
            message: `Proxy returned HTTP ${response.status}`,
            body: body.slice(0, 500),
            results: [],
          };
        }

        let data: ProxyResponse;
        try {
          data = (await response.json()) as ProxyResponse;
        } catch (err) {
          return {
            error: "invalid_json",
            message: `Proxy returned non-JSON: ${(err as Error).message}`,
            results: [],
          };
        }

        return {
          query: data.query ?? query,
          results: (data.results ?? []).slice(0, count),
          policy_tier: data.policy?.tier,
        };
      },
    }),
  ],
});
