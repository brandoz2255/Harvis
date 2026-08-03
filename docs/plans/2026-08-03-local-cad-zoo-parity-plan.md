# Harvis Local CAD — a locally-owned, Zoo-like parametric CAD lane in normal chat

> **Status as of 2026-08-03.** Approved and **partly executed**. **Gate 0 and Gate 1A are done and
> verified**; the measurements are in
> [`2026-08-03-local-cad-baseline.md`](./2026-08-03-local-cad-baseline.md) and the session write-up
> in [`../handoffs/2026-08-03-local-cad-gates-0-and-1a.md`](../handoffs/2026-08-03-local-cad-gates-0-and-1a.md).
> **Gate 1B is next; nothing beyond it has started.** CAD is still unreachable by any user, by design.
>
> Two places where measurement has since overtaken the text below. Where they disagree, the baseline
> is right and this document is the older draft:
>
> - **Gate 1A's admission control cannot fire for the only recipe that exists.** The per-parameter
>   bounds already cap the work. §10 reads as though the budget check is load-bearing today; it is
>   not. It becomes load-bearing at Gate 2's brick, and must be recalibrated there against measured
>   builds — the first estimator used bounding volume and scored the worst *legal* request at 807
>   against a cap of 250, refusing input the bounds explicitly allow.
> - **The `mem_limit: 2g` guess survived contact with the numbers.** Measured peak is 460.5 MiB,
>   22% of the ceiling, so §13's open decision 5 can be closed on the memory half.

**Rev 2** — rewritten after review. Eight blocking problems in Rev 1 are corrected below, and the
§0 section records exactly what changed and why, so nothing silently reverts.

**Branch:** `harvis1.2` @ `095678a5` · **96 dirty files, none CAD-related** — clean ground to build on.
**Mode when written:** plan only — nothing was executed during the planning pass, and every command
below was proposed rather than run. Gates 0 and 1A have since been executed and verified.

> Supersedes the completed Docker-footprint plan that previously occupied this file (tasks #78–#90, all
> closed; result in `docs/deploy/HOW-HARVIS-GOT-SMALL.md`).

---

## Context — why this change

Harvis already contains a working isolated parametric-CAD sidecar that **no user can reach.** It has been up
and healthy for three days, produces real B-Rep solids with exact STEP output, and is invisible because two
switches are off: the backend's `HARVIS_ADAPTIVE_CAD_ENABLED` is empty, and the only frontend host that
mounts a CAD panel — the Adaptive Space route — was deliberately hidden on 2026-07-12.

The goal is to turn that dark lane into a capability attached to **normal Harvis chat**: describe a part or
attach a drawing, get exact local geometry, see it, adjust it conversationally, version it, export it.
Functional parity with Zoo, without Zoo's proprietary cloud kernel. Local CAD must never depend on Zoo.

The work is gated because the lane is unsafe to expose today: **a single `NaN` parameter hangs the worker
past the backend's timeout, and the worker has no CPU, memory, PID, capability or filesystem limits at all.**
And — the correction that reshapes this revision — **that hang cannot be fixed by a timeout in the current
architecture**, because the geometry runs on a Python thread that nothing can interrupt. Hardening therefore
splits into 1A (reject bad input, cap the container) and 1B (make a build actually killable). CAD stays
unreachable until 1B is proven.

---

## 0. What changed in Rev 2, and why

| Rev 1 said | Rev 2 says | Why |
|---|---|---|
| Gate 1 adds "timeout and cancellation" to `server.py` | **Gate 1B runs each build in a killable subprocess** with a server-owned deadline and `SIGTERM`→`SIGKILL` | OCCT runs as native code on a FastAPI threadpool thread. `concurrent.futures` cannot cancel a future that has started, and dropping the HTTP connection stops nothing. A timeout in the same process is a lie. |
| `/api/cad/projects/{pid}/cancel` | **`cad_builds` table; `POST /api/cad/builds/{bid}/cancel`; `POST …/revisions` returns `202` + build id** | Rev 1 put a mutable `status` column on a table it called immutable, and cancel had no unambiguous target. Revisions are facts; builds are attempts. |
| Gate 3 changes `/cad/execute` to multipart "while `fab_cad.py` stays untouched until Gate 4" | **`/cad/execute` is frozen; `/cad/v2/build` is added, and both sides migrate inside the same gate** | Rev 1 contradicted itself and would have broken the only existing client. |
| Gate 3 creates `cad_artifacts` FK'd to revisions; Gate 4 creates revisions | **Persistence (projects + revisions + builds + artifacts) all lands in Gate 3; Gate 4 is the vertical slice** | Rev 1 had artifacts referencing a table that did not exist yet. |
| `cad_artifacts.content_bytes BYTEA` | **`storage_key TEXT` + metadata; bytes stay in the existing on-disk artifact store** | Every STEP/GLB/3MF/STL in `BYTEA` inflates the DB, WAL and every backup — directly against the storage work just finished. Your "new `cad_artifacts` table" decision stands; only the bytes move. |
| Rollback = `git checkout <paths>` + `DROP TABLE` | **Rollback = flip the flag off, then `git revert` a dedicated commit.** Schema/data deletion is a separate, explicitly approved cleanup | `git checkout` would silently destroy the user's 96 dirty files' neighbours and any later work; `DROP TABLE` destroys user CAD data. |
| Acceptance: exports are **byte-identical** across runs | **Stored artifacts are byte-identical; regenerated ones must be semantically equivalent** (canonical source hash + measured geometry) | **Measured this session and false as written** — see below. |
| "networkless worker", "disabled by default" (UI-gated) | **"no external egress"**, and **every `/api/cad` route enforces the server-side flag** | `internal: true` blocks outside routing but sibling containers on that network still talk. Hiding a tab disables nothing. |
| "the hardest part is already done" | **the hardest *infrastructure* is done; the hardest *Zoo-like* problems are all still ahead** | Topological naming, one canonical document across four editors, stale-edit handling, prompt→CadIR, and constrained sketching are the hard parts, and none of them exist. |

**The determinism measurement** (`docker exec harvis-cad`, same `Box(10,20,30)` exported twice back-to-back):

```
step  f0d43d47abbc499d  f0d43d47abbc499d  IDENTICAL   ← but only because both runs landed in the same second
stl   fde9b4a2e0e08b28  fde9b4a2e0e08b28  IDENTICAL
glb   7172e8a1300e2338  7172e8a1300e2338  IDENTICAL
3mf   d0243b4a08f595a5  764b738a2c00217b  DIFFERS     ← same second, same shape, different bytes
```
The STEP header explains the first line: `FILE_NAME('Open CASCADE Shape Model','2026-08-03T05:55:27', …)` —
a wall-clock timestamp at one-second resolution. STEP is byte-stable only *within a second*. 3MF is a ZIP
carrying per-write identifiers and is never byte-stable. **A byte-identity acceptance gate would have passed
in CI and failed in production on a slow build.** Gate 2 uses canonical-source hashing plus measured
geometry instead.

---

## 1. Simple verdict

