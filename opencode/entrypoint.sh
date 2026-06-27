#!/usr/bin/env bash
# Harvis OpenCode sidecar entrypoint: refresh the ollama provider's model list
# from live tags (so newly-pulled models work without an image rebuild), then idle
# so the backend can `docker exec` per-turn `opencode run` invocations.
set -u
CFG="${HOME}/.config/opencode/opencode.json"
OLLAMA="${OLLAMA_URL:-http://ollama:11434}"

node - "$CFG" "$OLLAMA" <<'JS' 2>/dev/null || echo "opencode.json: kept baked config (regen skipped)"
const fs = require('fs');
const cfgPath = process.argv[2];
const ollama = process.argv[3].replace(/\/$/, '');
(async () => {
  let cfg;
  try { cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8')); }
  catch { cfg = { "$schema": "https://opencode.ai/config.json", provider: {} }; }
  const prov = ((cfg.provider ||= {}).ollama ||= {});
  prov.npm ||= "@ai-sdk/openai-compatible";
  prov.name ||= "Ollama (local)";
  (prov.options ||= {}).baseURL = ollama + "/v1";
  let names = [];
  try {
    const r = await fetch(ollama + "/api/tags");
    const d = await r.json();
    names = (d.models || []).map((m) => m.name).filter(Boolean);
  } catch (_) {}
  if (names.length) prov.models = Object.fromEntries(names.map((n) => [n, { name: n }]));
  fs.mkdirSync(require('path').dirname(cfgPath), { recursive: true });
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));
  console.log("opencode.json: " + names.length + " ollama models registered");
})();
JS

echo "harvis-opencode sidecar ready (idle; invoked via docker exec)."
exec tail -f /dev/null
