# Local CAD — Gate 0 baseline, Gate 1A hardening

**Date:** 2026-08-03 · **Branch:** `harvis1.2` @ `095678a5`

Sections 1–9 are the frozen "before" record, taken with **nothing modified**. Sections 10–15 are
Gate 1A, measured after the hardening landed. Everything in both halves was measured against the
running `harvis-cad` sidecar, not read from configuration or inferred from source. Gate 1B is
accepted or rejected by comparing against these numbers.

Gate 0's stop condition — *"the two paths disagree on geometry"* — **did not trigger**. Both the
raw sidecar contract and the `fab_cad` controller produce byte-identical STL and identical
metadata for the same input.

---

## 1. The headline correction

The plan's central risk was recorded as *"a single `NaN` parameter hangs the worker past the
backend's timeout."* That was directionally right and specifically wrong in three ways, all now
measured.

**What actually happens.** A `NaN` in `arm_len_mm` makes the worker burn 1–2 CPU cores for
**45.91 seconds**, then return an honest `500`:

```
cad execution failed: [Errno 2] No such file or directory: '/tmp/cad_2jmv3xtk/part.stl'
```

OpenCascade produces a shape it cannot tessellate, `export_stl` writes no file, and `open()` fails.
The server's honest-500 path works exactly as designed. **It is not an infinite hang, and it does
not leak memory** — resident memory stayed flat at ~385 MiB for the entire 46 seconds.

**But it freezes the whole worker, not just its own request.** `GET /health` — which does nothing
but return a dict — **took 43.269 seconds** to answer while the `NaN` build ran. Every other
request was starved for the duration. The cause is the GIL: OCP holds it through the native
OpenCascade call, so FastAPI's 40-slot threadpool is irrelevant. **One malformed request is enough
to take the worker down. It does not take forty.**

**And Harvis gives up 16 seconds before the worker recovers.** `fab_cad.execute()` uses a 30 s
httpx timeout. The build runs 46 s. From the backend's side the request fails with no explanation
at t=30 s, and the worker stays frozen until t=46 s — so the *next* user request is also starved,
by a build nobody is waiting for any more.

CPU trace, sampled from the container cgroup at 1 s cadence (the `NaN` request was fired at t=0):

| t (s) | CPU % | RSS (MiB) | |
|---|---|---|---|
| 1–11 | 163–200 | 384.5–385.3 | two cores — OCCT's parallel mesher |
| 12–46 | ~100 | 384.5–387.2 | one core, sustained |
| 47 | 63.9 | 387.6 | build ends, `/health` finally answers |
| 48+ | 0.1–0.2 | 387.3–388.9 | fully recovered |

**Consequences for the plan.** All three reinforce the Gate 1A / 1B split rather than changing it,
but two specific claims in the plan need correcting:

- *"40 bad requests exhaust the pool"* → **one** does. The GIL is the bottleneck, not the pool.
- *"2 GB `mem_limit` contains it"* → it does not. Memory is flat; this is a pure CPU/GIL stall.
  Gate 1A's `cpus: 2.0` bounds the blast radius on the host, but **only Gate 1B's killable
  subprocess actually stops it** — and a subprocess also removes the GIL coupling entirely, which
  is a second, unplanned benefit worth stating: `/health` stays answerable during a runaway build.

### Related findings from the same probe

**`Infinity` is not slow.** On a quiet worker it returns `200` in **0.11 s** with `bbox
506×40×44`, because `min(inf, 500)` is `500` and the clamp holds. An earlier reading of 20.9 s was
this request queued behind a `NaN` build's GIL, not a property of `Infinity`. `min`/`max` clamp
`inf` correctly; they only fail on `NaN`.

**A strict JSON client cannot send `NaN`.** `httpx`'s `json=` kwarg raises `ValueError` locally at
0.00 s — the request never leaves. The literal `NaN` token only crosses the wire in a hand-built
raw body, which Python's `json.loads` accepts and Pydantic v2 passes through because
`allow_inf_nan` defaults to on. **The worker-side schema fix is still required** — Harvis is not
the only thing that can post to that socket, and `fab_cad` is one refactor away from forwarding a
float it did not construct.

**Negatives are already safe.** `arm_len_mm: -50` returns `200` in 0.07 s with `bbox 16×40×44` —
the clamp floors it to 10. No hang, no error. This is the one malformed input the current code
handles correctly.

