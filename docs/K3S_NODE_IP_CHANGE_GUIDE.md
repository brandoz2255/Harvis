# K3s Multi-Node Cluster: Node IP Change Guide

## Problem Summary

When a K3s node's IP address changes (e.g., network reconfiguration, moving between networks), the cluster experiences critical failures:

- **502 Bad Gateway** errors when accessing pods on remote nodes
- Unable to get logs: `kubectl logs` fails with proxy errors
- Unable to exec into pods: `kubectl exec` fails
- Node status errors: "failed to validate nodeIP: node IP not found"
- API server cannot communicate with kubelet on affected nodes

## Root Cause

K3s binds to specific IP addresses during initial setup. When the IP changes:

1. **Kubelet registers with old IP** - Node tries to use an IP that no longer exists on the interface
2. **Certificate mismatch** - TLS certificates reference the old IP
3. **API server can't proxy** - API server tries to connect to kubelet using old/invalid certificates
4. **Inter-node communication breaks** - Nodes can't communicate using outdated IPs

## Real-World Scenario (Our Case)

**Initial Setup:**
- Node1 (control plane): `192.168.1.195` (local network)
- Node2 (worker): `10.20.0.125` (remote/public IP)

**After Network Change:**
- Node1 moved to: `10.20.0.198` (same network as node2)
- K3s still configured with: `192.168.1.195` ❌

**Symptoms:**
```bash
# Error in K3s logs
E1202 19:27:11.228237 2476 kubelet_node_status.go:719 "Failed to set some node status fields"
err="failed to validate nodeIP: node IP: \"192.168.1.195\" not found in the host's network interfaces"

# 502 errors when accessing node2 pods
Error from server: Get "https://10.20.0.125:10250/containerLogs/...":
proxy error from 127.0.0.1:6443 while dialing 10.20.0.125:10250, code 502: 502 Bad Gateway
```

---

## Solution: Reconfigure K3s with New IPs

### Step 1: Update Control Plane (Server) Node

**On the control plane node (node1):**

```bash
#!/bin/bash
# Save as: fix_k3s_server_ip.sh

# Stop K3s server
sudo systemctl stop k3s

# Update K3s configuration with new IP
NEW_IP="10.20.0.198"  # Update this to your new IP

sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml << EOF
node-ip: ${NEW_IP}
node-external-ip: ${NEW_IP}
bind-address: ${NEW_IP}
advertise-address: ${NEW_IP}
tls-san:
  - ${NEW_IP}
  - $(hostname)
EOF

# Restart K3s server
sudo systemctl restart k3s

# Wait for startup
sleep 15

# Verify
kubectl get nodes -o wide
```

**Configuration Explained:**
- `node-ip`: IP kubelet advertises to the cluster
- `node-external-ip`: External-facing IP for the node
- `bind-address`: IP the API server binds to
- `advertise-address`: IP the API server advertises to nodes
- `tls-san`: Subject Alternative Names for TLS certificates

### Step 2: Rejoin Worker Nodes (If Certificate Issues Persist)

If you still get 502 errors after updating the server, worker nodes need new certificates.

**Get the node token from control plane:**
```bash
# On node1 (control plane)
sudo cat /var/lib/rancher/k3s/server/node-token
```

**Rejoin worker node:**
```bash
#!/bin/bash
# Save as: rejoin_k3s_agent.sh
# Run on worker node (node2)

K3S_TOKEN="<paste-token-here>"
K3S_URL="https://10.20.0.198:6443"  # Control plane IP

# Stop agent
sudo systemctl stop k3s-agent

# Backup old data (optional but recommended)
sudo mv /var/lib/rancher/k3s/agent /var/lib/rancher/k3s/agent.backup

# Clear old agent data to force certificate regeneration
sudo rm -rf /var/lib/rancher/k3s/agent

# Restart agent (will rejoin with new certificates)
sudo systemctl start k3s-agent

# Verify
sudo systemctl status k3s-agent
```

### Step 3: Update NFS Configuration (If Using NFS)

If using NFS for shared storage, update the NFS server IP in PersistentVolumes:

**Before:**
```yaml
nfs:
  server: 192.168.1.195
  path: /srv/nfs/ml-models-cache
```

**After:**
```yaml
nfs:
  server: 10.20.0.198
  path: /srv/nfs/ml-models-cache
```

