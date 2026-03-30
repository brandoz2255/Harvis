#!/bin/bash

# CI Pipeline Script for Harvis
# This script builds Docker containers for Frontend and Backend with version tagging.
# Supports both interactive and non-interactive (CI/CD) modes.

set -e # Exit on error

# ============================================================================
# CLI ARGUMENTS
# ============================================================================

# Default values
FRONTEND_VERSION="latest"
BACKEND_VERSION="latest"
PUSH_IMAGES="no"
SKIP_GIT_PUSH="no"
DEBUG_MODE="no"
DRY_RUN="no"
COMMIT_MSG=""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

show_help() {
  cat << EOF
Harvis CI Pipeline - Build, Tag, and Deploy

USAGE:
  ./ci_pipeline.sh [OPTIONS]

OPTIONS:
  -f, --frontend-version VERSION   Frontend image tag (default: latest)
  -b, --backend-version VERSION    Backend image tag (default: latest)
  -m, --commit-msg MESSAGE         Custom commit message (default: auto-generated)
  -p, --push                       Push images to Docker Hub after build
  -n, --no-git-push                Skip git commit and push
  -d, --debug                      Enable debug mode (verbose output)
  -y, --yes                        Skip all prompts (non-interactive mode)
  --dry-run                        Show what would be done without executing
  -h, --help                       Show this help message

EXAMPLES:
  # Interactive mode (prompts for versions)
  ./ci_pipeline.sh

  # Non-interactive with specific versions
  ./ci_pipeline.sh -f v1.2.3 -b v1.2.3 -p

  # Build only (no push)
  ./ci_pipeline.sh -f newest -b newest

  # Debug mode
  ./ci_pipeline.sh -d -f test -b test

NOTES:
  - Images are tagged as: dulc3/jarvis-{frontend,backend}:<VERSION>
  - With -p flag, images are pushed to Docker Hub
  - ArgoCD will auto-deploy after git push to main branch
  - MCP RAG server uses the same backend image

EOF
}

log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_debug() {
  if [ "$DEBUG_MODE" = "yes" ]; then
    echo -e "${YELLOW}[DEBUG]${NC} $1"
  fi
}

# Function to get input using Whiptail or fallback to read
get_input() {
  local prompt="$1"
  local title="$2"
  local default_val="$3"
  local result=""

  if command -v whiptail &>/dev/null; then
    result=$(whiptail --inputbox "$prompt" 10 60 "$default_val" --title "$title" 3>&1 1>&2 2>&3)
    exit_status=$?
    if [ $exit_status -ne 0 ]; then
      log_error "Operation cancelled by user."
      exit 1
    fi
  else
    echo -e "${GREEN}$title${NC}"
    read -p "$prompt [$default_val]: " input
    result="${input:-$default_val}"
  fi
  echo "$result"
}

# ============================================================================
# PARSE CLI ARGUMENTS
# ============================================================================

 while [[ $# -gt 0 ]]; do
  case $1 in
    -f|--frontend-version)
      FRONTEND_VERSION="$2"
      shift 2
      ;;
    -b|--backend-version)
      BACKEND_VERSION="$2"
      shift 2
      ;;
    -m|--commit-msg)
      COMMIT_MSG="$2"
      shift 2
      ;;
    -p|--push)
      PUSH_IMAGES="yes"
      shift
      ;;
    -n|--no-git-push)
      SKIP_GIT_PUSH="yes"
      shift
      ;;
    -d|--debug)
      DEBUG_MODE="yes"
      set -x  # Enable bash debug mode
      shift
      ;;
    -y|--yes)
      # Non-interactive mode - use defaults or provided values
      shift
      ;;
    --dry-run)
      DRY_RUN="yes"
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

# ============================================================================
# MAIN EXECUTION
# ============================================================================

