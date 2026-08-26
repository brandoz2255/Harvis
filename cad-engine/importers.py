"""Gate 8B — geometry a user brings in, parsed under the same limits as geometry we make.

Every other input this engine takes is a description we wrote the vocabulary for: a
recipe name off an allowlist, or a CadIR document a schema and a budget have already
walked. An imported file is the first input that is *data for a parser we did not
write* — OpenCascade's STEP reader, lib3mf's ZIP reader — and those parsers are C++
reading attacker-shaped bytes. So the posture here is different from the rest of the
engine: assume the file is hostile, spend as little as possible before deciding, and
never let the parser be the thing that discovers the file is too big.

Three ideas carry the module.

**Cheap structural checks come before the parser.** A 3MF is a ZIP, so its declared
uncompressed size, entry count and compression ratio are all readable from the central
directory without inflating a byte — which is the only moment a zip bomb is cheap to
refuse. A binary STL declares its triangle count in bytes 80-84, so a claimed 80-million-
triangle mesh is rejected in four bytes rather than after OCCT has allocated for it. A
STEP file's entity count is one pass over ASCII. None of these is a substitute for the
post-parse checks; they are what keeps the parse from being the expensive part.

**What comes back differs by format, and the difference is not cosmetic.** Measured
here on the same 10x20x30 box:

    STEP  -> Solid, volume 6000.0    exact B-Rep
    3MF   -> [Solid], via lib3mf     a closed shell OCCT rebuilt into a solid
    STL   -> Face, area 2200.0       a triangle soup; there is no volume to ask for

So a STEP import is exact reference geometry and an STL import is a mesh body, and
``provenance["exact"]`` says which. What none of them is, ever, is recovered design
intent: no importer here returns parameters, features, or a history you can edit. STEP
carries a solved shape, not the sketch that made it. ``recovered_features`` is False on
every path in this file and there is no branch that sets it True — if that ever changes
it should be because someone built a feature-recognition pass, not because a format
looked promising.

**This runs in the child, not the server.** Everything here is reached through
``worker_main``'s ``source_kind: "import"`` job, which means an import inherits Gate 1B
wholesale: its own process group, the parent's deadline, SIGTERM then SIGKILL, and a
workdir the parent removes either way. A parser that hangs on a malformed file is
exactly the failure mode Gate 1B exists for, and it would have been a mistake to give
imports their own quieter path around it.

GLB is deliberately absent. It is an *export* format here — the viewer's — and
build123d ships no glTF reader, so importing one would mean adding a mesh/JSON parser
to the one container that must not grow new parsers casually. Named in
:data:`UNSUPPORTED` so the caller gets a reason rather than "unknown format".
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
import zipfile

# Formats we can read. Extensions map onto these; the value is what the rest of the
# module switches on.
KINDS = ("step", "stl", "3mf", "brep")

_EXT_KIND = {
    ".step": "step", ".stp": "step",
    ".stl": "stl",
    ".3mf": "3mf",
    ".brep": "brep", ".brp": "brep",
}

# Formats we recognise and refuse, with the reason. Better than "unknown extension":
# a user who attaches a .glb should learn it is an output format here, not that Harvis
# has never heard of it.
UNSUPPORTED = {
    ".glb": "GLB is an export format here — build123d ships no glTF reader. "
            "Export as STEP, STL or 3MF instead.",
    ".gltf": "glTF is an export format here — build123d ships no glTF reader. "
             "Export as STEP, STL or 3MF instead.",
    ".obj": "OBJ is not supported. Export as STL or 3MF instead.",
    ".f3d": "Fusion archives are a proprietary container. Export as STEP instead.",
    ".sldprt": "SolidWorks parts are a proprietary format. Export as STEP instead.",
    ".ipt": "Inventor parts are a proprietary format. Export as STEP instead.",
    ".iges": "IGES is not enabled. Export as STEP instead.",
    ".igs": "IGES is not enabled. Export as STEP instead.",
}

# Caps. Every one of these is a refusal, never a truncation: half a part is worse than
# no part, because the user cannot see which half is missing.
MAX_ASSET_BYTES = int(os.environ.get("CAD_IMPORT_MAX_BYTES", 32 * 1024 * 1024))
MAX_STL_TRIANGLES = int(os.environ.get("CAD_IMPORT_MAX_TRIANGLES", 400_000))
MAX_STEP_ENTITIES = int(os.environ.get("CAD_IMPORT_MAX_ENTITIES", 200_000))
MAX_SOLIDS = int(os.environ.get("CAD_IMPORT_MAX_SOLIDS", 64))

# ZIP containment for 3MF. The ratio is the bomb check; the absolute cap is the backstop
# for a bomb patient enough to stay under the ratio.
MAX_ZIP_ENTRIES = 64
MAX_ZIP_RATIO = 100
MAX_ZIP_UNCOMPRESSED = 128 * 1024 * 1024

_STEP_ENTITY = re.compile(rb"^\s*#\d+\s*=", re.M)


# Every code :class:`ImportRejected` is raised with. Exported because the HTTP layer
# has to answer these 400 (the caller's file is wrong) and everything else 500 (we are
# wrong), and a hand-copied list in `server.py` is the kind that drifts silently —
# a new code would start returning 500 for a file the user could have fixed.
ERROR_CODES = frozenset({
    "import_unsupported_format",   # the extension names a format we do not read
    "import_empty",                # no bytes, or bytes that held no geometry
    "import_too_large",            # over a byte or entry cap
    "import_too_complex",          # over a triangle / entity / solid cap
    "import_malformed",            # the structure or the parser said no
})


class ImportRejected(ValueError):
    """A file we will not parse, with a code the caller can act on.

    Carries the same ``code``/``message`` shape as the CadIR errors so the worker's
    result-writing path does not need a second branch for imports.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def kind_for(name: str) -> str:
    """Which reader handles ``name``. Raises ImportRejected for anything else.

    Extension only, and on purpose: content-sniffing a format to decide which C++
    parser to hand it to is a way of letting the file choose its own reader.
    :func:`precheck` then verifies the content matches what the extension claimed, so a
    ``.step`` full of ZIP bytes is refused rather than quietly routed to lib3mf.
    """
    ext = os.path.splitext(name)[1].lower()
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    if ext in UNSUPPORTED:
        # The extension leads, because that is what the user typed and what they will
        # search their folder for. A message that only names the product ("SolidWorks
        # parts…") is correct and still leaves someone staring at `part.sldprt`
        # wondering whether it is the file being talked about.
        raise ImportRejected("import_unsupported_format",
                             f"{ext}: {UNSUPPORTED[ext]}")
    raise ImportRejected(
        "import_unsupported_format",
        f"{ext or 'that file'} cannot be imported as geometry — "
        f"supported: STEP, STL, 3MF, BREP.",
    )