**Apply updates:**
```bash
# Delete old PVs/PVCs
kubectl delete pvc nfs-ml-models-cache -n ai-agents
kubectl delete pv nfs-ml-models-cache-pv

# Force remove if stuck
kubectl patch pv nfs-ml-models-cache-pv -p '{"metadata":{"finalizers":null}}'

# Recreate with new IP
kubectl apply -f k8s-manifests/storage/nfs-storage.yaml
```

---

## Verification Steps

### 1. Check Node IPs
```bash
kubectl get nodes -o wide
```
Expected output shows correct INTERNAL-IP and EXTERNAL-IP.

### 2. Check Kubelet Logs
```bash
# Should NOT show nodeIP errors
sudo journalctl -u k3s -n 50 | grep -i "nodeIP\|node IP"
```

### 3. Test Pod Logs Access
```bash
# Should work without 502 errors
kubectl logs <pod-name> -n <namespace>
```

### 4. Test Pod Exec
```bash
# Should work without proxy errors
kubectl exec -it <pod-name> -n <namespace> -- bash
```

### 5. Direct Kubelet Health Check
```bash
# From control plane, test worker kubelet
curl -k https://<worker-ip>:10250/healthz
# Should return: Unauthorized (this is normal, means connection works)
```

---

## Prevention & Best Practices

### 1. Use Static IPs for Cluster Nodes
- Assign static IPs to all cluster nodes
- Avoid DHCP for production clusters
- Document IP assignments

### 2. Use DNS Names Instead of IPs
Configure K3s with hostnames instead of IPs when possible:

```yaml
node-ip: $(hostname -I | awk '{print $1}')  # Auto-detect
tls-san:
  - node1.example.com
  - node2.example.com
```

### 3. Plan for IP Changes
If IP changes are expected (cloud migrations, network reconfigurations):

**Option A: Full cluster rebuild**
- Export resources: `kubectl get all --all-namespaces -o yaml > backup.yaml`
- Rebuild cluster with new IPs
- Restore resources

**Option B: Rolling update**
- Update one node at a time
- Drain node before IP change
- Reconfigure and rejoin
- Verify before moving to next node

### 4. Monitor Kubelet Health
Set up monitoring for:
- Kubelet certificate expiration
- Node IP validation errors
- API server → Kubelet proxy errors

### 5. Document Your Infrastructure
Maintain documentation of:
- Current node IPs
- K3s token location
- NFS server IPs
- Network topology

---

## Common Errors & Solutions

### Error: "failed to validate nodeIP: node IP not found"
**Cause:** K3s configured with old IP that doesn't exist on interface
**Solution:** Update `/etc/rancher/k3s/config.yaml` with current IP

### Error: "502 Bad Gateway" when getting logs
**Cause:** API server can't authenticate to kubelet (certificate mismatch)
**Solution:** Rejoin worker node to regenerate certificates

### Error: NFS mount timeout
**Cause:** NFS PersistentVolume references old server IP
**Solution:** Delete and recreate PV with new IP

### Error: "connection refused" to kubelet port 10250
**Cause:** Firewall blocking kubelet port
**Solution:** Open port 10250/tcp between nodes

---

## Quick Troubleshooting Checklist

```bash
# 1. Verify current IPs
ip -4 addr show | grep "inet "

# 2. Check what K3s is configured with
cat /etc/rancher/k3s/config.yaml

# 3. Check node registration
kubectl get nodes -o wide

# 4. Check kubelet logs for errors
sudo journalctl -u k3s -n 100 | grep -E "error|Error|failed"

# 5. Test kubelet connectivity
curl -k https://<node-ip>:10250/healthz

# 6. Test kubectl logs (should work if everything is fixed)
kubectl logs <any-pod> -n <namespace>
```

---

## Files Modified in Our Fix

1. `/etc/rancher/k3s/config.yaml` - Added IP configuration
2. `k8s-manifests/storage/nfs-storage.yaml` - Updated NFS server IP from 192.168.1.195 → 10.20.0.198
3. `python_back_end/download_models.py` - Made NFS permission errors non-fatal
4. `k8s-manifests/services/ollama-dedicated.yaml` - Removed failing model downloads from startup

---

## Additional Resources

- [K3s Networking Documentation](https://docs.k3s.io/networking)
- [K3s Server Configuration Reference](https://docs.k3s.io/reference/server-config)
- [K3s Agent Configuration Reference](https://docs.k3s.io/reference/agent-config)
- [Kubernetes Node Registration](https://kubernetes.io/docs/reference/node/)
