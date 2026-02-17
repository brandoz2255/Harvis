#!/bin/bash

# CI Pipeline Script for Harvis
# This script builds Docker containers for Frontend and Backend with interactive version tagging.

set -e # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Helper function for logging
log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
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

# Main Execution

# 1. Get Versions
FRONTEND_VERSION=$(get_input "Enter tag for Frontend (e.g., v1.0.0):" "Frontend Version" "latest")
BACKEND_VERSION=$(get_input "Enter tag for Backend (e.g., v1.0.0):" "Backend Version" "latest")

log_info "Frontend Tag: $FRONTEND_VERSION"
log_info "Backend Tag: $BACKEND_VERSION"

# 2. Build Frontend
log_info "Starting Frontend Build..."
FRONTEND_DIR="front_end/newjfrontend"

if [ -d "$FRONTEND_DIR" ]; then
  pushd "$FRONTEND_DIR" >/dev/null

  if docker build -t dulc3/jarvis-frontend:$FRONTEND_VERSION .; then
    log_success "Frontend built successfully with tag: frontend:$FRONTEND_VERSION"
  else
    log_error "Frontend build failed!"
    popd >/dev/null
    exit 1
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

  if docker build -t dulc3/jarvis-backend:$BACKEND_VERSION .; then
    log_success "Backend built successfully with tag: backend:$BACKEND_VERSION"
  else
    log_error "Backend build failed!"
    popd >/dev/null
    exit 1
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 4. Build Artifact Executor (Node.js based)
log_info "Starting Artifact Executor Build..."
BACKEND_DIR="python_back_end"

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if docker build -f Dockerfile.executor -t dulc3/harvis-artifact-executor:$BACKEND_VERSION .; then
    log_success "Artifact Executor built successfully with tag: artifact-executor:$BACKEND_VERSION"
  else
    log_error "Artifact Executor build failed!"
    popd >/dev/null
    exit 1
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 5. Build Code Executor (Python based for document generation)
log_info "Starting Code Executor Build..."
BACKEND_DIR="python_back_end"

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if docker build -f Dockerfile.code-executor -t dulc3/harvis-code-executor:$BACKEND_VERSION .; then
    log_success "Code Executor built successfully with tag: code-executor:$BACKEND_VERSION"
  else
    log_error "Code Executor build failed!"
    popd >/dev/null
    exit 1
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 6. Build Document Worker (Lightweight async job processor)
log_info "Starting Document Worker Build..."
BACKEND_DIR="python_back_end"

if [ -d "$BACKEND_DIR" ]; then
  pushd "$BACKEND_DIR" >/dev/null

  if docker build -f Dockerfile.document-worker -t dulc3/harvis-document-worker:$BACKEND_VERSION .; then
    log_success "Document Worker built successfully with tag: document-worker:$BACKEND_VERSION"
  else
    log_error "Document Worker build failed!"
    popd >/dev/null
    exit 1
  fi

  popd >/dev/null
else
  log_error "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

# 7. Update Kustomization for ArgoCD
echo ""
log_info "Updating Kustomization for ArgoCD..."
KUSTOMIZE_FILE="k8s-manifests/overlays/prod/kustomization.yaml"

if [ -f "$KUSTOMIZE_FILE" ]; then
  # Update image versions
  sed -i "s/newTag: .*/newTag: $BACKEND_VERSION/g"
  
  # Also update document-worker
  sed -i "s/harvis-document-worker:.*/harvis-document-worker:$BACKEND_VERSION/g" "$KUSTOMIZE_FILE" "$KUSTOMIZE_FILE"
  
  # Update patch image references
  sed -i "s/dulc3\/jarvis-backend:.*/dulc3\/jarvis-backend:$BACKEND_VERSION/g" "$KUSTOMIZE_FILE"
  sed -i "s/dulc3\/jarvis-frontend:.*/dulc3\/jarvis-frontend:$FRONTEND_VERSION/g" "$KUSTOMIZE_FILE"
  
  log_success "Kustomization updated with new image versions"
  
  # Show the changes
  echo ""
  log_info "Changes to $KUSTOMIZE_FILE:"
  grep -E "(newTag|image:)" "$KUSTOMIZE_FILE" | head -10
  
  # Commit and push changes
  echo ""
  log_info "Committing changes to Git..."
  
  if git add "$KUSTOMIZE_FILE"; then
    if git commit -m "chore: update images to v$BACKEND_VERSION [ci]"; then
      log_success "Changes committed"
      
      log_info "Pushing to GitHub..."
      if git push origin main; then
        log_success "Changes pushed to GitHub - ArgoCD will auto-sync!"
      else
        log_error "Push failed - you may need to push manually:"
        echo "  cd $(pwd)"
        echo "  git push origin main"
      fi
    else
      log_info "No changes to commit (images already at this version)"
    fi
  else
    log_error "Failed to stage changes"
  fi
else
  log_error "Kustomization file not found: $KUSTOMIZE_FILE"
  log_info "You may need to update it manually"
fi

# Summary
echo ""
echo "=========================================="
log_success "CI Pipeline Completed Successfully!"
echo "Frontend: dulc3/jarvis-frontend:$FRONTEND_VERSION"
echo "Backend:  dulc3/jarvis-backend:$BACKEND_VERSION"
echo "Artifact Executor: dulc3/harvis-artifact-executor:$BACKEND_VERSION"
echo "Code Executor: dulc3/harvis-code-executor:$BACKEND_VERSION"
echo "Document Worker: dulc3/harvis-document-worker:$BACKEND_VERSION"
echo ""
echo "ArgoCD will auto-deploy the new images within 3 minutes!"
echo "=========================================="
