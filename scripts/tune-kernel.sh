#!/bin/bash
# tune-kernel.sh
# Apply kernel performance tuning for GPU inference nodes.
# Run on BOTH dulc3-os and dulc3-top.
#
# Usage: ./scripts/tune-kernel.sh [--persist]
#   --persist  also writes to /etc/sysctl.conf for reboot survival

set -euo pipefail
PERSIST=false
[[ "${1:-}" == "--persist" ]] && PERSIST=true

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC}   $1"; }

apply() {
  local key="$1" val="$2"
  echo "$val" | sudo tee "/proc/sys/${key//.//}" > /dev/null
  log_success "$key = $val"
  if $PERSIST; then
    if grep -qF "$key" /etc/sysctl.conf 2>/dev/null; then
      sudo sed -i "s|^$key.*|$key=$val|" /etc/sysctl.conf
    else
      echo "$key=$val" | sudo tee -a /etc/sysctl.conf > /dev/null
    fi
  fi
}

log_info "=== Huge Pages (reduces TLB pressure on large model weight loads) ==="
echo 20000 | sudo tee /proc/sys/vm/nr_hugepages > /dev/null
log_success "vm.nr_hugepages = 20000"
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null
log_success "transparent_hugepage = always"

if $PERSIST; then
  grep -qF "vm.nr_hugepages" /etc/sysctl.conf 2>/dev/null \
    || echo "vm.nr_hugepages=20000" | sudo tee -a /etc/sysctl.conf > /dev/null
fi

log_info "=== NUMA (disable rebalancing to prevent mid-inference page migrations) ==="
apply kernel.numa_balancing 0

log_info "=== CPU Performance Governor ==="
if command -v cpupower &>/dev/null; then
  sudo cpupower frequency-set -g performance
  log_success "CPU governor set to performance"
else
  log_info "cpupower not found — install linux-tools or cpupower"
fi

log_info "=== Writeback (reduce interference during long inference sessions) ==="
apply vm.dirty_ratio 80
apply vm.dirty_background_ratio 5

if $PERSIST; then
  # Transparent hugepage persistence via systemd
  cat << 'EOF' | sudo tee /etc/systemd/system/transparent-hugepage.service > /dev/null
[Unit]
Description=Enable Transparent Huge Pages
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo always > /sys/kernel/mm/transparent_hugepage/enabled'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl enable --now transparent-hugepage.service
  log_success "Persistent THP service enabled"
fi

log_success "=== Kernel tuning applied ==="
log_info "Re-run with --persist to survive reboots"
log_info "Run on dulc3-top too: ssh dulc3@<laptop-ip> 'bash -s -- --persist' < scripts/tune-kernel.sh"
