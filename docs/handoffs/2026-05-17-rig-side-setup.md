# Rig-side OpenClaw setup brief (for a separate Claude Code session running ON the rig)

**Audience:** a fresh Claude Code session opened on the 5080 rig (with filesystem access to `/home/harvis/harvis-host`).
**Goal:** finish wiring the rig's dockerized OpenClaw + Ollama so the **laptop's** Harvis backend can drive an agent loop on the rig's GPU.
**Date:** 2026-05-17

---

## Context from the laptop side (don't change these — they're already done)

The laptop backend has been reconfigured. Confirmed env on `harvis-backend` container:
- `OPENCLAW_URL=ws://192.168.20.58:18789` ← rig openclaw (primary)
- `OPENCLAW_FALLBACK_URL=ws://openclaw:18789` ← laptop docker openclaw (fallback)
- `DESKTOP_OLLAMA_URL=http://192.168.20.58:11434` ← rig Ollama (for model_proxy auto-routing)
- `OPENCLAW_HOME=/home/node` ← rig container is `node` user
- `OPENCLAW_GATEWAY_TOKEN=<your-gateway-token>`

**Verified network from laptop → rig:**
- TCP 192.168.20.58:18789 → open (openclaw exposed to LAN — already done)
- TCP 192.168.20.58:11434 → open (Ollama exposed to LAN — already done)
- Rig has **zero models installed** in Ollama currently.

