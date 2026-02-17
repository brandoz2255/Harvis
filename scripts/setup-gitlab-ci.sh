#!/bin/bash
# GitLab CI Integration Setup Script
# Run this when you're ready to switch from local CI to GitLab CI

set -e

echo "=========================================="
echo "  GitLab CI Integration Setup"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Step 1: Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed"
        exit 1
    fi
    
    # Check if GitLab runners are running
    if ! kubectl get pods -n gitlab-runner &> /dev/null; then
        log_warn "GitLab runners not found in namespace 'gitlab-runner'"
        log_info "Runners need to be registered with your GitLab instance"
    else
        log_success "GitLab runners found"
    fi
    
    # Check if ArgoCD is running
    if ! kubectl get pods -n argocd &> /dev/null; then
        log_error "ArgoCD is not running"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Step 2: Copy GitLab CI file
setup_gitlab_ci() {
    log_info "Setting up GitLab CI configuration..."
    
    if [ -f ".gitlab-ci.yml" ]; then
        log_warn ".gitlab-ci.yml already exists"
        read -p "Overwrite? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Skipping .gitlab-ci.yml setup"
            return
        fi
    fi
    
    cp .gitlab-ci.yml.example .gitlab-ci.yml
    log_success "Created .gitlab-ci.yml"
    
    log_info "Please review and customize .gitlab-ci.yml for your needs"
}

# Step 3: Configure GitLab repository mirror
configure_mirror() {
    log_info "GitLab Mirror Configuration Instructions:"
    echo ""
    echo "1. Go to your GitLab project"
    echo "2. Navigate to: Settings → Repository → Mirroring repositories"
    echo "3. Click 'Add new mirror'"
    echo ""
    echo "   Mirror URL: https://github.com/dulc3/harvis-aidev.git"
    echo "   Mirror direction: Pull"
    echo "   Authentication method: Password"
    echo "   Password: <Your GitHub Personal Access Token>"
    echo ""
    echo "4. Click 'Add mirror'"
    echo "5. Set mirror interval to your preference (e.g., '5' minutes)"
    echo ""
    log_info "This will automatically sync GitHub → GitLab"
}

# Step 4: Set up GitLab CI variables
setup_ci_variables() {
    log_info "Required GitLab CI Variables:"
    echo ""
    echo "Go to: GitLab Project → Settings → CI/CD → Variables"
    echo ""
    echo "Add these variables:"
    echo ""
    echo "1. DOCKER_PASSWORD"
    echo "   Value: <Your Docker Hub password or access token>"
    echo "   Protected: Yes"
    echo "   Masked: Yes"
    echo ""
    echo "2. GITHUB_TOKEN"
    echo "   Value: <GitHub Personal Access Token with repo scope>"
    echo "   Protected: Yes"
    echo "   Masked: Yes"
    echo ""
    echo "3. SLACK_WEBHOOK_URL (optional)"
    echo "   Value: <Your Slack webhook URL for notifications>"
    echo "   Protected: Yes"
    echo "   Masked: Yes"
    echo ""
}

# Step 5: Register GitLab runners
register_runners() {
    log_info "GitLab Runner Registration:"
    echo ""
    echo "Your runners are already deployed on Kubernetes:"
    kubectl get pods -n gitlab-runner -o wide
    echo ""
    echo "To register them with GitLab:"
    echo ""
    echo "1. Go to: GitLab Project → Settings → CI/CD → Runners"
    echo "2. Click 'New project runner'"
    echo "3. Select: 'Create runner with a runner authentication token'"
    echo "4. Copy the token"
    echo ""
    echo "5. Register runner 1 (raspberrypi):"
    echo "   kubectl exec -n gitlab-runner <pod-name-1> -- gitlab-runner register \\"
    echo "     --url https://gitlab.com/ \\"
    echo "     --token <YOUR_TOKEN> \\"
    echo "     --executor kubernetes \\"
    echo "     --name harvis-k8s-runner-1"
    echo ""
    echo "6. Register runner 2 (raspberrypi2):"
    echo "   kubectl exec -n gitlab-runner <pod-name-2> -- gitlab-runner register \\"
    echo "     --url https://gitlab.com/ \\"
    echo "     --token <YOUR_TOKEN> \\"
    echo "     --executor kubernetes \\"
    echo "     --name harvis-k8s-runner-2"
    echo ""
}