**Build it.** Roughly a third exists and runs: an isolated, non-root, egress-blocked OpenCascade kernel that
returns exact B-Rep geometry and lossless STEP. That is real infrastructure and it should not be rebuilt.

But it is the *foundation*, not the hard part. What makes Zoo feel like Zoo — clicking a face and getting a
stable semantic feature back, one canonical document that chat, sliders, source and the feature tree all
edit without fighting, and reliable prompt→geometry — is entirely unbuilt, and topological naming in
particular is a genuine research problem with a spike of its own (Gate 5).

Three of the brief's hypotheses are contradicted by evidence:

1. **No new Python dependency is needed for GLB, 3MF, or B-Rep validation** — all three verified working in
   the pinned worker this session.
2. **Base64 never reaches the frontend, and the viewer is not mock-only** — `fab_cad.py:97-98` decodes
   server-side; `HelmetHangerMockViewer.svelte:109-139` already fetches and renders real STL.
3. **CAD is invisible for two reasons, not one** — the empty env flag *and* the disabled Adaptive route.

---

## 2. Evidence table

### Verified repository facts

| Claim | Evidence | Status | Implication |
|---|---|---|---|
| Isolated build123d/OCP sidecar exists | `cad-engine/server.py` (59 lines), `recipes.py` (93), `Dockerfile` | **Verified** | Extend it. Do not add a `cad-worker` or a `cad-api`. |
| Exactly one registered recipe | `RECIPES = {"helmet_hanger_v1": helmet_hanger_v1}` | **Verified** | Gate 2 adds the second. |
| Only registered names execute | `server.py:39-41` | **Verified** | Allowlist is real; preserve it through the CadIR transition. |
| Backend controller exists | `owui_compat/fab_cad.py` (99 lines) | **Verified** | This *is* the controller layer. |
| Clamps in two places | `fab_cad.py:20-25` (`_LIMITS`) and `recipes.py` per-dimension | **Verified** | Defense in depth — but both NaN-blind. |
| Stage 1 stress is real | `owui_compat/fab_stress.py` — `closed_form_cantilever_v1`, `bolt_group_check`, `VERDICT_PHRASING` | **Verified** | "Finish forge-fab Stage 1 first" is stale. Stage 2 is the dark one. |
| Honest tool-status contract | `workspace_methods/fabrication.py` — 8 tools, Stage 1a→5 | **Verified** | Reuse; don't fork a second registry. |
| Printer boundary already designed | `docs/plans/printer-integration-design.md` | **Verified** | Gate 9 cites it; don't re-decide. |
| **Base64 never reaches the browser** | `fab_cad.py:97-98`; `adaptive_space.py:646-676` returns `mesh_rid` | **Contradicted** | Base64 exists only sidecar→backend. |
| **`STLLoader` is used, not dead** | `HelmetHangerMockViewer.svelte:109-139` `loadRealMesh()`, `realMode = true` | **Contradicted** | Gate 4 extends a working viewer. |
| Adaptive route disabled | `routes/(app)/harvis/adaptive/+page.svelte:2-7` | **Verified** | Second blocker; answered by a ChatControls tab. |
| That panel switch is a hardcoded `{#if}` | `adaptive/surfaces.ts:12-21` + `AdaptiveSpaceShell.svelte:527-535` | **Verified** | Copy the *real* registry at `agent-studio/surfaces.ts:17-55`. |
| Inline card extension point exists | `MarkdownTokens.svelte:428-449` dispatches `<details type="workspace_run">` | **Verified** | One `{:else if}` arm + one component. |
| Live right-side panel exists | `chat/ChatControls.svelte` — `:88`, `:96-104`, `:424-455`, store `:122-125` | **Verified** | CAD Studio's host. |
| three 0.169.0, `three/addons/*` | `package.json:146` + lockfile; `HelmetHangerMockViewer.svelte:10-13` | **Verified** | GLTFLoader/STLLoader/3MFLoader present. **No STEP loader** — STEP is download-only. |
| Nothing versioned exists anywhere | closest is `workspace_runs ← workspace_artifacts` | **Verified** | Revisions are greenfield; copy the FK/CASCADE shape from `orchestration/__init__.py:110-119`. |
| No Alembic; DDL in lifespan | `main.py:644-645, 876`; constants `main.py:796-816` | **Verified** | New tables = constants → export from `owui_compat/__init__.py` → one `await conn.execute`. |
| `user_id` is `INTEGER NOT NULL`, **no FK to users** | `adaptive_spaces` DDL in `adaptive_space.py` | **Verified** | Matching the convention is safe; adding a real FK is a deliberate deviation (Gate 3, after confirming `users.id`). |
| Pydantic v2 | worker 2.13.4; `notebooks/models.py:203` uses `ConfigDict` | **Verified** | `extra="forbid"` sketches are valid here. |
| Method-pack tools are declaration-only | `workspace_method.py:163-207`; execution is bespoke routes | **Verified** | LLM-invoked CAD needs `TOOL_SCHEMA` + `dispatch_tool` (`orchestration/tools.py:165,525`). |
| Attachments already deliver real bytes | `attachments.py:285-352`, `:393-435` | **Verified** | Gate 8 extends a working path. |
| Attachment resolution has **no ownership check** | `attachments.py:99-107` (its own comment); traversal guard only at `:104-107` | **Verified — security gap** | CAD must resolve ids through an ownership-checked route, never `_owui_stored_file` directly. |

### Verified runtime facts (live, this session)

| Claim | Evidence | Status | Implication |
|---|---|---|---|
| Sidecar produces real geometry | `{recipe: helmet_hanger_v1, arm_len_mm: 90}` → bbox `96 × 40 × 44 mm`, vol `20 622.7 mm³`, 87 KB STL, 69 KB STEP | **Verified** | Gate 0's golden capture is trivially obtainable. |
| Pinned versions | build123d **0.9.1**, cadquery-ocp **7.8.1.1.post1**, py3.11.15, fastapi 0.139.0, pydantic 2.13.4 | **Verified** | OCP 7.9 removes `TopoDS.HashCode` and breaks build123d 0.11.x. **Do not bump either.** |
| GLB export works | `export_gltf(Box(10,20,30),'a.glb',binary=True)` → 3404 B | **Verified** | Zero new dependency. |
| 3MF export works, in mm | `Mesher().add_shape(p); m.write(...)` → 1626 B, `model_unit = Unit.MM` | **Verified** | Zero new dependency. |
| B-Rep validation available | `BRepCheck_Analyzer(shape.wrapped, True).IsValid()` → `True` | **Verified** | Zero new dependency for Gate 1A. |
| STEP round-trips exactly | export → `import_step` → 1 solid, `5717.3` → `5717.3`, **Δ 0.0000%**, valid both sides | **Verified** | Safe to promise exact STEP. |
| STL re-imports as `Face` | `import_stl(...)` | **Verified** | STL is a reference body, never recovered parametrics. |
| **STEP embeds a wall-clock timestamp** | `FILE_NAME(…,'2026-08-03T05:55:27',…)` | **Verified** | Byte-identity is second-dependent. |
| **3MF differs byte-wise on identical input** | two writes, same second → `d0243b4a…` vs `764b738a…` | **Verified** | Byte-identity is impossible for 3MF. |
| STL and GLB byte-stable in this sample | identical hashes across runs | **Verified (sample of 2)** | Suggestive, not a guarantee — still tested semantically. |
| **No resource limits at all** | `HostConfig` → `Memory 0`, `NanoCpus 0`, `CpuQuota 0`, `PidsLimit null`, `ReadonlyRootfs false`, `CapDrop null`, `SecurityOpt null` | **Verified — Gate 1A** | compose `docker-compose.yaml:1533-1546` sets none. |
| Non-root, no binds, no docker socket | `uid=1001(appuser)`; `Binds null`; `Privileged false` | **Verified** | Already correct; preserve. |
| No external egress | in-worker `create_connection(('1.1.1.1',443))` → `OSError`; net `harvis_cad-internal` | **Verified** | Sibling containers on that network remain reachable — this is *not* "networkless". |
| **`NaN` hangs the worker past the timeout** | `{"arm_len_mm": NaN}` → nothing at 25 s; backend gives up at 30 s. Worker healthy after, 0 restarts | **Verified — headline risk** | `min`/`max` propagate `NaN` through both clamp layers into OCCT. |
| No worker-side timeout or cancellation | plain `def execute()`; `uvicorn` defaults (1 worker, 40-thread pool) | **Verified** | 40 bad requests exhaust the pool; a disconnect cancels nothing. |
| Backend flag present-but-empty | `HARVIS_ADAPTIVE_CAD_ENABLED=`; URL set | **Verified** | Compose env bakes at **create** — needs `up -d backend`, not `restart`. |

