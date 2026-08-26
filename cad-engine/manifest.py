"""The semantic scene manifest, and the GLB node ids that make it clickable (UX-A).

Two artifacts that only mean something together. ``scene-manifest.json`` describes what
the part *is* — an assembly holding bodies, each body holding the ordered features that
built it. The GLB describes what the part *looks like*. The manifest is useless for
selection unless a node in one can be matched to a node in the other, so this module
owns both halves: it derives the tree, and it writes the same opaque id into the GLB.

**Why the GLB has to be post-processed.** ``export_gltf`` goes through OpenCascade's XDE
document, which names every node after its internal label path — measured here, a
two-body compound came out as ``=>[0:1:1:2]`` and friends, ``Shape.label`` was discarded,
and the file carried no ``extras`` key at all. There is no exporter option for either.
So the ids are injected afterwards, by unpacking the GLB container, editing the JSON
chunk and repacking it. No new dependency: a GLB is a 12-byte header and length-prefixed
chunks, and :mod:`struct` reads that.

**Why bodies are counted from ``children`` and not from ``solids()``.** Measured: a
``BuildPart`` holding two boxes that never touch reports ``solids() == 2`` and exports as
**one** glTF node with one mesh. A tree claiming two bodies there would offer the user two
rows that the viewport cannot tell apart, and clicking either would highlight both. A
compound with real ``children``, by contrast, exports one node subtree per child, in
children order. So: children if there are any, otherwise exactly one body. The tree never
claims a distinction the viewport cannot honour.

**Why features are not selectable.** They have no ``glb_pick_key`` and
``selectable: false``, because after a boolean there is nothing in the mesh that belongs
to the operation that made it — the Gate 5a spike proved build123d discards the builder
carrying that attribution (``docs/design/2026-08-03-cad-topological-naming-spike.md``).
The tree still shows them, in order, with status, because the *order and status* are
true even when the geometry attribution is not, and ``selection.reason`` in the manifest
carries that sentence so the UI never has to invent its own explanation.

**Why a part is keyed on its name and carries a colour** (CS-2). A body's id used to be
derived from its slot, which meant inserting a second component renumbered the first and
the explorer lost the selection it had. Keying on the component's declared name instead
makes "the bottle" the same node across every revision that still has a bottle, and the
colour is hashed from that same key — so the bottle is the same blue in the viewport, in
the tree and after a rebuild, without any surface choosing for itself. The colour is
presentation only: it is written into the manifest, never into the exported geometry.

Gate 7D's named components change **where** a feature hangs, not whether it can be
clicked. An operation that names a component parents to that component's body, so the
tree finally says which part each step built — declared by the author rather than
inferred from geometry that does not carry it. The body is selectable; the features under
it are not, for the boolean reason above, which no amount of naming changes.
"""
from __future__ import annotations

import hashlib
import json
import struct

SCHEMA_VERSION = "0.1"

KINDS = ("assembly", "body", "feature", "reference")
STATUSES = ("planned", "building", "valid", "error", "suppressed")

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942

# Why nothing in the tree is face- or edge-selectable yet, in the words the UI shows.
# It lives here rather than in a Svelte string so the claim and the code that makes it
# true cannot drift apart.
SELECTION_REASON = (
    "Whole bodies can be selected. Individual features cannot: after a boolean "
    "operation the resulting surface carries no record of which step produced it, so "
    "a click cannot be attributed to one. Faces and edges are unavailable for the "
    "same reason."
)


# A part's colour, and the twelve it is chosen from (CS-2).
#
# Pastels, all around the same lightness, so no body reads as "the important one" and
# every one of them still takes a dark silhouette outline legibly in the illustrated
# display mode. This is *viewport presentation only*: it is written into the manifest,
# never into the STEP/STL geometry, which stays exactly what the engine measured.
PALETTE = (
    "#9EC5E8",  # sky — first only for ordering; the hash decides who gets it
    "#E8A0A0",  # rose
    "#BFE39E",  # leaf
    "#C79EE8",  # lilac
    "#E8C39E",  # apricot
    "#9EE0E0",  # aqua
    "#E89ED2",  # orchid
    "#E8DE9E",  # wheat
    "#A8AFE8",  # periwinkle
    "#9EE3B4",  # mint
    "#C9B79A",  # sand
    "#B0BCC6",  # slate
)


