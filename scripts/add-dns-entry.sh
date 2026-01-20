#!/bin/bash
# Add DNS entries to CoreDNS for Kubernetes cluster DNS workaround
# Usage: ./add-dns-entry.sh <domain>
# Example: ./add-dns-entry.sh registry.ollama.ai

set -e

DOMAIN=$1

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}❌ Error: No domain provided${NC}"
    echo ""
    echo "Usage: $0 <domain>"
    echo ""
    echo "Examples:"
    echo "  $0 registry.ollama.ai"
    echo "  $0 huggingface.co"
    echo "  $0 ghcr.io"
    exit 1
fi

echo -e "${BLUE}🔍 Resolving $DOMAIN...${NC}"
IPS=$(dig +short "$DOMAIN" | grep -E '^[0-9]+\.')

if [ -z "$IPS" ]; then
    echo -e "${RED}❌ Failed to resolve $DOMAIN${NC}"
    echo ""
    echo "Trying with nslookup as fallback..."
    IPS=$(nslookup "$DOMAIN" 8.8.8.8 2>/dev/null | grep -A10 'Name:' | grep 'Address:' | awk '{print $2}' | grep -E '^[0-9]+\.')

    if [ -z "$IPS" ]; then
        echo -e "${RED}❌ Still failed to resolve $DOMAIN${NC}"
        echo "Please check:"
        echo "  1. Domain name is correct"
        echo "  2. You have internet connectivity"
        echo "  3. DNS is working on your local machine"
        exit 1
    fi
fi

echo -e "${GREEN}✅ Found IPs:${NC}"
while IFS= read -r ip; do
    echo "  $ip"
done <<< "$IPS"

echo ""
echo -e "${BLUE}📋 Current CoreDNS hosts:${NC}"
CURRENT_HOSTS=$(kubectl get configmap coredns -n kube-system -o jsonpath='{.data.NodeHosts}' 2>/dev/null)

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to get CoreDNS config. Check kubectl access.${NC}"
    exit 1
fi

echo "$CURRENT_HOSTS" | while IFS= read -r line; do
    echo "  $line"
done

# Check if domain already exists
if echo "$CURRENT_HOSTS" | grep -q " $DOMAIN"; then
    echo ""
    echo -e "${YELLOW}⚠️  Warning: $DOMAIN already exists in CoreDNS hosts${NC}"
    echo "Existing entries:"
    echo "$CURRENT_HOSTS" | grep " $DOMAIN"
    echo ""
    read -p "Do you want to replace these entries? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}❌ Cancelled${NC}"
        exit 0
    fi
    # Remove old entries for this domain
    CURRENT_HOSTS=$(echo "$CURRENT_HOSTS" | grep -v " $DOMAIN$")
fi

echo ""
echo -e "${GREEN}➕ New entries to add:${NC}"
while IFS= read -r ip; do
    echo "  $ip $DOMAIN"
done <<< "$IPS"

echo ""
read -p "Add these entries to CoreDNS? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Build new hosts content
    NEW_HOSTS="$CURRENT_HOSTS"
    while IFS= read -r ip; do
        if [ -n "$NEW_HOSTS" ]; then
            NEW_HOSTS="${NEW_HOSTS}"$'\n'"${ip} ${DOMAIN}"
        else
            NEW_HOSTS="${ip} ${DOMAIN}"
        fi
    done <<< "$IPS"

    # Escape for JSON
    NEW_HOSTS_ESCAPED=$(echo "$NEW_HOSTS" | sed 's/\\/\\\\/g' | sed ':a;N;$!ba;s/\n/\\n/g')

    echo -e "${BLUE}🔄 Updating CoreDNS ConfigMap...${NC}"
    kubectl patch configmap coredns -n kube-system --type='json' -p="[{
        \"op\": \"replace\",
        \"path\": \"/data/NodeHosts\",
        \"value\": \"${NEW_HOSTS_ESCAPED}\"
    }]"

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Failed to update CoreDNS ConfigMap${NC}"
        exit 1
    fi

    echo -e "${BLUE}🔄 Restarting CoreDNS...${NC}"
    kubectl rollout restart deployment coredns -n kube-system

    echo -e "${BLUE}⏳ Waiting for CoreDNS rollout to complete...${NC}"
    kubectl rollout status deployment coredns -n kube-system --timeout=60s

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✅ Done! DNS entries added for $DOMAIN${NC}"
        echo ""
        echo -e "${YELLOW}📝 Note: Existing pods may need to be restarted or wait 5-10 minutes for DNS cache to expire${NC}"
        echo ""
        echo -e "${BLUE}Test with:${NC}"
        echo "  kubectl run test-dns --image=busybox:1.36 --rm -i --restart=Never -- sh -c 'getent hosts $DOMAIN'"
        echo ""
        echo "Or from an existing pod:"
        echo "  kubectl exec -n <namespace> <pod-name> -- sh -c 'getent hosts $DOMAIN'"
    else
        echo -e "${RED}❌ CoreDNS rollout failed or timed out${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}❌ Cancelled${NC}"
    exit 0
fi