### Inferences (not verified)

- The `NaN` hang is presumably OCCT iterating on a degenerate dimension; no profiler was attached.
- 2 GB is a guess for the memory ceiling; Gate 1A measures peak RSS and Gate 2 sets the final number.
- Extending the artifact mime map to `.step/.stl/.glb/.3mf` is needed for correct labels; unknown extensions
  already fall back to `application/octet-stream` (`workspace_router.py:3363`) — safe but wrong.

### Unknowns requiring an experiment or a decision

| Unknown | How to resolve |
|---|---|
| Does the exported 3MF carry units a real slicer honours? | Gate 2: open in PrusaSlicer/Cura, confirm 32 mm not 32 in. |
| Does `read_only: true` break OCCT (caches outside `/tmp`)? | Gate 1A: recreate with `read_only` + `tmpfs /tmp`, re-run the golden hanger. One revert to undo. |
| Peak RSS + wall-clock of the brick at max clamped counts | Gate 2 benchmark, before fixing `mem_limit`. |
| `users.id` type and whether an FK is safe to add | Gate 3, before writing the DDL. Existing tables use a bare `INTEGER`. |
| Can GLB carry stable per-feature node names through booleans? | **Gate 5 spike.** This is the real Zoo-parity risk. |
| Local model reliability for prompt→CadIR | Gate 7 benchmark. No commitment before data. |

---

## 3. Current architecture map

```
Browser ─ /harvis/adaptive ───────────► "coming soon" placeholder   ◄── SWITCH 2 (off)
            AdaptiveSpaceShell.svelte ── never mounted
              └ PrototypeTestPanel.svelte
                  └ HelmetHangerMockViewer.svelte  (three 0.169, OrbitControls,
                     STLLoader → REAL geometry when `meshUrl` set; procedural otherwise)

 POST /api/adaptive/spaces/{id}/cad/execute      owui_compat/adaptive_space.py:621
     ├ :627  fab_cad.cad_enabled() → 403         ◄── SWITCH 1 (flag empty)
     ├ :631  _fetch_owned(pool, space_id, user_id)         ownership OK
     ├ :634  fab_cad.params_from_meta(...)                 per-key clamps (_LIMITS)
     ├────── fab_cad.execute()  httpx timeout=30           fab_cad.py:88-99
     │            ▼  http://harvis-cad:8000/cad/execute  (cad-internal, no external egress, no host port)
     │       cad-engine/server.py:38  allowlist → tempdir → recipes.run()
     │            └ build123d 0.9.1 / OCP 7.8.1.1, uid 1001, NO LIMITS, NO KILL PATH
     │            ◄ {ok, meta, stl_b64, step_b64}
     ├ :646  base64 decoded SERVER-SIDE → $ARTIFACT_STORAGE_DIR/adaptive/<user>/<space>/<rid>.stl
     ├ :656  ⚠ DELETES the previous mesh/step — "keep only the LATEST part". No history.
     └────── returns {ok, cad:{…, mesh_rid}, mesh_rid, manifest}

 GET /api/adaptive/spaces/{id}/resource/{rid}    adaptive_space.py:594 → FileResponse
     ownership + realpath containment; already knows stl/step mime
```

Note `:646` — the on-disk store the artifacts should keep using, and `:656`, the destructive write that
makes revisions impossible.

---

## 4. Zoo-parity matrix

| Capability | Status |
|---|---|
| Isolated exact B-Rep kernel (OpenCascade) | **Already present** |
| Exact STEP export + lossless round-trip | **Already present** — Δ 0.0000% measured |
| STL export | **Already present** |
| GLB / glTF export | **Already present, unused** |
| 3MF export in millimetres | **Already present, unused** |
| B-Rep validity check | **Already present, unused** |
| STEP / STL / SVG import | **Already present, unused** |
| Real 3D viewport with orbit/zoom | **Already present** — authorized fetch + STLLoader |
| Named parameters with bounds | **Already present, partial** — NaN-blind |
| Non-root, no-egress, no-secret worker | **Already present** |
| Effective CPU/RAM/PID/caps/FS limits | **Immediate MVP (Gate 1A)** — verified absent |
| Strict finite input schemas, admission control, structured errors | **Immediate MVP (Gate 1A)** |
| Watertight / manifold mesh check | **Immediate MVP (Gate 1A)** |
| **Killable build with a real deadline** | **Immediate MVP (Gate 1B)** — impossible in today's architecture |
| Second trusted recipe (studded brick) | **Immediate MVP (Gate 2)** |
| Semantic determinism (canonical hash + measured geometry) | **Immediate MVP (Gate 2)** |
| Projects, immutable revisions, build jobs, quotas | **Immediate MVP (Gate 3)** — greenfield |
| Artifact ids + authorized streaming, no base64 on any hop | **Immediate MVP (Gate 3)** |
| End-to-end vertical slice with the real viewer | **Immediate MVP (Gate 4)** |
| Human-readable canonical parametric source (CadIR) | **Immediate MVP (Gate 5)** |
| **Stable semantic feature IDs surviving booleans** | **Gate 5 spike — unproven, the real parity risk** |
| CAD Studio inspector tabs | **Immediate MVP (Gate 6)** |
| Composer `+ → Create → 3D / CAD`, intent suggestion, capability chip, result card | **Immediate MVP (Gate 6)** |
| Chat + GUI + source editing one canonical document, stale-edit safe | **Immediate MVP (Gate 6)** |
| User capability/install status · admin profile/service controls | **Immediate MVP (Gate 6)** |
| Expand into the deep Prototype & Fabrication workspace | **Immediate MVP (Gate 6)** |
| Prompt → CadIR, schema-validated, bounded repair | **Gate 7** |
| Image / sketch guidance, dimension elicitation | **Gate 8** |
| Viewport markup tied to camera pose + selection | **Later (Gate 8)** |
| Slicer adapters, Blender handoff, printer bridge | **Later (Gate 9)** — design already written |
| Constrained sketcher, assemblies, BOM, GD&T, FEA, CAM | **Later** |
| Zoo BYO-key cloud lane | **Later, optional** — verdict in `docs/research/2026-07-30-zoo-dev.md` |
| Zoo's hosted engine, streamed viewport, Zookeeper backend, KCL, branding | **Intentionally not cloned** |
| Training a bespoke CAD model | **Intentionally not cloned** — prove the generate→execute→check→repair loop first |

