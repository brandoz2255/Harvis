# K3s GPU Operator Fix — CNI Loopback Plugin + ldconfig on Arch Linux

**Issue Date:** 2026-03-14
**Status:** ✅ RESOLVED
**Node:** dulc3-top (Arch Linux, GTX 1650 Ti 4GB)
**Cluster:** K3s (dulc3-os control plane + mixed nodes)

---

## Symptoms

1. `kubectl get node dulc3-top -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'` returned `0`
   despite `nvidia-smi` working fine on the host.
2. GPU operator pods (`nvidia-device-plugin-daemonset-*`, `nvidia-operator-validator-*`) stuck in
   **Unknown** state after VPN outage caused the node to drop from the cluster.
3. After deleting the Unknown pods and running `systemctl restart k3s-agent`, all new pods on
   dulc3-top failed with:
   ```
   Failed to create pod sandbox: failed to setup network for sandbox ...:
   plugin type="loopback" failed (add): failed to find plugin "loopback" in path [/opt/cni/bin]
   ```
4. GPU operator pods rescheduled but never progressed past init containers — blocked by CNI failure.

---

## Root Causes (two separate issues)

### Issue 1 — ldconfig Arch Linux incompatibility

The GPU operator container toolkit writes its runtime config to:
```
/usr/local/nvidia/toolkit/.config/nvidia-container-runtime/config.toml
```

On Debian/Ubuntu nodes the default is:
```toml
ldconfig = "@/sbin/ldconfig.real"
```

Arch Linux has no `/sbin/ldconfig.real` — it only ships `/sbin/ldconfig`. When the toolkit tried
to run ldconfig it received `SIGKILL` (signal 9), which manifested as:
```
nvidia-container-cli.real: ldcache error: process /sbin/ldconfig terminated with signal 9
```

This prevented any container from accessing the GPU even though the driver was loaded.

### Issue 2 — Missing CNI loopback plugin after k3s-agent restart

K3s normally symlinks or installs CNI plugins into `/opt/cni/bin/` on startup. On dulc3-top after
the VPN outage + agent restart, `/opt/cni/bin/` was empty (or missing entirely). Without the
`loopback` CNI plugin, **no pod on the node can start** — this blocked the GPU operator from
making progress and made it look like a GPU issue when it was actually a network plugin issue.

---

## Fix

### Step 1 — Fix ldconfig (Arch Linux only)

On dulc3-top:
```bash
sudo sed -i \
  's|ldconfig = "@/sbin/ldconfig.real"|ldconfig = "@/sbin/ldconfig"|' \
  /usr/local/nvidia/toolkit/.config/nvidia-container-runtime/config.toml

# Verify
grep ldconfig /usr/local/nvidia/toolkit/.config/nvidia-container-runtime/config.toml
# Expected: ldconfig = "@/sbin/ldconfig"
```

Also verify `no-cgroups = true` is set (needed when `systemd` cgroup v2 is in use without full
cgroup driver integration):
```bash
grep no-cgroups /usr/local/nvidia/toolkit/.config/nvidia-container-runtime/config.toml
# Expected: no-cgroups = true
```

### Step 2 — Restore CNI loopback plugin

On dulc3-top:
```bash
# Check current state
ls /opt/cni/bin/ 2>/dev/null || echo "dir missing"

# K3s ships its own CNI binaries here:
ls /var/lib/rancher/k3s/data/current/bin/ | grep -E "loopback|flannel|bridge|host-local"

# Copy all CNI plugins from K3s data dir
sudo mkdir -p /opt/cni/bin
sudo cp /var/lib/rancher/k3s/data/current/bin/* /opt/cni/bin/
sudo chmod +x /opt/cni/bin/*

# Verify loopback is now present
ls /opt/cni/bin/loopback
```

### Step 3 — Restart k3s-agent to pick up CNI plugins

```bash
sudo systemctl restart k3s-agent
```

Wait ~60 seconds, then verify GPU is now advertised:
```bash
# From control plane (dulc3-os)
kubectl get node dulc3-top -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'
# Expected: 1
```

---

## Why CNI Plugins Were Missing

K3s normally places CNI plugins in `/opt/cni/bin/` via its startup sequence. After the VPN
outage caused a hard node disconnect, the k3s-agent restart apparently skipped this step (possibly
due to the directory being present but empty, or a race condition). Copying manually from
`/var/lib/rancher/k3s/data/current/bin/` is the correct fix — that's where K3s bundles them.

---

## Prevention

- **Monitoring**: Add an alert for `nvidia.com/gpu: 0` on nodes where GPU is expected.
- **After VPN reconnects**: Always check `kubectl get node <node> -o wide` and confirm `Ready`
  before assuming GPU workloads will schedule.
- **GPU operator Unknown pods**: If pods go Unknown after a network outage, force-delete them to
  allow rescheduling — don't wait for them to self-recover:
  ```bash
  kubectl delete pod -n gpu-operator --field-selector=status.phase=Unknown --force --grace-period=0
  ```
- **Arch Linux nodes**: The ldconfig fix must be reapplied after every GPU operator upgrade that
  rewrites its config.toml. Consider a DaemonSet or node-level script to enforce it.

---

## Timeline

| Time | Event |
|------|-------|
| VPN outage | dulc3-top drops from cluster; GPU operator pods go Unknown |
| After reconnect | Node rejoins as Ready but GPU shows 0 |
| Investigation | Deleted Unknown pods; GPU still 0 after reschedule |
| Diag 1 | Found ldconfig=`@/sbin/ldconfig.real` in toolkit config (Arch has no `.real`) |
| Fix 1 | sed replaced with `@/sbin/ldconfig`; restarted k3s-agent |
| Diag 2 | All new pods fail: `failed to find plugin "loopback" in path [/opt/cni/bin]` |
| Fix 2 | Copied K3s CNI plugins from `/var/lib/rancher/k3s/data/current/bin/` to `/opt/cni/bin/` |
| Resolution | GPU advertised as `nvidia.com/gpu: 1`; embed-qwen3 scheduled on GPU |

---

## Related

- `k8s-manifests/overlays/prod/llama-embed.yaml` — embed-qwen3 container uses `nvidia.com/gpu: 1`
  on dulc3-top (Qwen3-Embedding-4B Q4_K_M, ~2.5GB fits in 4GB VRAM)
- GPU operator version: v25.3.2
- K3s version: check with `k3s --version` on dulc3-top
