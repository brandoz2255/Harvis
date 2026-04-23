#!/bin/bash
# deploy-openclaw-ssh.sh
# Deploy SSH access for OpenClaw to host machine (dulc3-top)
# Run from: /home/dulc3/Documents/github/harvis/aidev

set -e

SSH_KEY="$HOME/.ssh/id_ed25519"
HOST_IP="10.0.0.4"  # dulc3-top (main machine with harvis user)
NAMESPACE="ai-agents"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPENCLAW_DIR="$SCRIPT_DIR/k8s-manifests/overlays/prod"

echo "=== OpenClaw SSH Deployment ==="
echo "OpenClaw pod: rocky2vm.local (10.0.0.6)"
echo "Target host: dulc3-top ($HOST_IP)"

# 1. Create SSH key secret
echo "[1/3] Creating SSH key secret..."
kubectl create secret generic openclaw-ssh-key \
  --from-file=harvis_key="$SSH_KEY" \
  --namespace="$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Apply network policy (with correct host IP)
echo "[2/3] Applying network policy..."
sed "s/192.168.1.100/$HOST_IP/g" "$OPENCLAW_DIR/openclaw-network.yaml" | kubectl apply -f -

# 3. Apply updated OpenClaw deployment
echo "[3/3] Applying OpenClaw deployment..."
kubectl apply -f "$OPENCLAW_DIR/openclaw.yaml"

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Next steps:"
echo "1. kubectl get pods -n $NAMESPACE -l component=openclaw -w"
echo "2. kubectl exec -n $NAMESPACE deploy/harvis-ai-openclaw -- ls -la /home/node/.ssh/"
echo "3. Test SSH: kubectl exec -n $NAMESPACE deploy/harvis-ai-openclaw -- bash -c 'ssh -i /home/node/.ssh/id_ed25519 -o StrictHostKeyChecking=no harvis@$HOST_IP \"docker ps\"'"
