# Ollama → vLLM Migration Plan — Harvis AI Stack

_Last updated: 2026-02-25_

**Target cluster:** `ai-agents` namespace, GPU node (merged-ollama-backend pod), OpenClaw node `rocky2vm.local`

**Scope:** Replace the `ollama` sidecar in `harvis-ai-merged-ollama-backend` with a vLLM server. Update OpenClaw config, Harvis backend chat code, and the `unload_ollama_model` helper. Cloud routing (Kimi K2.5, Qwen3 235B via harvis-proxy), auth, and the OpenClaw WebSocket protocol are untouched.

---

## 1. Why vLLM Over Ollama for Agentic / Tool-Use Workloads

### PagedAttention and Continuous Batching

Ollama allocates a fixed KV-cache block per request and processes one at a time. vLLM's PagedAttention treats KV cache like OS virtual memory — non-contiguous physical blocks allocated on demand, paged out when a sequence ends. For an agentic tool loop (`exec` → wait → `write` → wait → `read`), vLLM can interleave multiple incomplete sequences across the same GPU memory Ollama holds idle. Throughput on concurrent agentic sessions is 2–4x higher on a single GPU for short-context tool calls.

Continuous batching means new requests are inserted into an already-running batch at every decode step, not waiting for the whole batch to drain. Relevant when the backend fires near-simultaneous requests: workspace task message to OpenClaw + `/api/chat` call from a user.

### Native Tool-Call Parsers

vLLM ships `--enable-auto-tool-choice` and `--tool-call-parser` flags. For Qwen3, the correct parser is `hermes`. Without this, the model emits raw JSON inside a text token stream and the caller regex-parses it (what Ollama does). With the hermes parser, vLLM parses the tool call block, populates the OpenAI `tool_calls` array, and OpenClaw's tool execution engine receives a structured object — not a string. This is the primary reason to switch for workspace use.

### Structured Output (JSON Mode)

vLLM supports constrained decoding via `guided_json` (outlines backend). When the planner agent needs to return a structured JSON step list, pass `extra_body={"guided_json": schema}` and vLLM guarantees valid JSON matching the schema without post-processing. Ollama has no equivalent.

### OpenAI-Compatible API — Already Expected by This Stack

The `harvis-proxy` path in OpenClaw already uses `"api": "openai-completions"`. vLLM natively serves `/v1/chat/completions`, `/v1/models`, `/v1/completions`. The Ollama native API (`/api/chat`, `/api/generate`, `/api/tags`, `/api/keep-alive`) requires translation wrappers currently embedded in `main.py` — `make_ollama_request`, `stream_ollama_chunks`, `run_ollama_with_heartbeats`, `unload_ollama_model`. All of that translation layer disappears with vLLM.

---

## 2. Annoyance Assessment

| Component | Difficulty | Reasoning |
|-----------|-----------|-----------|
| **OpenClaw config** (`openclaw.json` ConfigMap) | 2 / 10 | Add one provider block, change two model reference strings. `harvis-proxy` already demonstrates the pattern. Exact diff in Section 6. |
| **NetworkPolicy** | 3 / 10 | Add egress to port 8001, remove 11434 in Phase 4. One rule change. |
| **K8s Deployment** | 4 / 10 | Replace `ollama` sidecar container. New init container for model pull. Resource request tuning. `runtimeClassName: nvidia` already set. |
| **Backend chat code** (`main.py`) | 6 / 10 | `stream_ollama_chunks` speaks Ollama NDJSON. vLLM returns OpenAI SSE. Response parsing loop (~lines 2575–2640) must be rewritten. Also `make_ollama_request`, `unload_ollama_model`, `/api/ollama-models` need updating. Contained but requires testing. |
| **Model management** | 5 / 10 | Ollama does lazy pull + automatic GGUF quant. vLLM requires the model on disk in HF format before startup. Need init container strategy and HF cache PVC. |
| **`unload_ollama_model` helper** | 3 / 10 | POSTs `keep_alive=0` to `/api/generate`. vLLM has no manual unload — memory is automatic. Replace with a no-op log statement. |

