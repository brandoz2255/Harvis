# ArgoCD Quickstart Guide

## 🚀 Access Your ArgoCD

**URL:** http://10.0.0.7:31179

**Get Password:**
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
echo
```

## 📋 Current Applications

```bash
kubectl get applications -n argocd
```

**Harvis AI:**
- Sync Status: Check in UI or run `kubectl get application harvis-ai -n argocd`
- Location: ai-agents namespace
- Images: v2.28.10

## 🔄 Update Workflow (Current - Local CI)

### Step 1: Build Images
```bash
./ci_pipeline.sh
```

### Step 2: Update Manifest
Edit `k8s-manifests/overlays/prod/kustomization.yaml`:
```yaml
images:
  - name: harvis-backend
    newName: dulc3/jarvis-backend
    newTag: v2.28.11  # ← Change this
  - name: harvis-frontend
    newName: dulc3/jarvis-frontend
    newTag: v2.28.11  # ← Change this
```

### Step 3: Commit & Push
```bash
git add k8s-manifests/overlays/prod/kustomization.yaml
git commit -m "Update Harvis to v2.28.11"
git push origin main
```

### Step 4: Watch ArgoCD Sync
```bash
# In ArgoCD UI, watch for sync
# Or check via CLI:
kubectl get application harvis-ai -n argocd -w
```

## 🆘 Troubleshooting

### Check Application Status
```bash
kubectl get application harvis-ai -n argocd
kubectl describe application harvis-ai -n argocd
```

### Force Sync
```bash
# Via kubectl
kubectl patch application harvis-ai -n argocd --type merge -p '{"operation":{"sync":{}}}'

# Or via ArgoCD CLI (if installed)
argocd app sync harvis-ai
```

### View Pod Status
```bash
kubectl get pods -n ai-agents
kubectl logs -n ai-agents deployment/harvis-ai-backend
```

## 🌟 Next Steps

1. **Test the workflow:** Update to v2.28.11 manually
2. **Read the full guide:** `docs/ARGOCD_GITOPS_GUIDE.md`
3. **Setup GitLab CI:** Run `./scripts/setup-gitlab-ci.sh`
4. **Create new apps:** Follow guide section 6

## 📚 Documentation

- **Full Guide:** docs/ARGOCD_GITOPS_GUIDE.md
- **GitLab CI Setup:** .gitlab-ci.yml.example
- **Setup Script:** scripts/setup-gitlab-ci.sh

## 🎯 Quick Commands

```bash
# Check all apps
kubectl get applications -n argocd

# Check Harvis status
kubectl get application harvis-ai -n argocd

# Check pods
kubectl get pods -n ai-agents

# View ArgoCD logs
kubectl logs -n argocd deployment/argocd-server --tail=50

# Port-forward (if VPN down)
kubectl port-forward -n argocd svc/argocd-server 8080:443
# Then: https://localhost:8080
```

---

**You're all set!** 🎉

ArgoCD is managing your Harvis deployment. Just update the kustomization.yaml when you have new images, push to Git, and ArgoCD handles the rest!