def _stl_triangle_count(path: str, size: int) -> int | None:
    """Triangles a binary STL *claims* to hold, or None for ASCII.

    The count lives at offset 80 and the body is 50 bytes per triangle, so the claim is
    checkable against the file size — a mismatch means the header is lying, and a header
    that lies is the input worth refusing before OCCT allocates from it.
    """
    if size < 84:
        raise ImportRejected("import_malformed", "this STL is too short to be a mesh")
    with open(path, "rb") as fh:
        head = fh.read(84)
    if head[:5].lstrip().lower().startswith(b"solid"):
        return None                      # ASCII STL — size cap is the only bound
    (count,) = struct.unpack("<I", head[80:84])
    expected = 84 + count * 50
    if expected != size:
        raise ImportRejected(
            "import_malformed",
            f"this STL declares {count} triangles but its size fits "
            f"{max(0, (size - 84) // 50)}",
        )
    return count


def _precheck_zip(path: str) -> None:
    """3MF containment, read from the central directory without inflating anything."""
    if not zipfile.is_zipfile(path):
        raise ImportRejected("import_malformed", "this 3MF is not a valid container")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ImportRejected(
                "import_too_complex",
                f"this 3MF holds {len(infos)} entries; the limit is {MAX_ZIP_ENTRIES}",
            )
        total = sum(i.file_size for i in infos)
        if total > MAX_ZIP_UNCOMPRESSED:
            raise ImportRejected(
                "import_too_large",
                f"this 3MF expands to {total // (1024 * 1024)} MB; the limit is "
                f"{MAX_ZIP_UNCOMPRESSED // (1024 * 1024)} MB",
            )
        packed = sum(i.compress_size for i in infos) or 1
        if total // packed > MAX_ZIP_RATIO:
            raise ImportRejected(
                "import_malformed",
                f"this 3MF expands {total // packed}x; anything over "
                f"{MAX_ZIP_RATIO}x is treated as a decompression bomb",
            )
        # Traversal: lib3mf reads from the archive rather than to disk, but a member
        # named ../.. is a signal about the file regardless of who unpacks it.
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ImportRejected(
                    "import_malformed", "this 3MF contains an unsafe member path"
                )