---

## 3. How to Load Models on vLLM

### Three Model Sources

vLLM accepts these via `--model`:

**1. HuggingFace Hub ID** (recommended):
```bash
vllm serve Qwen/Qwen3-4B --served-model-name qwen3:4b
```
vLLM downloads on first start if cache misses. Set `HF_HOME` to a mounted PVC so downloads persist across pod restarts.

**2. Local filesystem path:**
```bash
vllm serve /models/qwen3-4b --served-model-name qwen3:4b
```
Useful when you have a separate model sync job (rsync, rclone) or NFS.

**3. GGUF files** (vLLM 0.4.3+, 0.5+ recommended):
```bash
vllm serve /models/qwen3-4b.gguf --served-model-name qwen3:4b
```
Requires `pip install vllm[gguf]`. Performance is lower than native safetensors. Prefer HF safetensors or AWQ quantisation over GGUF for production.

### The `--served-model-name` Aliasing Trick

```bash
vllm serve Qwen/Qwen3-4B \
  --served-model-name qwen3:4b \
  --port 8001
```

`--served-model-name` sets the model ID returned by `/v1/models` and accepted by `/v1/chat/completions`. Existing code and OpenClaw config that references `qwen3:4b` requires **zero changes**. The only mandatory name change in the backend is `DEFAULT_MODEL = "llama3.2:3b"` → `"qwen3:4b"` at `main.py` line 849.

### Installing Models — Quick Reference

```bash
# Option A: Let vLLM download on first pod start (auto via init container below)
# Nothing to do manually — just set HF_HOME to a PVC path

# Option B: Pre-download from a machine with internet access, then rsync to node
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen3-4B', cache_dir='/models-cache/huggingface')
"

# Option C: Check what's loaded in a running vLLM pod
kubectl exec -n ai-agents deploy/harvis-ai-merged-ollama-backend -c vllm -- \
  curl -s http://localhost:8001/v1/models | python3 -m json.tool
```

### Multi-Model Options

- **Separate instances (recommended):** One vLLM process per model on different ports. Simple, isolated, clean resource accounting. Current stack needs only `qwen3:4b` locally so one instance suffices.
- **vLLM 0.6+ multi-model API:** Experimental. A single server can load multiple LoRA adapters but not independent base models. True multi-model needs multiple processes behind a router. Not worth the complexity for this stack.

### Pre-Pulling Models via K8s Init Container

```yaml
- name: pull-vllm-model
  image: python:3.11-slim
  command: ["/bin/bash", "-c"]
  args:
    - |
      set -e
      pip install -q huggingface_hub
      python3 -c "
      import os
      from huggingface_hub import snapshot_download
      token = os.environ.get('HF_TOKEN') or None
      snapshot_download(
          repo_id='Qwen/Qwen3-4B',
          cache_dir=os.environ.get('HF_HOME', '/models-cache/huggingface'),
          token=token,
          ignore_patterns=['*.gguf', '*.pt'],
      )
      print('Download complete.')
      "
  env:
    - name: HF_HOME
      value: "/models-cache/huggingface"
    - name: HF_TOKEN
      valueFrom:
        secretKeyRef:
          name: harvis-ai-backend-secret
          key: hf-token
          optional: true   # Qwen3-4B is public — token not required
  volumeMounts:
    - name: ml-models-cache
      mountPath: /models-cache
  resources:
    requests: { memory: 512Mi, cpu: 500m }
    limits:   { memory: 2Gi,   cpu: 2000m }
```

Add this to `spec.initContainers[]` after the existing `download-models` container.

**HuggingFace Hub DNS note:** Some campus networks block outbound UDP port 53. Add `huggingface.co` to CoreDNS before the init container will work:
```bash
./scripts/add-dns-entry.sh huggingface.co
# dig huggingface.co @8.8.8.8 first to get the current IP
```

---

## 4. Step-by-Step Migration Plan

### Phase 1 — Add vLLM Alongside Ollama (Zero Downtime)

**Goal:** vLLM running on port 8001, verified, zero production traffic.

