# Ollama runs 59% on the CPU — and it is not a device-selection bug

**Status:** diagnosed 2026-08-05, **not fixed**. Nothing in this document has been applied.
**Symptom as reported:** "ollama is getting my AMD CPU as the main and not my 5070 first."
**What is actually happening:** Ollama detects the RTX 5070 over CUDA and uses it. It then puts most
of the model on the CPU because the model does not fit in the VRAM that is free.

---

## The correction that matters

The GPU is found. From `docker logs harvis-ollama`:

```
library=CUDA  id=GPU-a395fa2c-…  name="NVIDIA GeForce RTX 5070 Laptop GPU"  total="8151 MiB"
sched.go:491  msg="gpu memory"  library=CUDA available="3.3 GiB" free="4.3 GiB" minimum="457.0 MiB"
device.go:245 msg="model weights" device=CPU size="3.3 GiB"
device.go:256 msg="kv cache"     device=CPU size="1.1 GiB"
load_tensors: offloaded 8/33 layers to GPU
llama_kv_cache: CPU KV buffer size = 1224.00 MiB
```

```
$ docker exec harvis-ollama ollama ps
NAME         ID            SIZE    PROCESSOR         CONTEXT  UNTIL
llama3.1:8b  46e0c10c039e  8.0 GB  59%/41% CPU/GPU   24576    Forever
```

Eight of thirty-three layers land on the GPU. The other twenty-five, plus the entire KV cache, run
on the CPU. So the AMD CPU carrying the load is the **consequence**; the cause is that only 3.3 GiB
was available on an 8 GB card when the model asked for roughly eight.

Chasing this as a device-selection problem — reinstalling drivers, setting `CUDA_VISIBLE_DEVICES`,
adding `--gpus all` — will change nothing, because none of those are broken.

---

## Why it does not fit

The card is a **laptop** RTX 5070: **8151 MiB total**, driver 580.159.03. Not the 12 GB desktop part.

At the moment of measurement, 5186 MiB were in use and 2496 MiB free. The holders:

| Process | VRAM | What it is |
|---|---:|---|
| `/usr/bin/ollama` | 2386 MiB | the 8 layers it did manage to offload |
| `python3 -m tts_system.server` | 788 MiB | **Harvis's own TTS stack** |
| `brave --type=gpu-process` | 512 MiB | browser |
| `Discord --type=gpu-process` | 184 MiB | chat |
| `python3 ./main.py --port 8188 --lowvram` | 128 MiB | ComfyUI, already in lowvram |
| `cosmic-app-library` | 70 MiB | desktop shell |
| `cosmic-term` | 46 MiB | terminal |
| `xdg-desktop-portal-cosmic` | 34 MiB | desktop shell |

Roughly **1.76 GB is held by things that are not the LLM**, and the single largest of those is
Harvis's own voice stack. The assistant is competing with itself for the same 8 GB.

The model itself is **already Q4_K_M** (`ollama show llama3.1:8b`: 8.0B parameters, Q4_K_M), so
"use a smaller quant" is not available — weights are about as small as they get for this model.
The `8.0 GB` in `ollama ps` is the resident footprint at a 24576-token context, not the file size.

The environment on the container:

```
OLLAMA_CONTEXT_LENGTH=24576      OLLAMA_KV_CACHE_TYPE=q8_0
OLLAMA_KEEP_ALIVE=-1             OLLAMA_GPU_OVERHEAD=536870912   (512 MiB reserved)
OLLAMA_FLASH_ATTENTION=1         OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_NUM_PARALLEL=1            OLLAMA_HOST=0.0.0.0:11434
NVIDIA_VISIBLE_DEVICES=all
```

`OLLAMA_CONTEXT_LENGTH=24576` is the one to look at first: it produces a **1224 MiB KV cache** even
at `q8_0` quantization. That cache is the difference between fitting and not fitting.

---

## Structural gotcha before anyone edits a file

**`harvis-ollama` is not in `docker-compose.yaml`.** The core trim deleted the `ollama:` service
(checklist item A3); the container now runs standalone — started 2026-08-02, `restarts=0` — and
Harvis reaches it through `HARVIS_LLM_BASE_URL`.

Consequences:

- Editing `docker-compose.yaml` will not change this container. There is no service block to edit.
- `docker compose up -d ollama` does not exist as a path here.
- Any environment change means recreating the standalone container with the new `-e` flags, or
  re-adding a compose service and migrating the model volume to it.

Confirm before changing anything:

```bash
docker inspect harvis-ollama --format '{{json .Config.Env}}' && docker inspect harvis-ollama --format '{{.HostConfig.Binds}}'
```

---

## Levers, most effective first

None of these have been applied. Each is a trade, not a free win.

1. **Lower `OLLAMA_CONTEXT_LENGTH` from 24576 to 8192.** The KV cache scales linearly with context,
   so this drops roughly 1224 MiB to roughly 408 MiB — about 800 MiB back, which is most of the gap.
   Cost: shorter conversations and smaller documents per turn. Measure the layer split afterwards
   (`ollama ps` should move well above 41% GPU) before deciding whether 8192 is enough or too tight.
2. **Reclaim the 788 MiB the TTS server holds.** It is Harvis's own process. Either run it on CPU,
   or stop it when it is idle. Nothing else on the list is this large or this much ours to control.
3. **Close Brave and Discord while running local inference** — about 700 MiB between them. A manual
   habit, not a fix, but it is free and immediate.
4. **Reduce `OLLAMA_GPU_OVERHEAD` from 512 MiB.** It exists to stop the GPU running dry mid-inference;
   lowering it trades safety margin for capacity. Try it only after 1 and 2, and watch for CUDA OOM.
5. **Accept a smaller default model for the box.** `qwen3:4b` and `gemma4:e4b` fit comfortably where
   an 8B at a long context does not. This is the honest option if the 8 GB ceiling stays.

`OLLAMA_KEEP_ALIVE=-1` pins the model in memory forever. That is correct once the fit is right and
counterproductive while it is wrong — a badly-fitting model never gets evicted.

---

## How to tell whether a change worked

Do not trust the absence of an error message. Check the split directly:

```bash
docker exec harvis-ollama ollama ps
```

`PROCESSOR` should read mostly or entirely `GPU`. Then confirm the layer count in the logs:

```bash
docker logs harvis-ollama --tail 200 2>&1 | grep -E "offloaded|model weights|kv cache"
```

`offloaded 33/33 layers to GPU` is the target. Anything less is a partial fit, and the difference
shows up as tokens per second.

---

## Related

- The dev box has 8 GB of VRAM, and this is the concrete reason it constrains model choice — the
  same constraint named in the CAD Gate 7B stop rule (`docs/handoffs/2026-08-04-gate7a-cadir-executable.md`).
- `HARVIS_LLM_BASE_URL` is the canonical pointer to this engine (checklist item A5).