**Unknown keys are silently ignored.** `{"nonexistent_key": 1}` returns the default part with
`200`. Confirms the missing `extra="forbid"`.

**`ps` is not installed in `harvis-cad`.** `command -v ps` → `MISSING`. The plan's Gate 1B
verification step (`docker exec harvis-cad sh -c 'ps -eo pid,ppid,pgid,etime,comm'`) **will not
run as written.** `/proc` is mounted and readable, so process-survival checks must parse
`/proc/<pid>/stat` instead — or the test asserts from inside the Python process that owns the
children.

---

## 2. Geometry baseline

Measured in-worker against the same `recipes.RECIPES["helmet_hanger_v1"]` function the sidecar
calls, using `BRepCheck_Analyzer`, `BRepGProp.SurfaceProperties_s` / `VolumeProperties_s`, and
`TopExp_Explorer(shape, TopAbs_SOLID)`. **Surface area, solid count, centre of mass and B-Rep
validity are all measurable today and none of them appear in the `meta` the sidecar returns.**

| Metric | `{}` (defaults) | `{"arm_len_mm": 90}` (golden) |
|---|---|---|
| `brep_valid` | `true` | `true` |
| `solid_count` | 1 | 1 |
| `volume_mm3` | 21582.6902 | **20622.6902** |
| `surface_area_mm2` | 9237.7964 | **8837.7964** |
| `bbox_mm` (x,y,z) | 106 × 40 × 44 | **96 × 40 × 44** |
| `center_of_mass_mm` | (34.5175, −0.0, 1.0408) | **(30.5848, 0.0, 1.0893)** |
| STL | 65484 B | **65484 B** |
| STEP | 51998 B | **51988 B** |

**The golden probe is `{"arm_len_mm": 90}`.** Its STL SHA-256 is the regression anchor:

```
4481225fce2ee78ec37535848f38fd21fc2754f696be55cbce68c802fe060f85
```

Stable across every run in this session. **STEP's hash is not** — three runs of identical input
gave `4ee0da4f…`, `8c0b6054…`, `ef110e2b…`, because `FILE_NAME(...)` embeds a wall-clock timestamp.
This is the measurement that killed the byte-identity acceptance criterion; Gate 2 compares
canonical source hashes and geometry instead.

---

## 3. Both paths agree

| | Path A — raw sidecar | Path B — `fab_cad` controller |
|---|---|---|
| Entry | `POST http://harvis-cad:8000/cad/execute` | `fab_cad.params_from_meta({"crit_arm_length_mm": 90})` → `fab_cad.execute()` |
| Resolved params | `{"arm_len_mm": 90}` | `{"arm_len_mm": 90.0}` |
| `meta` | `bbox [96,40,44]`, `volume 20622.7`, `step true` | identical |
| STL sha256 | `4481225f…fe060f85` | identical |
| Latency | 0.0712 s | 0.0593 s |

`paths_agree_on_geometry: true`. The controller adds clamping and key mapping and changes nothing
about the geometry.

---

## 4. Frozen wire contract

**Hop 1 — backend → sidecar** (`cad-engine/server.py:38`). This shape is frozen; Gate 3 adds
`/cad/v2/build` beside it rather than changing it.

```jsonc
// request
{ "recipe": "helmet_hanger_v1", "params": { "arm_len_mm": 90 }, "step": true }
// response  (200)
{ "ok": true,
  "meta": { "recipe": "helmet_hanger_v1", "bbox_mm": [96.0, 40.0, 44.0],
            "volume_mm3": 20622.7, "step": true },
  "stl_b64":  "<87312 chars>",     // 65484 B  → +33.3 % base64 inflation
  "step_b64": "<69320 chars>" }    // 51988 B  → +33.3 %
// response  (400) unknown recipe   ·  (500) "cad execution failed: <exception text>"
```

The 500 detail currently interpolates the raw exception, which is how the tempdir path
`/tmp/cad_2jmv3xtk/part.stl` leaked into the `NaN` response above. **Gate 1A's structured
error codes must close that** — it is a real (if low-value) path disclosure.

**Hop 2 — sidecar → backend → disk.** `fab_cad.py:97-98` decodes base64 **server-side**; the
browser never sees it. Bytes land at
`$ARTIFACT_STORAGE_DIR/adaptive/<user_id>/<space_id>/<rid>.<ext>` with `ARTIFACT_STORAGE_DIR =
/data/artifacts`, and `adaptive_space.py:656-658` **deletes the previous mesh/step on every
build** — the destructive write that makes revisions impossible today.