def precheck(kind: str, path: str) -> dict:
    """Structural limits, before any parser touches the file.

    Returns facts worth keeping (size, sha256, declared triangle count) so the caller
    does not re-read the file to record provenance. Raises ImportRejected otherwise.
    """
    size = os.path.getsize(path)
    if size == 0:
        raise ImportRejected("import_malformed", "that file is empty")
    if size > MAX_ASSET_BYTES:
        raise ImportRejected(
            "import_too_large",
            f"that file is {size // (1024 * 1024)} MB; the limit is "
            f"{MAX_ASSET_BYTES // (1024 * 1024)} MB",
        )

    facts: dict = {"bytes": size, "declared_triangles": None}

    if kind == "stl":
        count = _stl_triangle_count(path, size)
        if count is not None and count > MAX_STL_TRIANGLES:
            raise ImportRejected(
                "import_too_complex",
                f"this mesh has {count} triangles; the limit is {MAX_STL_TRIANGLES}",
            )
        facts["declared_triangles"] = count
    elif kind == "3mf":
        _precheck_zip(path)
    elif kind in ("step", "brep"):
        with open(path, "rb") as fh:
            data = fh.read()
        if kind == "step":
            if b"ISO-10303" not in data[:2048]:
                raise ImportRejected(
                    "import_malformed", "this file does not look like a STEP part"
                )
            entities = len(_STEP_ENTITY.findall(data))
            if entities > MAX_STEP_ENTITIES:
                raise ImportRejected(
                    "import_too_complex",
                    f"this STEP file has {entities} entities; the limit is "
                    f"{MAX_STEP_ENTITIES}",
                )
            facts["step_entities"] = entities

    # Hash last: it is the one check that must read every byte, so it runs only after
    # the cheap refusals have had their chance.
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    facts["sha256"] = digest.hexdigest()
    return facts


def _as_one_shape(shapes: list):
    """Collapse what a reader returned into a single shape, or refuse.

    3MF readers hand back a list. One object is the ordinary case; several is an
    assembly, which this gate does not model — refusing is honest, and quietly keeping
    the first object would silently drop the rest of the user's file.
    """
    if not shapes:
        raise ImportRejected("import_empty", "that file contained no geometry")
    if len(shapes) > 1:
        raise ImportRejected(
            "import_unsupported_format",
            f"that file contains {len(shapes)} separate bodies; import one body at a "
            f"time — assemblies are not supported yet",
        )
    return shapes[0]


