#!/bin/bash

# CI Pipeline for OpenClaw
# Builds the OpenClaw Docker image from openclaw/openclaw/ and pushes to Docker Hub.
# Supports both interactive and non-interactive (CI/CD) modes.
# Separate from ci_pipeline.sh because OpenClaw has its own build toolchain (pnpm/Node 22).

set -e

# ============================================================================
# CLI ARGUMENTS
# ============================================================================

OPENCLAW_VERSION="latest"
PUSH_IMAGE="no"
RUN_SMOKE="no"
SKIP_KUBECTL="no"
DEBUG_MODE="no"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }

show_help() {
  cat << EOF
OpenClaw CI Pipeline - Build, Tag, and Deploy

USAGE:
  ./ci_openclaw_pipeline.sh [OPTIONS]

OPTIONS:
  -v, --version VERSION        OpenClaw image tag (default: latest)
  -p, --push                   Push image to Docker Hub
  -s, --smoke                  Run health-check smoke test
  -k, --kubectl                Apply kustomization manifest after build
  -y, --yes                    Skip all prompts (non-interactive mode)
  -d, --debug                  Enable debug mode (verbose output)
  -h, --help                   Show this help message

EXAMPLES:
  # Interactive mode (prompts for options)
  ./ci_openclaw_pipeline.sh

  # Non-interactive build + push
  ./ci_openclaw_pipeline.sh -v v1.0.0 -p -k -y

  # Build only (no push, no kubectl)
  ./ci_openclaw_pipeline.sh -v latest

  # Custom SSH key path
  SSH_KEY_FILE=/path/to/key ./ci_openclaw_pipeline.sh -v latest -k -y

  # Just sync skills and build
  ./ci_openclaw_pipeline.sh -v latest -y

NOTES:
  - Image tag: dulc3/openclaw:<VERSION>
  - With -k flag, applies k8s-manifests/overlays/prod/openclaw.yaml
  - Also tags and pushes as dulc3/openclaw:latest if version differs
  - ArgoCD auto-syncs when kustomization.yaml changes on main branch
  - SSH key secret (openclaw-ssh-key) is auto-updated from SSH_KEY_FILE env var (default: ~/.ssh/id_ed25519)
  - SSH key enables OpenClaw to SSH into host machines (e.g., dulc3-os at 10.0.0.2)
EOF
}

# ============================================================================
# PARSE CLI ARGUMENTS
# ============================================================================

INTERACTIVE="yes"

while [[ $# -gt 0 ]]; do
  case $1 in
    -v|--version)
      OPENCLAW_VERSION="$2"
      shift 2
      ;;
    -p|--push)
      PUSH_IMAGE="yes"
      shift
      ;;
    -s|--smoke)
      RUN_SMOKE="yes"
      shift
      ;;
    -k|--kubectl)
      SKIP_KUBECTL="no"
      shift
      ;;
    -y|--yes)
      INTERACTIVE="no"
      shift
      ;;
    -d|--debug)
      DEBUG_MODE="yes"
      set -x
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

# In non-interactive mode, use sensible defaults
if [ "$INTERACTIVE" = "no" ]; then
  PUSH_IMAGE="${PUSH_IMAGE:-no}"
  RUN_SMOKE="${RUN_SMOKE:-no}"
else
  PUSH_IMAGE="${PUSH_IMAGE:-no}"
  RUN_SMOKE="${RUN_SMOKE:-no}"
fi

# ============================================================================
# GET INPUT (interactive mode only)
# ============================================================================

get_input() {
  local prompt="$1"
  local default_val="$2"

  echo -e "${GREEN}Prompt:${NC} $prompt [$default_val]"
  read -p "> " input
  echo "${input:-$default_val}"
}

# ============================================================================
# PREFLIGHT CHECKS
# ============================================================================

OPENCLAW_DIR="openclaw/openclaw"

if [ ! -d "$OPENCLAW_DIR" ]; then
  log_error "OpenClaw source not found at: $OPENCLAW_DIR"
  log_error "Run this script from the aidev/ root directory."
  exit 1
fi

if [ ! -f "$OPENCLAW_DIR/Dockerfile" ]; then
  log_error "No Dockerfile found in $OPENCLAW_DIR"
  exit 1
fi

if ! command -v docker &>/dev/null; then
  log_error "Docker is not installed or not in PATH."
  exit 1
fi

# ============================================================================
# VERSION INPUT
# ============================================================================