**`fab_cad.execute()` does not check the feature flag.** Only the route at
`adaptive_space.py:627` does. That is why this session could exercise Path B with the flag empty,
and it is why §8 of the plan requires `require_cad_enabled()` on every new route.

---

## 5. Resource limits: none

Read from the daemon (`docker inspect harvis-cad --format '{{json .HostConfig}}'`), not from YAML.
Saved verbatim at `/tmp/cad-hostconfig-baseline.json`.

| Key | Now | Gate 1A target |
|---|---|---|
| `Memory` | `0` | `2147483648` (2 g) |
| `MemorySwap` | `0` | set with `Memory` |
| `NanoCpus` | `0` | `2000000000` (2.0) |
| `CpuQuota` / `CpuShares` | `0` / `0` | — |
| `PidsLimit` | `null` | `128` |
| `ReadonlyRootfs` | `false` | `true` |
| `CapDrop` / `CapAdd` | `null` / `null` | `[ALL]` / `null` |
| `SecurityOpt` | `null` | `[no-new-privileges:true]` |
| `Tmpfs` | `null` | `/tmp` 512 m `noexec,nosuid,nodev` |

**Already correct, and must be preserved:** `Privileged false` · `Binds null` (no host mounts, no
docker socket) · `NetworkMode harvis_cad-internal` · `User appuser` (uid 1001) · no `ports:` ·
`profiles: ["cad"]` · in-worker `create_connection(('1.1.1.1', 443))` → `OSError`, so no external
egress. Note the precise claim: `internal: true` blocks external routing; **sibling containers on
`cad-internal` remain reachable.** The worker's safety rests on having no secrets, no socket and
no binds — not on being unreachable.

Container: `running`, started `2026-07-31T04:26:36Z`, **0 restarts**.

---

## 6. Peak RSS, sampled during execution

Host-side sampler on `/sys/fs/cgroup/system.slice/docker-<CID>.scope/memory.current` at 5 ms
cadence, running for the lifetime of each build. Idle readings would have been useless for sizing
`mem_limit`; these are transient high-water marks.

| Case | Peak RSS | Latency | Geometry |
|---|---|---|---|
| idle | 396,345,344 B (378.0 MiB) | — | — |
| golden `{arm_len_mm: 90}` | 400,785,408 B (**382.2 MiB**) | 0.0861 s | bbox 96×40×44 |
| **max clamped** | 405,667,840 B (**386.9 MiB**) | 0.1175 s | bbox 540×300×340, vol 7,607,964.6 mm³, STL 166684 B, STEP 69035 B |

"Max clamped" sets every parameter to its ceiling: `arm_len 500`, `arm_w 80`, `arm_h 80`,
`plate_t 40`, `plate_w 300`, `plate_h 300`, `hook_h 150`, `fillet_r 20`, `screw_d 20`,
`screw_count 6` — the largest part the current clamps permit.

**A build costs ~10 MiB over the loaded-OCP baseline.** The 2 GB ceiling is generous headroom, not
a tight fit. Gate 2's brick benchmark sets the final number; nothing here suggests it needs to be
larger.

---

## 7. Versions and image

Do not bump these. OCP 7.9 removes `TopoDS.HashCode` and breaks build123d 0.11.x.

```
python 3.11.15 · build123d 0.9.1 · cadquery-ocp 7.8.1.1.post1
fastapi 0.139.0 · pydantic 2.13.4 · uvicorn 0.50.0
```

`GET /health` → `{"ok": true, "recipes": ["helmet_hanger_v1"]}`

Image `harvis-cad:local` — **418,283,460 B (0.42 GB)**. Profile-gated, so it does not count against
the default set, and it is far too small to threaten the 7.5 GB CI guard. The plan's suggestion to
measure it against that guard can be dropped.

---

## 8. The two switches

**Switch 1 — backend feature flag.** `HARVIS_ADAPTIVE_CAD_ENABLED` is present and **empty**;
`HARVIS_ADAPTIVE_CAD_URL = http://harvis-cad:8000`. Wired at `docker-compose.yaml:363-365`, read by
`fab_cad.cad_enabled()` against `_TRUTHY = {"1","true","yes","on"}`. Compose bakes `environment:`
at container **create**, so flipping it requires a recreate, not a restart:

```bash
HARVIS_ADAPTIVE_CAD_ENABLED=1 docker compose up -d backend
```