---

## 5. Gaps in priority order

1. **A build cannot be stopped.** OCCT runs native code on a threadpool thread; a started `Future` cannot be
   cancelled and an HTTP disconnect does nothing. Every "timeout" claim depends on fixing this first.
2. **`NaN` hangs the worker past the backend's timeout** — `min`/`max` propagate `NaN` through both clamp
   layers. Verified live.
3. **No effective resource limits** — read from `HostConfig`, not inferred from YAML.
4. **No geometry validation** — `bbox` + `volume` only, despite `BRepCheck_Analyzer` being installed.
5. **Two switches, and neither is a real gate** — the env flag, the hidden route, and (once routes exist)
   no server-side enforcement at all.
6. **The CAD write is destructive** — `adaptive_space.py:656-658` deletes the previous part every build.
7. **No project / revision / build store.**
8. **One recipe, hardcoded.**
9. **Attachment resolution has no ownership check** (`attachments.py:99-107`).
10. **No stable feature identity** — nothing maps a clicked triangle back to a semantic feature.
11. **GLB/3MF/validation sit installed and unused.**

---

## 6. Contracts

Pydantic v2, `ConfigDict(extra="forbid")`, matching `notebooks/models.py:203`. Every float field is
`allow_inf_nan=False` — this is the schema-level half of the `NaN` fix.

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

Mm = Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]   # rejects NaN/Inf at parse time

class DesignSpec(StrictModel):
    schema_version: Literal["0.1"]
    units: Literal["mm"] = "mm"
    intent: str
    process: Literal["fdm","sla","cnc","sheet","unspecified"] = "unspecified"
    material: str | None = None
    dimensions: dict[str, Mm] = {}      # only what the user actually stated
    assumptions: list[str] = []         # every value Harvis chose — surfaced in the UI
    unknowns: list[str] = []            # what must be asked before claiming accuracy
    tolerances_mm: float | None = None

class CadDocument(StrictModel):                      # Gate 5
    schema_version: Literal["0.1"]
    units: Literal["mm"] = "mm"
    parameters: list[Parameter] = Field(max_length=64)
    operations: list[CadOperation] = Field(max_length=128)
    expected_solids: int = Field(ge=1, le=16)
    acceptance: list[AcceptanceCheck] = []
# Formulas: restricted `ast` walk — Name/Constant/BinOp/UnaryOp and + - * / ** only.
# No eval, no exec, no attribute access, no calls. Reject on any other node type.

class FeatureRef(StrictModel):                       # Gate 5 spike output, not assumed to work
    feature_id: str                                  # "support_tube[2]" — author-stable, not an OCCT index
    op_id: str
    gltf_node: str | None                            # null until the spike proves node naming survives booleans
    selectable: bool                                 # false ⇒ whole-body selection only, said honestly in the UI

class ValidationReport(StrictModel):
    brep_valid: bool
    solid_count: int
    expected_solids: int
    volume_mm3: float
    surface_area_mm2: float
    bbox_mm: dict[str, float]
    center_of_mass_mm: dict[str, float]
    mesh_watertight: bool | None
    mesh_manifold: bool | None
    warnings: list[str]                              # printability advice — NEVER a safety claim

class ArtifactRef(StrictModel):
    id: UUID
    format: Literal["step","stl","glb","3mf"]
    media_type: str
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")   # of the stored bytes

class BuildResult(StrictModel):
    build_id: UUID
    project_id: UUID
    revision_id: UUID
    status: Literal["queued","running","succeeded","failed","cancelled"]
    validation: ValidationReport | None
    artifacts: list[ArtifactRef]
    error_code: str | None                           # structured + repairable
    error_detail: str | None                         # safe text: no paths, no argv, no host names
```

`BuildResult` never carries a filesystem path, a `storage_key`, or base64.

---

## 7. Database and artifact storage

Four tables. DDL constants in the owning module, exported from `owui_compat/__init__.py`, executed once at
`main.py:808-816` — the pattern already used by `orchestration_pool.py:23-30`. No Alembic (the runner at
`migrations/` is never invoked, `main.py:644-645`).

**Bytes do not go in Postgres.** Artifacts keep using the existing on-disk store that
`adaptive_space.py:239-241,646-653` already writes to, under `$ARTIFACT_STORAGE_DIR/cad/<user_id>/
<project_id>/<build_id>.<ext>`, with the same realpath-containment check as `adaptive_space.py:607-611`.
Postgres holds metadata and an opaque `storage_key`.

```sql
CREATE TABLE IF NOT EXISTS cad_projects (
    id              UUID PRIMARY KEY,
    user_id         INTEGER NOT NULL,          -- FK to users only after confirming users.id (Gate 3)
    conversation_id TEXT,                      -- nullable: a project can outlive the chat
    title           TEXT NOT NULL,
    head_revision   UUID,                      -- FK added after cad_revisions exists
    next_seq        INTEGER NOT NULL DEFAULT 1,-- bumped in the same tx as the insert
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cad_projects_user ON cad_projects(user_id, updated_at DESC);

-- IMMUTABLE. Insert only. No status column, no UPDATE path in the store module.
CREATE TABLE IF NOT EXISTS cad_revisions (
    id             UUID PRIMARY KEY,
    project_id     UUID NOT NULL REFERENCES cad_projects(id) ON DELETE CASCADE,
    parent_id      UUID,
    seq            INTEGER NOT NULL,
    design_spec    JSONB NOT NULL,             -- snapshot per revision, not only on the project
    source_kind    TEXT NOT NULL,              -- 'recipe' | 'cadir'
    recipe_name    TEXT,
    cadir          JSONB,
    parameters     JSONB NOT NULL DEFAULT '{}',
    created_by     TEXT NOT NULL,              -- user|gui|template|ai
    model_provider TEXT, model_name TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, seq),
    UNIQUE (project_id, id),                                       -- target for the composite FK below
    FOREIGN KEY (project_id, parent_id) REFERENCES cad_revisions(project_id, id)
);  -- composite FK: a revision can never name a parent in a different project