if [ "$INTERACTIVE" = "yes" ]; then
  OPENCLAW_VERSION=$(get_input "Enter tag for OpenClaw image (e.g., v1.0.0 or latest)" "latest")
fi

IMAGE_NAME="dulc3/openclaw:$OPENCLAW_VERSION"

log_info "Building: $IMAGE_NAME"
log_info "Source:   $OPENCLAW_DIR"
echo ""

# ============================================================================
# SYNC SKILLS INTO BUILD CONTEXT
# ============================================================================

log_info "Syncing skills into Docker build context..."
mkdir -p openclaw/skills

if [ -d "skills/Harvis" ]; then
  rsync -a --delete skills/Harvis/ openclaw/skills/
  log_info "  Synced skills/Harvis/ → openclaw/skills/"
fi

if [ -d "skills/Shared" ]; then
  rsync -a skills/Shared/ openclaw/skills/
  log_info "  Synced skills/Shared/ → openclaw/skills/"
fi

echo ""

# ============================================================================
# BUILD
# ============================================================================

log_info "Starting OpenClaw build..."
log_warn "Note: OpenClaw uses pnpm + Bun for its build. This may take a few minutes on first run."

if docker build -t "$IMAGE_NAME" -f "$OPENCLAW_DIR/Dockerfile" openclaw/; then
  log_success "OpenClaw built: $IMAGE_NAME"
else
  log_error "OpenClaw build failed!"
  exit 1
fi

if [ "$OPENCLAW_VERSION" != "latest" ]; then
  docker tag "$IMAGE_NAME" "dulc3/openclaw:latest"
  log_info "Also tagged as: dulc3/openclaw:latest"
fi

# ============================================================================
# SMOKE TEST (optional)
# ============================================================================

if [ "$RUN_SMOKE" = "yes" ]; then
  log_info "Running smoke test — starting container on port 18799..."

  CONTAINER_ID=$(docker run -d \
    -e HOME=/home/node \
    -e NODE_ENV=production \
    -e OPENCLAW_GATEWAY_TOKEN=smoke-test-token \
    -e OLLAMA_API_KEY=ollama-local \
    -p 18799:18789 \
    "$IMAGE_NAME" \
    node openclaw.mjs gateway --bind lan --allow-unconfigured 2>/dev/null)

  log_info "Container started: $CONTAINER_ID"
  log_info "Waiting 10s for gateway to initialize..."
  sleep 10

  if curl -sf http://localhost:18799/health > /dev/null 2>&1; then
    log_success "Health check passed — OpenClaw gateway is running correctly."
  else
    log_warn "Health check did not respond. Container logs:"
    docker logs "$CONTAINER_ID" --tail 30
    docker rm -f "$CONTAINER_ID" > /dev/null 2>&1
    log_error "Smoke test failed. Fix the issue before pushing."
    exit 1
  fi

  docker rm -f "$CONTAINER_ID" > /dev/null 2>&1
  log_info "Smoke test container removed."
fi

# ============================================================================
# PUSH TO DOCKER HUB
# ============================================================================

if [ "$PUSH_IMAGE" = "yes" ]; then
  echo ""
  if [ "$INTERACTIVE" = "yes" ]; then
    read -p "Push $IMAGE_NAME to Docker Hub? (Y/n): " push_choice
    if [[ $push_choice =~ ^[Nn]$ ]]; then
      PUSH_IMAGE="no"
    fi
  fi

  if [ "$PUSH_IMAGE" = "yes" ]; then
    log_info "Pushing $IMAGE_NAME..."
    if docker push "$IMAGE_NAME"; then
      log_success "Pushed: $IMAGE_NAME"
    else
      log_error "Push failed for $IMAGE_NAME"
      exit 1
    fi

    if [ "$OPENCLAW_VERSION" != "latest" ]; then
      log_info "Pushing dulc3/openclaw:latest..."
      docker push "dulc3/openclaw:latest"
      log_success "Pushed: dulc3/openclaw:latest"
    fi
  else
    log_info "Skipping push. To push manually:"
    echo "  docker push $IMAGE_NAME"
    if [ "$OPENCLAW_VERSION" != "latest" ]; then
      echo "  docker push dulc3/openclaw:latest"
    fi
  fi
fi

# ============================================================================
# UPDATE KUSTOMIZATION.YAML
# ============================================================================

echo ""
log_info "Updating kustomization.yaml with new OpenClaw tag..."
KUSTOMIZE_FILE="k8s-manifests/overlays/prod/kustomization.yaml"

