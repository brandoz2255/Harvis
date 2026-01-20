# Kubernetes DNS Workaround for Model Pulling

## Problem Overview

Your Kubernetes cluster is in a network environment that blocks outbound UDP port 53 traffic from pods. This prevents CoreDNS from querying external DNS servers, causing DNS resolution failures when pulling models or accessing external registries.

**Symptoms:**
- `dial tcp: lookup <domain>: i/o timeout`
- `Error: pull model manifest: Get "https://<registry>": dial tcp: lookup <registry>: i/o timeout`
- Cannot resolve external domains from within pods

## Solution

Add external domain IP addresses directly to CoreDNS's hosts file to bypass DNS lookups.

---

## Quick Reference Guide

### When You Need to Pull a Model

**Step 1: Identify the registry domain**

For Ollama models, the registry is: `registry.ollama.ai`

For other sources, check the error message or documentation.

---

**Step 2: Get the IP addresses**

Run this command **from your local machine** (not inside a pod):

```bash
dig +short <registry-domain>
```

**Example:**
```bash
dig +short registry.ollama.ai
```

**Output:**
```
104.21.75.227
172.67.182.229
```

**Alternative using nslookup:**
```bash
nslookup <registry-domain> 8.8.8.8
```

---

**Step 3: Get current CoreDNS hosts**

```bash
kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}'
```

This shows you the current entries. You'll need to preserve these.

---

**Step 4: Add the new entries**

Create the updated hosts content with ALL entries (old + new):

```bash
kubectl patch configmap coredns -n kube-system --type='json' -p='[{
  "op": "replace",
  "path": "/data/NodeHosts",
  "value": "139.182.180.125 pop-os-343570d8 pop-os\n139.182.180.198 pop-os\n104.21.75.227 registry.ollama.ai\n172.67.182.229 registry.ollama.ai\n<NEW_IP> <NEW_DOMAIN>"
}]'
```

**IMPORTANT:** Replace `<NEW_IP>` and `<NEW_DOMAIN>` with your values, and keep all existing entries!

---

**Step 5: Restart CoreDNS**

```bash
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system --timeout=60s
```

---

**Step 6: Wait for pod DNS refresh (if needed)**

If your target pod was already running, delete it to get new DNS settings:

```bash
# Find the pod
kubectl get pods -n <namespace>

# Delete it (deployment will recreate it)
kubectl delete pod <pod-name> -n <namespace>
```

Or wait 5-10 minutes for the pod's DNS cache to expire naturally.

---

**Step 7: Verify DNS resolution**

Test from inside a pod:

```bash
kubectl exec -n <namespace> <pod-name> -- sh -c 'getent hosts <domain>'
```

**Example:**
```bash
kubectl exec -n ai-agents harvis-ai-ollama-77f48b6447-2ckgk -- sh -c 'getent hosts registry.ollama.ai'
```

**Expected output:**
```
104.21.75.227   registry.ollama.ai
```

---

**Step 8: Pull your model**

Now you can pull models normally:

```bash
kubectl exec -n ai-agents <ollama-pod> -- ollama pull <model-name>
```

**Example:**
```bash
kubectl exec -n ai-agents harvis-ai-ollama-77f48b6447-2ckgk -- ollama pull qwen2.5-coder:3b
```

---

## Complete Example: Adding Hugging Face Hub

Let's say you need to access `huggingface.co`:

```bash
# Step 1: Get IP addresses
dig +short huggingface.co
# Output: 13.224.157.84, 13.224.157.26, etc.

# Step 2: Get current hosts
kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}'

# Step 3: Add new entries (preserving old ones)
kubectl patch configmap coredns -n kube-system --type='json' -p='[{
  "op": "replace",
  "path": "/data/NodeHosts",
  "value": "139.182.180.125 pop-os-343570d8 pop-os\n139.182.180.198 pop-os\n104.21.75.227 registry.ollama.ai\n172.67.182.229 registry.ollama.ai\n13.224.157.84 huggingface.co\n13.224.157.26 huggingface.co"
}]'

# Step 4: Restart CoreDNS
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system --timeout=60s

# Step 5: Test
kubectl run test-dns --image=busybox:1.36 --rm -i --restart=Never -- sh -c 'getent hosts huggingface.co'
```

---

## Common Registries You Might Need

### Ollama Registry
```
Domain: registry.ollama.ai
IPs: 104.21.75.227, 172.67.182.229
```

### Docker Hub
```bash
dig +short registry-1.docker.io
# Add all returned IPs
```

### GitHub Container Registry
```bash
dig +short ghcr.io
# Add all returned IPs
```

### Hugging Face
```bash
dig +short huggingface.co
dig +short cdn.huggingface.co
# Add all returned IPs for both domains
```

