---
name: harvis-ssh
description: >
  SSH access to the harvis user account on dulc3-os (10.0.0.2). Gives OpenClaw
  command-line access to docker, kubectl, git, and the codebase.
metadata:
  openclaw:
    emoji: "🔑"
    always: false
    requires:
      bins: [ssh, scp, curl, jq]
---

# Harvis SSH Skill

Use this skill when OpenClaw needs to execute commands on dulc3-os.

## Connection Details

| Property | Value |
|----------|-------|
| Host | `10.0.0.2` (dulc3-os) |
| User | harvis |
| Auth | SSH key at `/home/node/.ssh/id_ed25519` |
| KUBECONFIG | `/home/harvis/.kube/config` |

## SSH Connection

```bash
ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@10.0.0.2
```

## Important: Non-interactive Shell Limitation

SSH command execution (non-interactive) does NOT source `~/.bashrc` or `~/.bash_profile`.
For kubectl commands, wrap in `bash -l -c "..."`:

```bash
# WRONG — KUBECONFIG won't be set:
ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@10.0.0.2 \
  "kubectl get pods -n ai-agents"

# CORRECT — login shell sources .bash_profile:
ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@10.0.0.2 \
  "bash -l -c 'kubectl get pods -n ai-agents'"
```

## Once Connected

harvis has access to:
- **docker** — manage containers, images, k8s deployments
- **kubectl** — manage K8s cluster (requires `bash -l -c` wrapper)
- **git** — version control (no sudo)
- **python3, node** — run scripts
- **vim, nano, code** — edit files
- **scp, rsync** — transfer files

## Security Boundaries

- **No sudo** — harvis cannot escalate privileges
- **No port forwarding** — disabled in authorized_keys
- **No X11 forwarding** — disabled in authorized_keys
- **No agent forwarding** — disabled in authorized_keys

## Common Tasks

### Run a docker command
```bash
ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@10.0.0.2 \
  "docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

### Run kubectl (always use bash -l -c wrapper)
```bash
ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@10.0.0.2 \
  "bash -l -c 'kubectl get pods -n ai-agents --no-headers'"
```

### Execute a multi-line script
```bash
ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@10.0.0.2 \
  'bash -l -c "
    cd /home/harvis/harvis-workspace/aidev
    git status
    ls python_back_end/
  "'
```

### SCP a file to the harvis user
```bash
scp -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no myfile.txt \
  harvis@10.0.0.2:/home/harvis/harvis-workspace/
```

### SCP a file from the harvis user
```bash
scp -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no \
  harvis@10.0.0.2:/home/harvis/harvis-workspace/aidev/output.txt ./
```

## When to Use SSH vs Direct Tools

| Use SSH when... | Use direct tools when... |
|----------------|--------------------------|
| Need docker/kubectl | Need to read/write files in OpenClaw context |
| Need to run arbitrary commands | Need to interact with OpenClaw protocol |
| Need to access the host filesystem | Need to call other OpenClaw tools |
| Need to build/run the project | Need RAG search (use harvis-rag skill) |

## Error Handling

If SSH fails with "Permission denied":
- Check that the SSH key is added to harvis's authorized_keys

If SSH fails with "Could not resolve hostname":
- Use the host's IP address directly: `10.0.0.2`

If SSH fails with "connection refused":
- Check that SSH server is running on the host: `systemctl status sshd`

If commands are blocked:
- harvis has no sudo — this is intentional
- Contact dulc3 for privileged operations