log_info "======================================"
log_info "Harvis CI Pipeline"
log_info "======================================"
log_info "Frontend Version: $FRONTEND_VERSION"
log_info "Backend Version:  $BACKEND_VERSION"
log_info "Commit Message:   ${COMMIT_MSG:-auto-generated}"
log_info "Push to Docker:   $PUSH_IMAGES"
log_info "Skip Git Push:    $SKIP_GIT_PUSH"
log_info "Debug Mode:       $DEBUG_MODE"
log_info "Dry Run:          $DRY_RUN"
log_info "======================================"

if [ "$DRY_RUN" = "yes" ]; then
  log_warn "DRY RUN - No changes will be made"
fi

# 2. Build Frontend
log_info "Starting Frontend Build..."
FRONTEND_DIR="front_end/newjfrontend"

if [ -d "$FRONTEND_DIR" ]; then
  pushd "$FRONTEND_DIR" >/dev/null

  if [ "$DRY_RUN" != "yes" ]; then
    if docker build -t dulc3/jarvis-frontend:$FRONTEND_VERSION .; then
      log_success "Frontend built successfully with tag: dulc3/jarvis-frontend:$FRONTEND_VERSION"
    else
      log_error "Frontend build failed!"
      popd >/dev/null
      exit 1
    fi
  else
    log_debug "Would run: docker build -t dulc3/jarvis-frontend:$FRONTEND_VERSION ."
  fi

  popd >/dev/null
else
  log_error "Frontend directory not found: $FRONTEND_DIR"
  exit 1
fi

# 3. Build Backend
log_info "Starting Backend Build..."
BACKEND_DIR="python_back_end"

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if [ "$DRY_RUN" != "yes" ]; then
    if docker build -t dulc3/jarvis-backend:$BACKEND_VERSION .; then
      log_success "Backend built successfully with tag: dulc3/jarvis-backend:$BACKEND_VERSION"
    else
      log_error "Backend build failed!"
      popd >/dev/null
      exit 1
    fi
  else
    log_debug "Would run: docker build -t dulc3/jarvis-backend:$BACKEND_VERSION ."
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 4. Build Artifact Executor (Node.js based)
log_info "Starting Artifact Executor Build..."

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if [ "$DRY_RUN" != "yes" ]; then
    if docker build -f Dockerfile.executor -t dulc3/harvis-artifact-executor:$BACKEND_VERSION .; then
      log_success "Artifact Executor built successfully with tag: dulc3/harvis-artifact-executor:$BACKEND_VERSION"
    else
      log_error "Artifact Executor build failed!"
      popd >/dev/null
      exit 1
    fi
  else
    log_debug "Would run: docker build -f Dockerfile.executor -t dulc3/harvis-artifact-executor:$BACKEND_VERSION ."
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 5. Build Code Executor (Python based for document generation)
log_info "Starting Code Executor Build..."

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if [ "$DRY_RUN" != "yes" ]; then
    if docker build -f Dockerfile.code-executor -t dulc3/harvis-code-executor:$BACKEND_VERSION .; then
      log_success "Code Executor built successfully with tag: dulc3/harvis-code-executor:$BACKEND_VERSION"
    else
      log_error "Code Executor build failed!"
      popd >/dev/null
      exit 1
    fi
  else
    log_debug "Would run: docker build -f Dockerfile.code-executor -t dulc3/harvis-code-executor:$BACKEND_VERSION ."
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 6. Build Document Worker (Lightweight async job processor)
log_info "Starting Document Worker Build..."

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if [ "$DRY_RUN" != "yes" ]; then
    if docker build -f Dockerfile.document-worker -t dulc3/harvis-document-worker:$BACKEND_VERSION .; then
      log_success "Document Worker built successfully with tag: dulc3/harvis-document-worker:$BACKEND_VERSION"
    else
      log_error "Document Worker build failed!"
      popd >/dev/null
      exit 1
    fi
  else
    log_debug "Would run: docker build -f Dockerfile.document-worker -t dulc3/harvis-document-worker:$BACKEND_VERSION ."
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 7. Tag TTS Worker (same image as backend — different entrypoint, no separate build needed)
log_info "Tagging TTS Worker (reuses jarvis-backend image)..."

