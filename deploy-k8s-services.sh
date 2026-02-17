#!/bin/bash
# Complete K8s Deployment Script for GitLab Runners, ArgoCD, and Artifact Executor
# This script deploys all services to the Harvis AI Kubernetes cluster

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if kubectl is available
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Verify cluster state
verify_cluster() {
    log_info "Verifying cluster state..."
    
    echo "=== Node Status ==="
    kubectl get nodes -o wide
    
    echo -e "\n=== Checking existing deployments ==="
    kubectl get pods --all-namespaces | grep -E "(gitlab-runner|argocd|artifact-executor)" || echo "No existing pods found"
    
    log_success "Cluster verification complete"
}

# Deploy GitLab Runners
deploy_gitlab_runners() {
    log_info "Phase 1: Deploying GitLab Runners to Raspberry Pis..."
    
    # Apply namespace
    log_info "Creating gitlab-runner namespace..."
    kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-namespace.yaml
    
    # Apply RBAC
    log_info "Creating GitLab runner RBAC..."
    kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-rbac.yaml
    
    # Apply config
    log_info "Creating GitLab runner config..."
    kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-config.yaml
    
    # Apply deployments (updated for Raspberry Pis)
    log_info "Deploying GitLab runners to Raspberry Pi nodes..."
    kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-deployment-updated.yaml
    
    # Wait for deployments
    log_info "Waiting for GitLab runner pods to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=gitlab-runner -n gitlab-runner --timeout=120s || true
    
    log_success "GitLab Runners deployed successfully!"
    echo ""
    kubectl get pods -n gitlab-runner -o wide
    echo ""
    log_warn "NOTE: Runners need to be registered with GitLab. Check pod logs for registration instructions."
}

# Deploy ArgoCD
deploy_argocd() {
    log_info "Phase 2: Deploying ArgoCD..."
    
    # Apply namespace
    log_info "Creating argocd namespace..."
    kubectl apply -f k8s-manifests/argocd/namespace.yaml
    
    # Install ArgoCD
    log_info "Installing ArgoCD core components..."
    kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
    
    # Wait for ArgoCD to be ready
    log_info "Waiting for ArgoCD pods to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-server -n argocd --timeout=300s || true
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-repo-server -n argocd --timeout=300s || true
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-application-controller -n argocd --timeout=300s || true
    
    # Apply ArgoCD LoadBalancer service
    log_info "Creating ArgoCD LoadBalancer service..."
    kubectl apply -f k8s-manifests/argocd/argocd-server-service.yaml
    
    # Apply ArgoCD nginx proxy
    log_info "Creating ArgoCD nginx proxy..."
    kubectl apply -f k8s-manifests/argocd/argocd-nginx-proxy.yaml
    
    # Wait for nginx proxy
    log_info "Waiting for ArgoCD nginx proxy..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-nginx -n argocd --timeout=120s || true
    
    log_success "ArgoCD deployed successfully!"
    echo ""
    kubectl get pods -n argocd -o wide
    echo ""
    kubectl get svc -n argocd
    echo ""
    log_info "ArgoCD will be accessible at:"
    log_info "  - Via nginx proxy: http://192.168.4.242"
    log_info "  - Direct LB: http://192.168.4.243"
    log_info "  - Internal: http://argocd-server.argocd.svc.cluster.local"
}

# Deploy Artifact Executor
deploy_artifact_executor() {
    log_info "Phase 3: Deploying Artifact Executor..."
    
    # Check if namespace exists, create if not
    log_info "Creating artifact-executor namespace..."
    kubectl apply -f k8s-manifests/services/artifact-executor-namespace.yaml
    
    # Deploy artifact executor
    log_info "Deploying artifact executor to rocky3vm.local..."
    kubectl apply -f k8s-manifests/services/artifact-executor.yaml
    
    # Wait for deployment
    log_info "Waiting for artifact executor to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/component=artifact-executor -n artifact-executor --timeout=120s || true
    
    log_success "Artifact Executor deployed successfully!"
    echo ""
    kubectl get pods -n artifact-executor -o wide
}

# Deploy Harvis Application to ArgoCD
deploy_harvis_to_argocd() {
    log_info "Phase 4: Configuring Harvis Application in ArgoCD..."
    
    # Apply Harvis application manifest
    kubectl apply -f k8s-manifests/argocd/harvis-application.yaml
    
    log_success "Harvis Application configured in ArgoCD!"
}

# Final verification
verify_deployments() {
    log_info "Phase 5: Final Verification..."
    
    echo ""
    echo "=== GitLab Runner Status ==="
    kubectl get pods -n gitlab-runner -o wide || echo "No gitlab-runner namespace"
    
    echo -e "\n=== ArgoCD Status ==="
    kubectl get pods -n argocd -o wide || echo "No argocd namespace"
    
    echo -e "\n=== Artifact Executor Status ==="
    kubectl get pods -n artifact-executor -o wide || echo "No artifact-executor namespace"
    
    echo -e "\n=== LoadBalancer Services ==="
    kubectl get svc --all-namespaces | grep LoadBalancer
    
    echo -e "\n=== Node Distribution ==="
    kubectl get pods --all-namespaces -o wide | grep -E "(gitlab-runner|argocd|artifact-executor)" | awk '{print $8}' | sort | uniq -c
    
    log_success "Deployment verification complete!"
}

# Print access information
print_access_info() {
    echo ""
    echo "=========================================="
    echo "  🚀 DEPLOYMENT COMPLETE! 🚀"
    echo "=========================================="
    echo ""
    echo "📋 Service Access Information:"
    echo ""
    echo "GitLab Runners:"
    echo "  - Pods: kubectl get pods -n gitlab-runner"
    echo "  - Logs: kubectl logs -n gitlab-runner -l app.kubernetes.io/name=gitlab-runner"
    echo ""
    echo "ArgoCD:"
    echo "  - UI URL: http://192.168.4.242 (via nginx proxy)"
    echo "  - UI URL: http://192.168.4.243 (direct LoadBalancer)"
    echo "  - CLI: argocd login 192.168.4.242"
    echo "  - Get password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" | base64 -d"
    echo ""
    echo "Artifact Executor:"
    echo "  - Service: artifact-executor.artifact-executor.svc.cluster.local:8080"
    echo "  - Node: rocky3vm.local"
    echo ""
    echo "🔧 Next Steps:"
    echo "  1. Register GitLab runners with your GitLab instance"
    echo "  2. Login to ArgoCD and configure applications"
    echo "  3. Update your DNS to point argocd.dulc3.tech to 192.168.4.242"
    echo ""
    echo "📊 Useful Commands:"
    echo "  watch kubectl get pods --all-namespaces"
    echo "  kubectl logs -f -n argocd deployment/argocd-server"
    echo "  kubectl logs -f -n gitlab-runner deployment/gitlab-runner-pi1"
    echo ""
    echo "=========================================="
}

# Main execution
main() {
    log_info "Starting K8s Deployment Script"
    log_info "================================"
    
    # Get script directory
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$SCRIPT_DIR"
    
    check_prerequisites
    verify_cluster
    
    # Deploy in phases
    deploy_gitlab_runners
    deploy_argocd
    deploy_artifact_executor
    deploy_harvis_to_argocd
    
    verify_deployments
    print_access_info
}

# Run main function
main "$@"