def part_key(label: str, slot: int) -> str:
    """The identity of one body, preferring the name its author gave it.

    A component the document *named* keeps that name as its key, so "bottle" is the same
    part in revision 2 as in revision 9 even if a "cap" was inserted before it. Only an
    unnamed body falls back to its position, which is the most that can honestly be said
    about it.

    The two spaces are prefixed apart because a component could legitimately be called
    ``"0"``, and a name colliding with a slot number would silently merge two parts.
    """
    name = (label or "").strip()
    return f"name:{name}" if name else f"slot:{slot}"


def color_for(key: str) -> str:
    """A stable pastel for one part key.

    Hashed rather than assigned in order, because order is the thing that is *not*
    stable: adding a second component must not repaint the first. The same part
    therefore keeps its colour across revisions, across sessions, and between the
    viewport and the tree — which is the whole point of putting the colour on the
    manifest instead of letting each surface pick its own.
    """
    digest = hashlib.sha256(f"harvis-cad-color:{key}".encode()).hexdigest()
    return PALETTE[int(digest[:8], 16) % len(PALETTE)]


def node_id(scope: str, kind: str, key: str) -> str:
    """An opaque id that is stable across revisions of the same document.

    Derived from *structure* — the document's name, the kind, and the op_id or
    :func:`part_key` — and deliberately **not** from parameter values or the source
    hash. A slider
    edit produces a new revision of the same tree, and if the ids moved with it the
    explorer would collapse its expansion and drop its selection on every build. It
    also means a body id can be compared across two revisions, which is what the
    compare view needs.

    Opaque because the id crosses into the GLB and into model-facing context: it must
    not spell out an internal name, and the model receives ids rather than structure it
    could forge.
    """
    digest = hashlib.sha256(f"harvis-cad-node:{scope}:{kind}:{key}".encode()).hexdigest()
    return f"node_{digest[:16]}"


def _humanize(op_id: str) -> str:
    """``neck_threads`` -> ``Neck threads``. The author already chose a meaningful name;
    this only makes it presentable, and never invents one."""
    return op_id.replace("_", " ").strip().capitalize() or op_id


def bodies_of(part) -> list[str]:
    """The labels of the bodies this part will export as, in GLB node order.

    The return length is the contract: it is exactly how many mesh subtrees the GLB
    will have, so a manifest built from it can never promise a pick key that has
    nowhere to land.
    """
    children = list(getattr(part, "children", None) or [])
    if not children:
        return [""]
    return [str(getattr(c, "label", "") or "") for c in children]


def plan(doc, steps, *, scope: str, error_op_id: str | None = None) -> list[dict]:
    """The feature rows, from the document alone — no geometry needed.

    Called on a *failed* build too, which is the point: the workspace has to show which
    operation went wrong, and by then there is no GLB to derive anything from. Every
    operation the document declares gets a row; the ones the plan dropped are marked
    ``suppressed`` with the guard that dropped them, so "why is that grey" has an
    answer on screen instead of in a log.
    """
    ran = {op.op_id: pts for op, pts in (steps or [])}
    rows = []
    for op in doc.operations:
        planned = op.op_id in ran
        if op.op_id == error_op_id:
            status = "error"
        elif planned:
            status = "valid"
        else:
            status = "suppressed"
        row = {
            "op_id": op.op_id,
            "label": _humanize(op.op_id),
            "op": op.op,
            "mode": getattr(op, "mode", "add"),
            "status": status,
            "instances": len(ran.get(op.op_id, ())) if planned else 0,
            "optional": bool(getattr(op, "optional", False)),
            # Which body this operation built, when the document said. This is the whole
            # of feature attribution: the author declared it, so nothing here has to
            # infer it from geometry that does not carry it.
            "component": getattr(op, "component", None),
        }
        when = getattr(op, "when", None)
        if when is not None:
            # The guard text, not a boolean: "when thread_count >= 1" tells the user
            # which parameter to change, and "false" tells them nothing.
            row["when"] = str(when)
        rows.append(row)
    return rows


