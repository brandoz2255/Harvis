# 2026-08-03 — Local CAD: the dark lane, measured, capped, and finally stoppable

**Branch:** `harvis1.2` @ `095678a5` · **Gates 0 + 1A + 1B built, deployed, live-verified.**

Harvis has had a working parametric CAD kernel running for three days that no user can reach. This
session measured exactly what it does (Gate 0), made it safe to send bad input to (Gate 1A), and
then made a build that has already started actually killable (Gate 1B).

It is still unreachable, on purpose. Gate 1B was the plan's condition for CAD ever becoming
reachable, and that condition is now met — but nothing has been switched on.

**Read next:** [`docs/plans/2026-08-03-local-cad-baseline.md`](../plans/2026-08-03-local-cad-baseline.md)
is the numbers. [`docs/plans/2026-08-03-local-cad-zoo-parity-plan.md`](../plans/2026-08-03-local-cad-zoo-parity-plan.md)
is the approved 10-gate plan. This file is why.

## Files changed

| File | Change |
|---|---|
| `cad-engine/server.py` | Rewritten. Strict schema, body cap, admission control, output caps, structured `error_code`s |
| `cad-engine/recipes.py` | Rewritten. Declared `PARAM_SPEC` per recipe, finite-checked coercer, area-based cost estimate |
| `cad-engine/validation.py` | **New.** B-Rep validity, solid count, mass properties, binary-STL watertight/manifold check |
| `cad-engine/tests/test_input_hardening.py` | **New.** 34 tests, geometry pinned to the Gate 0 baseline |
| `cad-engine/runner.py` | **New (1B).** Subprocess supervisor: process groups, deadline, `SIGTERM`→`SIGKILL`, `/proc` survivor check |
| `cad-engine/worker_main.py` | **New (1B).** The child entrypoint. File-based job contract, reports its own peak RSS |
| `cad-engine/admission.py` | **New (1B).** Bounded concurrency, fast honest 429. *Not* `queue.py` — see below |
| `cad-engine/tests/test_kill_path.py` | **New (1B).** 12 tests that assert nothing is left running, not that a timeout was reported |
| `cad-engine/Dockerfile` | `httpx` + `pytest`, `PYTHONDONTWRITEBYTECODE`, copies `validation.py`, the three 1B modules and `tests/` |
| `docker-compose.yaml` | `cad-engine` block: memory, CPU, PID, cap, rootfs and tmpfs limits; the three `CAD_*` deadline/concurrency vars |
| `python_back_end/owui_compat/fab_cad.py` | `CadError`, non-finite rejection, structured error mapping, `build_id` plumbing, `cancel()` |

**Deploy note:** `cad-engine` code is `COPY`'d into the image, **not bind-mounted**. Every change
needs `docker compose --profile cad build cad-engine` then `up -d --force-recreate cad-engine`.
`fab_cad.py` is bind-mounted and only needs `docker compose restart backend`.

---

## 1. The failure was a whole-worker freeze, not a hang

The plan recorded the central risk as *"a single `NaN` parameter hangs the worker past the backend's
timeout."* Directionally right, specifically wrong in three ways — all of which changed what the fix
had to be.

A `NaN` in `arm_len_mm` makes the worker burn 1–2 cores for **45.91 seconds** and then return an
honest 500. It is not infinite, and it is not a memory leak — RSS stayed flat at ~385 MiB the whole
time. OpenCascade produces a shape it cannot tessellate, `export_stl` writes nothing, and `open()`
fails.

**The damage is that it takes everything else with it.** `GET /health` — which does nothing but
return a dict — **took 43.269 seconds** to answer during that build. OCP holds the GIL through the
native OpenCascade call, so FastAPI's 40-slot threadpool is irrelevant.

> **One malformed request is enough. It does not take forty.**
> The plan's "40 bad requests exhaust the pool" was wrong, and so was "2 GB `mem_limit` contains it"
> — memory is flat, so `mem_limit` never fires on this at all.

Two more corrections from the same probe:

