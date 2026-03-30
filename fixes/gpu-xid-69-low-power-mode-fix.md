# GPU Xid 69 Error - dulc3-top (Low Power Mode Fix)

**Date**: 2026-03-26  
**Affected Node**: dulc3-top (GTX 1650 Ti laptop GPU)  
**Symptom**: Embedding pods stuck in Pending state, GPU unavailable

---

## Problem

**Error Message:**
```
Warning  FailedScheduling  0/7 nodes are available: 1 Insufficient nvidia.com/gpu
```

**Root Cause:**
GPU enters low power mode on laptop → NVIDIA driver loses access → Device plugin marks GPU as unhealthy

**Device Plugin Logs:**
```
XidCriticalError: Xid=69 on Device=GPU-03b3ea5d-d232-71d4-39a6-ac74d0d2f216
'nvidia.com/gpu' device marked unhealthy: GPU-03b3ea5d-d232-71d4-39a6-ac74d0d2f216
```

**Affected Service:**
- `harvis-ai-llama-embed` deployment (Qwen3-Embedding 4B model)
- Any GPU workload scheduled to `dulc3-top`

---

## Symptoms to Look For

1. **Pod stuck in Pending:**
   ```bash
   kubectl get pods -n ai-agents | grep embed
   # harvis-ai-llama-embed-xxxxx  0/2  Pending
   ```

2. **GPU marked as 0 allocatable:**
   ```bash
   kubectl describe node dulc3-top | grep "nvidia.com/gpu"
   # Capacity: 1
   # Allocated: 1 (but actually 0 usable)
   ```

3. **Device plugin logs show Xid 69 errors**

---

## Quick Fix (When Laptop is in Low Power Mode)

### Step 1: Set Laptop to High Performance Mode

**On dulc3-top (laptop):**
- Switch power mode to **High Performance** in BIOS/OS settings
- Or run: `sudo powertop --auto-tune`

### Step 2: Restart GPU Device Plugin

```bash
# Find the device plugin pods on dulc3-top
kubectl get pods -n gpu-operator -o wide | grep dulc3-top | grep device-plugin

# Restart them (replace pod name from above)
kubectl delete pod <nvidia-device-plugin-pod> -n gpu-operator
kubectl delete pod <nvidia-device-plugin-pod> -n kube-system
```

**Or one-liner:**
```bash
kubectl delete pods -n gpu-operator -l name=nvidia-device-plugin-daemonset
kubectl delete pods -n kube-system -l name=nvidia-device-plugin-daemonset
```

### Step 3: Restart Affected Pods

```bash
# Delete pending embedding pod to trigger reschedule
kubectl delete pod -n ai-agents -l app=harvis-ai-llama-embed

# Or restart the deployment
kubectl rollout restart deployment harvis-ai-llama-embed -n ai-agents
```

### Step 4: Verify GPU is Healthy

```bash
# Check device plugin logs (should NOT see Xid 69)
kubectl logs -n gpu-operator -l name=nvidia-device-plugin-daemonset --tail=5

# Check embedding pod is running
kubectl get pods -n ai-agents | grep embed
# Should show: READY 2/2, STATUS Running

# Verify GPU allocated
kubectl describe node dulc3-top | grep -A 5 "Allocated resources"
```

---

## Verification Commands

**Check GPU is available:**
```bash
kubectl describe node dulc3-top | grep "nvidia.com/gpu"
# Should show: Capacity: 1, Allocatable: 1
```

**Check embedding service is ready:**
```bash
kubectl get pods -n ai-agents | grep embed
# Expected: READY=2/2, STATUS=Running, NODE=dulc3-top
```

**Test embedding endpoint:**
```bash
# Check Qwen3 embed container logs
kubectl logs -n ai-agents -l app=harvis-ai-llama-embed -c embed-qwen3 | grep "server is listening"
# Should see: main: server is listening on http://0.0.0.0:8080
```

---

## Prevention Tips

1. **Keep laptop on power adapter** when running GPU workloads
2. **Set power mode to High Performance** before deploying GPU pods
3. **Monitor GPU health** periodically:
   ```bash
   kubectl logs -n gpu-operator -l name=nvidia-device-plugin-daemonset | grep -i "unhealthy"
   ```

4. **Consider taints/tolerations** to schedule GPU workloads only to desktop nodes (dulc3-os with RTX 5090)

---

## Related Issues

- **Xid 69**: GPU driver lost access (power management)
- **Graphics mode conflict**: GPU used for display + compute simultaneously
- **Solution for hybrid laptops**: Use `prime-offload` for compute workloads

---

## Quick Reference

| Issue | Command |
|-------|---------|
| Check GPU health | `kubectl logs -n gpu-operator -l device-plugin --tail=10` |
| Restart GPU plugin | `kubectl delete pods -n gpu-operator -l name=nvidia-device-plugin` |
| Restart embedding | `kubectl rollout restart deployment harvis-ai-llama-embed -n ai-agents` |
| Check pod status | `kubectl get pods -n ai-agents -o wide` |

---

**Last Updated**: 2026-03-26  
**Tested On**: dulc3-top (GTX 1650 Ti, k3s v1.35.2)