1. Create `hf-token` key in `harvis-ai-backend-secret` (empty string is fine for public models):
   ```bash
   kubectl patch secret harvis-ai-backend-secret -n ai-agents \
     --type=merge -p '{"stringData": {"hf-token": ""}}'
   ```

2. Add CoreDNS entry for `huggingface.co` (see above).

3. Add the `pull-vllm-model` init container to the backend Deployment (spec in Section 5).

4. Add the `vllm` sidecar container to the pod spec (full spec in Section 5).

5. Add port 8001 to the `harvis-ai-merged-backend` Service:
   ```yaml
   - name: vllm
     port: 8001
     targetPort: vllm
     protocol: TCP
   ```

6. Apply and verify:
   ```bash
   kubectl apply -f k8s-manifests/overlays/prod/merged-ollama-backend.yaml
   kubectl rollout status deploy/harvis-ai-merged-ollama-backend -n ai-agents

   # Verify vLLM is serving
   kubectl exec -n ai-agents deploy/harvis-ai-merged-ollama-backend -c vllm -- \
     curl -s http://localhost:8001/v1/models

   # Test a completion
   kubectl exec -n ai-agents deploy/harvis-ai-merged-ollama-backend -c vllm -- \
     curl -s http://localhost:8001/v1/chat/completions \
       -H "Content-Type: application/json" \
       -d '{"model":"qwen3:4b","messages":[{"role":"user","content":"say hello"}],"max_tokens":50}'
   ```

**Rollback:** Remove the vLLM container from the pod spec. Zero production impact.

---

### Phase 2 — Switch OpenClaw's Local Agent to vLLM

**Goal:** `main` OpenClaw agent uses vLLM at port 8001 instead of Ollama at 11434.

1. Update `k8s-manifests/overlays/prod/openclaw.yaml` — see exact diff in Section 6.

2. Add egress rule for port 8001 to the NetworkPolicy (keep 11434 rule until Phase 4):
   ```yaml
   - to:
       - podSelector:
           matchLabels:
             app.kubernetes.io/component: merged-ollama-backend
     ports:
       - protocol: TCP
         port: 8001
   ```

3. Apply and restart OpenClaw:
   ```bash
   kubectl apply -f k8s-manifests/overlays/prod/openclaw.yaml
   kubectl rollout restart deploy/harvis-ai-openclaw -n ai-agents
   ```

4. Test: Launch a Harvis Workspace from the UI with a simple task. Confirm `tool stream phase=start name=exec` appears in OpenClaw logs (structured tool call, not text).

**Rollback:** Revert ConfigMap change, restart OpenClaw pod.

---

### Phase 3 — Switch Main Backend Chat to vLLM

**Goal:** `/api/chat` uses vLLM's OpenAI-compat API instead of Ollama native API.

**Files to change:**

| File | What changes |
|------|-------------|
| `python_back_end/main.py` | `stream_ollama_chunks` → OpenAI SSE parser; `make_ollama_request` → httpx to vLLM; `/api/ollama-models` → `/v1/models`; `DEFAULT_MODEL`; add `VLLM_URL` env var |
| `python_back_end/vison_models/llm_connector.py` | `unload_ollama_model` → no-op; `query_llm` Ollama path → vLLM |

**Key code change — response parsing:**

Current (Ollama NDJSON, `main.py` ~lines 2606–2615):
```python
if "message" in chunk_json:
    content_chunk = chunk_json["message"].get("content", "")
```

Replacement (OpenAI SSE):
```python
# Each line from vLLM: data: {"choices":[{"delta":{"content":"..."}}]}
# or: data: [DONE]
if decoded_line.startswith("data: "):
    data_str = decoded_line[6:]
    if data_str.strip() == "[DONE]":
        break
    chunk_json = json.loads(data_str)
    content_chunk = (
        chunk_json.get("choices", [{}])[0]
        .get("delta", {})
        .get("content", "")
    ) or ""
```

**Add to backend container env:**
```yaml
- name: VLLM_URL
  value: "http://localhost:8001/v1"
```

