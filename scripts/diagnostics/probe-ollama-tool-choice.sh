#!/usr/bin/env bash
# Step 0.5 of plan noble-noodling-pnueli.
#
# Probe whether Ollama honors OpenAI-spec `tool_choice` field.
# Success = response.choices[0].message.tool_calls is non-null array.
# Failure = response has content text and tool_calls is null → Ollama
# is silently ignoring tool_choice; the matrix in Step 1+2 needs a
# different strategy (e.g., grammar-constrained format instead).
#
# Usage:
#   bash scripts/diagnostics/probe-ollama-tool-choice.sh
#   MODEL=gpt-oss:latest bash scripts/diagnostics/probe-ollama-tool-choice.sh
#   MODEL=qwen3:14b OLLAMA_URL=http://your-ollama-host:11434 \
#       bash scripts/diagnostics/probe-ollama-tool-choice.sh
set -euo pipefail

BASE_URL="${OLLAMA_URL:-http://localhost:11434}"
MODEL="${MODEL:-granite4.1:8b}"

echo "=== Probe: ${MODEL} @ ${BASE_URL} ==="

curl -s -m 120 "${BASE_URL}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [
      {"role": "user", "content": "Use the exec tool to run: echo hello"}
    ],
    "tools": [{
      "type": "function",
      "function": {
        "name": "exec",
        "description": "Run a shell command and return its stdout.",
        "parameters": {
          "type": "object",
          "required": ["command"],
          "properties": {
            "command": {"type": "string"}
          }
        }
      }
    }],
    "tool_choice": {"type":"function","function":{"name":"exec"}},
    "stream": false,
    "options": {"num_ctx": 8192}
  }' | jq '{
      model: .model,
      content: .choices[0].message.content,
      tool_calls: .choices[0].message.tool_calls,
      finish_reason: .choices[0].finish_reason,
      eval_count: .usage.completion_tokens
    }'
