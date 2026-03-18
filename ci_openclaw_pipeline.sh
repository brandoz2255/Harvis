#!/bin/bash

# CI Pipeline for OpenClaw
# Builds the OpenClaw Docker image from openclaw/openclaw/ and pushes to Docker Hub.
# Separate from the main ci_pipeline.sh because OpenClaw is an external service
# (not part of the main Harvis codebase) with its own build toolchain (pnpm/Node 22).

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }

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

OPENCLAW_DIR="openclaw/openclaw"

# ─── Preflight checks ────────────────────────────────────────────────────────

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

# ─── Version input ───────────────────────────────────────────────────────────

OPENCLAW_VERSION=$(get_input "Enter tag for OpenClaw image (e.g., v1.0.0 or latest):" "OpenClaw Version" "latest")
IMAGE_NAME="dulc3/openclaw:$OPENCLAW_VERSION"

log_info "Building: $IMAGE_NAME"
log_info "Source:   $OPENCLAW_DIR"
echo ""

# ─── Sync skills into build context ──────────────────────────────────────────
# Source of truth: skills/Harvis/ and skills/Shared/ at the repo root.
# openclaw/skills/ is the staging area for the Docker build context (gitignored).

log_info "Syncing skills into Docker build context..."
mkdir -p openclaw/skills

# Harvis-specific skills
if [ -d "skills/Harvis" ]; then
  rsync -a --delete skills/Harvis/ openclaw/skills/
  log_info "  Synced skills/Harvis/ → openclaw/skills/"
fi

# Shared skills (append, don't overwrite Harvis)
if [ -d "skills/Shared" ]; then
  rsync -a skills/Shared/ openclaw/skills/
  log_info "  Synced skills/Shared/ → openclaw/skills/"
fi

echo ""

# ─── Build ───────────────────────────────────────────────────────────────────

log_info "Starting OpenClaw build..."
log_warn "Note: OpenClaw uses pnpm + Bun for its build. This may take a few minutes on first run."

# Build context is openclaw/ so:
#   - COPY openclaw/...    resolves to openclaw/openclaw/... (the submodule)
#   - COPY skills/         resolves to openclaw/skills/     (synced from skills/Harvis/ above)
if docker build -t "$IMAGE_NAME" -f "$OPENCLAW_DIR/Dockerfile" openclaw/; then
  log_success "OpenClaw built: $IMAGE_NAME"
else
  log_error "OpenClaw build failed!"
  exit 1
fi

# Also tag as latest if a specific version was given
if [ "$OPENCLAW_VERSION" != "latest" ]; then
  docker tag "$IMAGE_NAME" "dulc3/openclaw:latest"
  log_info "Also tagged as: dulc3/openclaw:latest"
fi

# ─── Smoke test (optional but recommended) ───────────────────────────────────

echo ""
if command -v whiptail &>/dev/null; then
  if whiptail --yesno "Run a quick health-check smoke test before pushing?" 10 60 --title "Smoke Test"; then
    RUN_SMOKE=true
  else
    RUN_SMOKE=false
  fi
else
  read -p "Run a quick smoke test before pushing? (Y/n): " smoke_choice
  if [[ $smoke_choice =~ ^[Nn]$ ]]; then
    RUN_SMOKE=false
  else
    RUN_SMOKE=true
  fi
fi

if [ "$RUN_SMOKE" = true ]; then
  log_info "Running smoke test — starting container on port 18799 (offset to avoid conflicts)..."

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

# ─── Push (BEFORE kustomize git-push so ArgoCD never sees a tag that isn't on Hub yet) ───

echo ""
if command -v whiptail &>/dev/null; then
  if whiptail --yesno "Push $IMAGE_NAME to Docker Hub?" 10 60 --title "Push Image"; then
    PUSH_IMAGE=true
  else
    PUSH_IMAGE=false
  fi
else
  read -p "Push $IMAGE_NAME to Docker Hub? (Y/n): " push_choice
  if [[ $push_choice =~ ^[Nn]$ ]]; then
    PUSH_IMAGE=false
  else
    PUSH_IMAGE=true
  fi
fi

if [ "$PUSH_IMAGE" = true ]; then
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

# ─── Update kustomization.yaml (after Docker push so the image exists on Hub) ───

echo ""
log_info "Updating kustomization.yaml with new OpenClaw tag..."
KUSTOMIZE_FILE="k8s-manifests/overlays/prod/kustomization.yaml"

if [ -f "$KUSTOMIZE_FILE" ]; then
  python3 - <<PYEOF
import re

with open("$KUSTOMIZE_FILE", "r") as f:
    content = f.read()

# Update only the dulc3/openclaw entry — leave all harvis image tags untouched.
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

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
log_success "OpenClaw CI Pipeline Complete!"
echo "Image:    $IMAGE_NAME"
echo "Gateway:  ws://harvis-ai-openclaw:18789 (internal K8s)"
echo "Health:   http://harvis-ai-openclaw:18789/health"
echo ""
echo "ArgoCD will auto-deploy once the push and git push are done."
echo "Monitor: kubectl -n ai-agents logs -f deploy/harvis-ai-openclaw"
echo "=========================================="