**⚠️ Critical:** The parser change and `VLLM_URL` env var must be deployed atomically. Deploying one without the other will break all chat responses.

**Other `main.py` changes:**
- `DEFAULT_MODEL = "llama3.2:3b"` → `"qwen3:4b"` (line ~849)
- `/api/ollama-models`: Replace `/api/tags` call with `GET {VLLM_URL}/models`, parse `data[].id`
- `unload_ollama_model()`: Replace body with `logger.debug("vLLM manages memory automatically")` + `return`

**Steps:**
1. Make code changes, build and push new image.
2. Update image tag in `k8s-manifests/overlays/prod/merged-ollama-backend.yaml`.
3. Apply and test `/api/chat` end-to-end in the UI.
4. Verify `/api/ollama-models` returns `qwen3:4b` in the frontend model selector.
5. Test the `<think>` tag reasoning path — `separate_thinking_from_final_output()` is model-agnostic and unchanged.

**Rollback:** Roll back the image tag.

---

### Phase 4 — Remove Ollama

**Prerequisites:** Phases 1–3 stable, no Ollama references in logs.

1. Remove `ollama` container block from the Deployment spec.
2. Remove `ollama-model-cache` volume and volumeMount.
3. Remove port 11434 from the Service spec.
4. Remove port 11434 egress rule from the NetworkPolicy.
5. Apply all manifests.
6. Optionally delete the now-unused PVC:
   ```bash
   kubectl delete pvc ollama-model-cache -n ai-agents
   ```
7. Remove legacy env vars (`OLLAMA_URL`, `OLLAMA_API_KEY`, `OLLAMA_CLOUD_URL`) from backend ConfigMap.

---

## 5. Full vLLM Sidecar Container Spec

```yaml
- name: vllm
  image: vllm/vllm-openai:latest
  imagePullPolicy: IfNotPresent
  ports:
    - name: vllm
      containerPort: 8001
      protocol: TCP
  command: ["python3", "-m", "vllm.entrypoints.openai.api_server"]
  args:
    - "--model"
    - "Qwen/Qwen3-4B"
    - "--served-model-name"
    - "qwen3:4b"                    # Preserves existing model ID — no code changes needed
    - "--port"
    - "8001"                        # Avoids clash with harvis-backend on 8000
    - "--host"
    - "0.0.0.0"
    - "--dtype"
    - "auto"                        # Detects bf16/fp16 based on GPU capability
    - "--max-model-len"
    - "8192"                        # Qwen3-4B supports 32k but 8k is safe for 8 GB VRAM
    - "--gpu-memory-utilization"
    - "0.85"                        # Leave 15% headroom for backend Python process
    - "--enable-auto-tool-choice"   # Enable structured tool-call output ← key for OpenClaw
    - "--tool-call-parser"
    - "hermes"                      # Qwen3 uses Hermes-format tool calls
    - "--enable-chunked-prefill"    # Better latency for interactive workloads
    - "--trust-remote-code"         # Required for some Qwen model variants
    - "--disable-log-stats"         # Reduce log noise; remove to see throughput metrics
  env:
    - name: HF_HOME
      value: "/models-cache/huggingface"
    - name: TRANSFORMERS_CACHE
      value: "/models-cache/huggingface"
    - name: HF_TOKEN
      valueFrom:
        secretKeyRef:
          name: harvis-ai-backend-secret
          key: hf-token
          optional: true
    - name: VLLM_WORKER_MULTIPROC_METHOD
      value: "spawn"
    - name: TOKENIZERS_PARALLELISM
      value: "false"
  volumeMounts:
    - name: ml-models-cache
      mountPath: /models-cache
  resources:
    requests:
      memory: 8Gi
      cpu: 1000m
    limits:
      nvidia.com/gpu: 1
      memory: 24Gi
      cpu: 4000m
  livenessProbe:
    httpGet:
      path: /health
      port: 8001
    initialDelaySeconds: 120    # vLLM takes ~90s to load Qwen3-4B on first start
    periodSeconds: 30
    timeoutSeconds: 10
    failureThreshold: 3
  readinessProbe:
    httpGet:
      path: /v1/models
      port: 8001
    initialDelaySeconds: 90
    periodSeconds: 15
    timeoutSeconds: 10
    failureThreshold: 5
```