**Switch 2 — the frontend host.** `front_end/owui/src/routes/(app)/harvis/adaptive/+page.svelte`
renders a "coming soon" placeholder; `AdaptiveSpaceShell` is never mounted. Its own header records
the 2026-07-12 deployment cut and the two steps to restore it. The approved plan does not reopen
this route — CAD Studio lands as a new ChatControls tab, and Gate 6 revisits `/harvis/adaptive` as
the "Expand" target.

Neither switch is a real gate. Hiding a route disables no API, and `fab_cad.execute()` ignores the
flag entirely. Server-side `require_cad_enabled()` on every `/api/cad` route is what makes the lane
actually off.

---

## 9. Gate 0 verdict

**Pass.** Both paths agree on geometry; the baseline records measurements rather than only hashes;
peak RSS is a sampled maximum taken during execution.

Carried into Gate 1A and 1B as corrections to the approved plan:

1. The `NaN` failure is a **~46 s whole-worker freeze from GIL retention**, self-terminating with
   an honest 500 — not an unbounded hang, and not memory-bound. One request, not forty.
2. `mem_limit` does not mitigate it. Only Gate 1B does, and a subprocess additionally decouples
   `/health` from geometry work.
3. `Infinity` and negative values are already handled correctly. **`NaN` is the only numeric input
   that breaks the clamps**, which narrows what Gate 1A's `_finite()` coercer must catch.
4. `ps` is absent from the container; Gate 1B's process-survival assertions must read `/proc`.
5. The 500 handler interpolates raw exception text and has already leaked a tempdir path.
6. The image is 0.42 GB — no CI size concern.

Not resolved here, and not blocking: whether `read_only: true` breaks an OCCT cache path outside
`/tmp` (Gate 1A's golden-hanger test answers it), and the subprocess startup cost that Gate 1B
must measure before anyone proposes a warm pool.

---

# Gate 1A — reject bad input, cap the container

**Date:** 2026-08-03 · image rebuilt, `harvis-cad` recreated · **34/34 tests pass.**
Every number below was read from the running container, not from the YAML or the source.

## 10. Effective limits, read from the daemon

`docker inspect harvis-cad --format '{{json .HostConfig}}'`, against §5's all-zero baseline:

| Key | Before | After |
|---|---|---|
| `Memory` | `0` | `2147483648` (2 GiB) |
| `NanoCpus` | `0` | `2000000000` (2.0) |
| `PidsLimit` | `null` | `128` |
| `ReadonlyRootfs` | `false` | `true` |
| `CapDrop` | `null` | `["ALL"]` |
| `SecurityOpt` | `null` | `["no-new-privileges:true"]` |
| `Tmpfs` | `null` | `/tmp` 512m + `/home/appuser/.cache` 32m, both `noexec,nosuid,nodev` |
| `Privileged` / `Binds` | `false` / `null` | unchanged |

Enforcement confirmed, not just declared: `touch /app/x` → `Read-only file system`; `id` → `uid=1001`;
`socket.create_connection(("1.1.1.1", 443))` → `OSError`, so egress isolation survived `cap_drop: ALL`.

These are top-level Compose keys. `deploy.resources` would have been silently ignored outside Swarm
and every row above would still read zero.

## 11. Rejection latency, over real HTTP

From `harvis-backend` on `cad-internal` — a raw body, because a strict client cannot emit a literal
`NaN`. A background thread polled `/health` throughout.

| Payload | Before | After | `error_code` |
|---|---|---|---|
| `NaN` | **45.91 s CPU, 500** | **0.005 s** | `invalid_request` |
| `Infinity` | 0.11 s, 500 | 0.002 s | `invalid_request` |
| `-50` | 200 — **silently built a 10 mm arm** | 0.001 s | `param_out_of_range` |
| `arm_length_mm` (typo) | 200 — **silently built the default part** | 0.001 s | `unknown_param` |
| unknown recipe | 400 | 0.001 s | `unknown_recipe` |
| `true` as a length | 200 — **1 mm** | 0.001 s | `invalid_request` |
| extra top-level field | 200 — ignored | 0.001 s | `invalid_request` |
| 70 KB body | parsed | 0.000 s | `body_too_large` (413) |

**`/health` during that run: 13 ms worst case, 4 ms mean.** Gate 0 measured it blocked for 43.269 s
behind a single `NaN`. That is the whole point of this gate.

The four rows marked *silently* are the ones worth remembering. The `NaN` freeze was the loud
failure; a typo'd parameter returning `200 OK` with the wrong solid is the quiet one, and it would
have shipped wrong parts.

## 12. No geometry regression

Golden hanger (`arm_len_mm: 90`) through `fab_cad`, under the hardened container:

```
stl   65484 B   sha256 4481225fce2ee78ec37535848f38fd21fc2754f696be55cbce68c802fe060f85
step  51988 B
meta  bbox [96.0, 40.0, 44.0]   volume 20622.7
new   brep_valid=True  solids=1  volume 20622.6902  area 8837.7964  watertight=True
```

Byte-identical to §2. `read_only: true` broke nothing; the only casualty was an `ezdxf` font-cache
warning at import, fixed with a 32 MB tmpfs rather than by giving back the read-only rootfs.

Peak memory across the whole session, from the container's own cgroup: **482,840,576 B (460.5 MiB)
against a 2 GiB ceiling — 22% used.**

## 13. The cost model was wrong, and the tests caught it

First version of `estimate_cost` charged **bounding volume**. Scoring the worst request the declared
bounds permit gave **807.6 against a cap of 250** — admission control refusing a request the
parameter ranges explicitly allow. It was inert in the request path only because nothing had
reached it yet.

The comment above it claimed that case "measures ~3.4". I had written the number without computing
it; it was off by 240×.

Volume is simply the wrong quantity. Measured across the legal range:

| | default | max-clamped | ratio |
|---|---|---|---|
| bounding volume | — | — | **385×** |
| build time | 0.032 s | 0.040 s | 1.25× |
| triangles | 1308 | 3332 | 2.5× |
| peak RSS | 429 MiB | 441 MiB | 1.03× |

Surface area drives tessellation, so the estimator now sums the primitives' face area, normalised
against the spec's own defaults (derived, not pasted, so a changed default cannot silently rescale
every stored estimate). Default = 1.000, worst legal = 48.7, cap = 150.

