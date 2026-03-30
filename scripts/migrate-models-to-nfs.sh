#!/bin/bash
# Migrate existing ML models and Ollama models to NFS storage
# Run this script AFTER setting up NFS server

set -e

echo "=== Migrating Models to NFS Storage ==="

# Configuration
RUNNING_POD="harvis-ai-merged-ollama-backend-78d89684d-lc9l5"
NAMESPACE="ai-agents"
NFS_ML_PATH="/srv/nfs/ml-models-cache"
NFS_OLLAMA_PATH="/srv/nfs/ollama-models"

echo ""
echo "Step 1: Creating temporary directories for model extraction..."
mkdir -p /tmp/ml-models-migration
mkdir -p /tmp/ollama-models-migration

echo ""
echo "Step 2: Copying ML models from running pod to temp directory..."
kubectl cp -n ${NAMESPACE} ${RUNNING_POD}:/models-cache/huggingface /tmp/ml-models-migration/huggingface -c harvis-backend
kubectl cp -n ${NAMESPACE} ${RUNNING_POD}:/models-cache/whisper /tmp/ml-models-migration/whisper -c harvis-backend

echo ""
echo "Step 3: Copying Ollama models from running pod to temp directory..."
kubectl cp -n ${NAMESPACE} ${RUNNING_POD}:/root/.ollama/models /tmp/ollama-models-migration/models -c ollama

echo ""
echo "Step 4: Moving models to NFS storage..."
sudo mkdir -p ${NFS_ML_PATH}/huggingface
sudo mkdir -p ${NFS_ML_PATH}/whisper
sudo mkdir -p ${NFS_OLLAMA_PATH}

sudo cp -r /tmp/ml-models-migration/huggingface/* ${NFS_ML_PATH}/huggingface/
sudo cp -r /tmp/ml-models-migration/whisper/* ${NFS_ML_PATH}/whisper/
sudo cp -r /tmp/ollama-models-migration/models ${NFS_OLLAMA_PATH}/

echo ""
echo "Step 5: Setting proper permissions..."
sudo chmod -R 777 ${NFS_ML_PATH}
sudo chmod -R 777 ${NFS_OLLAMA_PATH}

echo ""
echo "Step 6: Verifying migration..."
echo "ML Models Cache:"
ls -lh ${NFS_ML_PATH}/huggingface/
ls -lh ${NFS_ML_PATH}/whisper/

echo ""
echo "Ollama Models:"
ls -lh ${NFS_OLLAMA_PATH}/

echo ""
echo "Step 7: Cleaning up temp directories..."
rm -rf /tmp/ml-models-migration
rm -rf /tmp/ollama-models-migration

echo ""
echo "=== Migration Complete! ==="
echo ""
echo "Next steps:"
echo "1. Run: kubectl apply -f k8s-manifests/storage/nfs-storage.yaml"
echo "2. Verify PVCs are bound: kubectl get pvc -n ai-agents | grep nfs"
echo "3. Delete old deployment: kubectl delete deployment harvis-ai-merged-ollama-backend -n ai-agents"
echo "4. Apply new deployments: kubectl apply -f k8s-manifests/services/ollama-dedicated.yaml"
echo "5. Apply backend deployment: kubectl apply -f k8s-manifests/services/backend-dedicated.yaml"