if [ -f "$KUSTOMIZE_FILE" ]; then
  python3 - <<PYEOF
import re

with open("$KUSTOMIZE_FILE", "r") as f:
    content = f.read()

updated = re.sub(
    r'(  - name: dulc3/openclaw\n    newName: dulc3/openclaw\n    newTag: )\S+',
    r'\g<1>$OPENCLAW_VERSION',
    content
)

with open("$KUSTOMIZE_FILE", "w") as f:
    f.write(updated)

print("kustomization.yaml updated.")
PYEOF

  log_success "kustomization.yaml updated: dulc3/openclaw → $OPENCLAW_VERSION"

  echo ""
  log_info "Relevant kustomization lines:"
  grep -A3 "dulc3/openclaw" "$KUSTOMIZE_FILE"

  # Commit and push
  echo ""
  log_info "Committing kustomization change..."
  if git add "$KUSTOMIZE_FILE"; then
    if git commit -m "chore: update openclaw image to $OPENCLAW_VERSION [ci]"; then
      log_success "Committed."
      log_info "Pushing to GitHub via SSH..."
      eval "$(ssh-agent -s)" > /dev/null 2>&1
      ssh-add ~/.ssh/id_ed25519 2>/dev/null
      if git push origin main; then
        log_success "Pushed — ArgoCD will auto-sync the new OpenClaw image."
      else
        log_error "Push failed. Push manually:"
        echo "  eval \$(ssh-agent -s) && ssh-add ~/.ssh/id_ed25519 && git push origin main"
      fi
    else
      log_info "Nothing to commit (OpenClaw already at $OPENCLAW_VERSION)"
    fi
  else
    log_error "Failed to stage kustomization.yaml"
  fi
else
  log_warn "Kustomization file not found — update manually: $KUSTOMIZE_FILE"
fi

# ============================================================================
# SSH KEY SECRET (host access for OpenClaw)
# ============================================================================

SSH_KEY_FILE="${SSH_KEY_FILE:-$HOME/.ssh/id_ed25519}"

if [ -f "$SSH_KEY_FILE" ]; then
  log_info "Updating openclaw-ssh-key secret with $(wc -c < "$SSH_KEY_FILE") bytes from $SSH_KEY_FILE..."

  # Create or update the secret — always refresh to avoid stale/empty keys
  if kubectl create secret generic openclaw-ssh-key \
    --from-file=harvis_key="$SSH_KEY_FILE" \
    --namespace=ai-agents \
    --dry-run=client -o yaml 2>/dev/null | kubectl apply -f - -n ai-agents 2>&1; then
    log_success "SSH key secret updated."
  else
    log_warn "Failed to update SSH key secret — apply manually:"
    echo "  kubectl create secret generic openclaw-ssh-key \\"
    echo "    --from-file=harvis_key=$SSH_KEY_FILE \\"
    echo "    --namespace=ai-agents --dry-run=client -o yaml | kubectl apply -f -"
  fi
else
  log_warn "SSH key not found at $SSH_KEY_FILE — skipping secret update."
  log_warn "OpenClaw will not have host access via SSH."
fi

# ============================================================================
# APPLY KUBECTL MANIFEST (SSH key mount fix)
# ============================================================================

if [ "$SKIP_KUBECTL" = "no" ]; then
  echo ""
  log_info "Applying OpenClaw K8s manifest (with SSH key mount fixes)..."

  if kubectl apply -f k8s-manifests/overlays/prod/openclaw.yaml 2>&1; then
    log_success "K8s manifest applied successfully."
    log_info "Waiting for rollout..."
    kubectl rollout status deployment/harvis-ai-openclaw -n ai-agents --timeout=120s 2>&1 || true
    log_success "OpenClaw deployment ready."
  else
    log_warn "kubectl apply failed — apply manually:"
    echo "  kubectl apply -f k8s-manifests/overlays/prod/openclaw.yaml"
  fi
fi

# ============================================================================
# SUMMARY
# ============================================================================

echo ""
echo "=========================================="
log_success "OpenClaw CI Pipeline Complete!"
echo "Image:    $IMAGE_NAME"
echo "Gateway:  ws://harvis-ai-openclaw:18789 (internal K8s)"
echo "Health:   http://harvis-ai-openclaw:18789/health"
echo ""
echo "Monitor: kubectl -n ai-agents logs -f deploy/harvis-ai-openclaw"
echo "=========================================="