-- MUTABLE. One row per build attempt.
CREATE TABLE IF NOT EXISTS cad_builds (
    id              UUID PRIMARY KEY,
    revision_id     UUID NOT NULL REFERENCES cad_revisions(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,             -- queued|running|succeeded|failed|cancelled
    idempotency_key TEXT,                      -- client retry of the same intent reuses the build
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    started_at      TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    duration_ms     INTEGER, peak_rss_bytes BIGINT,
    validation      JSONB,
    error_code      TEXT, error_detail TEXT,   -- safe text only
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (revision_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_cad_builds_rev ON cad_builds(revision_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cad_artifacts (
    id          UUID PRIMARY KEY,
    build_id    UUID NOT NULL REFERENCES cad_builds(id) ON DELETE CASCADE,
    format      TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    size_bytes  BIGINT NOT NULL,
    sha256      CHAR(64) NOT NULL,
    storage_key TEXT NOT NULL,                 -- opaque; never returned to the client
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (build_id, format)
);
```

Also required in Gate 3, each with a test:

- **Atomic head/seq:** `next_seq` bump, revision insert, and `head_revision` update in one transaction.
- **Stale-edit detection:** every revision-creating request carries `base_revision_id`; a mismatch against
  the current head returns **409** with both revisions, so the UI can show a conflict instead of silently
  forking.
- **Idempotency:** `idempotency_key` on build creation; a retry returns the existing build.
- **Quotas and retention before any artifact is written** — per-user and per-project byte caps and a
  max-revisions-retained policy, enforced in the store, not documented as future work.
- **Orphan reaper** for storage keys whose row was CASCADE-deleted.

**Rollback:** turn the flag off (routes 404 immediately), then `git revert` the gate's dedicated commit.
Tables stay. Dropping them is a separate cleanup that must be approved on its own, because it destroys user
CAD data.

---

## 8. Endpoint changes

New router `owui_compat/cad_router.py`, registered beside `register_adaptive_space_routes`
(`router.py:730`), authed with `Depends(get_current_user)` (`main.py:312`). **Every route calls the same
`require_cad_enabled()` dependency** — the server-side flag is the gate; the UI merely reflects it. Routes
404 (never 403) on a project the caller does not own, matching `_fetch_owned_artifact`
(`workspace_router.py:3341-3355`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/cad/capability` | Honest status: flag, engine reachable, recipes, formats, units, quota headroom |
| `POST` | `/api/cad/projects` | Create from a DesignSpec → project + revision 1 (no build) |
| `GET` | `/api/cad/projects` · `/{pid}` | List; project + revisions |
| `POST` | `/api/cad/projects/{pid}/revisions` | Body carries `base_revision_id` + `idempotency_key`. Inserts a revision, enqueues a build, returns **`202` + `{revision_id, build_id}`**. `409` on stale base |
| `GET` | `/api/cad/builds/{bid}` | Build status + validation (poll; SSE later, reusing the shared run-stream store) |
| `POST` | `/api/cad/builds/{bid}/cancel` | Sets `cancel_requested`; the worker kills the process group |
| `GET` | `/api/cad/builds/{bid}/artifacts/{aid}` | Streams bytes from the on-disk store. `nosniff`, disposition by query. `storage_key` never leaves the server |
| `POST` | `/api/cad/projects/{pid}/revisions/{rid}/restore` | New revision whose parent is `{rid}` |
| `GET` | `/api/cad/projects/{pid}/compare?a=&b=` | Parameter + measurement diff |

**Sidecar.** `POST /cad/execute` is **frozen** in its current JSON/base64 shape so `fab_cad.py` and the
adaptive lane keep working. Gate 3 adds `POST /cad/v2/build` — accepts `formats: [...]` and `deadline_s`,
streams files as multipart, returns `{ok, meta, validation}` — and migrates `fab_cad.py` to it **in the same
gate**. `/cad/execute` is removed only after the adaptive lane is retired (open decision 2).
`GET /health` gains `{formats, build123d_version, ocp_version, queue_depth, active_builds}`.

---

## 9. UI component and route changes

CAD Studio is a **new ChatControls tab** (your decision). Adaptive Space stays hidden and becomes the later
"Expand" target.

| File | Change |
|---|---|
| `chat/ChatControls.svelte` | Add `'cad'` to `activeTab` (`:88`), its gate (`:96-104`), the stale-tab redirect (`:110-119`), and the render switch (`:424-455`). The tab appears only when `/api/cad/capability` is healthy **and** a project is attached. |
| `chat/ChatControls/CadStudioPanel.svelte` | **New.** Top bar (project · revision · build status · validation · export) + viewport + inspector tabs: Parameters, Features, Inspect, Validate, Versions, Source, Files. |
| `chat/ChatControls/CadViewer.svelte` | **New.** Generalizes the working fetch-and-render path to `GLTFLoader` (`three/addons/loaders/GLTFLoader.js`); STL fallback. Standard views, wireframe, section, measure, resize, loading/error states, `dispose()` on unmount. **Never renders model-authored JS/HTML.** |
| `chat/Messages/CadResultCard.svelte` | **New.** The `<details type="cad_build">` token carries **only an opaque `build_id`**. The card fetches `/api/cad/builds/{bid}` and renders authorized state — it never trusts model-authored measurements, verdicts, or links. |
| `chat/Messages/Markdown/MarkdownTokens.svelte` | One `{:else if token?.attributes?.type === 'cad_build'}` arm at `:441`, as `workspace_run` is dispatched. |
| `chat/MessageInput/InputMenu.svelte` | `Create → 3D / CAD`, modelled on **Create Image** (`:181-191` → `MessageInput.svelte:1865-1878`). |
| `chat/MessageInput.svelte` | `onCreateCad` prop (mount site `:1821-1892`); capability chip `Local CAD · millimetres`; **CAD-intent suggestion** — a dismissible inline offer when the detector fires, never an automatic mode switch. |
| `chat/MessageInput/CadContextChip.svelte` | **New.** Selection context is a **structured chip object** on the message (feature id, revision id, camera pose), rendered as text for the model but validated server-side against the user's own project. Not free text the model can forge. |
| `lib/stores/index.ts` | `showCadStudio`, `activeCadProject` (structured attachment, not a string) beside `showArtifacts` (`:176-177`). |
| `lib/apis/cad/index.ts` | **New.** Typed client for §8, including build polling. |
| `lib/agent-studio/ArtifactPreview.svelte` | Add a `mesh` kind (`:18-35`) so `.stl/.glb/.3mf/.step` stop falling to the code view. |
| `routes/(app)/harvis/adaptive/+page.svelte` | Gate 6 only: the CAD Studio "Expand" action re-enables this route behind the same capability flag, mounting `AdaptiveSpaceShell` for the deep Prototype & Fabrication workspace. |
| Settings (user) | CAD capability status + install/enable state, reading `/api/cad/capability`. |
| Settings (admin) | Engine profile/service controls: enable the lane, deadline, concurrency, quotas. |

Selection context, once the Gate-5 spike proves it, appears as:

```text
Selected feature: support_tube[2]      (chip → {feature_id, revision_id}, server-validated)
Selected revision: rev_0007
```
Until then the chip says **"Selected: whole body"** and the Features tab states plainly that per-face
selection is not yet available. No pretending.

---

## 10. Gated implementation plan

Each gate is independently approvable and independently reversible. The lane stays behind
`HARVIS_ADAPTIVE_CAD_ENABLED` + the `cad` compose profile, **enforced server-side**, through Gate 6.
**CAD stays unreachable by any user until Gate 1B is proven.**

---

### Gate 0 — Baseline and contract freeze  ← first tranche

**Files:** `docs/plans/2026-08-03-local-cad-baseline.md` (new). No code.

**Work:** run the golden hanger through **both** paths — sidecar directly and through `fab_cad.execute()` —
and record: geometry metrics (bbox, volume, surface area, solid count), artifact sizes and SHA-256s, latency,
**peak RSS sampled during execution** (not after), the exact request/response schema on both hops, the
effective `HostConfig`, and both switches with the exact command to flip each.

**Disabled by default:** yes (nothing ships).

**Commands after approval:**
```bash
docker exec harvis-cad python -c "import importlib.metadata as m;print(m.version('build123d'),m.version('cadquery-ocp'))"
```
```bash
docker inspect harvis-cad --format '{{json .HostConfig}}' > /tmp/cad-hostconfig-baseline.json
```
```bash
docker stats harvis-cad --no-stream --format 'CPU={{.CPUPerc}} MEM={{.MemUsage}}'
```

**Success:** both paths produce the same geometry metrics; the doc records metrics rather than only hashes;
peak RSS is a sampled maximum, not an idle reading.

**Rollback:** delete the doc. **Risks:** none.
**Stop if:** the two paths disagree on geometry — that is a live bug to investigate before anything else.

---

### Gate 1A — Reject bad input, cap the container  ← first tranche

**Files:** `docker-compose.yaml:1533-1546` · `cad-engine/server.py` (strict schemas, admission control,
structured errors) · `cad-engine/validation.py` **(new)** · `cad-engine/recipes.py` (finite-checked coercer)
· `owui_compat/fab_cad.py` (reject non-finite before the HTTP call; map structured errors) ·
`cad-engine/tests/test_input_hardening.py` **(new)**.

**Compose hardening** — top-level keys, because this is ordinary Compose and `deploy.resources` is ignored
outside Swarm:

```yaml
    user: "1001:1001"
    read_only: true
    tmpfs: ["/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777"]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    pids_limit: 128
    mem_limit: 2g
    cpus: 2.0
    stop_grace_period: 10s
```
Keep `profiles: ["cad"]`, `cad-internal`, and the absence of `ports:` exactly as they are.

**The `NaN` fix, both layers.** `allow_inf_nan=False` on every float field rejects it at parse time; a
`_finite(value, lo, hi)` coercer in `recipes.py` rejects `nan`/`inf` **before** clamping, because `min`/`max`
propagate them silently. The inner layer never trusts the outer one.

**Also in 1A:** unknown-key rejection (`extra="forbid"`); admission control that rejects a request whose
static complexity budget exceeds the cap *before* geometry starts; output-size, tempdir-size and
triangle-count limits; `BRepCheck_Analyzer` validity, solid count, finite positive volume/bbox, and a
watertight/manifold check on exported triangles — all with primitives already installed; structured
`error_code`s with safe detail text (no paths, no argv, no host names).

**Dependencies:** none. **Disabled by default:** yes.

**Commands after approval:**
```bash
docker compose --profile cad up -d --force-recreate cad-engine
```
```bash
docker inspect harvis-cad --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}'
```
```bash
docker exec harvis-cad python -m pytest tests/test_input_hardening.py -q
```

**Success (all must hold):**
- `HostConfig` shows non-zero `Memory`, `NanoCpus`, `PidsLimit`, `ReadonlyRootfs true`, `CapDrop [ALL]`,
  `SecurityOpt [no-new-privileges]` — **read from the daemon, not the YAML**
- the golden hanger still builds under `read_only`, geometry metrics unchanged from Gate 0
- `NaN`, `Infinity`, negatives and unknown keys each return a structured **400 in under 1 second**
- every geometry failure returns a structured `error_code`; none returns `ok: true`
- peak RSS under the ceiling, recorded

**Rollback:** flag off, then `git revert` the Gate-1A commit, then recreate the container.
**Risks:** `read_only` may break an OCCT cache path outside `/tmp` — caught by the golden-hanger test.
`mem_limit: 2g` may OOM a legitimate large part; Gate 2's benchmark sets the final number.
**Stop if:** the hardened worker cannot reproduce Gate 0's geometry. Report; do not loosen limits to pass.

*(The 16×16 pattern-bomb test moves to Gate 2 — the brick does not exist yet.)*

---

### Gate 1B — Make a build killable  ← first tranche, and the gate that unblocks everything

**The problem, stated plainly:** OCCT executes as native code on a thread from FastAPI's threadpool.
`concurrent.futures` cannot cancel a future that has begun, and an HTTP disconnect does not propagate. A
`timeout` parameter added to the current code would return a response while the geometry kept running and
kept its slot. **Gate 1A caps the damage; only 1B stops it.**

**Files:** `cad-engine/server.py` · `cad-engine/runner.py` **(new)** — subprocess supervisor ·
`cad-engine/worker_main.py` **(new)** — the child entrypoint that does the geometry · `cad-engine/queue.py`
**(new)** — bounded admission queue · `owui_compat/fab_cad.py` (deadline plumbing, structured
timeout/cancel errors) · `cad-engine/tests/test_kill_path.py` **(new)**.

**Design:**
- each build runs in its own child process, started in a **new process group** (`start_new_session=True`)
- the parent owns the deadline; on expiry or on a cancel flag it sends `SIGTERM` to the **process group**,
  waits a grace period, then `SIGKILL` — killing the group, not just the child, so no orphan survives
- geometry writes into a per-build tempdir the parent removes afterwards, verified by test
- a bounded queue with an explicit concurrency cap; excess requests get a fast, honest **429**, never a
  silent wait
- the child reports peak RSS back with its result, feeding `cad_builds.peak_rss_bytes`
- the parent's deadline is strictly shorter than `fab_cad`'s httpx timeout, which is shorter than nginx's —
  each layer gives up after the one it depends on, never before

**Disabled by default:** yes.

**Commands after approval:**
```bash
docker compose --profile cad up -d --force-recreate cad-engine
```
```bash
docker exec harvis-cad python -m pytest tests/test_kill_path.py -q
```
```bash
docker exec harvis-cad sh -c 'ps -eo pid,ppid,pgid,etime,comm'
```

**Success (all must hold):**
- a deliberately unbounded build is terminated at the deadline, and `ps` shows **no surviving child or
  grandchild** in that process group
- an explicit cancel mid-build kills it within the grace period and returns `cancelled`, not `failed`
- the tempdir is gone after both a killed and a completed build
- N+1 concurrent requests with a cap of N return **429**, and the worker stays responsive to `/health`
- the pre-1A `NaN` payload now returns a structured error **and** leaves no running process
- 100 sequential kills leak no memory, no file descriptors and no processes

**Rollback:** flag off, `git revert` the Gate-1B commit, recreate. `/cad/execute`'s contract is unchanged,
so the adaptive lane is unaffected either way.
**Risks:** subprocess startup adds per-build latency — measure it; if OCP import dominates, a warm pre-forked
pool is the follow-up, but only after the kill path is proven with plain spawning.
**Stop if:** any process survives a kill, or the tempdir persists. **This is the gate that decides whether
CAD may ever be reachable.**

---

### Gate 2 — Second recipe, real exporters, semantic determinism

**Files:** `cad-engine/recipes.py` · `cad-engine/exporters.py` (new; GLB + 3MF via the verified
`export_gltf` / `Mesher`) · `cad-engine/tests/test_brick.py`, `test_determinism.py` (new) ·
`owui_compat/fab_cad.py` (recipe name becomes a validated argument, not the constant `RECIPE` at `:16`).

Generic interlocking studded brick — **no trademarked branding, and no trademarked dimensions used as
naming or documentation.**

**Determinism, corrected.** Byte-identity is measurably wrong: STEP embeds a one-second-resolution
timestamp, and 3MF differs on two writes in the same second. The gate is instead:

1. **Canonical source hash** — SHA-256 over the normalized (recipe name + sorted resolved parameters +
   schema version). Same input ⇒ same hash, and it is what `cad_revisions` is compared on.
2. **Geometric equivalence** — volume, surface area, bbox, solid count, centre of mass, and per-feature
   counts within tolerance across two independent builds.
3. **Normalized mesh signature** — sorted, rounded triangle set, so STL/GLB are compared by geometry rather
   than by encoding.
4. **Stored artifacts must be byte-identical to themselves** — the `sha256` column is verified on read; it
   detects corruption, and is never used as a rebuild test.

**Also here:** the 16×16 pattern bomb (moved from Gate 1A), the memory/wall-clock benchmark that sets the
final `mem_limit`, and the slicer check that the 3MF measures 32 mm rather than 32 inches.

**Success:** both recipes pass validity, solid count, STEP round-trip tolerance, and the three determinism
tests; the worst case completes inside the Gate-1B deadline and under the ceiling, or is rejected by
admission control before geometry starts.

**Rollback:** flag off, revert the commit; the hanger is untouched. **Disabled by default:** yes.
**Stop if:** geometric equivalence fails across builds — revisions and compare both depend on it.

---

### Gate 3 — Persistence: projects, revisions, builds, artifacts, quotas

**Files:** `owui_compat/cad_store.py` (new) · `owui_compat/cad_router.py` (new) · DDL constants +
`owui_compat/__init__.py` + `main.py:796-816` · `cad-engine/server.py` (`/cad/v2/build`, multipart) ·
`owui_compat/fab_cad.py` (**migrated to v2 in this gate**) · `python_back_end/tests/test_cad_store.py` (new).

Everything in §7, including the composite parent FK, atomic head/seq, `base_revision_id` 409s, idempotency
keys, quotas and retention enforced in the store, and the orphan reaper. Before writing the DDL, confirm
`users.id`'s type and decide the FK; `adaptive_spaces` uses a bare `INTEGER` with no FK, so adding one is a
deliberate deviation to state in the commit.

`adaptive_space.py:656-658`'s destructive delete is **not** touched here — the adaptive lane keeps its
current behaviour until decision 2 is made.

**Success:** create a project, build a revision, restart the backend, and read it all back; a second build
of the same revision with the same idempotency key returns the first build; a stale `base_revision_id`
returns 409; quota exhaustion returns a structured error before bytes are written; a cross-user request for
any project, build or artifact returns 404; `storage_key` never appears in any response body.

**Rollback:** flag off, revert. Tables stay (dropping them is a separate approval).
**Disabled by default:** yes — routes exist, but `require_cad_enabled()` 404s them and no UI reaches them.
**Stop if:** an artifact row can outlive its bytes or vice versa without the reaper noticing.

---

### Gate 4 — One complete vertical slice

Template part → build job → authorized GLB → real viewer → parameter revision → restore → export. The first
gate a human can actually use, still flag-gated.

**Files:** `ChatControls/CadViewer.svelte` (new) · `ChatControls/CadStudioPanel.svelte` (minimal: viewport +
Parameters + Versions) · `lib/apis/cad/index.ts` (new) · `ChatControls.svelte` (the `'cad'` tab) ·
`agent-studio/ArtifactPreview.svelte:18-35`.

**Success:** end-to-end in a browser — the brick renders from a real authorized GLB, a slider change creates
a new revision and a new build, restore returns the earlier one, and all four exports open in independent
readers. GLB is self-contained (asserted: no external URI in the buffer). Chat with CAD disabled or the
engine down behaves normally — an explicit test.

**Stop if:** the viewer cannot render an authorized GLB without widening the artifact route's auth.

---

### Gate 5 — CadIR, plus the topological-naming spike

Two pieces, and the spike comes first because it can invalidate the design.

**Spike (timeboxed, written up before any CadIR code lands):** can a build123d/OCCT export carry per-feature
node names through booleans and fillets, so a clicked GLB triangle maps back to `support_tube[2]`? Options
to test: named glTF nodes per feature; a companion selection manifest mapping triangle ranges to feature
ids; or per-feature colour tagging. **If none survives booleans, the MVP is limited to whole-body selection
and the Features tab says so** — `FeatureRef.selectable = false` exists for exactly this outcome.

**CadIR:** only the operations the two tested recipes justify. Restricted-`ast` formulas — **no `eval`,
ever**. Static budget before dispatch. Named recipes survive as trusted templates that emit CadIR.

**Files:** `cad-engine/cadir/{schema,interpret,budget,expr}.py` (new) · `owui_compat/cad_ir.py` (new) ·
`docs/design/2026-XX-XX-cad-topological-naming-spike.md` (new) · schema-migration fixtures.

**Success:** hanger and brick both expressible as CadIR, both still passing Gate 2's determinism and
measurement tests unchanged. **Stop if:** either golden test needs relaxing to accommodate the IR.

---

### Gate 6 — Full chat integration, settings, and the deep workspace

Everything in §9 not already delivered in Gate 4: the remaining inspector tabs, the composer entry, CAD-intent
suggestion, the capability chip, the structured selection chip, the result card, **user capability/install
status**, **admin profile/service controls**, and the Expand action that re-enables `/harvis/adaptive` behind
the same flag.

**One canonical document:** chat, parameters, source and feature tree all emit typed changes carrying
`base_revision_id`; conflicts surface as a 409 the UI explains. No hidden second model.

**Disabled by default:** the tab renders only when the capability endpoint is healthy and a project is
attached; every route still enforces the flag server-side.

---

### Gate 7 — Local AI generation and bounded repair

Prompt → DesignSpec → CadIR patch → static validation → execute → validate → bounded repair → **proposed**
revision the user accepts. Structured output validated against the schema; **no arbitrary Python**; a hard
repair cap; patches preferred over regeneration; **no silent provider or cloud fallback**; assumptions shown
before any accuracy claim. Benchmarked on dimensions / solid count / validity / feature count / runtime /
repair attempts — **not screenshot similarity.**

**Stop if:** no locally-installed model clears the benchmark. Report the numbers; do not paper over it.

---

### Gate 8 — Attachments, imports, markup

Real authorized bytes via `materialize_attachments()` (`attachments.py:285-352`), real image parts via
`build_image_parts()` (`:393-435`). **Resolve attachment ids only through an ownership-checked route** —
`attachments.py:99-107` has none, by its own admission. Import limits: size, count, decompression ratio,
parser time, geometry complexity, all inside the killable subprocess from 1B. STEP imports as exact
reference geometry with **no claim of recovered feature history**; STL/GLB/3MF as mesh bodies. Viewport
markup ties to camera pose + selection. Provenance recorded per asset.

---

### Gate 9 — Downstream fabrication

Export validation, Blender handoff, CLI slicer adapters, reusing `docs/plans/printer-integration-design.md`
unchanged. **Export, slice, upload and print-start remain four separate approvals.** No automatic printing.

---

## 11. Tests and acceptance gates

| Layer | Tests |
|---|---|
| Worker input (1A) | schema rejection of NaN/Inf/negative/unknown-key; clamps at every bound; admission-control rejection before geometry; output/tempdir/triangle caps |
| Worker kill path (1B) | deadline kills the **process group**; explicit cancel; tempdir removed after kill and after success; N+1 → 429; 100 kills leak no pid/fd/memory; `/health` stays responsive under load |
| Worker geometry | `brep_valid`; solid count; finite positive volume; bbox tolerance; watertight/manifold; STEP round-trip delta |
| Determinism (2) | canonical source hash equality; geometric equivalence across two builds; normalized mesh signature; stored-artifact `sha256` verified on read |
| Backend | flag enforced on every route; cross-user 404 on project/build/artifact; `storage_key` absent from all responses; structured error propagation; capability honesty when the sidecar is down |
| Persistence (3) | revisions insert-only; composite parent FK rejects a cross-project parent; atomic head/seq under concurrent inserts; stale `base_revision_id` → 409; idempotency returns the first build; quota exhaustion before bytes; reaper clears orphans |
| Frontend | viewer renders a fetched GLB and disposes on unmount; result card renders only from fetched state, never from token attributes; chat unaffected with CAD absent/unhealthy; selection chip rejected server-side when it names another user's revision |
| E2E (4) | brick from the composer → card → studio → parameter change → new revision → restore → four exports open in independent readers |

---

## 12. Risks

**Security.** Widening from named recipes to a CadIR trades the strongest posture available — no interpreter
at all — for capability. That makes Gates 1A and 1B **load-bearing** rather than defense-in-depth. Note
precisely what the network gives us: `internal: true` means **no external egress**; sibling containers on
`cad-internal` remain reachable, so the worker's isolation rests on it having no secrets, no socket, no
binds, and now no unkillable work — not on being unreachable. Attachment ownership
(`attachments.py:99-107`) must be closed before Gate 8. Imported-geometry parsers are new attack surface and
run only inside the killable subprocess.

**Performance.** Base64 costs +33% per hop (closed in Gate 3). Subprocess-per-build adds startup latency —
measured in 1B before any optimisation. Artifacts on disk avoid the WAL/backup blow-up that BYTEA would have
caused, but still need the quotas Gate 3 enforces.

**Deployment.** The `cad-engine` image carries an OCP/OCCT stack — Gate 0 records its measured size against
the 7.5 GB CI guard. Profile-gated, so the default set is unaffected. **Do not bump `build123d` or
`cadquery-ocp`**: 0.9.1 + 7.8.1.1 is the verified pair; OCP 7.9 removes `TopoDS.HashCode`.

**Licensing.** build123d Apache-2.0; OpenCascade LGPL-2.1-with-exception (dynamically linked in a separate
container — the exception applies, but the notice must ship); `py_lib3mf`'s notice needs checking and adding
to the dependency inventory. Zoo, if ever added: BYO key per user, never a shared Harvis key, and its terms
forbid using the service to develop competing technology — the local lane must stay independently derived
from permissively licensed sources.

**Honesty.** Valid geometry is not printable, printable is not strong, strong is not safe. Three separate
statements, never merged. `fab_stress.VERDICT_PHRASING` and its SF thresholds are the precedent.

---

## 13. Open decisions

**Settled:** CAD Studio is a new ChatControls tab · a new `cad_artifacts` table, **metadata only, bytes on
disk** · the first tranche is Gate 0 + 1A + 1B.

**Still yours to call — none block the first tranche:**

1. **Retention policy numbers.** The mechanism lands in Gate 3; the caps are your call — per-user bytes,
   per-project bytes, revisions retained.
2. **Adaptive Space's fate.** Gate 6 re-enables it as the deep Prototype & Fabrication workspace. Retire the
   old `/api/adaptive/.../cad/execute` lane at that point, or keep both?
3. **Does the CAD build become an LLM-callable tool?** That means `TOOL_SCHEMA` + `dispatch_tool`
   (`orchestration/tools.py:165,525`), not `make_tool` — a larger integration, and a different threat model.
4. **Zoo BYO-key lane** — Gate 9 or parked indefinitely? The research verdict is already written.
5. **Memory ceiling and concurrency cap** — 2 GB and a small N are starting guesses; Gate 2's benchmark and
   1B's latency measurement should set both.

---

## 14. Smallest recommended first execution tranche

**Gate 0 + Gate 1A + Gate 1B.** Backend and infrastructure only. No UI, no persistence, no new dependencies,
nothing user-visible. It closes the verified `NaN` hang, puts real limits on a worker that has none, and —
the part Rev 1 got wrong — makes a runaway build actually stoppable rather than merely reported as
timed out.

Files: `docker-compose.yaml` (one service block) · `cad-engine/server.py` · `recipes.py` · `validation.py`
(new) · `runner.py` (new) · `worker_main.py` (new) · `queue.py` (new) · `tests/test_input_hardening.py`,
`tests/test_kill_path.py` (new) · `owui_compat/fab_cad.py` · one new doc.

Each gate is one commit. Rollback is `git revert <commit>` plus a container recreate — never
`git checkout <paths>`, which would endanger the 96 unrelated dirty files.

---

## Verification of the tranche, end to end

1. Recreate the sidecar with the `cad` profile; read the effective limits **from the daemon**, not the YAML.
2. Re-run the golden hanger through both paths and compare **geometry metrics** to Gate 0 — not bytes.
3. Fire the malformed matrix (`NaN`, `Infinity`, negative, unknown key) and confirm each returns a structured
   error in under a second.
4. Start an unbounded build, let the deadline fire, and confirm via `ps` that **no process survives** in that
   group and the tempdir is gone.
5. Cancel a running build explicitly; confirm `cancelled`, not `failed`, and no survivors.
6. Saturate the concurrency cap; confirm honest 429s and a still-responsive `/health`.
7. Confirm the worker stays healthy, non-root and egress-blocked after all of it.
8. Confirm normal chat is entirely unaffected — the lane is still disabled server-side.

## Standing constraints honoured throughout

Nothing committed or pushed without explicit permission · no `git reset` / `checkout --` / `restore` /
`clean` / `stash` · the 96 unrelated dirty files are the user's and are never touched · no secrets printed ·
never `grep` on this box (it resolves to `ugrep` and wedges) · Python + `rg` for discovery · CAD stays
optional, profile-gated and server-side flag-enforced · print start is never automatic.