def load(kind: str, path: str, *, facts: dict | None = None) -> tuple[object, dict]:
    """Parse ``path`` and return ``(shape, provenance)``.

    Imports build123d lazily so this module stays importable — and unit-testable on its
    refusal paths — without OCP. That is not a nicety: the refusals are the security
    surface, and they should be testable without a 1.4 s kernel import.
    """
    facts = dict(facts or {})
    provenance: dict = {
        "kind": kind,
        "bytes": facts.get("bytes"),
        "sha256": facts.get("sha256"),
        # Never True anywhere in this file. See the module docstring.
        "recovered_features": False,
        "notes": [],
    }

    try:
        if kind == "step":
            from build123d import import_step

            shape = import_step(path)
            provenance.update(
                exact=True, parser="OCCT STEP reader (build123d import_step)"
            )
            provenance["notes"].append(
                "STEP carries a solved B-Rep, so dimensions are exact — but not the "
                "sketches or features that produced it. Edits are new operations on "
                "this body, not changes to its history."
            )
        elif kind == "brep":
            from build123d import import_brep

            shape = import_brep(path)
            provenance.update(exact=True, parser="OCCT BREP reader")
        elif kind == "3mf":
            from build123d import Mesher

            shapes = Mesher().read(path)
            shape = _as_one_shape(list(shapes))
            provenance.update(exact=False, parser="lib3mf via build123d Mesher")
            provenance["notes"].append(
                "3MF is a mesh format: this body is the triangles the file carried, "
                "at the resolution whoever exported it chose."
            )
        elif kind == "stl":
            from build123d import import_stl

            shape = import_stl(path)
            provenance.update(exact=False, parser="OCCT STL reader")
            provenance["notes"].append(
                "STL is a triangle soup with no notion of a solid — this body has "
                "surface area but no volume, and cannot be booleaned against."
            )
        else:  # pragma: no cover — kind_for is the only producer of `kind`
            raise ImportRejected("import_unsupported_format", f"unknown kind {kind!r}")
    except ImportRejected:
        raise
    except Exception as exc:  # noqa: BLE001
        # The parser's own message names file offsets and internal type names. The
        # caller gets the fact and the format, not OCCT's internals.
        raise ImportRejected(
            "import_malformed",
            f"this {kind.upper()} file could not be read ({type(exc).__name__})",
        ) from exc

    if shape is None:
        raise ImportRejected("import_empty", "that file contained no geometry")
    if _occupies_no_space(shape):
        # OCCT's STEP reader does not raise on a body it could not parse — it prints to
        # stderr and hands back an empty Compound, which `is None` does not catch.
        # Without this the file becomes a successful import of nothing, and the user
        # gets a reference body they cannot see and were never told is missing.
        raise ImportRejected(
            "import_malformed",
            f"no geometry could be read from this {kind.upper()} file",
        )

    solids = _solid_count(shape)
    if solids > MAX_SOLIDS:
        raise ImportRejected(
            "import_too_complex",
            f"that file yields {solids} solids; the limit is {MAX_SOLIDS}",
        )
    provenance["solid_count"] = solids
    return shape, provenance


def _occupies_no_space(shape) -> bool:
    """True when a reader returned a shape that is nowhere and is nothing.

    The bounding-box diagonal, because it is the one measure that means the same thing
    in every format here. Counting topology does not work: measured on the same
    10x20x30 box, a STEP import is a Solid with 8 vertices and 6 faces while an STL
    import is a Face with **zero** vertices, zero edges and one face — the triangles
    are a triangulation hanging off the face, not topology. A diagonal of 37.417 vs
    0.0 separates both of those from the empty Compound a failed STEP parse returns.

    A shape that cannot be asked is treated as non-empty. Refusing on an unfamiliar
    type would turn "we do not recognise this" into "your file is broken", and the
    solid-count check downstream is the better place for that argument.
    """
    try:
        return shape.bounding_box().diagonal == 0
    except Exception:  # noqa: BLE001
        return False


def _solid_count(shape) -> int:
    """Solids in an imported shape. An STL comes back as a Face and has none."""
    try:
        return len(shape.solids())
    except Exception:  # noqa: BLE001
        return 0