if [ "$DRY_RUN" != "yes" ]; then
  if docker tag dulc3/jarvis-backend:$BACKEND_VERSION dulc3/harvis-tts-worker:$BACKEND_VERSION; then
    log_success "TTS Worker tagged: dulc3/harvis-tts-worker:$BACKEND_VERSION"
  else
    log_error "TTS Worker tagging failed!"
    exit 1
  fi
else
  log_debug "Would run: docker tag dulc3/jarvis-backend:$BACKEND_VERSION dulc3/harvis-tts-worker:$BACKEND_VERSION"
fi

# 8. Update Kustomization for ArgoCD
log_info "Updating Kustomization for ArgoCD..."
KUSTOMIZE_FILE="k8s-manifests/overlays/prod/kustomization.yaml"

if [ -f "$KUSTOMIZE_FILE" ]; then
  log_info "Updating image tags in kustomization (harvis images only — openclaw tag is managed by ci_openclaw_pipeline.sh)..."

  if [ "$DRY_RUN" != "yes" ]; then
    # Use targeted per-image replacements so the openclaw newTag is never touched.
    python3 - <<PYEOF
import re, sys

with open("$KUSTOMIZE_FILE", "r") as f:
    content = f.read()

replacements = [
    # images: section entries
    (r'(  - name: harvis-backend\n    newName: dulc3/jarvis-backend\n    newTag: )\S+',      r'\g<1>$BACKEND_VERSION'),
    (r'(  - name: harvis-frontend\n    newName: dulc3/jarvis-frontend\n    newTag: )\S+',     r'\g<1>$FRONTEND_VERSION'),
    (r'(  - name: harvis-document-worker\n    newName: dulc3/harvis-document-worker\n    newTag: )\S+', r'\g<1>$BACKEND_VERSION'),
]

for pattern, repl in replacements:
    content = re.sub(pattern, repl, content)

with open("$KUSTOMIZE_FILE", "w") as f:
    f.write(content)

print("kustomization.yaml updated (harvis images only).")
PYEOF

    # Update patch image references for backend
    sed -i "s|dulc3/jarvis-backend:[^ ]*|dulc3/jarvis-backend:$BACKEND_VERSION|g" "$KUSTOMIZE_FILE"

    # Update patch image references for frontend
    sed -i "s|dulc3/jarvis-frontend:[^ ]*|dulc3/jarvis-frontend:$FRONTEND_VERSION|g" "$KUSTOMIZE_FILE"

    # Update patch image references for document-worker
    sed -i "s|dulc3/harvis-document-worker:[^ ]*|dulc3/harvis-document-worker:$BACKEND_VERSION|g" "$KUSTOMIZE_FILE"

    # Update patch image references for tts-worker
    sed -i "s|dulc3/harvis-tts-worker:[^ ]*|dulc3/harvis-tts-worker:$BACKEND_VERSION|g" "$KUSTOMIZE_FILE"

    # Update MCP RAG server image references (uses same backend image)
    sed -i "s|dulc3/jarvis-backend:[^ ]*|dulc3/jarvis-backend:$BACKEND_VERSION|g" "$KUSTOMIZE_FILE"

    log_success "Kustomization updated with new image versions"

    # Show the changes
    echo ""
    log_info "Changes to $KUSTOMIZE_FILE:"
    grep -E "(newTag|value:.*dulc3)" "$KUSTOMIZE_FILE" | head -15
  else
    log_debug "Would update $KUSTOMIZE_FILE with versions: frontend=$FRONTEND_VERSION, backend=$BACKEND_VERSION"
  fi

  # Commit and push changes
  if [ "$SKIP_GIT_PUSH" != "yes" ]; then
    echo ""
    log_info "Committing changes to Git..."

    # Determine commit message (use custom if provided, otherwise auto-generate)
    if [ -z "$COMMIT_MSG" ]; then
      COMMIT_MSG="chore: update images to $BACKEND_VERSION [ci]"
    fi

    # Add all k8s manifest changes, not just kustomization.yaml
    if [ "$DRY_RUN" != "yes" ]; then
      if git add k8s-manifests/; then
        if git commit -m "$COMMIT_MSG"; then
          log_success "Changes committed"

          log_info "Pushing to GitHub via SSH..."
          eval "$(ssh-agent -s)" > /dev/null 2>&1
          ssh-add ~/.ssh/id_ed25519 2>/dev/null
          if git push origin main; then
            log_success "Changes pushed to GitHub - ArgoCD will auto-sync!"
          else
            log_error "Push failed - you may need to push manually:"
            echo "  eval \$(ssh-agent -s) && ssh-add ~/.ssh/id_ed25519 && git push origin main"
          fi
        else
          log_info "No changes to commit (images already at this version)"
        fi
      else
        log_error "Failed to stage changes"
      fi
    else
      log_debug "Would commit and push k8s-manifests/ changes"
    fi
  else
    log_warn "Skipping git push (SKIP_GIT_PUSH=yes)"
  fi