- **`Infinity` was never slow.** On a quiet worker it returns 200 in 0.11 s, because `min(inf, 500)`
  is `500` and the clamp holds. An earlier 20.9 s reading was that request queued behind a `NaN`
  build's GIL. I had reported it as a property of `Infinity`. It wasn't.
- **A strict JSON client cannot send `NaN`.** `httpx`'s `json=` raises `ValueError` locally at
  0.00 s. Reproducing the failure needed a hand-built raw body, which `json.loads` accepts and
  Pydantic v2 passes through because `allow_inf_nan` defaults on.

### The trap worth remembering

`min` and `max` do not clamp `NaN` — they propagate it. And **argument order silently decides whether
you survive:**

```python
max(lo, min(hi, nan))   # -> hi     accidentally safe    (what fab_cad happened to write)
min(max(nan, lo), hi)   # -> nan    hands NaN to OCCT    (what the sidecar wrote)
```

Two clamp layers, written for defense in depth, and both were blind to the same value. One of them
worked by luck. There is now a test asserting `math.isnan(max(float("nan"), 10))` so the trap can't
rot out of the codebase's memory.

---

## 2. Gate 1A — reject bad input, cap the container

### Limits, read from the daemon

`deploy.resources` is silently ignored outside Swarm, so everything is a top-level Compose key and
every value below was read back from `docker inspect`, never from the YAML:

| | Before | After |
|---|---|---|
| `Memory` | `0` | 2 GiB |
| `NanoCpus` | `0` | 2.0 |
| `PidsLimit` | `null` | 128 |
| `ReadonlyRootfs` | `false` | `true` |
| `CapDrop` | `null` | `["ALL"]` |
| `SecurityOpt` | `null` | `["no-new-privileges:true"]` |

Enforcement confirmed rather than assumed: `touch /app/x` → `Read-only file system`; `id` → 1001;
`create_connection(("1.1.1.1", 443))` → `OSError`, so egress isolation survived `cap_drop: ALL`.

### Rejection latency, over real HTTP

Fired from `harvis-backend` with a background thread polling `/health` throughout:

| Payload | Before | After |
|---|---|---|
| `NaN` | **45.91 s, 500** | **0.005 s**, `invalid_request` |
| `Infinity` | 0.11 s, 500 | 0.002 s, `invalid_request` |
| `-50` | 200 — *silently built a 10 mm arm* | 0.001 s, `param_out_of_range` |
| `arm_length_mm` (typo) | 200 — *silently built the default part* | 0.001 s, `unknown_param` |
| `true` as a length | 200 — *silently meant 1 mm* | 0.001 s, `invalid_request` |
| extra top-level field | 200 — ignored | 0.001 s, `invalid_request` |
| 70 KB body | parsed | 0.000 s, `body_too_large` (413) |

**`/health` peaked at 13 ms.** Gate 0 measured it blocked for 43.269 s.

The italic rows are the ones I'd flag to anyone reviewing this. The `NaN` freeze was loud and
obvious. A typo'd parameter returning `200 OK` with confidently wrong geometry is the quiet one, and
it is the one that would have shipped a wrong physical part.

### No geometry regression

Golden hanger through `fab_cad`, under the hardened read-only container:

```
stl   65484 B   sha256 4481225fce2ee78ec37535848f38fd21fc2754f696be55cbce68c802fe060f85
step  51988 B   bbox [96.0, 40.0, 44.0]   volume 20622.7
new:  brep_valid=True  solids=1  area 8837.7964  watertight=True
```

Byte-identical to the Gate 0 baseline. `read_only: true` broke nothing — its only casualty was an
`ezdxf` font-cache warning at import, fixed with a 32 MB tmpfs rather than by handing back the
read-only rootfs. Peak memory across the whole session was **460.5 MiB of the 2 GiB ceiling**.

---

## 3. The cost model was wrong, and the tests caught it

Worth writing down because I nearly shipped it.

The first `estimate_cost` charged **bounding volume**. Scoring the worst request the declared bounds
permit gave **807.6 against a cap of 250** — admission control refusing a request the parameter
ranges explicitly allow. It never fired in production only because nothing had reached it yet.