**VRAM note during Phase 1 (Ollama + vLLM coexist):** Both containers share the same GPU device. Reduce `--gpu-memory-utilization` to `0.60` during testing so they don't OOM each other. Raise back to `0.85` after Ollama is removed in Phase 4.

**First-start latency:** vLLM compiles CUDA kernels via Triton/torch.compile on the first run — can take 3–8 minutes. Subsequent starts reuse cached compilation. Set `VLLM_TORCH_COMPILE_LEVEL=0` env var to skip compilation if startup time is unacceptable during testing (costs ~15% inference speed).

---

## 6. OpenClaw Config Changes — Exact Diff

File: `k8s-manifests/overlays/prod/openclaw.yaml`, ConfigMap `openclaw-config`, key `openclaw.json`.

**Replace the `models.providers` block** (remove `ollama`, add `vllm-local`):

```json
"models": {
  "mode": "replace",
  "providers": {
    "vllm-local": {
      "api": "openai-completions",
      "baseUrl": "http://harvis-ai-merged-backend:8001/v1",
      "apiKey": "vllm-local",
      "models": [
        { "id": "qwen3:4b", "name": "Qwen3 4B (Local vLLM)" }
      ]
    },
    "harvis-proxy": {
      "api": "openai-completions",
      "baseUrl": "http://harvis-ai-merged-backend:8000/v1",
      "apiKey": "${OPENCLAW_GATEWAY_TOKEN}",
      "models": [
        { "id": "kimi-k2.5",              "name": "Kimi K2.5 (via Harvis proxy)" },
        { "id": "gpt-oss:120b",           "name": "GPT-OSS 120B (via Harvis proxy)" },
        { "id": "qwen3:235b-a22b-q8_0",   "name": "Qwen3 235B (via Harvis proxy)" }
      ]
    }
  }
}
```

**Replace `agents.defaults` and `agents.list[0]`** (update model reference):

```json
"defaults": {
  "model": { "primary": "vllm-local/qwen3:4b" }
},
"list": [
  {
    "id": "main",
    "default": true,
    "model": { "primary": "vllm-local/qwen3:4b" }
  },
  {
    "id": "kimi",
    "model": { "primary": "harvis-proxy/kimi-k2.5" }
  },
  {
    "id": "gpt-oss",
    "model": { "primary": "harvis-proxy/gpt-oss:120b" }
  },
  {
    "id": "qwen3",
    "model": { "primary": "harvis-proxy/qwen3:235b-a22b-q8_0" }
  }
]
```

**What changed:** `ollama` provider (native Ollama API, port 11434) → `vllm-local` (OpenAI-compat, port 8001). The `apiKey` is a static placeholder since vLLM doesn't enforce token auth by default. If you add `--api-key mykey` to the vLLM args, set this to match. Model IDs are unchanged because of `--served-model-name` aliasing. The `kimi`, `gpt-oss`, and `qwen3` (cloud) agents are completely untouched.

**NetworkPolicy diff:**

During Phases 2–3, keep **both** port rules:
```yaml
# OLD (keep until Phase 4)
- to: [merged-ollama-backend]
  ports: [TCP 11434]

# NEW (add in Phase 2)
- to: [merged-ollama-backend]
  ports: [TCP 8001]
```

In Phase 4, remove the port 11434 rule.

---

## 7. Risks and Gotchas

### GGUF Support

vLLM added GGUF in v0.4.3, more stable in 0.5.x. Still slower to load than safetensors (weight re-packing on first load). Some IQ adaptive quant types from llama.cpp are unsupported. Prefer AWQ quantisation from HuggingFace (`Qwen/Qwen3-4B-AWQ` if available) over GGUF if you need a smaller footprint. AWQ is first-class in vLLM, loaded natively without re-packing.

### VRAM Budget