# Step 6: Test the setup
test_setup() {
    log_info "Testing the setup..."
    
    # Check if .gitlab-ci.yml is valid
    if [ -f ".gitlab-ci.yml" ]; then
        log_success "Found .gitlab-ci.yml"
        
        # Validate YAML syntax
        if command -v yq &> /dev/null; then
            yq eval '.stages' .gitlab-ci.yml > /dev/null 2>&1 && \
                log_success "YAML syntax is valid" || \
                log_error "YAML syntax error"
        else
            log_warn "yq not installed, skipping YAML validation"
        fi
    else
        log_error ".gitlab-ci.yml not found"
    fi
    
    # Check kustomization
    if [ -f "k8s-manifests/overlays/prod/kustomization.yaml" ]; then
        log_success "Found kustomization.yaml"
        
        if command -v kustomize &> /dev/null; then
            kustomize build k8s-manifests/overlays/prod > /dev/null 2>&1 && \
                log_success "Kustomize build successful" || \
                log_error "Kustomize build failed"
        else
            log_warn "kustomize not installed, skipping build test"
        fi
    fi
    
    echo ""
    log_info "Manual tests to perform:"
    echo "1. Push a commit to GitHub"
    echo "2. Verify it syncs to GitLab within 5 minutes"
    echo "3. Check GitLab CI pipeline triggers"
    echo "4. Verify ArgoCD updates after pipeline completes"
}

# Step 7: Create helper scripts
create_helper_scripts() {
    log_info "Creating helper scripts..."
    
    # Create update-images script
    cat > update-images.sh << 'EOF'
#!/bin/bash
# Helper script to update image versions manually

if [ -z "$1" ]; then
    echo "Usage: ./update-images.sh <version>"
    echo "Example: ./update-images.sh v2.28.11"
    exit 1
fi

VERSION=$1
FILE="k8s-manifests/overlays/prod/kustomization.yaml"

echo "Updating images to version: $VERSION"

# Update the kustomization file
sed -i "s/newTag: .*/newTag: $VERSION/g" $FILE

echo "Updated $FILE"
echo ""
echo "Next steps:"
echo "1. Review changes: git diff"
echo "2. Commit: git add $FILE && git commit -m 'Update to $VERSION'"
echo "3. Push: git push origin main"
echo "4. ArgoCD will auto-sync!"
EOF

    chmod +x update-images.sh
    log_success "Created update-images.sh"
    
    # Create check-status script
    cat > check-argocd-status.sh << 'EOF'
#!/bin/bash
# Check ArgoCD application status

echo "=== ArgoCD Application Status ==="
kubectl get applications -n argocd

echo ""
echo "=== Harvis AI Details ==="
kubectl get application harvis-ai -n argocd -o jsonpath='{
    "Sync Status: "}{.status.sync.status}{"\n"
    "Health Status: "}{.status.health.status}{"\n"
    "Last Sync: "}{.status.operationState.finishedAt}{"\n"
}'

echo ""
echo "=== Pods in ai-agents namespace ==="
kubectl get pods -n ai-agents

echo ""
echo "=== Recent Sync Operations ==="
kubectl get events -n argocd --field-selector reason=OperationCompleted --sort-by='.lastTimestamp' | tail -5
EOF

    chmod +x check-argocd-status.sh
    log_success "Created check-argocd-status.sh"
}

# Main menu
main_menu() {
    echo ""
    echo "What would you like to do?"
    echo ""
    echo "1) Full setup (run all steps)"
    echo "2) Check prerequisites only"
    echo "3) Setup GitLab CI file"
    echo "4) Show mirror configuration"
    echo "5) Show CI variables setup"
    echo "6) Show runner registration"
    echo "7) Test current setup"
    echo "8) Create helper scripts"
    echo "9) Exit"
    echo ""
    read -p "Select option (1-9): " choice
    
    case $choice in
        1)
            check_prerequisites
            setup_gitlab_ci
            configure_mirror
            setup_ci_variables
            register_runners
            create_helper_scripts
            test_setup
            ;;
        2)
            check_prerequisites
            ;;
        3)
            setup_gitlab_ci
            ;;
        4)
            configure_mirror
            ;;
        5)
            setup_ci_variables
            ;;
        6)
            register_runners
            ;;
        7)
            test_setup
            ;;
        8)
            create_helper_scripts
            ;;
        9)
            echo "Goodbye!"
            exit 0
            ;;
        *)
            log_error "Invalid option"
            main_menu
            ;;
    esac
}

# Main execution
echo "This script helps you set up GitLab CI integration"
echo "for your Harvis AI project with ArgoCD."
echo ""

if [ "$1" == "--auto" ]; then
    # Run all steps automatically
    check_prerequisites
    setup_gitlab_ci
    create_helper_scripts
    test_setup
    echo ""
    log_success "Setup complete! Review the files and follow the instructions above."
else
    main_menu
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Review .gitlab-ci.yml"
echo "2. Configure GitLab mirror (see instructions above)"
echo "3. Add CI/CD variables in GitLab"
echo "4. Register GitLab runners"
echo "5. Push a test commit!"
echo ""
echo "Documentation: docs/ARGOCD_GITOPS_GUIDE.md"
echo ""