The comment above it said that case "measures ~3.4". I had written that number without computing it.
It was off by 240×.

Volume is simply the wrong quantity:

| | default | max-clamped | ratio |
|---|---|---|---|
| bounding volume | — | — | **385×** |
| build time | 0.032 s | 0.040 s | 1.25× |
| triangles | 1308 | 3332 | 2.5× |
| peak RSS | 429 MiB | 441 MiB | 1.03× |

Surface area drives tessellation, so the estimator now sums the primitives' face area, normalised
against the spec's own defaults — derived rather than pasted, so changing a default can't silently
rescale every stored estimate. Default = 1.000, worst legal = 48.7, cap = 150.

**And it is stated plainly in the code that for this recipe the gate can never fire.** The bounds
already cap the work. It is a backstop that earns its place at Gate 2's studded brick, where stud
count multiplies boolean operations without any single parameter looking unreasonable — and where it
must be recalibrated against measured builds instead of guessed at a second time.

---

## 4. Deliberate behaviour changes

- **Out-of-range rejects instead of clamping.** Baseline `-50` produced a part. A silently resized
  object is worse than an error the caller can fix.
- **Unknown parameter names reject** rather than being ignored.
- **500 bodies carry `type(e).__name__` only.** Gate 0 caught this handler leaking
  `/tmp/cad_2jmv3xtk/part.stl` through `str(e)`; a test now scans every error body for `/tmp`,
  `/app` and `cad_[a-z0-9]{6,}`.
- **`fab_cad` raises `CadError`** with the sidecar's structured code. Verified that no error reaches
  the caller carrying a host name or port — `httpx.HTTPStatusError.__str__` would otherwise have put
  `http://harvis-cad:8000` into a user-facing 502.
- Responses gain `params` (every resolved value including defaults the caller never supplied) and
  `validation`. `meta`, `stl_b64`, `step_b64` keep the frozen shape the backend already consumes.

---

---

## 5. Gate 1B — the build is finally killable

Gate 1A removed the one known trigger. It did not remove the mechanism: any runaway that gets past
input validation would still starve the worker exactly as the `NaN` did, because OCP holds the GIL
through native calls. `concurrent.futures` cannot cancel a started future and an HTTP disconnect
propagates nothing — **a `timeout=` parameter added to the old in-process path would have returned a
response while the geometry kept running.** That is the lie Gate 1B exists to avoid telling.

Each build now runs in a child process started with `start_new_session=True`, which makes it a
process-group leader. The parent owns a 20 s deadline plus a 3 s grace; on expiry or an explicit
cancel it signals the **group**, waits, then `SIGKILL`s the group. The per-build tempdir is removed
by the parent on every exit path, and a bounded semaphore caps concurrency at 2.

### Verified live, over real HTTP

| Check | Result |
|---|---|
| Deadline fires (temporarily set to `0.5`) | **504 `build_timeout` in 0.616 s**, `/tmp/cad_*` empty, zero surviving processes |
| Explicit cancel mid-build | `POST /cad/cancel/{id}` → 200; the in-flight request returned **409 `build_cancelled` in 0.429 s** |
| 3 concurrent against a cap of 2 | two 200s, one **429 `queue_full` in 0.009 s** |
| `/health` during saturation, 66 probes | **worst 0.083 s.** Gate 0 measured 43.269 s |
| Golden hanger, ×3 | `sha256 4481225fce2ee78e…` — still byte-identical to the Gate 0 baseline |
| Posture after all of it | egress blocked, rootfs read-only, uid 1001, `active_builds` back to 0 |

**46/46 tests pass** in the container (34 from 1A, 12 new kill-path tests).

### Two bugs the tests caught, both of which would have shipped silently

**A killed grandchild re-parents to PID 1 — uvicorn — which does not reap strangers.** It therefore
lingers in `/proc` as a state-`Z` zombie indefinitely. A zombie holds no CPU, no memory and no file
descriptors, so counting it as a survivor reported a *successful* kill as a failure. `group_members()`
excludes zombies by default, and there is now a settle loop after `SIGKILL` because the signal is
delivered asynchronously — the kernel tears the process down afterwards, and an immediate survivor
check reports false failures on a busy box.

