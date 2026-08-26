#!/bin/bash
# copy-nvidia-toolkit.sh
# Copies the working NVIDIA container toolkit from THIS machine to another
# k3s node and restarts containerd/k3s on the target.
#
# Usage: ./scripts/copy-nvidia-toolkit.sh [-i identity_file] <target-ip> [ssh-user]
# Example: ./scripts/copy-nvidia-toolkit.sh -i ~/.ssh/id_ed25519 10.0.0.4 myuser

set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}   $1"; }
log_error()   { echo -e "${RED}[ERR]${NC}  $1"; }

# ── Parse args ────────────────────────────────────────────────────────────────
SSH_IDENTITY=""
while getopts ":i:" opt; do
  case $opt in
    i) SSH_IDENTITY="$OPTARG" ;;
    *) echo "Usage: $0 [-i identity_file] <target-ip> [ssh-user]"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

TARGET_IP="${1:?Usage: $0 [-i identity_file] <target-ip> [ssh-user]}"
SSH_USER="${2:-dulc3}"
TMP_PKG_DIR="/tmp/nct-packages"
TARGET="$SSH_USER@$TARGET_IP"

# Build SSH/SCP option strings
SSH_OPTS=(-o StrictHostKeyChecking=no)
SCP_OPTS=(-o StrictHostKeyChecking=no)
if [ -n "$SSH_IDENTITY" ]; then
  SSH_OPTS+=(-i "$SSH_IDENTITY")
  SCP_OPTS+=(-i "$SSH_IDENTITY")
fi

# ── Step 1: check driver versions match ──────────────────────────────────────
log_info "Checking NVIDIA driver version on this machine..."
LOCAL_DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
log_info "Local driver: $LOCAL_DRIVER"

log_info "Checking NVIDIA driver version on $TARGET_IP..."
REMOTE_DRIVER=$(ssh "${SSH_OPTS[@]}" "$TARGET" \
  "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo unknown")
log_info "Remote driver: $REMOTE_DRIVER"

if [ "$LOCAL_DRIVER" != "$REMOTE_DRIVER" ]; then
  log_error "Driver version mismatch! Local=$LOCAL_DRIVER Remote=$REMOTE_DRIVER"
  log_error "Copying the toolkit may not work — the toolkit must match the driver."
  read -rp "Continue anyway? (y/N): " yn
  [[ "${yn,,}" == "y" ]] || exit 1
fi

# ── Step 2: collect toolkit packages from local pacman cache ──────────────────
log_info "Finding nvidia-container-toolkit packages on this machine..."
mkdir -p "$TMP_PKG_DIR"

NCT_PKG=$(find /var/cache/pacman/pkg/ -name "nvidia-container-toolkit-*.pkg.tar.zst" 2>/dev/null | sort -V | tail -1 || true)
LIBNCT_PKG=$(find /var/cache/pacman/pkg/ -name "libnvidia-container-tools-*.pkg.tar.zst" 2>/dev/null | sort -V | tail -1 || true)
LIBNCT1_PKG=$(find /var/cache/pacman/pkg/ -name "libnvidia-container1-*.pkg.tar.zst" 2>/dev/null | sort -V | tail -1 || true)

if [ -z "$NCT_PKG" ]; then
  log_info "Package not in cache — downloading via pacman..."
  sudo pacman -Sw --cachedir "$TMP_PKG_DIR" nvidia-container-toolkit --noconfirm
  NCT_PKG=$(find "$TMP_PKG_DIR" -name "nvidia-container-toolkit-*.pkg.tar.zst" | sort -V | tail -1)
  LIBNCT_PKG=$(find "$TMP_PKG_DIR" -name "libnvidia-container-tools-*.pkg.tar.zst" | sort -V | tail -1 || true)
  LIBNCT1_PKG=$(find "$TMP_PKG_DIR" -name "libnvidia-container1-*.pkg.tar.zst" | sort -V | tail -1 || true)
else
  cp "$NCT_PKG" "$TMP_PKG_DIR/" 2>/dev/null || true
  [ -n "$LIBNCT_PKG" ]  && cp "$LIBNCT_PKG"  "$TMP_PKG_DIR/" 2>/dev/null || true
  [ -n "$LIBNCT1_PKG" ] && cp "$LIBNCT1_PKG" "$TMP_PKG_DIR/" 2>/dev/null || true
fi

log_success "Packages ready in $TMP_PKG_DIR:"
ls -lh "$TMP_PKG_DIR"/*.zst 2>/dev/null || { log_error "No packages found!"; exit 1; }

# ── Step 3: SCP packages to target ───────────────────────────────────────────
log_info "Copying packages to $TARGET:~/nct-packages/ ..."
ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p ~/nct-packages"
scp "${SCP_OPTS[@]}" "$TMP_PKG_DIR"/*.zst "$TARGET:~/nct-packages/"
log_success "Packages transferred."

# ── Step 4: Install on target and restart runtime ────────────────────────────
log_info "Installing on $TARGET_IP and restarting container runtime..."
ssh -tt "${SSH_OPTS[@]}" "$TARGET" bash <<'REMOTE'
set -euo pipefail
echo "[remote] Installing nvidia-container-toolkit packages..."
sudo pacman -U --noconfirm ~/nct-packages/*.zst

echo "[remote] Running ldconfig..."
sudo ldconfig

echo "[remote] Generating CDI spec..."
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>/dev/null || true

echo "[remote] Configuring containerd runtime..."
sudo nvidia-ctk runtime configure --runtime=containerd 2>/dev/null || true

echo "[remote] Restarting containerd and k3s..."
sudo systemctl restart containerd 2>/dev/null || true
sudo systemctl restart k3s-agent 2>/dev/null || sudo systemctl restart k3s 2>/dev/null || true
sleep 3

echo "[remote] Verifying toolkit:"
nvidia-container-cli info || true
echo "Done!"
REMOTE

log_success "NVIDIA container toolkit installed on $TARGET_IP!"
log_info "Next: kubectl delete pod -n ai-agents -l app.kubernetes.io/component=llama-server"
log_info "      (K8s will reschedule and the new pod should start cleanly)"
