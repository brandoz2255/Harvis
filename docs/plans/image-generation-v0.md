# Harvis Local Image Generation — v0 design (2026-07-10)

**Status:** ✅ SHIPPED + verified E2E (2026-07-10). Backend built (`python_back_end/image/`), ComfyUI
provider stood up (`harvis-comfyui` container, SD1.5, --lowvram), flag on, 2 real images generated through
`/api/harvis/image/generate` → artifact preview. REMAINING: a user-facing trigger (API-only today). See
memory `project_image_generation_v0`.

## 1. Goal / non-goals
- **Goal:** give Harvis a real, local "make me an image" path that reuses the judgment layer already
  built (jobs, artifacts, trace, tool policy, provider readiness, skill learning) — without making
  Harvis own the model runtime.
- **Non-goals (v0):** no img2img/inpaint/upscale, no ControlNet/LoRA UI, no image-to-3D wiring (that's
  a separate mock→real track in `adaptive_space.py`), no in-process Diffusers.

## 2. Ground truth (verified 2026-07-10)
- Image gen gated off: `owui_compat/config.py` `enable_image_generation: False`; capability
  `owui_compat/translate.py` `image_generation: False`.
- Image-**to-3D** is scaffolded but MOCK: `owui_compat/workspace_methods/fabrication.py`,
  `owui_compat/adaptive_space.py` "image-to-3d" exemplar, `workspace_methods/general.py` pack.
- **No provider installed**: `:8188` (ComfyUI) and `:7860` (A1111) both closed; only `harvis-ollama` runs.
- **GPU: RTX 5070 Laptop, 8 GB VRAM** (modern/fast, but 8 GB caps model size).

## 3. Provider decision
- **Primary: ComfyUI** — its JSON workflows are reusable graphs that map 1:1 onto Harvis skills; the
  "run → judge → save workflow as draft skill" loop is native. Cost: must drive prompt-graph JSON +
  node ids.
- **Fallback: A1111 / Forge** — dead-simple REST (`POST /sdapi/v1/txt2img`); Forge is the low-VRAM fork.
- **Decision: one `ImageProvider` interface, ComfyUI behind it as primary, A1111 as a drop-in fallback.**
  Harvis uses whichever reports `ready`. First working generation must NOT depend on perfect graph JSON.
- Fooocus (opaque to agents) and Diffusers-in-process (whole model stack inside Harvis) are deferred.

## 4. `ImageProvider` interface (new: `python_back_end/image/provider.py`)
```python
class ImageProvider(Protocol):
    id: str                       # "comfyui" | "a1111"
    async def readiness(self) -> dict          # {ready, url, reason, capabilities: [...], models: [...]}
    async def txt2img(self, spec: GenSpec) -> str   # returns a job_id (runs in the background)
    async def status(self, job_id) -> dict     # {state, progress, preview?, error?}
    async def result(self, job_id) -> bytes     # final PNG bytes (→ artifact)

@dataclass
class GenSpec:                    # ONLY safe fields Harvis fills in
    prompt: str; negative_prompt: str = ""
    width: int = 1024; height: int = 1024
    steps: int = 20; cfg: float = 6.0; seed: int | None = None
    model: str | None = None; workflow: str = "basic_txt2img"
```
- ComfyUI impl: loads a **locked workflow JSON** (`image/workflows/basic_txt2img_sdxl.json`), patches only
  the whitelisted fields, POSTs `/prompt`, polls `/history/{id}` + WS `/ws`, fetches the PNG via `/view`.
- A1111 impl: single `POST /sdapi/v1/txt2img`, base64 PNG out. ~30 lines.

## 5. v0 scope (smallest solid slice)
1. **Readiness** — add an `image` provider to `workspace/harvis_readiness.py` `/api/harvis/providers`
   (probe `:8188` then `:7860`; report ready/missing/unreachable + capabilities + installed models).
2. **One locked workflow** — `basic_txt2img_sdxl.json` (or SD1.5 for 8 GB), whitelisted fields only.
3. **`POST /api/harvis/image/generate`** (new small router `image/harvis_image.py`) — auth'd, validates
   `GenSpec`, gated on `enable_image_generation` + provider `ready` + tool policy.
4. **Runs as a background job** — reuse `workspace/harvis_jobs.py` / `terminal_container.exec_bg` so chat
   isn't blocked; stream progress as trace events.
5. **Save the PNG as an artifact** — reuse `_db_save_artifact(..., content_bytes=png)` (E2 binary path)
   → `/artifact/{id}/raw`.
6. **Preview in the right rail** — REUSE what shipped today: the generated PNG previews via the same
   right-side Artifacts panel the sandbox-file preview uses (`ContentRenderer` linkify → rail).
7. **"Save workflow as draft skill"** — reuse `workspace/skill_extractor.py`
   (`/api/harvis/runs/{id}/save-as-skill`); draft-only, human `supported` verdict required (invariant).

## 6. Data flow (all existing infra)
```
user request → tool policy (image.generate exposed iff ready+allowed)
  → /api/harvis/image/generate  (validate GenSpec)
  → ImageProvider.txt2img → background job (E1)  →  trace: progress events
  → PNG bytes → _db_save_artifact(content_bytes) (E2)  →  artifact event
  → right-rail preview (today's mechanism)  →  optional: judge → save workflow as draft skill (F)
```

## 7. GPU / lane strategy (8 GB, reuse desktop-preferred routing)
- **Local on the 5070:** SD 1.5, SDXL-Turbo, Flux-schnell (GGUF) — fast.
- **Dev rig:** full SDXL / Flux-dev — route via the existing `_prefers_desktop()` /
  `HARVIS_DESKTOP_PREFERRED_MODELS` mechanism. Readiness reports honestly when a model needs the rig.

## 8. API surface (new)
- `GET /api/harvis/providers` → gains `{kind:"image", id:"comfyui|a1111", ready, url, capabilities, models}`.
- `POST /api/harvis/image/generate` → `{job_id}`.
- `GET /api/harvis/image/{job_id}` → status; `GET .../result` → artifact id.
- Config: flip `enable_image_generation` per-user/flag when a provider is ready (not globally).

## 9. Prerequisite / open decision (blocks the build)
No provider is installed. To build **and verify**, pick one:
- (a) I add a ComfyUI service to docker-compose (GPU passthrough + a small model + 1 workflow).
- (b) A1111/Forge first (fastest working generation), ComfyUI primary after.
- (c) You install ComfyUI and give me the URL.

## 10. v1 (after v0 works)
img2img · upscale · inpaint · style presets · prompt-improve · multi-seed + compare · ComfyUI workflow
library · local VLM/CLIP result scoring (auto-judge) · then connect the image-**to-3D** mock stages.

## Invariants
Skills stay text-only + human-gated; `authorize_action` is the only dispatch authority; provider
readiness is honest (never silent 503); image gen is a WORKSPACE/background lane, never the chat lane.