else
  log_error "Kustomization file not found: $KUSTOMIZE_FILE"
  log_info "You may need to update it manually"
fi

# 9. Push Images (Optional)
echo ""
log_info "Docker images built successfully!"

# If --push flag was provided, skip prompt and push
if [ "$PUSH_IMAGES" = "yes" ]; then
  PUSH_CHOICE="yes"
else
  if command -v whiptail &>/dev/null; then
    if whiptail --yesno "Push all images to Docker Hub?" 10 60 --title "Push Images"; then
      PUSH_CHOICE="yes"
    else
      PUSH_CHOICE="no"
    fi
  else
    read -p "Push all images to Docker Hub? (y/N): " push_choice
    if [[ $push_choice =~ ^[Yy]$ ]]; then
      PUSH_CHOICE="yes"
    else
      PUSH_CHOICE="no"
    fi
  fi
fi

if [ "$PUSH_CHOICE" = "yes" ]; then
  log_info "Pushing images to Docker Hub..."
  
  if [ "$DRY_RUN" != "yes" ]; then
    docker push dulc3/jarvis-frontend:$FRONTEND_VERSION && \
    docker push dulc3/jarvis-backend:$BACKEND_VERSION && \
    docker push dulc3/harvis-artifact-executor:$BACKEND_VERSION && \
    docker push dulc3/harvis-code-executor:$BACKEND_VERSION && \
    docker push dulc3/harvis-document-worker:$BACKEND_VERSION && \
    docker push dulc3/harvis-tts-worker:$BACKEND_VERSION && \
    log_success "All images pushed successfully!"
  else
    log_debug "Would push images to Docker Hub"
  fi
else
  log_info "Skipping push. To push manually, run:"
  echo "  docker push dulc3/jarvis-frontend:$FRONTEND_VERSION"
  echo "  docker push dulc3/jarvis-backend:$BACKEND_VERSION"
  echo "  docker push dulc3/harvis-artifact-executor:$BACKEND_VERSION"
  echo "  docker push dulc3/harvis-code-executor:$BACKEND_VERSION"
  echo "  docker push dulc3/harvis-document-worker:$BACKEND_VERSION"
  echo "  docker push dulc3/harvis-tts-worker:$BACKEND_VERSION"
fi

# Summary
echo ""
echo "=========================================="
log_success "CI Pipeline Completed Successfully!"
echo "Frontend:          dulc3/jarvis-frontend:$FRONTEND_VERSION"
echo "Backend:           dulc3/jarvis-backend:$BACKEND_VERSION"
echo "Artifact Executor: dulc3/harvis-artifact-executor:$BACKEND_VERSION"
echo "Code Executor:     dulc3/harvis-code-executor:$BACKEND_VERSION"
echo "Document Worker:   dulc3/harvis-document-worker:$BACKEND_VERSION"
echo "TTS Worker:        dulc3/harvis-tts-worker:$BACKEND_VERSION  (tagged from backend)"
echo "MCP RAG Server:    Uses dulc3/jarvis-backend:$BACKEND_VERSION"
echo ""
echo "ArgoCD will auto-deploy the new images within 3 minutes!"
echo "=========================================="
