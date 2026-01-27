#!/bin/bash
# Fix DNS for Backend Workstation - Adds Hugging Face domains to CoreDNS
# Run this from a machine that has:
#   1. Working DNS (can resolve domains)
#   2. kubectl access to the cluster

set -e

echo "=========================================="
echo "  Fixing DNS for Backend Workstation"
echo "=========================================="
echo ""

# Domains needed for ML model downloads (Whisper, TTS, etc.)
DOMAINS=(
    "huggingface.co"
    "cdn-lfs.huggingface.co"
    "cdn-lfs-us-1.huggingface.co"
    "cdn.huggingface.co"
)

echo "1. Resolving domains from this machine..."
echo ""

NEW_ENTRIES=""
for domain in "${DOMAINS[@]}"; do
    echo "   Resolving: $domain"
    IPS=$(dig +short "$domain" 2>/dev/null | grep -E '^[0-9]+\.' | head -2)

    if [ -n "$IPS" ]; then
        while IFS= read -r ip; do
            if [ -n "$ip" ]; then
                echo "      -> $ip"
                NEW_ENTRIES="${NEW_ENTRIES}${ip} ${domain}\n"
            fi
        done <<< "$IPS"
    else
        echo "      -> (no IPs found, skipping)"
    fi
done

echo ""
echo "2. Getting current CoreDNS hosts..."
CURRENT_HOSTS=$(kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}' 2>/dev/null)

if [ -z "$CURRENT_HOSTS" ]; then
    echo "   ERROR: Could not get current CoreDNS config"
    echo "   Make sure kubectl is configured and can access the cluster"
    exit 1
fi

echo "   Current entries:"
echo "$CURRENT_HOSTS" | sed 's/^/      /'

echo ""
echo "3. New entries to add:"
echo -e "$NEW_ENTRIES" | sed 's/^/      /'

echo ""
echo "4. Merging entries..."

# Combine current and new, removing duplicates
MERGED_HOSTS=$(echo -e "${CURRENT_HOSTS}\n${NEW_ENTRIES}" | grep -v '^$' | sort -u | tr '\n' '\n')

echo ""
echo "5. Patching CoreDNS configmap..."

# Escape for JSON
ESCAPED_HOSTS=$(echo "$MERGED_HOSTS" | tr '\n' '\\' | sed 's/\\/\\n/g' | sed 's/\\n$//')

kubectl patch configmap coredns -n kube-system --type='json' -p="[{
    \"op\": \"replace\",
    \"path\": \"/data/NodeHosts\",
    \"value\": \"${ESCAPED_HOSTS}\"
}]"

echo "   Done!"

echo ""
echo "6. Restarting CoreDNS..."
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system --timeout=60s

echo ""
echo "=========================================="
echo "  DNS Fix Complete!"
echo "=========================================="
echo ""
echo "Current CoreDNS hosts:"
kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}' | tr '\\n' '\n' | sed 's/^/   /'
echo ""
echo ""
echo "To test, run:"
echo "   kubectl run test-dns --image=busybox:1.36 --rm -i --restart=Never -- sh -c 'getent hosts huggingface.co'"
echo ""
echo "Then redeploy the backend:"
echo "   kubectl delete pod -n ai-agents -l app.kubernetes.io/component=backend,app.kubernetes.io/variant=workstation"
echo ""
