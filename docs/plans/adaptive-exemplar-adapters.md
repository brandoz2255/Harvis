# Adaptive Space exemplar workflows — tool-adapter interfaces (P9)

The three exemplar templates (`social-post`, `fabrication`, `image-to-3d`) are
**tool-orchestrated**: the LLM routes between real tools and never fakes their
output. This doc pins the per-stage adapter contracts so real adapters can land
later, each behind its own gate. Until then, every execute-class stage routes to
the **mock adapter** (`POST /api/adaptive/spaces/{id}/mock-execute`), which
records `"Prepared successfully — no real action was taken (mock adapter)."` and
performs nothing.

## Common adapter contract

Matches `docs/plans/printer-integration-design.md`'s `PrinterAdapter` shape:

```python
class ToolAdapter(Protocol):
    def prepare(self, inputs: dict) -> PrepareResult      # validate + stage inputs
    def preview(self, prepared_id: str) -> PreviewResult  # exactly what WOULD happen
    def execute(self, prepared_id: str, approval: ApprovalToken) -> ExecResult
    def status(self, exec_id: str) -> StatusResult
```

Rules that apply to every adapter:
- `execute` requires an **ApprovalToken**: single-use, bound to the content hash
  of the previewed payload, minted only by an explicit user click. Agents cannot
  mint or reuse one — changing the payload after preview invalidates the token.
- `preview` output must be byte-faithful to what `execute` would do (same
  caption text, same mesh file hash, same G-code).
- All executions append an audit entry to the space manifest (`linked_runs`).
- **Mock first**: each real adapter ships alongside its mock, selected by an
  explicit env flag per adapter (`HARVIS_ADAPTER_<NAME>`), default mock.

## social-post (Action Studio)

| Stage | Adapter call | Real tool (later, gated) |
|---|---|---|
| asset pick | `prepare({media_path})` | file registry / artifact store |
| caption | LLM generation (content only — not an adapter) | — |
| preview | `preview()` → rendered post (platform, media ref, caption) | — |
| execute | `execute(approval)` | per-platform adapter (Instagram etc.) — **separate gated phase**; policy: user-approved, no unattended/mass posting |

## fabrication

| Stage | Adapter call | Real tool (later, gated) |
|---|---|---|
| CAD generation | `prepare({spec})` → script candidates | OpenSCAD / FreeCAD CLI |
| checks | `preview()` → geometry/sanity report | mesh check (admesh/trimesh class) |
| export | `execute(approval)` → STL/3MF file artifact | slicer CLI (Prusa/Cura) — CLI-lane |

Assisted prototyping framing is part of the contract: adapter outputs carry an
`assumptions` field (material, load, margin) and a not-certified disclaimer.

## image-to-3d

| Stage | Adapter call | Real tool (later, gated) | Lane |
|---|---|---|---|
| generate | `prepare({image})` | image-to-3D model (TripoSR/Hunyuan3D class) | **dev-rig GPU** — exceeds the 8GB laptop ceiling |
| repair/check | `preview()` | watertight/manifold repair (trimesh/meshlab class) | backend |
| sim hook | optional `preview()` extension | FEA engine (CalculiX class) — real engineering domain, assumptions logged | dev-rig |
| printability | `preview()` | slicer dry-run | backend/CLI |
| export | `execute(approval)` | STL/3MF writer → printer workflow (see printer design doc) | CLI-lane |

## Gate summary (nothing below is enabled by this phase)

| Gate | Flag | Status |
|---|---|---|
| Real social platform adapter | per-adapter `HARVIS_ADAPTER_SOCIAL_*` | not built |
| CAD/mesh/sim/slicer adapters | `HARVIS_ADAPTER_FAB_*` | not built |
| Printer send | see printer design doc | design only |
| Mock adapter | none needed | live, side-effect-free |
