#!/bin/bash
# NFS Server Setup Script for Harvis AI Multi-GPU Cluster
# Run this script with sudo on the control plane node.
#
# Configure for YOUR cluster before running — the defaults export to nothing.
# NFS_ALLOWED_CIDRS is a space-separated list of networks allowed to mount.
# Never widen it past the subnet your nodes actually sit on: no_root_squash
# means any host in the range gets root-equivalent write access to the share.
#
#   NFS_SERVER_IP=10.0.0.5 NFS_ALLOWED_CIDRS="10.0.0.0/24" \
#     sudo -E ./setup-nfs-server.sh

set -e

NFS_SERVER_IP="${NFS_SERVER_IP:-$(hostname -I | awk '{print $1}')}"
NFS_ALLOWED_CIDRS="${NFS_ALLOWED_CIDRS:-}"
NFS_CLIENT_HOST="${NFS_CLIENT_HOST:-<worker-node>}"

if [ -z "$NFS_ALLOWED_CIDRS" ]; then
  echo "ERROR: set NFS_ALLOWED_CIDRS to the subnet(s) your nodes are on," >&2
  echo "       e.g. NFS_ALLOWED_CIDRS=\"10.0.0.0/24\". Refusing to guess," >&2
  echo "       because a wrong guess exports root-writable storage." >&2
  exit 1
fi

echo "=== Setting up NFS Server for ML Models Shared Storage ==="

# Create NFS export directories
echo "Creating NFS export directories..."
mkdir -p /srv/nfs/ml-models-cache
mkdir -p /srv/nfs/ollama-models
mkdir -p /srv/nfs/harvis-audio
chmod 777 /srv/nfs/ml-models-cache
chmod 777 /srv/nfs/ollama-models
chmod 777 /srv/nfs/harvis-audio

# Configure NFS exports
echo "Configuring NFS exports..."
{
  echo "# Harvis AI Shared Storage - accessible from all cluster nodes"
  for share in ml-models-cache ollama-models harvis-audio; do
    for cidr in $NFS_ALLOWED_CIDRS; do
      echo "/srv/nfs/$share ${cidr}(rw,sync,no_subtree_check,no_root_squash)"
    done
  done
} > /etc/exports

# Export the NFS shares
echo "Exporting NFS shares..."
exportfs -ra

# Restart NFS server
echo "Restarting NFS server..."
systemctl restart nfs-kernel-server

# Enable NFS server on boot
systemctl enable nfs-kernel-server

# Show NFS exports
echo ""
echo "=== NFS Exports configured ==="
showmount -e localhost

echo ""
echo "=== NFS Server setup complete! ==="
echo "NFS Share: ${NFS_SERVER_IP}:/srv/nfs/ml-models-cache"
echo ""
echo "Next steps:"
echo "1. Install nfs-common on worker node: ssh ${NFS_CLIENT_HOST} 'sudo apt install -y nfs-common'"
echo "2. Test mount from worker node: sudo mount -t nfs ${NFS_SERVER_IP}:/srv/nfs/ml-models-cache /mnt"