### PyPI (pip packages)
```bash
dig +short pypi.org
dig +short files.pythonhosted.org
# Add all returned IPs for both domains
```

---

## Helper Script

Create a script to automate this process:

```bash
#!/bin/bash
# File: add-dns-entry.sh
# Usage: ./add-dns-entry.sh <domain>

DOMAIN=$1

if [ -z "$DOMAIN" ]; then
    echo "Usage: $0 <domain>"
    echo "Example: $0 registry.ollama.ai"
    exit 1
fi

echo "🔍 Resolving $DOMAIN..."
IPS=$(dig +short $DOMAIN | grep -E '^[0-9]+\.')

if [ -z "$IPS" ]; then
    echo "❌ Failed to resolve $DOMAIN"
    exit 1
fi

echo "✅ Found IPs:"
echo "$IPS"

echo ""
echo "📋 Current CoreDNS hosts:"
CURRENT_HOSTS=$(kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}')
echo "$CURRENT_HOSTS"

echo ""
echo "➕ New entries to add:"
while IFS= read -r ip; do
    echo "$ip $DOMAIN"
done <<< "$IPS"

echo ""
read -p "Add these entries to CoreDNS? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    NEW_ENTRIES=""
    while IFS= read -r ip; do
        NEW_ENTRIES="${NEW_ENTRIES}\n${ip} ${DOMAIN}"
    done <<< "$IPS"

    NEW_HOSTS="${CURRENT_HOSTS}${NEW_ENTRIES}"

    kubectl patch configmap coredns -n kube-system --type='json' -p="[{
        \"op\": \"replace\",
        \"path\": \"/data/NodeHosts\",
        \"value\": \"${NEW_HOSTS}\"
    }]"

    echo "🔄 Restarting CoreDNS..."
    kubectl rollout restart deployment coredns -n kube-system
    kubectl rollout status deployment coredns -n kube-system --timeout=60s

    echo "✅ Done! DNS entries added for $DOMAIN"
    echo ""
    echo "Test with:"
    echo "  kubectl run test-dns --image=busybox:1.36 --rm -i --restart=Never -- sh -c 'getent hosts $DOMAIN'"
else
    echo "❌ Cancelled"
fi
```

**Make it executable:**
```bash
chmod +x add-dns-entry.sh
```

**Usage:**
```bash
./add-dns-entry.sh registry.ollama.ai
./add-dns-entry.sh huggingface.co
```

---

## Troubleshooting

### Issue: IPs change over time (CDN/load balancers)

**Problem:** Services behind CDNs (like Cloudflare) may change IPs.

**Solution:** If pulls start failing again, re-resolve and update:
```bash
# Get fresh IPs
dig +short registry.ollama.ai

# Update CoreDNS hosts with new IPs
# (Follow steps 3-5 above)
```

### Issue: Too many domains to add manually

**Problem:** Some operations need many domains.

**Long-term solution:** Set up a DNS forwarder on the host network:

1. **Deploy a DNS proxy in host network mode:**
   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: dns-proxy
     namespace: kube-system
   spec:
     hostNetwork: true
     containers:
     - name: dnsmasq
       image: andyshinn/dnsmasq
       args:
       - --log-queries
       - --no-daemon
       - --server=8.8.8.8
       - --server=8.8.4.4
   ```

2. **Update CoreDNS to forward to host DNS proxy:**
   ```
   forward . <NODE_IP>:53
   ```

### Issue: Can't resolve ANY domains

**Check CoreDNS logs:**
```bash
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
```

**Verify CoreDNS is running:**
```bash
kubectl get pods -n kube-system | grep coredns
```

**Check CoreDNS config:**
```bash
kubectl get configmap coredns -n kube-system -o yaml
```

---

## Current DNS Entries (as of 2026-01-20)

```
139.182.180.125 pop-os-343570d8 pop-os
139.182.180.198 pop-os
104.21.75.227 registry.ollama.ai
172.67.182.229 registry.ollama.ai
```

**Note:** Update this list whenever you add new entries for your reference.

---

## Alternative: Use kubectl plugin

Install the kubectl-dns plugin (if available) for easier management:

```bash
# Check if available
kubectl krew search dns

# Example usage (if plugin exists)
kubectl dns add registry.ollama.ai
kubectl dns list
```

---

## Summary

**Every time you need to pull from a new registry:**

1. Get IPs: `dig +short <domain>`
2. Get current hosts: `kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}'`
3. Patch with new entries (preserving old): `kubectl patch configmap coredns -n kube-system --type='json' -p='...'`
4. Restart CoreDNS: `kubectl rollout restart deployment coredns -n kube-system`
5. Test: `kubectl exec <pod> -- getent hosts <domain>`
6. Pull your model/image

**Keep this file updated** with your current DNS entries for easy reference!
