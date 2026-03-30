# KVM/QEMU Setup Guide for OpenClaw

This guide covers setting up OpenClaw automation VMs using KVM/QEMU instead of VirtualBox. KVM offers better performance and is native to Linux systems.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [VM Creation](#vm-creation)
4. [Networking Options](#networking-options)
5. [Shared Storage](#shared-storage)
6. [GUI Access](#gui-access)
7. [Automated Setup Scripts](#automated-setup-scripts)
8. [Troubleshooting](#troubleshooting)

## Prerequisites

### Check KVM Support

```bash
# Check if CPU supports virtualization
egrep -c '(vmx|svm)' /proc/cpuinfo
# Should return a number > 0

# Check if KVM modules are loaded
lsmod | grep kvm
# Should show kvm_intel or kvm_amd

# If not loaded:
sudo modprobe kvm
sudo modprobe kvm_intel  # or kvm_amd for AMD CPUs
```

### Install Required Packages

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y \
    qemu-kvm \
    qemu-utils \
    libvirt-daemon-system \
    libvirt-clients \
    bridge-utils \
    virt-manager \
    virtinst \
    cloud-image-utils

# Add user to libvirt group
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER

# Log out and back in for group changes to take effect
```

## Installation

### Option 1: Using virt-manager (GUI)

```bash
# Launch virt-manager
virt-manager
```

1. Create New VM
2. Import existing disk or install from ISO
3. Allocate 4GB RAM, 2+ CPU cores
4. Disk: 20GB minimum

### Option 2: Command Line (Recommended for Automation)

## VM Creation

### Method 1: Cloud Image (Fastest)

```bash
# Create working directory
mkdir -p ~/openclaw-vms
cd ~/openclaw-vms

# Download Ubuntu cloud image
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img

# Create VM disk (20GB)
qemu-img create -f qcow2 -b jammy-server-cloudimg-amd64.img -F qcow2 openclaw-vm.qcow2 20G

# Create cloud-init config
cat > user-data.yaml << 'EOF'
#cloud-config
users:
  - name: openclaw
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - YOUR_SSH_PUBLIC_KEY_HERE

package_update: true
packages:
  - nodejs
  - npm
  - git
  - xfce4
  - xfce4-goodies
  - tigervnc-standalone-server
  - firefox

runcmd:
  - systemctl enable --now vncserver@1
EOF

# Create meta-data
cat > meta-data.yaml << 'EOF'
instance-id: openclaw-vm-001
local-hostname: openclaw-vm
EOF

# Create cloud-init ISO
cloud-localds cloud-init.iso user-data.yaml meta-data.yaml
```

### Method 2: Fresh ISO Install

```bash
# Download Ubuntu ISO
wget https://releases.ubuntu.com/22.04/ubuntu-22.04.3-live-server-amd64.iso

# Create blank disk
qemu-img create -f qcow2 openclaw-vm-fresh.qcow2 20G

# Install OS (interactive)
virt-install \
    --name openclaw-vm \
    --memory 4096 \
    --vcpus 2 \
    --disk path=openclaw-vm-fresh.qcow2,format=qcow2 \
    --cdrom ubuntu-22.04.3-live-server-amd64.iso \
    --network network=default \
    --graphics vnc,listen=0.0.0.0 \
    --noautoconsole

# Connect via VNC to complete installation
# VNC server will be on port 5900
```

## Networking Options

### Option 1: User Networking (SLIRP) - Easiest

**Best for:** Quick testing, no root access needed, isolated environments

```bash
# VM can reach internet via NAT
# VM can reach host at 10.0.2.2
# Host reaches VM via port forwarding

qemu-system-x86_64 \
    -m 4096 \
    -smp 2 \
    -hda openclaw-vm.qcow2 \
    -cdrom cloud-init.iso \
    -netdev user,id=net0,\
        hostfwd=tcp::2222-:22,\
        hostfwd=tcp::5900-:5900,\
        hostfwd=tcp::8080-:8080 \
    -device virtio-net-pci,netdev=net0 \
    -daemonize

# Port mappings:
# Host:2222 -> VM:22 (SSH)
# Host:5900 -> VM:5900 (VNC)
# Host:8080 -> VM:8080 (OpenClaw bridge)
```

**Harvis Bridge URL for VM:**
```
ws://10.0.2.2:8000/ws/openclaw/vm/your-instance-id
```

### Option 2: Bridge Networking - Best Performance

**Best for:** Production, multiple VMs, direct host↔VM communication

```bash
# Create bridge interface (run once)
sudo ip link add name br0 type bridge
sudo ip link set br0 up
sudo ip addr add 192.168.100.1/24 dev br0

# Or use libvirt's default bridge
# virsh net-start default
# virsh net-autostart default

# Launch VM with bridge
qemu-system-x86_64 \
    -m 4096 \
    -smp 2 \
    -hda openclaw-vm.qcow2 \
    -netdev bridge,id=net0,br=br0 \
    -device virtio-net-pci,netdev=net0 \
    -daemonize

# VM will get IP from 192.168.100.x range
# Can communicate directly with host at 192.168.100.1
```

### Option 3: MacVTap - Direct Connection

**Best for:** Direct host↔VM without bridge overhead

```bash
# Replace eth0 with your actual interface
qemu-system-x86_64 \
    -m 4096 \
    -smp 2 \
    -hda openclaw-vm.qcow2 \
    -netdev tap,id=net0,ifname=tap0,script=no,downscript=no \
    -device virtio-net-pci,netdev=net0 \
    -daemonize
```

## Shared Storage

### Method 1: Virtio-9p (Recommended)

**Fast, native, works with user networking**

```bash
# Create shared directory
mkdir -p ~/openclaw-vms/shared/screenshots

# Launch VM with 9p filesystem
qemu-system-x86_64 \
    -m 4096 \
    -smp 2 \
    -hda openclaw-vm.qcow2 \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 \
    -device virtio-net-pci,netdev=net0 \
    -virtfs local,path=/home/$USER/openclaw-vms/shared,mount_tag=hostshare,security_model=mapped,id=fs0 \
    -daemonize

# Inside VM, mount the share:
sudo mkdir -p /mnt/screenshots
sudo mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/screenshots

# Make permanent by adding to /etc/fstab:
echo "hostshare /mnt/screenshots 9p trans=virtio,version=9p2000.L,rw 0 0" | sudo tee -a /etc/fstab
```

### Method 2: SSH/SCP

**Works everywhere, secure**

```bash
# Inside VM, install SSH server
sudo apt install openssh-server

# From host, copy files
scp -P 2222 screenshots/*.png openclaw@localhost:/mnt/screenshots/

# Or use SSHFS on host to mount VM filesystem
sshfs -p 2222 openclaw@localhost:/mnt/screenshots ~/vm-screenshots
```

### Method 3: NFS

**Best for multiple VMs accessing same storage**

```bash
# On host (NFS server)
sudo apt install nfs-kernel-server
echo "/home/$USER/openclaw-vms/shared 192.168.100.0/24(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -a

# Inside VM (NFS client)
sudo apt install nfs-common
sudo mkdir -p /mnt/nfs
sudo mount 192.168.100.1:/home/username/openclaw-vms/shared /mnt/nfs
```

## GUI Access

### Option 1: SPICE (Recommended)

**Best performance, audio support, USB redirection**

```bash
# Launch VM with SPICE
qemu-system-x86_64 \
    -m 4096 \
    -smp 2 \
    -hda openclaw-vm.qcow2 \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 \
    -device virtio-net-pci,netdev=net0 \
    -spice port=5900,disable-ticketing=on \
    -vga qxl \
    -device virtio-serial-pci \
    -device virtserialport,chardev=spicechannel0,name=com.redhat.spice.0 \
    -chardev spicevmc,id=spicechannel0,name=vdagent \
    -daemonize

# Connect with remote-viewer
remote-viewer spice://localhost:5900

# Or with spicy
spicy -h localhost -p 5900
```

### Option 2: VNC

**Universal compatibility**

```bash
# Launch VM with VNC
qemu-system-x86_64 \
    -m 4096 \
    -smp 2 \
    -hda openclaw-vm.qcow2 \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 \
    -device virtio-net-pci,netdev=net0 \
    -vnc localhost:0,password \
    -vga std \
    -daemonize

# Set VNC password
printf "your-password" | xargs -I {} qemu-monitor-command openclaw-vm --cmd "change vnc password {}"

# Connect with any VNC client
# localhost:5900
```

### Option 3: noVNC (Web-based)

**Access via browser**

```bash
# Install noVNC on host
sudo apt install novnc websockify

# Start WebSocket proxy
websockify -D --web=/usr/share/novnc 6080 localhost:5900

# Access via browser
# http://localhost:6080/vnc.html
```

## Automated Setup Scripts

### Complete VM Launch Script

```bash
#!/bin/bash
# openclaw-vm-launcher.sh

set -e

VM_NAME="openclaw-vm"
VM_DIR="$HOME/openclaw-vms"
VM_DISK="$VM_DIR/openclaw-vm.qcow2"
SHARED_DIR="$VM_DIR/shared"
BRIDGE_NAME="br0"
VM_IP="192.168.100.10"
HARVIS_HOST="192.168.100.1"
HARVIS_PORT="8000"

# Create directories
mkdir -p "$SHARED_DIR/screenshots"
mkdir -p "$SHARED_DIR/logs"

# Check if VM exists
if [ ! -f "$VM_DISK" ]; then
    echo "VM disk not found. Please create it first using cloud-init method."
    exit 1
fi

# Networking mode: bridge or user
NETWORK_MODE="${1:-user}"

if [ "$NETWORK_MODE" = "bridge" ]; then
    # Check if bridge exists
    if ! ip link show "$BRIDGE_NAME" &>/dev/null; then
        echo "Creating bridge $BRIDGE_NAME..."
        sudo ip link add name "$BRIDGE_NAME" type bridge
        sudo ip link set "$BRIDGE_NAME" up
        sudo ip addr add 192.168.100.1/24 dev "$BRIDGE_NAME"
    fi
    
    NETDEV="bridge,id=net0,br=$BRIDGE_NAME"
    BRIDGE_URL="ws://$HARVIS_HOST:$HARVIS_PORT/ws/openclaw/vm/$(cat $VM_DIR/instance-id.txt)"
else
    # User networking with port forwarding
    NETDEV="user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::5900-:5900"
    BRIDGE_URL="ws://10.0.2.2:$HARVIS_PORT/ws/openclaw/vm/$(cat $VM_DIR/instance-id.txt)"
fi

echo "Starting OpenClaw VM..."
echo "Bridge URL: $BRIDGE_URL"

# Save bridge config for VM
cat > "$VM_DIR/bridge-config.json" << EOF
{
  "bridge_url": "$BRIDGE_URL",
  "bridge_token": "$(cat $VM_DIR/bridge-token.txt)",
  "network_mode": "$NETWORK_MODE",
  "shared_path": "/mnt/screenshots"
}
EOF

# Launch VM
qemu-system-x86_64 \
    -name "$VM_NAME" \
    -m 4096 \
    -smp 2 \
    -cpu host \
    -enable-kvm \
    -hda "$VM_DISK" \
    -netdev "$NETDEV" \
    -device virtio-net-pci,netdev=net0 \
    -virtfs local,path="$SHARED_DIR",mount_tag=hostshare,security_model=mapped,id=fs0 \
    -spice port=5900,disable-ticketing=on \
    -vga qxl \
    -device virtio-serial-pci \
    -device virtserialport,chardev=spicechannel0,name=com.redhat.spice.0 \
    -chardev spicevmc,id=spicechannel0,name=vdagent \
    -daemonize \
    -pidfile "$VM_DIR/vm.pid"

echo "VM started!"
echo "SPICE: spice://localhost:5900"
echo "SSH: ssh -p 2222 openclaw@localhost"
echo "Bridge config: $VM_DIR/bridge-config.json"

# Wait for VM to boot
sleep 5

# Mount shared folder via SSH
ssh -p 2222 -o StrictHostKeyChecking=no openclaw@localhost << 'SSH_EOF'
    sudo mkdir -p /mnt/screenshots
    sudo mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/screenshots
    echo "hostshare /mnt/screenshots 9p trans=virtio,version=9p2000.L,rw 0 0" | sudo tee -a /etc/fstab
SSH_EOF

echo "Setup complete! VM is ready for OpenClaw."
```

### OpenClaw Bridge Agent Setup (Inside VM)

```bash
#!/bin/bash
# setup-openclaw-agent.sh (run inside VM)

set -e

# Update system
sudo apt update
sudo apt upgrade -y

# Install dependencies
sudo apt install -y \
    nodejs \
    npm \
    git \
    xfce4 \
    xfce4-goodies \
    tigervnc-standalone-server \
    firefox \
    chromium-browser

# Install OpenClaw
if [ ! -d "$HOME/openclaw" ]; then
    git clone https://github.com/opencrawl/openclaw.git "$HOME/openclaw"
fi

cd "$HOME/openclaw"
npm install
npm run build

# Create bridge agent config
mkdir -p "$HOME/.config/openclaw"
cat > "$HOME/.config/openclaw/bridge-config.json" << 'EOF'
{
  "bridge_url": "ws://10.0.2.2:8000/ws/openclaw/vm/INSTANCE_ID_PLACEHOLDER",
  "bridge_token": "TOKEN_PLACEHOLDER",
  "screenshot_path": "/mnt/screenshots",
  "auto_connect": true,
  "reconnect_interval": 5000
}
EOF

# Create systemd service for bridge agent
cat > /tmp/openclaw-bridge.service << 'EOF'
[Unit]
Description=OpenClaw Bridge Agent
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/home/openclaw/openclaw
ExecStart=/usr/bin/npm run bridge
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/openclaw-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw-bridge

# Setup VNC
mkdir -p "$HOME/.vnc"
echo "your-vnc-password" | vncpasswd -f > "$HOME/.vnc/passwd"
chmod 600 "$HOME/.vnc/passwd"

# Create VNC xstartup
cat > "$HOME/.vnc/xstartup" << 'EOF'
#!/bin/bash
xrdb $HOME/.Xresources
startxfce4 &
EOF
chmod +x "$HOME/.vnc/xstartup"

echo "OpenClaw agent setup complete!"
echo "Start VNC: vncserver :1"
echo "Start bridge: sudo systemctl start openclaw-bridge"
```

## Troubleshooting

### VM Won't Start

```bash
# Check KVM modules
lsmod | grep kvm

# If missing:
sudo modprobe kvm
sudo modprobe kvm_intel  # or kvm_amd

# Check permissions
sudo chmod 666 /dev/kvm

# Check virtualization in BIOS
# Must be enabled: VT-x (Intel) or AMD-V (AMD)
```

### No Network Access

```bash
# Check network interface in VM
ip addr show

# Check host forwarding
sudo iptables -t nat -L -n -v

# Test from host
nc -zv localhost 2222

# Test from VM
ping 10.0.2.2  # Should reach host in user mode
```

### Shared Folder Not Mounting

```bash
# Inside VM, check 9p support
lsmod | grep 9p

# If missing:
sudo modprobe 9p
sudo modprobe 9pnet
sudo modprobe 9pnet_virtio

# Manual mount
sudo mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/screenshots

# Check dmesg for errors
dmesg | tail -20
```

### WebSocket Connection Failed

```bash
# Test from VM
curl -I http://10.0.2.2:8000/health  # or your Harvis URL

# If using bridge mode, test:
ping 192.168.100.1

# Check firewall on host
sudo iptables -L -n | grep 8000

# Allow port on host
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
```

### Performance Issues

```bash
# Enable KVM acceleration (should be automatic)
qemu-system-x86_64 -accel kvm ...

# Use virtio devices
-device virtio-net-pci
-device virtio-scsi-pci
-drive file=disk.qcow2,if=virtio

# CPU pinning
-taskset -c 0,1 qemu-system-x86_64 ...

# Hugepages for better memory performance
# Requires setup on host
echo 1024 | sudo tee /proc/sys/vm/nr_hugepages
```

### Cleanup

```bash
# Stop VM
kill $(cat ~/openclaw-vms/vm.pid)

# Or using qemu-monitor
qemu-monitor-command openclaw-vm --cmd "system_powerdown"

# Force stop
qemu-monitor-command openclaw-vm --cmd "quit"

# Remove VM (careful!)
rm ~/openclaw-vms/openclaw-vm.qcow2
```

## Quick Reference

| Feature | Command |
|---------|---------|
| Start VM | `./openclaw-vm-launcher.sh` |
| Connect VNC | `remote-viewer spice://localhost:5900` |
| SSH to VM | `ssh -p 2222 openclaw@localhost` |
| Copy file to VM | `scp -P 2222 file.txt openclaw@localhost:/tmp/` |
| Mount shared folder | `sudo mount -t 9p hostshare /mnt/screenshots` |
| Check VM status | `ps aux | grep qemu` |
| Stop VM gracefully | `kill -TERM $(cat vm.pid)` |
| Force stop | `kill -9 $(cat vm.pid)` |

## Comparison: KVM vs VirtualBox

| Feature | KVM | VirtualBox |
|---------|-----|------------|
| Performance | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Setup Complexity | Medium | Easy |
| GUI Management | virt-manager | Built-in |
| Headless Operation | Excellent | Good |
| Nested Virtualization | Yes | Limited |
| Snapshots | Yes | Yes |
| Live Migration | Yes | No |
| Resource Usage | Lower | Higher |
| Integration | Native Linux | Cross-platform |

## Next Steps

1. Run the setup script: `./setup-openclaw-agent.sh` (inside VM)
2. Configure the bridge connection using the generated `bridge-config.json`
3. Start the OpenClaw bridge agent
4. Register the VM in Harvis: `POST /api/openclaw/instances`
5. Create your first automation task!

For issues specific to Harvis integration, see the main `SETUP_GUIDE.md`.