**Stated plainly: for this recipe admission control can never fire.** The per-parameter bounds
already cap the work. It is a backstop, and it earns its place at Gate 2, where the studded brick's
stud count multiplies boolean operations without any single parameter looking unreasonable — where
it must be recalibrated against measured builds rather than guessed again.

## 14. Deliberate behaviour changes

- **Out-of-range now rejects instead of clamping.** Baseline `-50` produced a part. A silently
  resized object is worse than an error a caller can fix.
- **Unknown parameter names reject** rather than being ignored.
- **500 bodies carry `type(e).__name__` only.** §9 item 5 recorded this handler leaking
  `/tmp/cad_2jmv3xtk/part.stl`; a test now scans every error body for `/tmp`, `/app` and
  `cad_[a-z0-9]{6,}`.
- **`fab_cad` raises `CadError`** carrying the sidecar's structured code. Verified that
  `param_out_of_range` and `unknown_param` reach the caller with **no host name and no port** —
  `httpx.HTTPStatusError.__str__` would have put `http://harvis-cad:8000` into a user-facing 502.
- Response gains `params` (every resolved value, including defaults the caller never supplied) and
  `validation`. `meta`, `stl_b64` and `step_b64` keep the frozen §4 shape.

## 15. Gate 1A verdict

**Pass**, against every criterion in the approved plan: limits read from the daemon and non-zero;
golden geometry unchanged under `read_only`; `NaN`, `Infinity`, negatives and unknown keys each
structured-400 in **under 5 ms** against a 1 s budget; no geometry failure returns `ok: true`; peak
RSS recorded and far under the ceiling.

**What this gate does NOT do, and must not be read as doing:** a build that has started still cannot
be stopped. OCP holds the GIL through native OpenCascade calls, so any runaway that gets past input
validation still starves the worker exactly as the `NaN` did. Gate 1A removed the one known trigger;
it did not remove the mechanism. **CAD stays unreachable until Gate 1B proves hard process
termination.**

Carried into Gate 1B:

1. `-NaN` never reaches the schema — Python's JSON scanner special-cases the bare tokens `NaN`,
   `Infinity`, `-Infinity` and nothing else, so it dies as a decode error one layer earlier.
2. A `pytest` cache is another write to a read-only rootfs; the suite runs with
   `-p no:cacheprovider`.
3. `read_only: true` is survivable, but each new library may want its own cache dir. Check the logs
   after adding one rather than assuming silence.
4. The cost estimator is now honest about being inert. Do not let Gate 2 quietly re-derive a cap
   from a formula nobody measured.