| Component | Approximate VRAM |
|-----------|-----------------|
| `Qwen/Qwen3-4B` bfloat16 weights | ~8.5 GB |
| vLLM KV cache (at 0.85 utilization on 24 GB GPU) | ~12.4 GB reserved |
| Backend Python process (Whisper, PyTorch) | 2–4 GB (when vision model not loaded) |
| Qwen2VL vision model (when loaded) | 6–8 GB |

If vision inference (Qwen2VL) and vLLM are loaded simultaneously, VRAM contention is real. Reduce `--gpu-memory-utilization` to `0.70` if OOM errors appear. Keep Qwen2VL on CPU (conditionally loaded) and let vLLM own the GPU full-time — this is already how the backend loads vision models.

### Tool-Call Parser Selection Per Model

Wrong parser = malformed tool call JSON = OpenClaw agent failures.

| Model family | Correct `--tool-call-parser` |
|-------------|------------------------------|
| Qwen2.5, **Qwen3** | `hermes` |
| LLaMA 3.1, 3.3 | `llama3_json` |
| Mistral / Mixtral 2024+ | `mistral` |
| DeepSeek-V2.5+ | `deepseek` |

If you ever swap the local model to LLaMA 3.1, update `--tool-call-parser` in the vLLM container args and redeploy.

### Streaming Response Format Is a Hard Break

The chunk parsing in `/api/chat` (~lines 2575–2640 of `main.py`) is tightly coupled to Ollama's NDJSON format. If you deploy vLLM before updating the parser, every `/api/chat` call will silently return empty responses. Deploy the parser change and `VLLM_URL` env var in the **same image push**.

### `DEFAULT_MODEL` Constant

`DEFAULT_MODEL = "llama3.2:3b"` at `main.py` line 849 is the fallback when no model is selected. `llama3.2:3b` won't exist in vLLM after migration. Change to `"qwen3:4b"` as part of Phase 3.

### `CLOUD_OLLAMA_URL` in ConfigMap

`k8s-manifests/base/configmaps.yaml` has a `OLLAMA_CLOUD_URL: "http://harvis-ai-ollama:11434"` entry in `harvis-ai-backend-config`. This appears to be a legacy entry for a standalone Ollama service that no longer exists. Remove in Phase 4 cleanup after confirming `CLOUD_OLLAMA_URL` in `main.py` (user settings model) has no active code path.

### HF_TOKEN for Gated Models

`Qwen/Qwen3-4B` is not gated — no token required. The `optional: true` on the secret key is defensive and allows pulling gated models in the future (LLaMA 3, Gemma) without restructuring the secret.

### DNS Resolution on Networks That Block DNS

Outbound UDP port 53 is blocked on the cluster. The init container needs to resolve `huggingface.co`. Run before first deployment:
```bash
# Find current HuggingFace IP
dig huggingface.co @8.8.8.8

# Add to CoreDNS
./scripts/add-dns-entry.sh huggingface.co
```

Alternatively, if there's no internet at all: pre-stage the model on the NFS volume from a machine with internet access, then use `--model /nfs/models/qwen3-4b` (local path) in the vLLM args.

---

## Critical Files Summary

| File | What to change |
|------|---------------|
| `k8s-manifests/overlays/prod/merged-ollama-backend.yaml` | Add `pull-vllm-model` init container; add `vllm` sidecar container; add port 8001 to Service |
| `k8s-manifests/overlays/prod/openclaw.yaml` | ConfigMap: replace `ollama` provider with `vllm-local`; update `main` agent model ref; NetworkPolicy: add port 8001 egress, remove 11434 in Phase 4 |
| `python_back_end/main.py` | `stream_ollama_chunks` response parser; `make_ollama_request` → httpx to vLLM; `/api/ollama-models` → `/v1/models`; `DEFAULT_MODEL`; add `VLLM_URL` env var |
| `python_back_end/vison_models/llm_connector.py` | `unload_ollama_model` → no-op; `query_llm` Ollama path → vLLM |
| `k8s-manifests/storage/pvcs.yaml` | Possibly expand `ml-models-cache` to 50 Gi (Qwen3-4B safetensors = ~7.6 GB + existing Whisper/TTS) |