def compose(*, scope: str, label: str, bodies: list[str], features: list[dict],
            body_status: str = "valid") -> dict:
    """Assemble the manifest from the two halves that were derived separately.

    ``bodies`` comes from the geometry (or is a single placeholder before the build has
    run); ``features`` comes from the document. They are joined here rather than in
    either producer so there is exactly one place that decides parenting, and one place
    that decides what is selectable.
    """
    root = node_id(scope, "assembly", "root")
    nodes: list[dict] = [{
        "node_id": root,
        "parent_id": None,
        "label": label or scope or "Design",
        "kind": "assembly",
        "status": body_status,
        "selectable": False,
    }]

    body_ids = []
    used: set[str] = set()
    taken: set[str] = set()
    for slot, body_label in enumerate(bodies):
        # Named parts key on their name so the id and the colour survive a sibling being
        # inserted before them; a duplicate name would merge two real bodies into one
        # id, so the second one falls back to its slot.
        key = part_key(body_label, slot)
        if key in used:
            key = f"slot:{slot}"
        used.add(key)
        bid = node_id(scope, "body", key)
        body_ids.append(bid)

        # Two parts landing on the same swatch is only a display collision, so it is
        # resolved by walking the palette rather than by changing the key — the id, and
        # therefore selection and the code view, stay keyed on identity alone.
        color = color_for(key)
        if color in taken and len(taken) < len(PALETTE):
            start = PALETTE.index(color)
            for i in range(1, len(PALETTE)):
                alt = PALETTE[(start + i) % len(PALETTE)]
                if alt not in taken:
                    color = alt
                    break
        taken.add(color)

        nodes.append({
            "node_id": bid,
            "parent_id": root,
            "label": body_label or (label or "Body") if len(bodies) == 1 else (body_label or f"Body {slot + 1}"),
            "kind": "body",
            "status": body_status,
            # The name the document gave this part, or null when it named none. The
            # tree, the code view and any future per-part file all need the same answer
            # to "which part is this", and this is it.
            "component": (body_label or "").strip() or None,
            "color": color,
            # The only selectable kind, and only once the build has actually produced
            # it — a planned body has no mesh to pick.
            "selectable": body_status == "valid",
            "glb_pick_key": bid if body_status == "valid" else None,
        })

    # Features parent to the body their operation named, when the document named one —
    # that is what Gate 7D's components buy, and the bodies arrive here in component
    # order because the interpreter builds them in it. Without names there is one body
    # to parent to, or, with several, the assembly: nothing then knows which body an
    # operation contributed to, and guessing would put a feature under the wrong part.
    by_component = {label: bid for label, bid in zip(bodies, body_ids) if label}
    fallback = body_ids[0] if len(body_ids) == 1 else root
    for row in features:
        nodes.append({
            "node_id": node_id(scope, "feature", row["op_id"]),
            "parent_id": by_component.get(row.get("component")) or fallback,
            "label": row["label"],
            "kind": "feature",
            "status": row["status"],
            "selectable": False,
            "cadir_operation_id": row["op_id"],
            "glb_pick_key": None,
            "op": row["op"],
            "mode": row["mode"],
            "instances": row["instances"],
            "optional": row["optional"],
            **({"when": row["when"]} if "when" in row else {}),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "root_id": root,
        "nodes": nodes,
        "selection": {
            "selectable_kinds": ["body"],
            "faces": False,
            "edges": False,
            "reason": SELECTION_REASON,
        },
    }


# ---------------------------------------------------------------------------
# GLB rewriting
# ---------------------------------------------------------------------------

def _unpack(raw: bytes) -> tuple[dict, bytes]:
    magic, _version, total = struct.unpack_from("<III", raw, 0)
    if magic != _GLB_MAGIC:
        raise ValueError("not a GLB container")
    gltf = None
    binary = b""
    off = 12
    while off + 8 <= min(total, len(raw)):
        length, kind = struct.unpack_from("<II", raw, off)
        body = raw[off + 8: off + 8 + length]
        if kind == _CHUNK_JSON:
            gltf = json.loads(body.decode("utf-8").rstrip("\x00").rstrip())
        elif kind == _CHUNK_BIN:
            binary = body
        off += 8 + length
        off += (4 - off % 4) % 4
    if gltf is None:
        raise ValueError("GLB has no JSON chunk")
    return gltf, binary


def _pack(gltf: dict, binary: bytes) -> bytes:
    # Separators without spaces keep the chunk as small as it was; the padding below is
    # what the spec requires, and it is spaces for JSON and zeros for BIN.
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    chunks = [struct.pack("<II", len(js), _CHUNK_JSON) + js]
    if binary:
        bn = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
        chunks.append(struct.pack("<II", len(bn), _CHUNK_BIN) + bn)
    body = b"".join(chunks)
    return struct.pack("<III", _GLB_MAGIC, 2, 12 + len(body)) + body


def _mesh_nodes_by_slot(gltf: dict) -> list[list[int]]:
    """Mesh-bearing node indices, grouped by which top-level child of the scene root
    they descend from.

    A single-body export has the mesh on the scene root itself and no children at all
    (measured: a bare ``Box`` and the brick recipe both export as exactly one node), so
    that case yields one group. Anything else groups by root child, in order — which is
    ``Compound.children`` order, asserted by ``test_manifest.py`` against three bodies
    with distinct geometry so a reordering by the exporter fails loudly instead of
    silently mislabelling every body in the tree.
    """
    nodes = gltf.get("nodes") or []
    scenes = gltf.get("scenes") or []
    if not nodes or not scenes:
        return []
    roots = scenes[gltf.get("scene", 0)].get("nodes") or []

    def walk(i: int, seen: set[int]) -> list[int]:
        if i in seen or i >= len(nodes):
            return []
        seen.add(i)
        found = [i] if "mesh" in nodes[i] else []
        for c in nodes[i].get("children") or []:
            found.extend(walk(c, seen))
        return found

    groups: list[list[int]] = []
    for root in roots:
        kids = nodes[root].get("children") or []
        if kids:
            for k in kids:
                groups.append(walk(k, set()))
        else:
            groups.append(walk(root, set()))
    return groups


def tag_glb(path: str, pick_keys: list[str]) -> list[str]:
    """Write one pick key into the GLB per body, and report which ones landed.

    The return value is the honest half. If the exporter produced a different number of
    mesh groups than the manifest expected, the extra bodies get no key and the caller
    drops their ``glb_pick_key`` rather than shipping a manifest whose keys point at
    nothing — a row that highlights nothing when clicked is worse than a row that says
    it cannot be selected.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    gltf, binary = _unpack(raw)
    groups = _mesh_nodes_by_slot(gltf)
    nodes = gltf.get("nodes") or []

    landed: list[str] = []
    for slot, key in enumerate(pick_keys):
        if slot >= len(groups) or not groups[slot]:
            landed.append("")
            continue
        for idx in groups[slot]:
            node = nodes[idx]
            node["name"] = key
            extras = node.get("extras")
            if not isinstance(extras, dict):
                extras = {}
            extras["harvis_node_id"] = key
            node["extras"] = extras
        landed.append(key)

    with open(path, "wb") as fh:
        fh.write(_pack(gltf, binary))
    return landed


def write(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), sort_keys=False)
