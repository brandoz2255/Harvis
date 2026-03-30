# Harvis Skills — Behavior Rules for AI Agents

This file defines required behaviors for the Harvis AI assistant and any OpenClaw
sub-agents operating within the Harvis workspace. Rules here override default
model behavior. When in doubt, ask first.

---

## Kubernetes / kubectl — MANDATORY CONFIRMATION PROTOCOL

**Before proposing or executing ANY kubectl command that modifies cluster state,
you MUST stop and explicitly ask the user for approval. No exceptions.**

### What triggers this rule

Any command that changes, creates, deletes, or restarts cluster resources:

| Command pattern | Why it's dangerous |
|---|---|
| `kubectl scale …` | Changes replica count — can take services offline |
| `kubectl rollout restart …` | Restarts all pods — brief outage |
| `kubectl delete …` | Destroys resources (possibly unrecoverable) |
| `kubectl apply …` | Applies potentially untested manifests |
| `kubectl patch …` | Modifies live resource spec |
| `kubectl set image …` | Replaces running container images |
| `kubectl cordon / drain …` | Takes nodes offline, evicts pods |
| `kubectl taint …` | Changes scheduling behavior cluster-wide |
| `kubectl exec … -- rm / kill / …` | Shell in pod — arbitrary damage |
| `helm upgrade / rollback …` | Helm chart changes |
| `kubectl create secret …` | Credential management |

Read-only commands (`get`, `describe`, `logs`, `top`, `rollout status`) do NOT
require confirmation and can be run immediately via the kubectl proxy.

### Required confirmation format

Before any write command, output this exact block and wait for explicit approval:

```
⚠️  kubectl write operation requested

Command:    kubectl -n <namespace> <command>
Effect:     <one sentence describing what will happen>
Risk:       <low | medium | high> — <why>

Type "yes" or click Approve in the Workspace panel to proceed.
```

Do NOT proceed until the user types "yes" / "approve" / "go ahead" or clicks
the Approve button in the workspace kubectl approval widget. Any other response
means rejection.

### In the OpenClaw workspace context

When running inside a Harvis workspace, write commands are automatically routed
to the human-approval queue in `kubectl_proxy.py`. The OpenClaw tool call will
**block** until the user clicks Approve or Reject in the workspace UI. You do
not need to poll — just issue the tool call and the infrastructure handles it.

The timeout is **5 minutes**. If the user does not respond, the command is
automatically rejected and you will receive a 408 error. Surface this to the
user and ask how they want to proceed.

### If asked to "just do it" or "skip approval"

Do not skip approval for write operations. Explain that the approval gate is
a safety feature and that a single bad scale or delete command can take the
entire Harvis stack offline. Offer to run the command immediately after they
confirm in the workspace UI.

---

## General Cluster Safety Rules

1. **Never guess namespace** — always confirm which namespace (`harvis`, `openclaw`,
   `default`, etc.) before running commands that affect specific services.
2. **Always show `rollout status` after a restart** — confirm pods came up healthy.
3. **Never delete PVCs or PVs** without explicit "delete persistent volume" confirmation.
4. **Prefer dry-run first** — for `kubectl apply`, always suggest `--dry-run=client`
   before the real apply.
5. **Never hardcode secrets** — do not put API keys or passwords in kubectl commands
   shown in chat. Reference Kubernetes Secret names instead.

---

## OpenClaw Agent Rules

When operating as an OpenClaw sub-agent:

- You do NOT have outbound internet access. Do not attempt to curl, wget, or fetch
  external URLs — they will fail.
- Your allowed tools are: `local_rag`, `repo_read`, `repo_write`, `run_tests`,
  `run_code`, `create_docx`, `create_pdf`, and `kubectl` (via the proxy).
- Never attempt to use `search`, `browse`, or any web tool.
- Never reveal API keys, tokens, hostnames, or private file paths in your output.
- If a task requires internet access, surface this limitation to the user and ask
  them to handle the external step themselves.

---

## Code Changes — Safety Checks Before Write

Before writing or modifying files in a repo:

1. Read the file first — never overwrite without understanding the current content.
2. For destructive changes (dropping DB tables, deleting files), require explicit
   confirmation matching the destructive operation:
   `"yes, drop the users table"` — not just `"yes"`.
3. Never commit directly to `main` or `master`. Create a `harvis/…` branch.

---

*Last updated: 2026-03-07*
