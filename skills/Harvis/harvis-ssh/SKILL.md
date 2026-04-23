---
name: harvis-ssh
description: >
  SSH access to the harvis user account on the host machine. Gives OpenClaw
  command-line access to docker, kubectl, git, and the codebase — same
  capabilities as opencode but via SSH.
metadata:
  openclaw:
    emoji: "🔑"
    always: false
    requires:
      bins: [ssh, scp, curl, jq]
---

# Harvis SSH Skill

Use this skill when OpenClaw needs to execute commands on the host machine
or access the codebase directly.

## Connection Details

| Property | Value |
|----------|-------|
| Host | `host.docker.internal` (Docker) or host IP (K8s) |
| User | harvis |
| Auth | SSH key at `/home/node/.ssh/harvis_key` |
| Workspace | /home/harvis/harvis-workspace/aidev |

## SSH Connection

```bash
ssh -i /home/node/.ssh/harvis_key -o StrictHostKeyChecking=no harvis@host.docker.internal
```

For K8s, replace `host.docker.internal` with your host IP (e.g., `192.168.1.100`).

## SSH Configuration (mount the key!)

The SSH key must be mounted into the container:

### Docker Compose
Add to the openclaw service volumes:
```yaml
volumes:
  - ./openclaw/.ssh:/home/node/.ssh:ro
```

Create the key:
```bash
mkdir -p openclaw/.ssh
cp ~/.ssh/id_ed25519 openclaw/.ssh/harvis_key
chmod 600 openclaw/.ssh/harvis_key
```

### K8s Secret
```bash
kubectl create secret generic openclaw-ssh-key \
  --from-file=harvis_key=~/.ssh/id_ed25519 \
  --namespace=ai-agents

# Then mount in openclaw pod spec:
# volumes:
#   - name: ssh-key
#     secret:
#       secretName: openclaw-ssh-key
# containers:
#   - volumeMounts:
#       - name: ssh-key
#         mountPath: /home/node/.ssh/harvis_key
#         subPath: harvis_key
```

## Once Connected

harvis has access to:
- **docker** — manage containers, images, k8s deployments
- **kubectl** — manage K8s cluster
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
ssh -i /home/node/.ssh/harvis_key -o StrictHostKeyChecking=no harvis@host.docker.internal \
  "docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

### Execute a multi-line script
```bash
ssh -i /home/node/.ssh/harvis_key -o StrictHostKeyChecking=no harvis@host.docker.internal << 'EOF'
cd /home/harvis/harvis-workspace/aidev
git status
ls python_back_end/
EOF
```

### SCP a file to the harvis user
```bash
scp -i /home/node/.ssh/harvis_key -o StrictHostKeyChecking=no myfile.txt \
  harvis@host.docker.internal:/home/harvis/harvis-workspace/
```

### SCP a file from the harvis user
```bash
scp -i /home/node/.ssh/harvis_key -o StrictHostKeyChecking=no \
  harvis@host.docker.internal:/home/harvis/harvis-workspace/aidev/output.txt ./
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
- Ensure no-port-forwarding is set (allows SSH but blocks port forwarding)

If SSH fails with "Could not resolve hostname":
- Docker: use `host.docker.internal`
- K8s: use the host's IP address directly

If SSH fails with "connection refused":
- Check that SSH server is running on the host: `systemctl status sshd`
- Check that the host IP is reachable from the container/pod

If commands are blocked:
- harvis has no sudo — this is intentional
- Contact dulc3 for privileged operations
