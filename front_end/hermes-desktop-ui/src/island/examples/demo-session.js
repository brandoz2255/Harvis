// Neutral sample session used by the demo page and tests. Real sessions come from Harvis:
// each user defines their own agents (local or API models, personalities, looks).
export const DEMO_SESSION = {
  agents: [
    { id: "researcher", name: "Researcher", provider: "ollama", model: "qwen3:8b", personality: "Curious, talkative research assistant" },
    { id: "coder", name: "Coder", provider: "ollama", model: "qwen2.5-coder:7b", personality: "Quiet, meticulous coding assistant who never gossips" },
    { id: "writer", name: "Writer", provider: "openai", model: "gpt-4.1-mini", personality: "Friendly, energetic writer" },
    { id: "planner", name: "Planner", provider: "anthropic", model: "claude-haiku", personality: "Reserved planner" },
  ],
};
