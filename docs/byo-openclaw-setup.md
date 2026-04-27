# BYO OpenClaw Setup Guide

Run your own OpenClaw instance alongside Harvis to unlock full agent capabilities: GitHub PR automation, unrestricted code execution, kubectl cluster access, and your own model choice.

## Prerequisites

| Requirement | Minimum |
|---|---|
| Node.js | v20+ |
| RAM | 8 GB (for agent + model) |
| Storage | 4 GB |
| Ollama (or compatible) | Running locally or accessible |

## Installation

### 1. Install OpenClaw

```bash
npm install -g @anthropic/openclaw
```

### 2. Initialize Configuration

```bash
openclaw init
# Creates ~/.openclaw/openclaw.json
```

### 3. Configure Your LLM

Edit `~/.openclaw/openclaw.json` and set your model provider:

```json
{
  "model": {
    "provider": "ollama",
    "baseUrl": "http://localhost:11434",
    "model": "qwen2.5-coder:32b"
  }
}
```

### 4. Start the Gateway

```bash
openclaw gateway --port 18789 --bind lan
```

The gateway must be reachable from the Harvis backend. If Harvis runs in Docker:
- Use `host.docker.internal:18789` (Docker Desktop)
- Use your LAN IP (Linux): `ws://192.168.x.x:18789`

### 5. Copy Your Gateway Token

```bash
cat ~/.openclaw/openclaw.json | grep -i token
```

Copy the `gateway_token` value — you'll paste this into Harvis Settings.

### 6. Configure Harvis

1. Navigate to **Settings → OpenClaw Mode**
2. Enter your Gateway URL: `ws://localhost:18789` (or `ws://YOUR_IP:18789`)
3. Enter your Gateway Token
4. Click **Test Connection** — wait for the green checkmark
5. Click **Save & Switch to BYO**

### 7. Verify

Launch a workspace and confirm the header shows **BYO** mode. Try a GitHub or kubectl task — if it works, you're set.

## Networking Troubleshooting

| Symptom | Fix |
|---|---|
| Connection refused | `openclaw gateway` not running, or port blocked by firewall |
| Connection timed out | Firewall / NAT / WSL2 not forwarding. Bind to `0.0.0.0` |
| Protocol mismatch | Update OpenClaw: `npm update -g @anthropic/openclaw` |
| Invalid token | Regenerate: delete `~/.openclaw/openclaw.json`, re-init |

### WSL2 Users

WSL2 requires port forwarding from Windows host:

```powershell
netsh interface portproxy add v4tov4 listenport=18789 listenaddress=0.0.0.0 connectport=18789 connectaddress=$(wsl hostname -I)
```

## Reverting to Bundled

Navigate to **Settings → OpenClaw Mode** and click **Switch to Bundled**. Your BYO config is preserved for later.

## Security Notes

- Your gateway token is encrypted at rest (Fernet AES-128-CBC) in the Harvis database
- Harvis never stores your OpenClaw config files
- The verification endpoint only checks reachability — it doesn't store credentials unless verification succeeds
- BYO mode grants all capabilities; ensure your OpenClaw has appropriate exec-approvals
