"""Artifact writers for the CAD sidecar (Gate 2).

Four formats, no new dependency: ``export_stl``/``export_step`` come straight from
build123d and already lived in :mod:`recipes`; GLB and 3MF were installed and unused
since the image was first built, and this module is where they start earning their
place.

Each writer is a thin, named function rather than a lookup into build123d, because
the *options* are the interesting part and they belong in one reviewable place:

* **STEP** — exact B-Rep. The only format that survives a round trip (measured at
  Gate 0: 5717.3 mm³ out, 5717.3 mm³ back, Δ 0.0000%).
* **STL** — triangles, no units in the file at all. A slicer assumes millimetres by
  convention; nothing in the bytes says so.
* **GLB** — binary glTF, for the viewer. Self-contained by construction here: no
  external URI, because we hand build123d a single shape and no textures.
* **3MF** — the print format that *does* carry units. ``Mesher(unit=Unit.MM)`` is
  passed explicitly even though MM is the library default, because the whole reason
  3MF is here is that the receiving slicer must read 32 mm and not 32 inches, and a
  default is a thing that can change under us.

**On determinism.** ``Mesher.add_shape`` mints a random UUID per write when it is not
given one, which is half of why two 3MF writes of the same shape in the same second
produced different bytes at Gate 0 (``d0243b4a…`` vs ``764b738a…``). We pass a UUID
derived from the build's canonical source hash instead, so the identifier is a
function of the input rather than of the clock. That removes one source of variance;
it does not make 3MF byte-stable, because the container is a ZIP and ZIPs carry their
own per-write metadata. Byte-identity is not the acceptance gate for anything here —
see :func:`validation.mesh_signature` and :func:`recipes.canonical_source_hash`.
"""
from __future__ import annotations

import uuid

from build123d import Mesher, Unit, export_gltf, export_step, export_stl

# The names a caller may ask for. Ordered so the frozen pair the backend already
# consumes comes first; anything else is additive.
FORMATS = ("stl", "step", "glb", "3mf")
DEFAULT_FORMATS = ("stl", "step")

MEDIA_TYPES = {
    "stl": "model/stl",
    "step": "model/step",
    "glb": "model/gltf-binary",
    "3mf": "model/3mf",
}

# build123d's own defaults, restated so every format tessellates the SAME surface.
# If STL and GLB deflected differently, the mesh signature of one would not describe
# the other, and "the viewer shows what the slicer will print" would stop being true.
LINEAR_DEFLECTION = 0.001
ANGULAR_DEFLECTION = 0.1


def _stable_uuid(seed: str) -> uuid.UUID:
    """A UUID that is a function of the build, not of the clock."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"harvis-cad:{seed}")


def write_stl(part, path: str) -> None:
    export_stl(part, path)


def write_step(part, path: str) -> None:
    export_step(part, path)


def write_glb(part, path: str) -> None:
    export_gltf(
        part,
        path,
        unit=Unit.MM,
        binary=True,
        linear_deflection=LINEAR_DEFLECTION,
        angular_deflection=ANGULAR_DEFLECTION,
    )


def write_3mf(part, path: str, *, seed: str = "") -> None:
    mesher = Mesher(unit=Unit.MM)
    mesher.add_shape(
        part,
        linear_deflection=LINEAR_DEFLECTION,
        angular_deflection=ANGULAR_DEFLECTION,
        uuid_value=_stable_uuid(seed) if seed else None,
    )
    mesher.write(path)


def write(fmt: str, part, path: str, *, seed: str = "") -> None:
    """Dispatch by format name. Unknown names raise rather than skipping quietly —
    a caller that asked for ``gltf`` and got nothing back would read the empty result
    as "the part has no mesh"."""
    if fmt == "stl":
        write_stl(part, path)
    elif fmt == "step":
        write_step(part, path)
    elif fmt == "glb":
        write_glb(part, path)
    elif fmt == "3mf":
        write_3mf(part, path, seed=seed)
    else:
        raise ValueError(f"unknown export format: {fmt}")