**Key IPs:**
- Laptop LAN IP: `192.168.10.244` (the rig's openclaw needs to call back here for the harvis-proxy LLM router)
- Rig LAN IP: `192.168.20.58`
- Same `/22` subnet so routing is direct, no NAT.

---

## Tasks to do on the rig (in order)

### 1. Verify OPENCLAW_GATEWAY_TOKEN matches

```bash
grep '^OPENCLAW_GATEWAY_TOKEN=' /home/harvis/harvis-host/.env
# expected: OPENCLAW_GATEWAY_TOKEN=<your-gateway-token>
```

If it differs, the laptop's backend will get "Invalid proxy token" errors and every workspace will fail at the WebSocket handshake. Either change the rig to match, or change the laptop's `.env` and restart the laptop's backend. Whichever you pick, both ends must agree.

### 2. Fix the rig's openclaw.json `harvis-proxy` provider

The rig's openclaw mounts its config from `openclaw/config/<mode>/openclaw.json` (where `<mode>` is `byo` or `bundled` — check `OPENCLAW_MODE` env or the docker-compose override). When the rig's openclaw needs to call an LLM, it talks to whatever `harvis-proxy.baseUrl` points at. Inside the rig's container, the hostname `backend` doesn't resolve to anything useful — it needs to call back to the **laptop's** backend explicitly.

Edit the active config file (likely `openclaw/config/byo/openclaw.json` per the laptop's pattern). The `harvis-proxy` provider should look like:

```jsonc
"models": {
  "mode": "replace",
  "providers": {
    "harvis-proxy": {
      "api": "openai-completions",
      "baseUrl": "http://192.168.10.244:8000/v1",   // ← LAPTOP's LAN IP
      "apiKey": "${OPENCLAW_GATEWAY_TOKEN}",
      "models": [
        { "id": "auto", "name": "Auto (follows /model picked in Discord)" }
      ]
    }
  }
},
"agents": {
  "defaults": {
    "model": { "primary": "harvis-proxy/auto" }
  },
  "list": [
    { "id": "main", "default": true, "model": { "primary": "harvis-proxy/auto" } }
  ]
}
```

Then restart the openclaw container so the new config is picked up:

```bash
cd /home/harvis/harvis-host
docker compose restart openclaw
```

(The bind-mount-inode gotcha applies: openclaw reads the JSON at process start, so a restart is required even though the file on disk is updated.)

### 3. Pull the target model on the rig's Ollama

```bash
# qwen3:14b — recommended by the laptop session for the 5080.
# Dense 14B Q4 fits comfortably on 16GB VRAM with the 16k context cap,
# strong tool-call discipline.
docker exec -it harvis-ollama ollama pull qwen3:14b   # adjust container name if different on rig
# OR if Ollama is host-installed:
ollama pull qwen3:14b
```

About 8-9 GB download.

### 4. Verify 100% GPU residency

After the pull finishes, load the model once to get an `api/ps` entry:

```bash
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen3:14b","prompt":"ping","stream":false,"keep_alive":-1}' > /dev/null

curl -s http://localhost:11434/api/ps | python3 -c "
import sys, json
d = json.load(sys.stdin)
for m in d.get('models', []):
    sv = m.get('size_vram', 0); st = m.get('size', 0)
    pct = (sv/st*100) if st else 0
    print(f\"{m['name']:30s} {pct:.0f}% on GPU ({sv/1e9:.1f}/{st/1e9:.1f}GB)\")"
```

**Pass criterion:** `100% on GPU`. If less (partial CPU offload), the 14B is too big for available VRAM after KV cache reservation. Drop to `qwen3:8b` or apply more aggressive context-length env caps.

### 5. Confirm the rig's `OLLAMA_CONTEXT_LENGTH` env

The laptop uses `OLLAMA_CONTEXT_LENGTH=16384` to keep KV cache small. The rig has more VRAM headroom, so it can probably use 32768 or even 65536 without OOM. Check the rig's docker-compose for Ollama:

```bash
docker exec harvis-ollama env | grep -E '^OLLAMA_(CONTEXT_LENGTH|KEEP_ALIVE|FLASH_ATTENTION|KV_CACHE_TYPE)'
```

Recommended starting values for the 5080:
```
OLLAMA_CONTEXT_LENGTH=32768
OLLAMA_KEEP_ALIVE=-1
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
```

If `FLASH_ATTENTION` or `KV_CACHE_TYPE` is missing, add them to the rig's docker-compose ollama service env, `docker compose up -d --no-deps ollama`.

### 6. Smoke test from rig → laptop → rig (round-trip)

This proves the full loop works before involving Discord. From the rig:

```bash
# Call the laptop's model_proxy with harvis-proxy/auto, which will:
#   1. Strip the prefix
#   2. Hit the auto-sentinel branch
#   3. Look up openclaw_llm_config for the current /model pick
#   4. If model is on rig, route to http://192.168.20.58:11434
#   5. Stream back the response

LAPTOP=192.168.10.244
TOK=<your-gateway-token>

curl -sS -X POST http://$LAPTOP:8000/v1/chat/completions \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  --max-time 60 \
  -d '{
    "model": "harvis-proxy/auto",
    "messages": [{"role":"user","content":"reply with the single word PONG"}],
    "max_tokens": 30,
    "stream": false
  }' | python3 -m json.tool
```

**Pass criterion:** HTTP 200 with a `choices[0].message.content` that says "PONG". The `model` field in the response should be `qwen3:14b` (or whichever model the laptop's `/model` pick resolved to). If you see the model running on the rig's Ollama in `api/ps` after this call, the routing chain is healthy.

### 7. After all checks pass — tell the user to fire the NCL benchmark in Discord

```
@Harvis-Bot Pokemon (Medium)(100 points)25 attempts remaining
Cyber Command
Our analysts have obtained password dumps storing hacker passwords. After obtaining a few plaintext passwords, it appears that they are based on Pokemon.

a532443f3e04a9e00295a8cd2a75e080
54c10b9736b70e75c6e505f340b6e2f1
b8a24794813a47521b4be55747e0665a
83b020b0a7b3c353e1c11b1647b53cda
999cae1e22fe69d89d6f56e3050f18cb
```

The laptop bot will dispatch to the rig's openclaw, which will run qwen3:14b on the 5080. Watch the laptop's backend logs (`docker logs harvis-backend -f`) for the connection trace.

---

## Failure modes you might hit (and quick diagnoses)

| Symptom | Likely cause | Fix |
|---|---|---|
| Discord: workspace fails immediately with "Connection refused" | Rig openclaw not running or port not LAN-exposed | `docker ps` on rig + check the openclaw service is up + verify `0.0.0.0:18789:18789` port binding |
| Discord: "Invalid proxy token" or auth errors | Token mismatch | Re-sync `OPENCLAW_GATEWAY_TOKEN` between rig `.env` and laptop `.env` |
| Workspace launches but agent never produces output | Rig openclaw can't reach laptop backend (harvis-proxy callback) | curl from inside the rig's openclaw container: `docker exec harvis-openclaw curl http://192.168.10.244:8000/health` — should return 200 |
| Agent runs but model is wrong | model_proxy resolver didn't find the model on rig Ollama | Check laptop backend logs for `model_proxy: capping ollama num_ctx=` and `model_proxy: resolved` lines; ensure rig Ollama has the model in `api/tags` |
| GPU residency < 100% | KV cache too big OR model too big | Lower `OLLAMA_CONTEXT_LENGTH` on rig, or pick a smaller model (qwen3:8b) |

---

## What this brief deliberately does NOT do

- It does not commit anything to git. The rig setup is local-machine config, not a product feature.
- It does not touch the laptop's code. The laptop has been wired for the rig via `docker-compose.override.yml` (gitignored). The rig session should not edit anything in `/home/ommblitz/Projects/Recent-EX/Harvis/` (different machine anyway).
- It does not pre-pick a model beyond `qwen3:14b`. If you want to try other 14B-class models or experiment with sizes, that's fine — just confirm GPU residency after the swap.
- It does not enable any production-facing flag. This is purely benchmark/eval infrastructure.

---

## Quick reference

- **Laptop LAN IP**: `192.168.10.244`
- **Rig LAN IP**: `192.168.20.58`
- **Shared gateway token**: `<your-gateway-token>`
- **Rig openclaw config (probable)**: `/home/harvis/harvis-host/openclaw/config/byo/openclaw.json`
- **Target model**: `qwen3:14b`
- **Smoke test endpoint**: `http://192.168.10.244:8000/v1/chat/completions`

If anything in the rig's directory structure doesn't match the laptop's pattern (different config paths, different compose layout), trust what's actually on disk over what this brief assumes — and tell the user so they can update this doc.