**A cancel that lands while the child is exiting loses the race with `proc.wait()`.** The build came
back as `failed: killed by signal 15` for doing exactly what the caller asked. The cancel flag is now
re-read after the wait loop. Cancelled is not failed.

### The cost, measured rather than estimated

Per-build latency went **0.05 s → 1.82 s**. Attribution: a bare Python spawn is 0.006 s; spawn plus
the OCP import is **1.767 s**. The import is the entire regression, not process creation. A warm
pre-fork pool is the obvious follow-up — the parent already has OCP imported, so `fork()` is nearly
free — and the plan explicitly deferred it until the kill path was proven with plain spawning.

### One deviation from the approved plan

The plan named the admission module `cad-engine/queue.py`. It shipped as **`admission.py`**: `/app` is
first on `sys.path` in this container, so `queue.py` would shadow the stdlib `queue` for
`multiprocessing`, `concurrent.futures` and urllib3 — surfacing as an unrelated `ImportError` deep
inside a dependency at import time. The rationale is in the module docstring.

### What Gate 1B deliberately does not do

- **No HTTP-disconnect detection.** A client that hangs up mid-build does not stop it. Only the
  deadline or an explicit cancel does. Stated in `server.py`'s docstring rather than papered over.
- **The PID-reuse window is documented, not proven closed.** Signalling the group before reaping the
  leader keeps it shut in practice; that is not a proof.
- **A `D`-state process is unkillable by anything**, `SIGKILL` included. `_terminate_group` returns
  the survivors so the caller reports it instead of claiming a clean kill.
- **The build registry is in memory.** A build id means nothing once its request returns; `cad_builds`
  arrives at Gate 3.

---

## State

- **46/46 tests pass** in the container, against the exact pinned OCP build that serves traffic.
- `harvis-cad` up and healthy, no host port, `cad-internal` only.
- `HARVIS_ADAPTIVE_CAD_ENABLED` is **empty**; `cad_enabled()` → `False`, `cad_status()` → `disabled`.
- The `cad` profile is opt-in, so the default service set is untouched and normal chat is unaffected.
- Gates 0, 1A and 1B are committed together in one commit — `server.py`'s 1A and 1B edits interleave,
  and splitting them by hunk would have produced an intermediate commit nobody ever ran. Reverting
  that commit returns to the pre-Gate-1A state, which is a coherent state.

## Carried forward for whoever picks this up

1. **`ps` is not installed in `harvis-cad`** (`command -v ps` → `MISSING`). The plan's verification
   command does not run as written, which is why `runner.group_members()` parses `/proc` in
   production code rather than in a test helper.
2. **`/proc/PID/stat` must be split on the *last* `)`.** `comm` is unquoted and may contain spaces
   and parentheses; splitting on whitespace mangles those rows silently.
3. **`-NaN` never reaches the schema.** Python's JSON scanner special-cases the bare tokens `NaN`,
   `Infinity`, `-Infinity` and nothing else, so it dies as a decode error one layer earlier. Pinned
   by a test.
4. **A `pytest` cache is another write to a read-only rootfs.** The suite runs with
   `-p no:cacheprovider`.
5. **`read_only: true` is survivable, but each new library may want its own cache dir.** Check the
   logs after adding one rather than assuming silence.

## Next — Gate 2

Second recipe (a generic interlocking studded brick, no trademarked branding), the GLB and 3MF
exporters that are already installed and unused, and semantic determinism. **Byte-identity is
measurably the wrong acceptance gate** — STEP embeds a one-second-resolution wall-clock timestamp and
3MF differs across two writes in the same second — so Gate 2 compares a canonical source hash plus
measured geometry instead. It also carries the 16×16 pattern bomb and the benchmark that should set
the final `mem_limit` and concurrency cap, replacing 1B's starting guesses of 2 GiB and 2.

Also unresolved and unrelated to CAD: **the Kimi API key and `OPENCLAW_GATEWAY_TOKEN` still need
rotating**, and `./scripts/commit-groups-2026-08-01.sh` has not been run.
