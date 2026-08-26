# CAD topological naming — Gate 5a spike

**Date:** 2026-08-03 · **Branch:** `harvis1.2` · **Gate 4 commit:** `17a6698f`
**Environment:** `harvis-cad` container — build123d 0.9.1, cadquery-ocp 7.8.1.1, Python 3.11.15
**Status:** answered. No CadIR code was written before this document existed, per the Gate 5 plan.

---

## The question

Can a build123d/OCCT export carry per-feature identity through booleans and fillets, so that a
clicked GLB triangle maps back to `support_tube[2]`?

The plan named three candidate mechanisms and required one to survive booleans, or else the MVP
falls back to whole-body selection and `FeatureRef.selectable = false`:

1. named glTF nodes, one per feature
2. a companion selection manifest mapping triangle ranges to feature ids
3. per-feature colour tagging

## The answer

**Yes — mechanism 2, in a simpler form than the plan assumed.** The manifest does not need triangle
ranges. `export_gltf` emits **one glTF primitive per B-Rep face**, in B-Rep face order, so the
manifest is a flat list of feature ids indexed by primitive index. Nothing is embedded in the GLB;
the picker reads `intersection.object`'s primitive index and looks it up.

Mechanism 1 does not work and mechanism 3 was not needed.

Feature identity survives fuse, cut, fillet, a parameter change, and a topology change. The
remaining limit is stated in §6 and it is real.

---

## 1. Spike A — do named glTF nodes survive?

Labelled the operands, built a `Compound`, exported.

**Result: no.** A `Compound` flattens per-feature labels to a single generic `SOLID` node. Feature
names do not reach the glTF node graph.

**But the same run found the mechanism that does work:** a 6-face box exports as one named mesh
containing **six primitives** — one per B-Rep face. That is the channel this whole design now rests
on, and it was not known before this spike.

---

## 2. Spike B — does OCCT history attribute result faces to source features?

`BRepAlgoAPI_*` exposes `Modified(shape)`, `Generated(shape)` and `IsDeleted(shape)`. Walking every
operand face and asking those three questions attributes each result face to the feature it came
from.

| Operation | Result faces | Attributed | Unattributed | Modified | Generated | Deleted |
|---|---|---|---|---|---|---|
| Fuse (plate + tube) | 9 | **9** | 0 | 5 | 3 | 0 |
| Cut (plate − tube) | 7 | **7** | 0 | 3 | 3 | 2 |

A face the builder never mentions was carried through unchanged and is matched by identity — that
third case matters, and omitting it leaves faces unnamed.

**Stability, same spike:**

- **B4** — two independent builds of identical input produce identical face order *and* identical
  per-face area and centre of mass.
- **B5** — a parameter change (tube radius 4.0 → 6.0) produces a **byte-for-byte identical id
  sequence**. This is the revision case, and it holds.

### The trap that cost the most time

The first version of this spike reported `Counter({'?': 14})` — every lookup missed — and read as
"OCCT history does not work." It was wrong.

**`TopoDS_Shape` wrappers do not compare by Python identity across separate `TopExp_Explorer`
walks.** A plain `dict` keyed on them misses every lookup. The correct key is
`TopTools_IndexedMapOfShape`, which uses OCCT's own hashing and `IsSame` equality. `.Add(s)` returns
the existing index when the shape is already present, so it doubles as an interning function:

```python
class ShapeTags:
    """A tag table keyed the way OCCT compares shapes, not the way Python does."""
    def __init__(self):
        self.map, self.tags = TopTools_IndexedMapOfShape(), {}
    def set(self, s, tag):        self.tags[self.map.Add(s)] = tag
    def setdefault(self, s, tag): self.tags.setdefault(self.map.Add(s), tag)
    def get(self, s):             return self.tags.get(self.map.Add(s))
```

Any Gate 5b code that tracks shapes must use this. A Python dict keyed on shapes will silently
return nothing.

---

## 3. Spike C — does the chain survive a fillet?

A fillet is a second operation consuming the first one's result, so it tests chaining, not just
single-op attribution.

Of the fused shape's 32 edges, **28 filleted successfully** at r=0.5. Applying four of them:

| | Faces | Attributed | Unattributed |
|---|---|---|---|
| After fillet | 13 | **9** | 4 |

**The 4 unattributed faces are exactly the 4 fillet surfaces.** They are new geometry belonging to
the fillet *operation*, which is itself a feature and gets its own id. This is correct semantics,
not a gap — but it must be handled explicitly, because those faces have no source face to inherit
from.

### The trap here

`Standard_Failure: There are no suitable edges for chamfer or fillet` appeared twice and looked like
a geometry limitation. It was not. `TopExp_Explorer.Current()` returns `TopoDS_Shape`, and
`BRepFilletAPI_MakeFillet.Add(radius, edge)` wants a `TopoDS_Edge`. The resulting `TypeError` was
being swallowed by a bare `except`, so zero edges were ever added and the builder complained about
having nothing to do. The fix is `TopoDS.Edge_s(shape)`.

---

## 4. Spike C2 — does glTF primitive *i* correspond to B-Rep face *i*?

| Shape | B-Rep faces | glTF primitives | In-order bbox matches | Max delta |
|---|---|---|---|---|
| Fuse | 9 | 9 | **9/9** | 0.0012 mm |
| Cut | 7 | 7 | **7/7** | 0.0009 mm |

Tessellation deflection was 0.001 mm, so the deltas are at the tessellation floor. Primitive order
is face order.

**C3 — order stability across a parameter change:** r=4.0 and r=6.0 produce the same primitive count
and the same id sequence.

### The unit trap — this one will bite the picker if it is forgotten

**`export_gltf` writes glTF in METRES regardless of `unit=Unit.MM`.** That parameter tells the
exporter what the *input* is; every exported coordinate is 1/1000 of the model value.

