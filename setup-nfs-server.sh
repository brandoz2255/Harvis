#!/bin/bash
# NFS Server Setup Script for Harvis AI Multi-GPU Cluster
# Run this script with sudo on the control plane node (pop-os)

set -e

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
cat > /etc/exports <<EOF
# Harvis AI Shared Storage - accessible from all cluster nodes
/srv/nfs/ml-models-cache 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/ml-models-cache 139.182.180.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/ollama-models 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/ollama-models 139.182.180.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/harvis-audio 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/harvis-audio 139.182.180.0/24(rw,sync,no_subtree_check,no_root_squash)
EOF

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
echo "NFS Share: 192.168.1.195:/srv/nfs/ml-models-cache"
echo ""
echo "Next steps:"
echo "1. Install nfs-common on worker node: ssh pop-os-343570d8 'sudo apt install -y nfs-common'"
echo "2. Test mount from worker node: sudo mount -t nfs 192.168.1.195:/srv/nfs/ml-models-cache /mnt"