The first version of this comparison reported `0/9` matches and read as "primitives don't correspond
to faces." It was comparing millimetres against metres. Anything in `CadViewer` or a future picker
that reasons about GLB coordinates in millimetres is wrong by three orders of magnitude.

---

## 5. Spike D1 — does identity survive a *topology* change?

The previous spikes all changed parameters. This one adds a third feature — a second tube — to an
already-attributed shape, then asks whether any pre-existing id now names geometry belonging to a
different feature.

**Result: 12 faces, 0 unattributed. No id crossed a feature boundary.**

| id | Before | After | Verdict |
|---|---|---|---|
| `base_plate[0..3]` | 1 face each | 1 face each, identical | unchanged |
| `base_plate[4]` (bottom) | 2 faces: plate underside + tube-1 footprint | 3 faces: plate underside (smaller) + tube-1 footprint + tube-2 footprint | **correct** — the second fuse split its own face again |
| `base_plate[5]` (top) | 371.73 mm² | 343.45 mm² | **correct** — the second tube pierces it |
| `support_tube[0..1]` | 2 faces | 2 faces, identical | unchanged |
| `second_tube[0..1]` | — | 2 faces | new feature |

An earlier version of this experiment reported `base_plate[4]` "migrating" from `(3,7,0)-(9,13,0)`
to `(11,7,0)-(17,13,0)`. That was a harness bug: the results dict was keyed on the id, so when one
source face legitimately splits into several result faces — all correctly carrying the same id —
only the last survived and the id appeared to jump. Keeping every face per id shows the attribution
was right the whole time.

---

## 6. The limit, stated without softening

**A feature id is stable. A position *within* a multi-face id is not.**

`base_plate[4]` names two surfaces before the second tube and three after. A saved selection stored
as "the second face of `base_plate[4]`" points at the tube-1 footprint before the edit and at the
tube-2 footprint after it — a silent, wrong pick. So:

- **Selection may be stored as a feature id.** Stable across parameter changes and across adding
  operations.
- **Selection may not be stored as a face ordinal within a feature id.** Any UI that lets a user
  pick one face out of a multi-face feature must either re-resolve it geometrically on each build or
  invalidate it when the operation list changes.

A second constraint applies to the id scheme itself. `base_plate[4]` means "the 5th face of the box
primitive," which is stable only while that primitive stays a box. If the author changes a `Box` to
a `Cylinder`, the index means something different. Gate 5b must key on an **author-stable `op_id`**
assigned when the operation is created and never renumbered — the index after it is only meaningful
relative to that op's own primitive kind.

Where a selection cannot be resolved, the plan's existing fallback applies unchanged:
`FeatureRef.selectable = false`, the chip says **"Selected: whole body"**, and the Features tab says
so plainly.

---

## 7. Consequence for Gate 5b — build123d's operators cannot be used

The attribution above requires holding the `BRepAlgoAPI_*` builder after `Build()`. build123d does
not give it back:

```
Shape.__add__ mentions BRepAlgoAPI:      False
Shape.fuse mentions BRepAlgoAPI_Fuse:    True
  | fuse_op = BRepAlgoAPI_Fuse()
  | return_value = self._bool_op((self,), to_fuse, fuse_op)
  | return return_value          # the shape, not the builder
```

`fuse_op` is a local and is discarded. **The CadIR interpreter must own its builder instances** —
construct `BRepAlgoAPI_Fuse` / `_Cut` / `BRepFilletAPI_MakeFillet` directly, call `Build()`, harvest
history, then wrap the result in a build123d `Solid` for export. build123d's `+` and `-` remain fine
anywhere history is not needed.

This is a real cost in Gate 5b, and it was not in the plan's estimate.

---

## 8. What Gate 5b should implement

1. Each CadIR operation carries an author-stable `op_id`. Face ids are `{op_id}[{index}]`, where the
   index is the `TopExp_Explorer` position within that operation's own primitive.
2. The interpreter drives `BRepAlgoAPI_*` / `BRepFilletAPI_*` directly and chains tags through
   `Modified` / `Generated` / `IsDeleted` / carried-through, keyed on `TopTools_IndexedMapOfShape`.
3. Faces a fillet generates get the fillet operation's own id, not the source feature's.
4. The build emits a selection manifest alongside the GLB: a flat list of feature ids, index-aligned
   to glTF primitive index. It is a build artifact, not a revision field — it is derived and
   regenerable.
5. `FeatureRef.gltf_node` stays `null`. Named nodes do not survive; the manifest replaces them.
6. `FeatureRef.selectable` is `true` for a feature id, and the UI never persists a face ordinal
   within one.
7. Any GLB-coordinate arithmetic scales by 1000. The exporter writes metres.

---

## 9. Verification harnesses

The five scripts behind these numbers were run with `docker exec -i harvis-cad python - < script.py`
(`cad-engine` has no bind mounts; the container is `read_only: true` with a 512 MB tmpfs on `/tmp`).
They are experiments, not deliverables, and are not committed — the reproducible content is the
tables above and the code excerpts in §2 and §7.

| Spike | Question | Verdict |
|---|---|---|
| A | Do named glTF nodes survive a Compound? | No — but one primitive per face does |
| B | Does OCCT history attribute faces to features? | Yes — 9/9 fuse, 7/7 cut |
| C | Does the chain survive a fillet? | Yes — 9 attributed, 4 fillet surfaces are the fillet's own |
| C2 | Is primitive *i* == face *i*? | Yes — 9/9 and 7/7, ≤0.0012 mm |
| D1 | Does identity survive a topology change? | Yes — 0 unattributed, no id crossed a feature |
| D2 | Does build123d expose the OCCT builder? | No — the interpreter must own it |
