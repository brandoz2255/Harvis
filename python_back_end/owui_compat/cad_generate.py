"""Gate 7B: a plain-English part description becomes a CadIR document, or it fails
loudly.

**What this is not.** It is not a second geometry path. Nothing here builds anything,
and nothing here writes a revision. It produces a *proposal* — a document plus the
assumptions that went into it — which the caller shows to the user, and which becomes a
revision only through the existing ``POST /api/cad/projects[/{id}/revisions]`` routes
that already check ownership, quota and staleness. A generator that could commit its own
output would be a model writing to the user's history without a human in between.

**The loop.**

0. :mod:`cad_designspec` reads the user's sentence into a frozen requirement list —
   regular expressions only, no model, and the model never sees a way to change it
1. one local model call returns a `document`, written against those requirements
2. the document is normalized (nulls dropped) — deterministic, no model involved
3. the backend's coarse fence (:mod:`cad_ir`) rejects the obviously malformed
4. the engine's ``POST /cad/validate`` runs the *real* grammar and budget check
5. the built solid is measured and graded against step 0 by :mod:`cad_conformance`
6. on any failure — invalid, unbuildable, or the wrong size — the specific error goes
   back to the model with the document it produced, capped at :data:`MAX_REPAIRS`
7. what comes out is a document the engine agreed to plan, carrying its conformance
   verdict, or an honest failure with every attempt

Step 4 rejects a part that is broken. Step 5 rejects a part that is fine and *wrong* —
Gate 7B shipped without it, and a request for a 30 mm cube with a 10 mm bore returned a
watertight, valid, single-solid 35 mm block with an 18 mm bore, reported as succeeded.

Step 4 is the one that matters. It is the same function ``/cad/v2/build`` calls before
taking a concurrency slot, so "validated" here means the engine has committed to
planning it — not that a second, laxer copy of the rules was satisfied.

**Deliberate deviations from the Gate 7 sketch, stated rather than buried:**

* *The DesignSpec is not a model call at all.* The plan reads "prompt → DesignSpec →
  CadIR", and Gate 7B did both in one call, with the model returning its own
  ``design_spec`` alongside its document. That is the defect Gate 7C exists to remove:
  a model that writes both the part and the requirements it will be judged against is
  marking its own work. The requirements now come from regular expressions over the
  user's sentence, which cannot invent a dimension the user did not say and cannot
  quietly relax one that it did. The model is still asked for a ``design_spec`` field
  because the prompt's examples are shaped around it and changing that shape measurably
  costs validity on a 4B model — but nothing reads it.
* *Repairs are re-emitted whole, not sent as a patch document.* "Patches preferred over
  regeneration" is honoured in the prompt — the model is given its own document and
  asked for the minimum change that fixes the named error — but it returns a complete
  document. A structured patch format is one more grammar for a 4B model to get wrong,
  and a malformed patch is indistinguishable from a malformed document while being
  harder to diagnose.

**No cloud fallback, silent or otherwise.** This calls Ollama at ``OLLAMA_URL`` and
nothing else. A missing model is an error naming the model; it is never quietly served
by a provider the user did not choose for it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx

from . import (cad_conformance, cad_designspec, cad_evidence, cad_ir,
               cad_measure_plan, cad_patterns, fab_cad)

logger = logging.getLogger(__name__)

# The cap the plan calls "hard". Attempts beyond the first are repairs, so a value of 2
# means at most three model calls for one prompt. It is deliberately small: past two
# corrections the models measured in the Gate 7B benchmark do not converge, they
# oscillate between two wrong documents, and each lap costs a full generation.
MAX_REPAIRS = int(os.getenv("HARVIS_CAD_MAX_REPAIRS", "2"))

# Set from the Gate 7B benchmark, not from reputation. gpt-oss:20b was the placeholder
# here and it is measurably the worst choice on this box: 13.8 GB of weights on an 8 GB
# card, and under this prompt it returns a zero-length string in 9.2 s. qwen3:4b is the
# smallest model tested and won on every axis that matters — most parts valid, most
# dimensions exact, and a median around 15 s against 90–400 s for everything larger,
# because it is the only one that fits in VRAM with room for its own context.
# An operator on a bigger card should re-run the benchmark rather than trust this line.
DEFAULT_MODEL = os.getenv("HARVIS_CAD_MODEL", "qwen3:4b")

# Generation is slow here on purpose. The 8 GB card runs an 8B model at roughly 59% CPU,
# so a first call that has to load weights can take a minute before it emits a token.
GEN_TIMEOUT_S = float(os.getenv("HARVIS_CAD_GEN_TIMEOUT", "180"))
VALIDATE_TIMEOUT_S = 10.0

MAX_PROMPT_CHARS = 2000


class GenerateError(RuntimeError):
    """A failure the caller can render. ``code`` is stable; ``message`` is safe text."""

    def __init__(self, code: str, message: str, attempts: list | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts or []


# ---------------------------------------------------------------------------
# The response schema handed to Ollama's grammar-constrained decoder.
#
# It is deliberately LOOSER than CadIR. The real grammar is a discriminated union
# (`box` has `size`, `cylinder` has `radius`/`height`, `fillet` has `select`) and
# `extra="forbid"` everywhere; expressing that as `oneOf` produces a grammar these
# models fall off. So the schema constrains what a grammar is good at — the key set,
# the op names, formulas being string-or-number — and `cadir.parse` enforces the rest.
# A wrong-shaped op comes back as a precise error the repair loop can act on, which is
# a better outcome than a decoder that stalls.
# ---------------------------------------------------------------------------
_FORMULA = {"type": ["string", "number"]}
_VEC3 = {"type": "array", "items": _FORMULA, "minItems": 3, "maxItems": 3}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["design_spec", "document"],
    "properties": {
        "design_spec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["intent", "assumptions", "unknowns"],
            "properties": {
                "intent": {"type": "string"},
                # Every value the model chose that the user did not state. This is the
                # field that makes a dimension claim honest, so it is required rather
                # than optional — an empty list is a claim too, and a deliberate one.
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "unknowns": {"type": "array", "items": {"type": "string"}},
            },
        },
        "document": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "units", "name", "parameters", "operations"],
            "properties": {
                # Both, because the engine parses both and a repair turn re-validates
                # whatever document it was handed — including a stored 0.1 revision.
                # New documents are told to write "0.2" in the prompt; pinning the enum
                # to one version here would have forced every generation to contradict
                # that instruction, which is a rejection the model cannot see or fix.
                "schema_version": {"type": "string", "enum": ["0.1", "0.2"]},
                "units": {"type": "string", "enum": ["mm"]},
                "name": {"type": "string"},
                "expected_solids": {"type": "integer"},
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "kind", "default", "min", "max"],
                        "properties": {
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": ["float", "int"]},
                            "default": {"type": "number"},
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                        },
                    },
                },
                "derived": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "value"],
                        "properties": {"name": {"type": "string"}, "value": _FORMULA},
                    },
                },
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["op", "op_id"],
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["box", "cylinder", "sphere", "cone", "torus",
                                         "extrude", "revolve", "fillet", "chamfer",
                                         "mirror", "shell"],
                            },
                            "op_id": {"type": "string"},
                            "mode": {"type": "string",
                                     "enum": ["add", "subtract", "intersect"]},
                            # Naming a component is what turns one fused lump into a
                            # housing and a lid. It is all-or-nothing across a
                            # document, which the engine enforces and a flat schema
                            # cannot say: an unnamed subtract in a document that has
                            # names could mean "cut every part" or "cut some default
                            # one", and either guess removes material from the wrong
                            # body while still reporting a valid solid.
                            "component": {"type": "string"},
                            "thickness": _FORMULA,
                            "size": _VEC3,
                            "radius": _FORMULA,
                            "height": _FORMULA,
                            # Gate 7D's additions. Listed flat, alongside the fields
                            # they are mutually exclusive with, for the reason the
                            # header states: a `oneOf` per operation is the accurate
                            # grammar and the one these models fall off. Sending a
                            # `radius` to an `extrude` is caught by `cadir.parse` with
                            # a message naming both, which the repair loop can act on.
                            "bottom_radius": _FORMULA,
                            "top_radius": _FORMULA,
                            "major_radius": _FORMULA,
                            "minor_radius": _FORMULA,
                            "amount": _FORMULA,
                            "angle": _FORMULA,
                            "length": _FORMULA,
                            "plane": {"type": "string", "enum": ["XY", "XZ", "YZ"]},
                            "both": {"type": "boolean"},
                            "profile": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["kind"],
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["rect", "circle", "ellipse", "polygon",
                                                 "regular_polygon", "slot"],
                                    },
                                    "origin": {
                                        "type": "array", "items": _FORMULA,
                                        "minItems": 2, "maxItems": 2,
                                    },
                                    "size": {
                                        "type": "array", "items": _FORMULA,
                                        "minItems": 2, "maxItems": 2,
                                    },
                                    "radii": {
                                        "type": "array", "items": _FORMULA,
                                        "minItems": 2, "maxItems": 2,
                                    },
                                    "points": {
                                        "type": "array",
                                        "items": {
                                            "type": "array", "items": _FORMULA,
                                            "minItems": 2, "maxItems": 2,
                                        },
                                    },
                                    "radius": _FORMULA,
                                    "corner_radius": _FORMULA,
                                    "sides": {"type": "integer"},
                                    "length": _FORMULA,
                                    "height": _FORMULA,
                                },
                            },
                            "rotation": {
                                "type": "array", "items": {"type": "number"},
                                "minItems": 3, "maxItems": 3,
                            },
                            "when": {"type": "string"},
                            "optional": {"type": "boolean"},
                            "at": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "positions": {
                                        "type": "array",
                                        "items": _VEC3,
                                    },
                                    # A grid's count is [nx, ny, nz]; a bolt circle's is
                                    # a single number. Both shapes are admitted here and
                                    # the engine's own union decides which placement it
                                    # is — a second `at` key to tag it would be one more
                                    # thing for a model to get wrong.
                                    "count": {"type": ["array", "string", "number"],
                                              "items": _FORMULA},
                                    "pitch": _VEC3,
                                    "center": _VEC3,
                                    "radius": _FORMULA,
                                    "start_angle": _FORMULA,
                                    "angle_span": _FORMULA,
                                },
                            },
                            "select": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["filter_by", "sort_by", "take"],
                                "properties": {
                                    "filter_by": {"type": "string", "enum": ["X", "Y", "Z"]},
                                    "sort_by": {"type": "string", "enum": ["X", "Y", "Z"]},
                                    "take": {
                                        "type": "array", "items": {"type": "integer"},
                                        "minItems": 2, "maxItems": 2,
                                    },
                                },
                            },
                            # Deliberately the same three fields as `select`, because a
                            # model that has learned to pick edges should not have to
                            # learn a second spelling to pick faces. What differs is
                            # what `filter_by` means: an edge parallel to the axis
                            # there, a face whose *normal* is parallel to it here.
                            "openings": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["filter_by", "sort_by", "take"],
                                "properties": {
                                    "filter_by": {"type": "string", "enum": ["X", "Y", "Z"]},
                                    "sort_by": {"type": "string", "enum": ["X", "Y", "Z"]},
                                    "take": {
                                        "type": "array", "items": {"type": "integer"},
                                        "minItems": 2, "maxItems": 2,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The grammar, written for a model rather than for a parser. Every rule here is one the
# engine actually enforces, and each is stated because a generated document broke on it
# during the benchmark — this is a list of observed failures, not a list of everything
# true about CadIR.
SYSTEM = """\
You are a mechanical CAD author. You write parts as CadIR — a small declarative JSON
format — and nothing else. You never write code, prose, or explanations outside the JSON.

CadIR has exactly eleven operations. There is nothing else. If a shape cannot be made
from these, approximate it with these.

  box       size: [x, y, z]                      a rectangular solid
  cylinder  radius: r, height: h                 a cylinder along +Z unless rotated
  sphere    radius: r
  cone      bottom_radius, top_radius, height    top_radius 0 is a point; use it for
                                                 countersinks and tapers
  torus     major_radius, minor_radius           a ring in the XY plane
  extrude   profile: {...}, amount: h            a 2-D outline pushed along its normal
  revolve   profile: {...}, angle: a             a 2-D outline turned about the Z axis
  fillet    radius: r, select: {...}             rounds edges of what was built before
  chamfer   length: l, select: {...}             cuts them flat instead
  mirror    plane: "XY"|"XZ"|"YZ"                reflects what was built before and
                                                 KEEPS BOTH HALVES; default "YZ"
  shell     thickness: t, openings: {...}        hollows out what was built before;
                                                 without openings the void is sealed

A `profile` is a 2-D outline and is one of:

  {"kind": "rect", "size": [w, h]}                 optional "corner_radius"
  {"kind": "circle", "radius": r}
  {"kind": "ellipse", "radii": [a, b]}
  {"kind": "polygon", "points": [[x, y], ...]}     3 to 64 points, closed for you
  {"kind": "regular_polygon", "radius": r, "sides": n}
  {"kind": "slot", "length": l, "height": h}       a rounded-end slot, length overall

Every profile may carry "origin": [x, y], which moves it inside its own plane.

USE extrude WHEN the cross-section is constant and is not a rectangle or a circle — an
L-bracket, a slotted foot, a hexagonal boss. USE revolve WHEN the part is turned on a
lathe — a bushing, a flanged collar, a spindle, a knob. Those two cover most of what
boxes and cylinders can only approximate, and an approximation with the wrong dimensions
is a wrong part.

RULES — every one of these is enforced, and breaking one rejects the whole document:

1. Every number may be a plain number OR a formula string over parameter names.
   Formulas allow + - * / ** and the functions min, max, abs. Nothing else: no
   attribute access, no other function, no variables you did not declare.
2. Parameter and derived names must match ^[a-z][a-z0-9_]*$. So must every op_id.
   All three name spaces share one namespace — no duplicates anywhere, and a derived
   value may not reuse a parameter name.
3. Every parameter needs name, kind ("float" or "int"), default, min, max, with
   min <= default <= max. Every symbol a formula names must be a parameter or a
   derived value DEFINED EARLIER in the derived list.
4. THE FIRST OPERATION CANNOT BE A FILLET, CHAMFER, MIRROR OR SHELL. All four act on
   what already exists, and at that point nothing does.
5. `mode` is "add" (default), "subtract" or "intersect". Use subtract for holes,
   pockets and slots; use intersect to keep only what two shapes share, which is how
   you round a block off to a cylinder or trim a part to an envelope. There is no
   separate union, cut or intersection operation — this is it.
6. `at` places copies. One of:
     {"positions": [[x, y, z], ...]}            explicit centres, up to 64
     {"count": [nx, ny, nz], "pitch": [px, py, pz], "center": [x, y, z]}
                                                a centred grid
     {"count": n, "radius": r}                  a bolt circle in the XY plane, with
                                                optional "start_angle", "angle_span"
                                                (default 360) and "center"
   Omit `at` entirely for a single copy at the origin. All coordinates are the CENTRE
   of the shape, not a corner. A bolt circle over a full turn spaces n holes evenly
   with none doubled at the seam; over a partial arc it puts one on each end.
   A bolt circle POSITIONS copies and does not turn them — a radial hole drilled
   inward at each station cannot be written yet, so do not try.
7. `rotation` is [rx, ry, rz] in degrees and must be plain numbers, never formulas.
   A cylinder is vertical by default; use rotation [0, 90, 0] for a horizontal hole
   through a wall that faces X.
8. `when` is a guard formula. The operation is skipped when it is false. Use it for
   features that only make sense at some parameter values, e.g. "hole_count >= 1".
9. `fillet` and `chamfer` take `select`: {"filter_by": axis, "sort_by": axis,
   "take": [lo, hi]}, which picks edges by position, with 0 <= lo < hi <= 64. Set
   "optional": true on either — a size the geometry cannot take then degrades the part
   instead of failing the build. `fillet` uses `radius`, `chamfer` uses `length`.
10. `shell` hollows the part out and leaves walls `thickness` thick. `openings` names
    the faces to remove and is what makes a cup, a tray or an enclosure rather than a
    sealed void: {"filter_by": axis, "sort_by": axis, "take": [lo, hi]}, where
    `filter_by` keeps the faces whose NORMAL points along that axis — "Z" on a box is
    its top and bottom — and `take` slices them once sorted. {"filter_by": "Z",
    "sort_by": "Z", "take": [1, 2]} opens the top alone. There is no "optional" on a
    shell: a wall that does not fit is an error, because a solid part where a hollow
    one was asked for is wrong about its own weight. The wall must be less than half
    the thinnest section it hollows.
11. `mirror` reflects everything built so far about a plane and keeps BOTH halves, so
    a symmetric part is drawn as one half — however many operations that takes — and
    mirrored once at the end. It defaults to "YZ", which is left-right symmetry.
12. Units are millimetres. Always. `schema_version` is "0.2".
13. `expected_solids` is how many separate solid bodies the finished part has. It is 1
    unless the part has named components — see below.
14. `component` is how a document describes an assembly of separate bodies: a housing
    and a lid, a body and a cap. Every operation carrying the same component name
    builds one body, and each body becomes a separately selectable part of the result
    instead of one fused lump. It is ALL-OR-NOTHING: either every operation names a
    component or none do, and a fillet, chamfer, mirror or shell names the component it
    works on, which must be one some solid operation builds. Set `expected_solids` to
    the number of components. Most parts have none — leave it out unless the user
    asked for pieces that come apart.

DESIGN RULES that decide whether the part is real rather than merely valid:

* Solids you intend to be one piece must OVERLAP, not merely touch. Two boxes that
  meet exactly face-to-face produce a seam the mesher reports as not watertight.
  Overlap them by a fraction of a millimetre or size them to interpenetrate.
* A subtract must pass fully THROUGH what it cuts, or stop deliberately inside it.
  A cut that ends exactly flush with a face creates a coplanar surface and the same
  problem. Make through-holes longer than the material they cross.
* Make every dimension the user stated a parameter with a sensible range around it.
  Do not hard-code a number the user gave you into a formula.

COMMON MISTAKES — every one of these was made by a real model on this exact task,
and every one of them rejects the document:

* `select` and `optional` belong to `fillet` and `chamfer` and to nothing else, and
  `openings` belongs to `shell`. A box or a cylinder that carries any of them is
  rejected. If you want part of a shape, build it that way; there is no selecting a
  subset of a box.
* Every operation takes ONLY its own fields. An `extrude` has `profile` and `amount` and
  no `radius`; a `revolve` has `profile` and `angle` and no `height`; a `cone` has
  `bottom_radius` and `top_radius` and no `radius`. Mixing them rejects the document.
* A REVOLVE PROFILE MAY NOT CROSS THE AXIS. `x` in the profile is distance from the
  centreline, and every x must be zero or more, so a bushing is a rectangle pushed out
  with `origin`: a 3 mm wall around a 6 mm bore is
  {"kind": "rect", "size": [3, h], "origin": [7.5, 0]} — bore radius plus half the wall.
  A rectangle left at the origin straddles the axis and is refused before it is built.
* `at` is either {"positions": [...]} or {"count": [...], "pitch": [...]}. Never both,
  never neither, never any other key. If the shape sits at the origin, leave `at` out
  entirely rather than writing an empty object.
* A subtraction has to sit INSIDE the material it cuts. Four holes placed at the
  corners of an 80 x 40 plate cut it into three separate pieces, and the build fails
  on solid count. "Inset 8 mm from each edge" on that plate means centres at
  x = +/-32, y = +/-12 — measured from the CENTRE, because every coordinate is.
* A hole through a 5 mm plate must be TALLER than 5 mm — make it 7 or 10 and centre
  it on the plate. A cylinder exactly 5 mm tall ends flush with both faces and the
  mesher reports the result as not closed.
* Do not put keys the format does not have on any operation. There is no `name`, no
  `label`, no `comment`, no `material`. `op_id`, `op`, and the operation's own body
  are all there is, plus the optional `mode`, `component`, `at`, `rotation` and
  `when`. `component` is the one that names a part; `name` is not.
* Two blocks that together make one part have to share a whole face or overlap. If
  they meet only along an edge or at a corner, the result is a shape the mesher calls
  non-manifold and the build fails. A step block 60 long whose front 30 is 20 tall and
  whose back 30 is 40 tall is two boxes sitting side by side on the same base, both
  starting at z = 0 — not one box balanced on the edge of another.
* A fillet radius has to be smaller than half the thinnest material it rounds. A 2 mm
  fillet on the edges of a 3 mm wall has nowhere to go and the build fails. When in
  doubt leave the fillet out — a part with square edges is a correct part.
* A LID, CAP OR COVER is a second solid that ASSEMBLES onto a body. It is never a
  disk fused onto the rim. Give the lid its own `component`, set expected_solids to
  2, and size its bore to CLEAR the neck (body radius + half the diametral gap).
  The lid needs a hollow SKIRT that drops over the neck — depth at least twice the
  wall — sitting coaxial on +Z. CadIR cannot cut threads; a slip-fit skirt is the
  printable substitute, and you must say so in assumptions.
* Call cad_lookup_pattern (when you have tools) or follow the mechanical-pattern
  block in this prompt before inventing a mating interface. Grammar-valid sculpture
  that will not assemble is the wrong part.

Put every value you chose that the user did not state into design_spec.assumptions,
one plain sentence each. Put anything you would need to ask about into
design_spec.unknowns. Do not put a value in assumptions and then not use it.
"""

# Both shipped recipes, as few-shot. They are the documents the engine already builds,
# which is what makes them worth the tokens: a model copying their shape is copying
# something measured, not something plausible.
_EXAMPLES = """\
Here are three complete, working examples.

--- "a wall bracket to hang a helmet on, about 100mm out from the wall" ---
{"design_spec": {"intent": "wall-mounted cantilever hook for a helmet",
  "assumptions": ["Back plate 40 x 44 mm, 6 mm thick, sized for two screws.",
                  "Arm cross-section 12 x 8 mm, adequate for a helmet's weight in PLA.",
                  "18 mm upturned lip at the tip so the strap cannot slide off."],
  "unknowns": ["Screw size and wall type were not stated; 4 mm clearance holes assumed."]},
 "document": {"schema_version": "0.2", "units": "mm", "name": "helmet_hanger",
  "expected_solids": 1,
  "parameters": [
    {"name": "plate_t_mm", "kind": "float", "default": 6, "min": 1, "max": 40},
    {"name": "plate_w_mm", "kind": "float", "default": 40, "min": 5, "max": 300},
    {"name": "plate_h_mm", "kind": "float", "default": 44, "min": 5, "max": 300},
    {"name": "arm_len_mm", "kind": "float", "default": 100, "min": 10, "max": 500},
    {"name": "arm_w_mm", "kind": "float", "default": 12, "min": 2, "max": 80},
    {"name": "arm_h_mm", "kind": "float", "default": 8, "min": 2, "max": 80},
    {"name": "hook_h_mm", "kind": "float", "default": 18, "min": 2, "max": 150},
    {"name": "fillet_r_mm", "kind": "float", "default": 3, "min": 0, "max": 20},
    {"name": "screw_d_mm", "kind": "float", "default": 4, "min": 1, "max": 20},
    {"name": "screw_count", "kind": "int", "default": 2, "min": 0, "max": 6}],
  "operations": [
    {"op": "box", "op_id": "back_plate", "size": ["plate_t_mm", "plate_w_mm", "plate_h_mm"],
     "at": {"positions": [["plate_t_mm / 2", 0, 0]]}},
    {"op": "box", "op_id": "arm", "size": ["arm_len_mm", "arm_w_mm", "arm_h_mm"],
     "at": {"positions": [["plate_t_mm + arm_len_mm / 2", 0, 0]]}},
    {"op": "box", "op_id": "hook_lip", "size": ["arm_h_mm", "arm_w_mm", "hook_h_mm"],
     "at": {"positions": [["plate_t_mm + arm_len_mm - arm_h_mm / 2", 0,
                           "hook_h_mm / 2 + arm_h_mm / 2"]]}},
    {"op": "cylinder", "op_id": "screw_holes", "radius": "max(0.5, screw_d_mm / 2)",
     "height": "plate_t_mm * 3", "rotation": [0, 90, 0], "mode": "subtract",
     "when": "screw_count >= 1",
     "at": {"count": [1, 1, "screw_count"], "pitch": [0, 0, "plate_h_mm / (screw_count + 1)"],
            "center": ["plate_t_mm / 2", 0, 0]}},
    {"op": "fillet", "op_id": "root_fillet",
     "radius": "max(0.5, min(fillet_r_mm, arm_h_mm / 2 - 0.5))",
     "select": {"filter_by": "Y", "sort_by": "X", "take": [0, 2]}, "optional": true}]}}

Note the screw holes: height is three times the plate thickness so the cut passes
clean through, and the rotation turns the cylinder to face along X.

--- "a 4x2 interlocking building brick" ---
{"design_spec": {"intent": "generic 4x2 studded interlocking brick",
  "assumptions": ["10 mm stud pitch and 10 mm body height.",
                  "1.6 mm walls, 0.1 mm clearance per side for a friction fit."],
  "unknowns": []},
 "document": {"schema_version": "0.2", "units": "mm", "name": "studded_brick",
  "expected_solids": 1,
  "parameters": [
    {"name": "studs_x", "kind": "int", "default": 4, "min": 1, "max": 16},
    {"name": "studs_y", "kind": "int", "default": 2, "min": 1, "max": 16},
    {"name": "pitch_mm", "kind": "float", "default": 10, "min": 4, "max": 40},
    {"name": "body_h_mm", "kind": "float", "default": 10, "min": 3, "max": 60},
    {"name": "wall_t_mm", "kind": "float", "default": 1.6, "min": 0.8, "max": 6},
    {"name": "stud_d_mm", "kind": "float", "default": 5, "min": 1, "max": 30},
    {"name": "stud_h_mm", "kind": "float", "default": 2, "min": 0.5, "max": 10},
    {"name": "clearance_mm", "kind": "float", "default": 0.1, "min": 0, "max": 1}],
  "derived": [
    {"name": "length", "value": "studs_x * pitch_mm - 2 * clearance_mm"},
    {"name": "width", "value": "studs_y * pitch_mm - 2 * clearance_mm"},
    {"name": "cavity_h", "value": "body_h_mm - wall_t_mm"}],
  "operations": [
    {"op": "box", "op_id": "shell", "size": ["length", "width", "body_h_mm"]},
    {"op": "box", "op_id": "cavity",
     "size": ["length - 2 * wall_t_mm", "width - 2 * wall_t_mm", "cavity_h"],
     "mode": "subtract", "at": {"positions": [[0, 0, "-wall_t_mm / 2"]]}},
    {"op": "cylinder", "op_id": "studs", "radius": "stud_d_mm / 2", "height": "stud_h_mm",
     "at": {"count": ["studs_x", "studs_y", 1], "pitch": ["pitch_mm", "pitch_mm", 0],
            "center": [0, 0, "body_h_mm / 2 + stud_h_mm / 2"]}}]}}

Note `derived`: a value used in several places is named once. And note that the studs
sit at body_h/2 + stud_h/2, which puts their base exactly on the top face — they
overlap the shell because a cylinder centred there is half inside it.

--- "a flanged bushing, 6mm bore, hex flange, four M4 bolt holes" ---
{"design_spec": {"intent": "flanged bushing on a hexagonal bolt-down flange",
  "assumptions": ["3 mm wall around the bore and a 12 mm boss above the flange.",
                  "40 mm across-corners hex flange, 6 mm thick.",
                  "Four 4.5 mm clearance holes on a 28 mm bolt circle.",
                  "1.5 mm chamfer on the six flange corners."],
  "unknowns": ["Shaft fit class was not stated; the bore is nominal, not undersized for reaming."]},
 "document": {"schema_version": "0.2", "units": "mm", "name": "flanged_bushing",
  "expected_solids": 1,
  "parameters": [
    {"name": "bore_d_mm", "kind": "float", "default": 6, "min": 1, "max": 80},
    {"name": "wall_t_mm", "kind": "float", "default": 3, "min": 0.8, "max": 20},
    {"name": "boss_h_mm", "kind": "float", "default": 12, "min": 2, "max": 100},
    {"name": "flange_ac_mm", "kind": "float", "default": 40, "min": 10, "max": 200},
    {"name": "flange_t_mm", "kind": "float", "default": 6, "min": 1, "max": 30},
    {"name": "bolt_d_mm", "kind": "float", "default": 4.5, "min": 1, "max": 20},
    {"name": "bolt_circle_mm", "kind": "float", "default": 28, "min": 4, "max": 180},
    {"name": "bolt_count", "kind": "int", "default": 4, "min": 0, "max": 12}],
  "derived": [
    {"name": "bore_r", "value": "bore_d_mm / 2"},
    {"name": "wall_mid", "value": "bore_r + wall_t_mm / 2"}],
  "operations": [
    {"op": "extrude", "op_id": "flange", "amount": "flange_t_mm",
     "profile": {"kind": "regular_polygon", "radius": "flange_ac_mm / 2", "sides": 6}},
    {"op": "revolve", "op_id": "boss",
     "profile": {"kind": "rect", "size": ["wall_t_mm", "boss_h_mm"],
                 "origin": ["wall_mid", "boss_h_mm / 2"]}},
    {"op": "chamfer", "op_id": "break_corners", "length": 1.5,
     "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 6]}},
    {"op": "cylinder", "op_id": "bore", "radius": "bore_r", "mode": "subtract",
     "height": "boss_h_mm * 2",
     "at": {"positions": [[0, 0, "boss_h_mm / 2"]]}},
    {"op": "cylinder", "op_id": "bolt_holes", "radius": "bolt_d_mm / 2",
     "height": "flange_t_mm * 3", "mode": "subtract", "when": "bolt_count >= 1",
     "at": {"count": "bolt_count", "radius": "bolt_circle_mm / 2",
            "center": [0, 0, "flange_t_mm / 2"]}}]}}

Note four things. An extrude grows from z = 0 upward, so the flange occupies z 0…6 while
the boss, revolved from a profile its own origin lifts, occupies z 0…12 — they overlap
and fuse into one solid. The revolve profile sits at bore_r + wall/2, so it never crosses
the axis. The chamfer comes AFTER both, because it cuts what was already built, and its
selector takes the six Z-parallel edges a hexagonal flange has — a round flange has none,
which is why this one is a hexagon rather than a disc. And the bore is a single subtract
running the full height, not a hole per feature.

--- "a lid on a jar" ---
{"design_spec": {"intent": "hollow jar with a separate slip-fit lid",
  "assumptions": ["Two components: jar_body and lid. Expected solids 2.",
                  "0.3 mm diametral slip clearance — CadIR cannot cut threads.",
                  "Skirt 5.5 mm deep so the lid cannot walk off the neck."],
  "unknowns": ["Thread spec was not stated; a slip fit is the printable substitute."]},
 "document": {"schema_version": "0.2", "units": "mm", "name": "jar_with_lid",
  "expected_solids": 2,
  "parameters": [
    {"name": "body_h", "kind": "float", "default": 115, "min": 20, "max": 400},
    {"name": "body_r", "kind": "float", "default": 20, "min": 5, "max": 100},
    {"name": "neck_wall", "kind": "float", "default": 2.5, "min": 0.5, "max": 20},
    {"name": "base_t", "kind": "float", "default": 4, "min": 0.5, "max": 30},
    {"name": "lid_bore_r", "kind": "float", "default": 20.15, "min": 5, "max": 110},
    {"name": "lid_wall", "kind": "float", "default": 2.5, "min": 0.5, "max": 20},
    {"name": "skirt_depth", "kind": "float", "default": 5.5, "min": 1, "max": 40},
    {"name": "lid_top_t", "kind": "float", "default": 2.5, "min": 0.5, "max": 40}],
  "derived": [
    {"name": "bore_r", "value": "body_r - neck_wall"},
    {"name": "lid_r", "value": "lid_bore_r + lid_wall"},
    {"name": "lid_h", "value": "skirt_depth + lid_top_t"},
    {"name": "body_z1", "value": "body_h / 2"},
    {"name": "bore_h", "value": "body_h - base_t + 1"},
    {"name": "lid_z0", "value": "body_z1 - skirt_depth"},
    {"name": "lid_center_z", "value": "lid_z0 + lid_h / 2"},
    {"name": "cav_h", "value": "skirt_depth + 1"}],
  "operations": [
    {"op": "cylinder", "op_id": "body_outer", "component": "jar_body",
     "radius": "body_r", "height": "body_h"},
    {"op": "cylinder", "op_id": "body_bore", "component": "jar_body", "mode": "subtract",
     "radius": "bore_r", "height": "bore_h",
     "at": {"positions": [[0, 0, "(-body_h / 2) + base_t + bore_h / 2"]]}},
    {"op": "cylinder", "op_id": "lid_outer", "component": "lid",
     "radius": "lid_r", "height": "lid_h",
     "at": {"positions": [[0, 0, "lid_center_z"]]}},
    {"op": "cylinder", "op_id": "lid_skirt_bore", "component": "lid", "mode": "subtract",
     "radius": "lid_bore_r", "height": "cav_h",
     "at": {"positions": [[0, 0, "lid_z0 - 1 + cav_h / 2"]]}}]}}

Note the lid: lid_bore_r is 0.15 mm bigger than body_r (0.3 mm on the diameter), the
skirt overlaps the neck, both components are named, expected_solids is 2. A disk fused
onto the rim is not this part.
"""


def grammar_reference() -> str:
    """The CadIR rules and both worked examples, for a caller that writes its own
    instructions around them.

    The native tool lane (:mod:`cad_agent`) needs exactly this and a different set of
    instructions after it. Sharing the text rather than paraphrasing it means a rule
    learned from a real failure gets learned once — a second copy would go stale the
    first time the grammar moves.
    """
    return f"{SYSTEM}\n{_EXAMPLES}"


def build_prompt(description: str, spec: dict | None = None,
                 retry_note: str | None = None) -> str:
    """The first attempt, and — with ``retry_note`` — every restart after one.

    A restart happens when an attempt died with nothing to patch: the reply was
    truncated, or it was not JSON at all. Re-sending this prompt byte-for-byte is what
    made the loop look stuck, because at temperature 0.1 the same prompt walks the same
    path into the same derail, three times, and the user watches three identical
    failures and reasonably concludes nothing is being retried. The note is the only
    thing that differs, and it names the failure so the model can avoid it.
    """
    return (
        f"{SYSTEM}\n{_EXAMPLES}\n"
        f"{cad_patterns.prompt_brief(description)}"
        "--- Now write this part ---\n"
        f"{description.strip()[:MAX_PROMPT_CHARS]}\n"
        f"{_requirements_block(spec)}\n"
        + (f"\n{retry_note}\n" if retry_note else "")
        + "Reply with one JSON object containing design_spec and document. Nothing else."
    )


# Named per failure, because "be brief" is useless advice for a reply that was not JSON
# and "return JSON" is useless advice for one that was JSON until the budget ran out.
_RESTART_NOTES = {
    "truncated": (
        "YOUR LAST REPLY WAS CUT OFF before the JSON closed, because it went on too "
        "long. Write the part with the FEWEST operations that can express it — no "
        "variants, no alternates, no repeated operations with numbered names. Finish "
        "and close the JSON."),
    "not_json": (
        "YOUR LAST REPLY WAS NOT VALID JSON. Emit one JSON object and nothing else: no "
        "prose before it, no explanation after it, no markdown fence."),
    "no_document": (
        "YOUR LAST REPLY HAD NO `document`. The object you return must contain both "
        "`design_spec` and `document`, and `document` must hold the operations."),
}


def _attach_pattern_assumptions(spec: dict, description: str) -> None:
    """Record the shop pattern on the spec so the UI shows what was invented.

    Does not add graded checks — a millimetre the user did not state is not an
    answer key. The authoring prompt still sees the pattern via prompt_brief.
    """
    pat = cad_patterns.match(description)
    if not pat:
        return
    assumptions = spec.setdefault("assumptions", [])
    label = f"mechanical pattern {pat['id']}: {pat['title']}"
    if label not in assumptions:
        assumptions.insert(0, label)
    for item in (*(pat.get("cannot") or ()), *(pat.get("assumptions") or ())):
        if item not in assumptions:
            assumptions.append(item)
    spec["pattern_id"] = pat["id"]


def _requirements_block(spec: dict | None) -> str:
    """The frozen requirements, restated for the model as a checklist.

    Showing them is not the enforcement — :mod:`cad_conformance` measures the finished
    solid and does not consult this text. This is here because a model that can see the
    checklist it will be graded on gets more of them right, and because a model that
    cannot see it has no way to notice it has drifted. It is deliberately worded so the
    model cannot mistake it for something it is allowed to negotiate with.
    """
    lines = [c.get("requirement") for c in (spec or {}).get("checks") or []]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    body = "\n".join(f"- {ln}" for ln in lines)
    return (
        "\n--- These will be MEASURED on the finished solid ---\n"
        f"{body}\n"
        "They come from the sentence above and are not negotiable. Do not restate them "
        "differently, and do not choose a size that is easier to model.\n"
    )


def build_repair_prompt(description: str, document: dict, error_code: str,
                        message: str) -> str:
    """Ask for the smallest change that fixes one named error.

    The prior document is included in full and the instruction is explicitly a minimal
    edit — this is the "patches preferred over regeneration" rule, expressed in the way
    these models can actually follow. Rewriting the part from scratch on every error is
    how a repair loop ends up oscillating between two different wrong answers instead of
    converging on one right one.
    """
    return (
        f"{SYSTEM}\n"
        "--- The part you were asked for ---\n"
        f"{description.strip()[:MAX_PROMPT_CHARS]}\n\n"
        "--- The document you produced ---\n"
        f"{json.dumps(document, indent=1)[:12000]}\n\n"
        "--- It was REJECTED ---\n"
        f"{error_code}: {message}\n\n"
        "Make the SMALLEST change that fixes exactly this error. Keep every other "
        "parameter, operation, op_id and formula byte-identical — do not rename "
        "anything, do not reorder operations, do not redesign the part. Reply with the "
        "complete corrected JSON object containing design_spec and document."
    )


def build_edit_prompt(instruction: str, document: dict, spec: dict | None = None,
                      note: str | None = None) -> str:
    """Ask for the smallest change that carries out one instruction from the user.

    Same shape as :func:`build_repair_prompt`, and deliberately so — the two tasks are
    the same task. "Fix this error" and "add a hinge" both mean *edit this document*,
    and the minimal-edit wording is what stops a 4B model from quietly redesigning the
    part around the one thing it was asked to change. What differs is where the
    instruction came from and that the requirements block is the MERGED spec, so the
    original's measured dimensions are restated and cannot be dropped by an edit
    sentence that never mentioned them.
    """
    return (
        f"{SYSTEM}\n"
        "--- The part as it stands ---\n"
        f"{json.dumps(document, indent=1)[:12000]}\n\n"
        f"{cad_patterns.prompt_brief(instruction)}"
        "--- The change the user asked for ---\n"
        f"{instruction.strip()[:MAX_PROMPT_CHARS]}\n"
        f"{_requirements_block(spec)}\n"
        + (f"\n{note}\n" if note else "")
        + "Make the SMALLEST change to the document above that carries out that "
        "request. Keep every other parameter, operation, op_id and formula "
        "byte-identical — do not rename anything, do not reorder operations, do not "
        "redesign the part, and do not start over. Reply with one JSON object "
        "containing design_spec and the complete edited document. Nothing else."
    )


def merge_edit_spec(base_spec: dict | None, edit_spec: dict | None) -> dict:
    """The requirements an edited part is graded on: the original's, plus new ones.

    Re-extracting from the edit sentence alone is what makes this necessary and is a
    measured failure, not a theoretical one: "a jar with a lid, 60 mm tall and 40 mm
    across" extracts three checks, and "add a hinge and make sure it seals" extracts
    exactly one — the *assumed* single-body default. Grading the edited part on that
    alone would drop the 60 mm and the 40 mm and call any size correct.

    So checks merge by ``id``, the edit's version winning where the user restated
    something, and any check the extractor only assumed is skipped entirely — an
    assumption made about a sentence that was never a part description has no claim to
    override a requirement the user really stated the first time.
    """
    base = dict(base_spec or {})
    edit = dict(edit_spec or {})

    merged: dict[str, dict] = {}
    for check in base.get("checks") or []:
        if check.get("id"):
            merged[check["id"]] = check
    dropped = set()
    for check in edit.get("checks") or []:
        cid = check.get("id")
        if not cid:
            continue
        if str(check.get("note") or "").startswith("assumed"):
            dropped.add(cid)
            continue
        merged[cid] = check

    # `stated` is what a human reads back, and its keys are not the check ids
    # (`bbox_has_height` is graded, `height_mm` is displayed), so it is merged as a
    # whole rather than key-by-key. The one exception is the value behind a check the
    # extractor only assumed — that must not overwrite what the original really said.
    stated = dict(base.get("stated") or {})
    stated.update({k: v for k, v in (edit.get("stated") or {}).items()
                   if k not in dropped})

    out = dict(base) if base else dict(edit)
    out["checks"] = list(merged.values())
    out["stated"] = stated
    # Both sentences, because the part is now the answer to both of them and a card
    # that showed only the edit would describe a part nobody asked for.
    intent = " · ".join(x for x in (base.get("intent"), edit.get("intent")) if x)
    out["intent"] = intent[:500]
    out["unknowns"] = list(base.get("unknowns") or [])
    return out


# Conformance checks that count features rather than measure them. A failure here means
# the document has the wrong operations, not the wrong numbers in the right ones.
_STRUCTURAL_KINDS = frozenset({"subtract_op_count", "solid_count"})


# How much closer a measurement has to come before a repair round counts as having
# worked. Readings are rounded to six decimals before they are graded, so anything
# below that is not a movement, it is the rounding.
_PROGRESS_EPS = 1e-6


def _face_text(ref: Any) -> str:
    """``lid/opening_plane`` — one body and one face role, in the engine's own words."""
    if not isinstance(ref, dict):
        return ""
    return "/".join(str(x) for x in (ref.get("part_key"), ref.get("face_role")) if x)


def _target_text(target: Any) -> str:
    """Where a reading was taken, or ``""`` when the check does not name a place.

    Three shapes, matching what the engine emits (``measure.py::_target_of``): a face
    pair, one part and an axis, or nothing at all. The v1 checks measure a bounding box
    and name no target — they have to read exactly as they always did rather than
    acquiring an empty bracket at the end of every line.
    """
    if not isinstance(target, dict) or not target:
        return ""
    a, b = _face_text(target.get("a")), _face_text(target.get("b"))
    if a and b:
        return f"{a} → {b}"
    if target.get("part_key"):
        axis = target.get("axis")
        return f"{target['part_key']}" + (f", {axis} axis" if axis else "")
    return a or b


def describe_failed_check(check: dict) -> str:
    """One failing requirement, as a line the model can act on.

    ``detail`` already carries the arithmetic — measured, wanted, out by how much —
    because the grader writes it for the panel. What it does not carry is *where the
    number came from*, and that is the difference between "the depth is wrong" and "the
    depth between these two faces on this body is wrong". A model rereading its own
    document has to map the requirement back onto an operation before it can change
    anything, and the target is the only thing in the record that names which operation's
    output was measured. The basis travels with it for the same reason: a clearance
    stated on the diameter and the same clearance stated radially are one fit and two
    numbers, and a model told only the number will halve it or double it at random.
    """
    head = (check.get("requirement") or check.get("id")
            or check.get("kind") or "requirement")
    bits = []
    where = _target_text(check.get("target"))
    if where:
        bits.append(f"measured at {where}")
    if check.get("basis"):
        bits.append(f"stated {check['basis']}")
    method = check.get("method")
    if method:
        version = check.get("method_version")
        bits.append(f"method {method}/v{version}" if version else f"method {method}")
    tail = " — " + ", ".join(bits) if bits else ""
    return f"- {head}: {check.get('detail') or 'not met'}{tail}"


def _nominal(check: dict) -> float | None:
    tol = check.get("tolerance")
    if isinstance(tol, dict):
        v = tol.get("nominal")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    v = check.get("expected")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _miss(check: dict) -> float | None:
    """How far this check landed from what was asked, when both are numbers."""
    nominal, measured = _nominal(check), check.get("measured")
    if nominal is None or isinstance(measured, bool):
        return None
    if not isinstance(measured, (int, float)):
        return None
    return abs(float(measured) - nominal)


def repair_made_progress(before: dict, after: dict) -> bool:
    """Did the round move anything, on the evidence?

    The budget is there to buy corrections, and a model that returns a document
    measuring exactly what the last one measured has not made one — it will not make one
    next round either, and every further attempt costs the user a model call to be told
    the same numbers again. So the loop stops on the evidence rather than on the count.

    Only a check that was already failing can improve, and only two things count as
    improvement: it passes now, or its reading is strictly closer to nominal. A failed
    check that came back **unverified** is deliberately not progress — the reading was
    lost, not corrected, and treating a part that became unmeasurable as an encouraging
    sign is how a loop spends its whole budget going blind.
    """
    old = {c.get("id"): c for c in (before.get("checks") or []) if c.get("id")}
    for check in (after.get("checks") or []):
        prev = old.get(check.get("id"))
        if prev is None or prev.get("ok") is not False:
            continue
        if check.get("ok") is True:
            return True
        was, now = _miss(prev), _miss(check)
        if was is not None and now is not None and now < was - _PROGRESS_EPS:
            return True
    return False


def build_conformance_prompt(description: str, document: dict, report: dict) -> str:
    """Ask for a correction, given measurements taken off the model's own solid.

    A conformance failure is a different problem from a rejection and needs a different
    prompt. The document is valid, it builds, and the geometry is sound — it is simply
    not the part that was asked for, and the model has no way to know that because it
    never sees the result. So it is handed the measurements: what was asked, what was
    built, and by how much they differ. Nothing here suggests which parameter to change;
    inferring that from its own document is the model's job, and telling it would be
    guessing at a design it can see and this function cannot.

    What the instruction is allowed to say depends on which checks failed, and getting
    that wrong once cost a whole repair loop. A count that came out wrong — no holes
    where one was asked for, three solids where one was asked for — cannot be fixed by
    changing a number: the live failure is a cylinder with no `mode`, and the only fix
    is to add one. Telling that model to "change only the numbers and do not restructure"
    forbids the single edit that would work, and it duly returned the identical document
    twice. So the minimal-edit instruction is held back unless every failed check really
    is a measurement.
    """
    bad = [c for c in (report.get("checks") or []) if c.get("ok") is False]
    lines = "\n".join(describe_failed_check(c) for c in bad) or "-"
    structural = any(c.get("kind") in _STRUCTURAL_KINDS for c in bad)

    # The arithmetic, not just the rule. Every observed "more bodies than asked for" has
    # been a feature left floating above the body it should join, and the cause is always
    # the same slip: the model treats z as the feature's base when it is the feature's
    # centre. SYSTEM already says coordinates are centres and the model still wrote
    # z = 9.6 - 1.8 for a stud on a 9.6-tall centred box, where the answer is
    # 9.6/2 + 1.8/2. So the correction spells the sum out. (Exact face-to-face contact is
    # NOT the culprit — measured: a stud placed tangent to the top face fuses into one
    # solid. The failure is a gap.)
    gap_case = any(c.get("kind") == "solid_count" and isinstance(c.get("measured"), int)
                   and c["measured"] > (c.get("expected") or 1) for c in bad)
    if gap_case:
        lines += (
            "\n\nMore bodies than asked for means a feature is floating clear of the body "
            "it should join — its position is wrong, not its size. Every position is the "
            "CENTRE of the shape, so a body of height H centred at z = 0 has its top face "
            "at H/2, NOT at H. A feature of height h resting on that face is centred at "
            "H/2 + h/2. Anything above that leaves a gap and becomes a separate solid.")

    how = (
        # The gap case is the one structural failure a number DOES fix, and the generic
        # structural sentence below actively forbids the fix: told "a different number
        # will not fix it", the model moved the floating stud to three different wrong
        # heights across four measured repair rounds and never once closed the gap.
        # "change nothing else" is load-bearing and was measured: softened to "change
        # only the numbers the measurements call for", the same model went 0/6 and put
        # the stud right back at the wrong height. The cost is that a part failing on a
        # gap AND a dimension gets told to fix only the gap; the next repair round then
        # sees the dimension alone and fixes it. Two rounds for the pair beats a wording
        # that fixes neither.
        "One position is wrong. Recompute the z of the feature that is floating, using "
        "the arithmetic above, and change nothing else — keep every op_id, operation "
        "order, parameter and formula identical."
        if gap_case else
        "A feature is missing or there is one too many, so a different number will not "
        "fix it. Look at which operations you wrote and what each one does to the solid. "
        "Keep the parameters and the op_ids you already have."
        if structural else
        "The geometry is valid, so do not restructure it. Change only the numbers that "
        "make the measurements above come out right, and keep every op_id, operation "
        "order and formula otherwise identical."
    )
    return (
        f"{SYSTEM}\n"
        "--- The part you were asked for ---\n"
        f"{description.strip()[:MAX_PROMPT_CHARS]}\n\n"
        "--- The document you produced ---\n"
        f"{json.dumps(document, indent=1)[:12000]}\n\n"
        "--- It BUILT, but it is the wrong part ---\n"
        "The solid was measured. These requirements are not met:\n"
        f"{lines}\n\n"
        f"{how} Reply with the complete corrected JSON object containing design_spec "
        "and document."
    )


# ---------------------------------------------------------------------------
# Normalization — deterministic, and never a fix for a wrong document
# ---------------------------------------------------------------------------

def normalize_document(doc: Any) -> dict:
    """Drop keys the constrained decoder emitted as null, recursively.

    The response schema lists every operation field on one object because a `oneOf`
    grammar is worse; the cost is that a model may fill the shape out with
    ``"radius": null`` on a box. CadIR forbids unknown fields, so a null `radius` on a
    box is a rejection — of a document that is otherwise correct and whose author never
    meant to say anything about a radius.

    An empty ``at`` is dropped for the same reason. ``at`` is a discriminated union of
    a point list and a grid, so ``"at": {}`` matches neither and pydantic rejects it by
    reciting both variants' required fields — an error that reads as though placement
    were mandatory when the model's actual mistake was writing "nothing" the long way.
    Measured: every locally-installed model tried tested emits ``"at": {}`` rather than
    omitting the key, however plainly the prompt asks. An empty placement and an absent
    placement say the identical thing, so treating them identically decides nothing on
    the model's behalf. An empty ``select`` is NOT dropped — select carries meaning, and
    an empty one is a real mistake that should be reported as one.

    A third case, added on measurement: ``"optional": false`` on an op that is not a
    fillet. `optional` means "skip me rather than fail the build if I do not fit", it
    defaults to false, and only a fillet has anything to degrade — so on a box or a
    cylinder, `optional: false` and no `optional` at all are the same statement, and
    dropping it decides nothing, exactly as with the empty `at`. ``optional: true``
    there is NOT dropped: the format has no meaning to give it, so it is a real request
    for something that does not exist and it stays a reported rejection. Neither is
    `select`, on the same principle at greater cost — `select` names edges the author
    meant to pick, and discarding it would build a different part in silence.

    This one is worth stating plainly because it was measured twice, in opposite
    directions. Across twenty live runs of two prompts on qwen3:4b, `cylinder.optional`
    was the rejection in every single failure. An earlier attempt to fix it in the
    prompt — a COMMON MISTAKES line naming `optional` — made it strictly worse (4/5
    builds down to 0/5, and every arm failed on the very key the new sentence had just
    named). Telling a small model not to emit a token is a way of showing it the token.

    Measured a second time in Gate 7D, in the opposite direction and with the same
    result. granite4.1:8b kept omitting `"mode": "subtract"` on bores, so a rule and a
    COMMON MISTAKES entry were added telling it — emphatically — always to write that
    key. Builds went 2/2 to 0/8, and not one failure was about `mode`: the documents
    came back carrying `select` and `profile` on cylinders, keys the worked examples
    use elsewhere. Adding emphasis anywhere in a 16 kB instruction block raises key
    leakage from the examples generally. Both entries were reverted. The lesson is now
    two-sided: at this model size the prompt is close to saturated, and a fix for a
    single key is more likely to cost builds than to buy the key.

    Beyond those three, this removes nothing. It never supplies a default, never coerces
    a type, and never changes a value. A document that is wrong stays wrong and goes to
    the repair loop, which is where a wrong document belongs.
    """
    if isinstance(doc, dict):
        out = {k: normalize_document(v) for k, v in doc.items() if v is not None}
        if out.get("at") == {}:
            del out["at"]
        if out.get("op") not in (None, "fillet") and out.get("optional") is False:
            del out["optional"]
        return out
    if isinstance(doc, list):
        return [normalize_document(v) for v in doc]
    return doc


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_model_json(raw: str) -> dict:
    """The model's text as an object.

    ``format`` should make this a plain ``json.loads``. It is not always: a model that
    emits reasoning before the object, or wraps it in a fence, still produces usable
    output, and refusing it would throw away a correct part over its packaging. So a
    direct parse is tried first and a braces-span fallback second — and if neither
    works, that is a real failure and it is reported as one.
    """
    text = (raw or "").strip()
    if not text:
        raise GenerateError("empty_response", "the model returned nothing")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        out = json.loads(text)
    except Exception:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise GenerateError("not_json", "the model did not return JSON") from None
        try:
            out = json.loads(m.group(0))
        except Exception:
            raise GenerateError("not_json", "the model returned malformed JSON") from None
    if not isinstance(out, dict):
        raise GenerateError("not_json", "the model did not return a JSON object")
    return out


# ---------------------------------------------------------------------------
# The two hops: the model, and the engine's static check
# ---------------------------------------------------------------------------

def _ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")


async def installed_models(*, timeout: float = 5.0) -> set[str] | None:
    """Every tag reachable on any inference host, or ``None`` when none could be asked.

    ``None`` is not "nothing is installed": an unreachable server would otherwise
    report every model as missing, and a caller deciding whether to honour a user's
    model choice would silently override it every time Ollama hiccuped.

    "Any host", not "the laptop". Harvis runs a second Ollama on the RTX 5080 rig, and
    the models too big for the laptop's 8 GB card — gemma4:12b among them — exist only
    there. Asking one URL is how a model the user can plainly see in the picker got
    reported as not installed.
    """
    from . import ollama_hosts
    return await ollama_hosts.available()


async def resolve_host(model: str) -> str:
    """The base URL to generate ``model`` on. Raises rather than guessing.

    Two different failures, named separately, because they need different actions:
    a model no reachable host has is a pull; a model whose host is down is a network.
    """
    from . import ollama_hosts
    base, reason = await ollama_hosts.resolve(model)
    if base:
        if reason == "desktop-preferred":
            logger.info("cad_generate: %s is desktop-preferred — designing on the rig", model)
        return base
    if reason == "unknown":
        raise GenerateError(
            "engine_unreachable",
            f"'{model}' is not on this machine and the host that has it did not answer")
    raise GenerateError("model_missing",
                        f"the model '{model}' is not installed on any inference host")


async def call_model(prompt: str, model: str, *, timeout: float = GEN_TIMEOUT_S,
                     base_url: str | None = None) -> str:
    """One non-streaming local generation. No fallback of any kind.

    ``format`` carries the JSON schema so the decoder is grammar-constrained; a model
    or an Ollama build that ignores it still produces text, which
    :func:`parse_model_json` handles. ``num_ctx`` is deliberately absent — setting it
    forces a reload of an already-resident model, which on this hardware costs more than
    the whole generation.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": RESPONSE_SCHEMA,
        "options": {"temperature": 0.1, "num_predict": 3000},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as hc:
            r = await hc.post(f"{base_url or _ollama_url()}/api/generate", json=payload)
    except Exception as e:
        raise GenerateError("engine_unreachable",
                            f"the local model server did not answer ({type(e).__name__})")
    if r.status_code == 404:
        # Named, because "model not found" and "server down" need different actions and
        # a generic 502 would hide which one happened.
        raise GenerateError("model_missing",
                            f"the model '{model}' is not installed on this deployment")
    if r.status_code != 200:
        raise GenerateError("model_error",
                            f"the local model server returned HTTP {r.status_code}")
    try:
        body = r.json()
    except Exception:
        raise GenerateError("model_error", "the local model server returned no response") from None
    text = (body.get("response") or "").strip()

    # `done_reason: "length"` means the decoder hit num_predict and stopped mid-token,
    # not that the model wrote bad JSON. Reporting it as malformed JSON — which is what
    # happened before this check, because the unterminated object failed to parse —
    # points at the model's competence when the truth is a budget, and a user chasing
    # the wrong cause changes the prompt instead of the model. Small models derail into
    # a repetition loop on this schema (v12, v13, v14 of the same operation) and burn
    # the budget that way, so the message names both possibilities.
    if body.get("done_reason") == "length":
        try:
            json.loads(text)
        except Exception:
            raise GenerateError(
                "truncated",
                f"'{model}' ran past its {payload['options']['num_predict']}-token budget "
                "without closing the design — usually a repetition loop. A larger or "
                "better-instructed model is the fix, not a longer prompt.") from None
    return text


async def validate_document(document: dict, params: dict | None = None) -> dict:
    """Static-check through the engine — the same check a build makes.

    The backend's own :func:`cad_ir.check_document` runs first because it is free and
    catches the grossly malformed without a hop. It is explicitly not a validity
    judgement, so passing it settles nothing; the engine's answer is the one that counts.
    """
    cad_ir.check_document(document)          # raises CadIRError
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(VALIDATE_TIMEOUT_S)) as hc:
            r = await hc.post(f"{fab_cad._cad_url()}/cad/validate",
                              json={"document": document, "params": params or {}})
    except Exception as e:
        raise GenerateError("engine_unreachable",
                            f"the CAD engine did not answer ({type(e).__name__})")
    if r.status_code == 200:
        return r.json()
    if r.status_code == 404:
        # An engine too old to have /cad/validate. Saying so is the only honest answer:
        # falling back to "assume it is fine" would hand the user an unvalidated
        # document with a validated document's confidence.
        raise GenerateError("validate_unavailable",
                            "this CAD engine has no /cad/validate — rebuild it to "
                            "generate parts from a description")
    try:
        detail = r.json().get("detail") or {}
        code = detail.get("error_code") or "invalid_document"
        message = detail.get("message") or "the document was rejected"
    except Exception:
        code, message = "invalid_document", f"the engine rejected it (HTTP {r.status_code})"
    raise GenerateError(code, message)


# `operations.1.box.select: Extra inputs are not permitted` — the engine's own words,
# because `_validation_detail` in the sidecar addresses every error by field path. That
# is what makes the repair below deterministic rather than a guess about what the model
# meant: the authority on the grammar has already named the operation and the key.
_EXTRA_KEY = re.compile(
    r"operations\.(\d+)\.[A-Za-z_]+\.([A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*Extra inputs are not permitted"
)

# Four is well past what a real document produces (the sidecar reports at most 8 errors
# and a model rarely lards more than one or two ops), and it bounds the loop against a
# message the regex reads but the strip cannot satisfy.
MAX_KEY_STRIPS = 4


def strip_forbidden_keys(document: dict, message: str) -> list[str]:
    """Remove the operation keys the engine just said are not permitted there.

    In place, and it returns what it removed as ``op_id.key`` so the caller can record
    it. Nothing else is touched, and a message this regex cannot read removes nothing.

    Why this exists, and why it is not `normalize_document`'s job. The response schema
    handed to the decoder lists every operation's fields on one flat object, because a
    per-op ``oneOf`` grammar is the one these models fall off. The cost is that the
    grammar cheerfully permits `select` on a box — the exact thing the prompt spends a
    COMMON MISTAKES bullet forbidding — and small models take the grammar's word for it.
    The whole document is then rejected, and the repair loop cannot rescue it: measured
    live, qwen3:4b failed three attempts running on this, and it had already been told
    the field path each time, because the engine's message carries it into the repair
    prompt verbatim. This module's own history says why more prompting is not the
    answer — naming a key in the instructions has twice made key leakage worse.

    So the fix is deterministic and it happens only *after* the authority has ruled. An
    extra key is inert by construction: the operation's schema does not read it, so
    removing it cannot change the geometry — only the intent behind it is lost, which is
    why every removal is returned, logged, and carried on the result. That is a real
    trade and it is the better half of it: a plate whose fillet was discarded is a part
    the user can see and correct, and a rejected document is nothing at all.
    """
    removed: list[str] = []
    ops = document.get("operations")
    if not isinstance(ops, list):
        return removed
    for idx_s, key in _EXTRA_KEY.findall(message or ""):
        try:
            op = ops[int(idx_s)]
        except (ValueError, IndexError):
            continue
        if not isinstance(op, dict) or key not in op:
            continue
        # `op` and `op_id` are the operation's identity, not decoration. If the engine
        # ever calls one of them an extra input the document is malformed in a way this
        # cannot mend, and pretending otherwise would build an unnamed operation.
        if key in ("op", "op_id"):
            continue
        del op[key]
        removed.append(f"{op.get('op_id') or f'operations[{idx_s}]'}.{key}")
    return removed


async def validate_with_key_repair(document: dict) -> tuple[dict, list[str]]:
    """Validate through the engine, dropping keys it names as not permitted.

    Returns the engine's validation report and the list of removed keys. Every rejection
    the strip cannot act on is re-raised untouched — this narrows exactly one failure
    mode and leaves the repair loop to do the rest.
    """
    removed: list[str] = []
    for _ in range(MAX_KEY_STRIPS + 1):
        try:
            return await validate_document(document), removed
        except GenerateError as e:
            if e.code != "invalid_document":
                raise
            gone = strip_forbidden_keys(document, e.message)
            if not gone:
                raise
            removed.extend(gone)
            logger.info("cad_generate: dropped %s — not permitted on that operation",
                        ", ".join(gone))
    return await validate_document(document), removed


BUILD_TIMEOUT_S = float(os.getenv("HARVIS_CAD_GEN_BUILD_TIMEOUT", "60"))

# "expected 1 solid(s), got 2" — the engine's own wording, and the ONLY problem string
# in that message when the body count is the sole complaint.
_SOLID_COUNT_ONLY = re.compile(r"^expected (\d+) solid\(s\), got (\d+)$")


async def build_document(document: dict, params: dict | None = None, *,
                         measurements: list[dict] | None = None) -> dict:
    """Actually build it, because a document that validates can still be wrong.

    Static validation checks the grammar, the symbols and the cost — everything that
    can be known without running OpenCascade. It cannot know that four corner holes
    were placed so far out that they cut the plate into three pieces; only geometry
    knows that, and it is exactly the mistake a model makes. So the loop builds, and
    a build failure is fed back as a repair instruction like any other.

    Returns the measured geometry. Raises :class:`GenerateError` carrying the engine's
    own structured code.
    """
    async def _run(doc: dict) -> dict:
        try:
            return await fab_cad.execute(params or {}, want_step=False,
                                         timeout=BUILD_TIMEOUT_S, formats=["stl"],
                                         document=doc, measurements=measurements)
        except fab_cad.CadError as e:
            raise GenerateError(e.code, e.message)
        except Exception as e:
            raise GenerateError("engine_unreachable",
                                f"the CAD engine did not build it ({type(e).__name__})")

    declared = document.get("expected_solids")
    try:
        res = await _run(document)
    except GenerateError as e:
        # A body count the model predicted wrong is not a reason to hand the user
        # nothing. The engine refuses the whole build — no measurements, no mesh — so a
        # part that came out as two loose bodies instead of one used to vanish, three
        # times in a row, with only a sentence about a number to look at. That is the
        # least useful moment to withhold the geometry: seeing the two pieces is what
        # tells you the stud never touched the body.
        #
        # So when the count is the ONLY complaint, correct the declaration to what the
        # geometry actually is and build again. Nothing is hidden by this: the document
        # now says two bodies, the conformance grader still checks the count against
        # what the description asked for and still fails it, and `declared_solids`
        # records what the model claimed. Every other verdict — invalid B-Rep, a
        # non-finite volume, a leaking mesh — is left to fail exactly as before.
        m = _SOLID_COUNT_ONLY.match(e.message or "") if e.code == "validation_failed" else None
        if not m:
            raise
        actual = int(m.group(2))
        logger.info("cad_generate: the model declared %s solid(s) and built %d — "
                    "rebuilding with the real count so the part is still returned",
                    declared, actual)
        document["expected_solids"] = actual
        res = await _run(document)
    # The measurements live under `validation`, not `meta` — `meta` is the frozen
    # Gate 0 shape and carries only bbox and volume. Reading the wrong one returns
    # an empty dict and no exception, which is the worst failure mode available:
    # the caller sees a successful build with nothing measured.
    v = res.get("validation") or {}
    mesh = v.get("mesh") or {}
    out = {k: v[k] for k in
           ("bbox_mm", "volume_mm3", "surface_area_mm2", "solid_count",
            "brep_valid", "mesh_signature", "estimated_cost", "duration_ms")
           if v.get(k) is not None}
    for src, dst in (("watertight", "mesh_watertight"), ("manifold", "mesh_manifold")):
        if mesh.get(src) is not None:
            out[dst] = mesh[src]
    # HE-3's typed evidence, carried out under a private key because the rest of this
    # dict is the flat geometry the grader reads positionally. The caller pops it and
    # hands it to `grade` as its own argument; nothing downstream sees the key.
    #
    # It rides along at all because this lane used to be structurally unable to fail a
    # measured check: `cad_router` planned measurements and the generator did not, so
    # every v2 check graded `unverified` here no matter what the model built, on any
    # model. That is a difference between two code paths, not between two models, and
    # it made a local-vs-cloud comparison meaningless.
    if v.get("measurements"):
        out["_measurements"] = v["measurements"]
    if declared is not None and declared != out.get("solid_count"):
        out["declared_solids"] = declared
    return out


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

async def generate(description: str, *, model: str | None = None,
                   max_repairs: int = MAX_REPAIRS,
                   base_document: dict | None = None,
                   base_spec: dict | None = None) -> dict:
    """A description in, a validated CadIR proposal out — or a failure with its history.

    Never raises for a model that produced a bad document: that is an outcome, and the
    attempt list is the evidence for it. It raises only when the loop could not run at
    all — no engine, no model, no validator.

    With ``base_document`` the same loop edits an existing part instead of designing a
    new one: ``description`` becomes the change the user asked for, the prompt carries
    the document as it stands, and the graded requirements are the base spec merged with
    whatever the edit sentence newly stated. Everything after the first call — repair,
    conformance correction, restart — is unchanged, which is the point: an edit that
    comes back invalid gets the same bounded repair a fresh design does.
    """
    if not (description or "").strip():
        raise GenerateError("empty_prompt", "describe the part you want")
    model = model or DEFAULT_MODEL
    editing = isinstance(base_document, dict) and bool(base_document)

    # Resolved once, before the first call, so every attempt and every repair in this
    # run talks to the same box. Resolving per attempt would let a rig that drops
    # mid-repair silently continue on a different model's machine.
    host = await resolve_host(model)

    # Extracted once, before the first model call, and never touched again. Freezing it
    # here rather than per-attempt is the point: a repair prompt that could shift the
    # requirements would let a model that cannot hit 30 mm settle for calling 35 mm
    # correct, which is exactly the failure this gate closes.
    design_spec = cad_designspec.extract(description)
    if editing:
        design_spec = merge_edit_spec(base_spec, design_spec)
    _attach_pattern_assumptions(design_spec, description)

    attempts: list[dict] = []
    # The description the repair and conformance prompts are given. On an edit that is
    # both sentences — a correction prompt headed only "add a hinge" would let a model
    # that measured wrong conclude the 60 mm it is being told about was never asked for.
    described = design_spec.get("intent") if editing else description
    prompt = (build_edit_prompt(description, base_document, design_spec) if editing
              else build_prompt(description, design_spec))
    document: dict | None = None
    best: dict | None = None
    # The report the last failing attempt produced, kept so the next one can be checked
    # for movement rather than only counted. See `repair_made_progress`.
    last_failed: dict | None = None

    for attempt_no in range(max_repairs + 1):
        kind = "generate" if attempt_no == 0 else "repair"
        t0 = time.monotonic()
        try:
            raw = await call_model(prompt, model, base_url=host)
            out = parse_model_json(raw)
            document = normalize_document(out.get("document"))
            # out["design_spec"] is deliberately ignored — see the module docstring.
            if not isinstance(document, dict) or not document:
                raise GenerateError("no_document", "the model returned no document")
            validation, stripped = await validate_with_key_repair(document)
            # Planned per attempt, not once: the plan binds check targets to this
            # document's own component names, and a repair may rename them.
            requests = None
            if cad_evidence.evidence_enabled():
                try:
                    requests = cad_measure_plan.plan(design_spec, document) or None
                except Exception:
                    logger.exception("cad_generate: measurement planning failed")
            geometry = await build_document(document, measurements=requests)
        except cad_ir.CadIRError as e:
            err = GenerateError(e.code, e.message)
        except GenerateError as e:
            err = e
        else:
            # build_document already returns the flat measurement dict — bbox_mm,
            # volume_mm3, solid_count. It is not nested under a "validation" key here;
            # that unwrapping happened in build_document, and reading for it again
            # would grade an empty dict and call the answer "unverified" every time.
            # Re-parsed rather than trusted: a record the evidence contract rejects
            # is the exact shape a plausible wrong answer takes, and the grader must
            # never see one. No revision or build row exists on this lane, so the
            # binding fields stamp as None.
            taken = None
            raw_measured = (geometry or {}).pop("_measurements", None)
            if raw_measured:
                try:
                    parsed = cad_evidence.parse(raw_measured)
                    if parsed:
                        taken = cad_evidence.stamp(parsed, revision_id=None,
                                                   build_id=None)
                except Exception:
                    logger.exception("cad_generate: measurement parsing failed")
            conformance = cad_conformance.grade(design_spec, document,
                                                geometry or {}, taken)
            attempts.append({
                "attempt": attempt_no + 1, "kind": kind, "ok": True,
                "conformance": conformance["status"],
                # Recorded on the attempt, not only in the log, so a part that reached
                # the user minus a key it asked for says so where the part is read.
                **({"stripped": stripped} if stripped else {}),
                "duration_ms": int((time.monotonic() - t0) * 1000),
            })
            result = {
                "ok": True,
                "model": model,
                "design_spec": design_spec,
                "document": document,
                "validation": validation,
                "geometry": geometry,
                "conformance": conformance,
                "attempts": attempts,
                **({"stripped": stripped} if stripped else {}),
                # Two different numbers, because they answer two different questions and
                # conflating them under-reports the work. `from_attempt` is which try
                # produced THIS document; `repairs` is how many repairs the loop ran, and
                # it is corrected below when an earlier attempt wins. A loop that tried
                # twice more and kept the first answer must not report "repairs: 0".
                "from_attempt": attempt_no + 1,
                "repairs": attempt_no,
            }
            # A part that builds and measures wrong is still a result — the caller gets
            # it either way, marked. Keeping the first one means a repair that makes
            # things worse cannot lose the better attempt; overwriting only on a pass
            # means a later correct one always wins.
            if conformance["status"] != "failed":
                return result
            if best is None:
                best = result
            if attempt_no >= max_repairs:
                best["repairs"] = attempt_no
                return best
            # A round that measured exactly what the round before it measured did not
            # repair anything, and the next one will not either — the model has already
            # seen these numbers and answered with this document. Stopping here returns
            # the same part a spent budget would have returned, minutes earlier and
            # without two more calls on the user's key.
            if last_failed is not None and not repair_made_progress(last_failed,
                                                                   conformance):
                best["repairs"] = attempt_no
                best["stopped"] = "no_improvement"
                logger.info("cad_generate: repair %d moved no measurement, stopping "
                            "model=%s", attempt_no, model)
                return best
            last_failed = conformance
            logger.info("cad_generate: attempt %d built the wrong part (%s) model=%s",
                        attempt_no + 1, conformance["summary"][:120], model)
            prompt = build_conformance_prompt(described, document, conformance)
            continue

        attempts.append({
            "attempt": attempt_no + 1, "kind": kind, "ok": False,
            "error_code": err.code, "message": err.message,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        })
        logger.info("cad_generate: attempt %d/%d failed (%s) model=%s",
                    attempt_no + 1, max_repairs + 1, err.code, model)

        # These four are not the model's fault and no amount of repairing fixes them.
        # Retrying would burn the whole cap producing the identical error three times.
        if err.code in ("engine_unreachable", "model_missing", "validate_unavailable",
                        "model_error", "queue_full", "bad_response", "unknown_format"):
            # A part that built but measured wrong outranks losing everything to an
            # engine that went away on the resize attempt. The caller still sees it
            # marked as non-conforming; it does not silently become a pass.
            if best is not None:
                best["repairs"] = attempt_no
                return best
            raise GenerateError(err.code, err.message, attempts)

        if attempt_no < max_repairs and isinstance(document, dict) and document:
            prompt = build_repair_prompt(described, document, err.code, err.message)
        elif attempt_no < max_repairs and editing:
            # A restart on an edit goes back to the EDIT prompt, never to build_prompt.
            # build_prompt designs a part from a sentence and has no idea a base exists,
            # so a restart through it would answer "add a hinge" with a hinge — the
            # user's jar silently replaced by the thing they asked to add to it.
            prompt = build_edit_prompt(description, base_document, design_spec,
                                       _RESTART_NOTES.get(err.code))
        elif attempt_no < max_repairs:
            # Nothing to patch — start over, but not from the identical prompt. See
            # build_prompt: an unchanged restart is what made three attempts fail three
            # times the same way and read as a loop that never retried.
            prompt = build_prompt(description, design_spec,
                                  _RESTART_NOTES.get(err.code))

    if best is not None:
        best["repairs"] = max_repairs
        return best

    last = attempts[-1] if attempts else {}
    return {
        "ok": False,
        "model": model,
        "design_spec": design_spec,
        "document": document,
        "validation": None,
        "geometry": None,
        # Graded against nothing on purpose. `document` here is the last REJECTED
        # document — never built, often not even valid CadIR — and counting features on
        # it would report "failed" for a part that was never made. A generation that
        # produced no solid has not been shown to be the wrong part; it has not been
        # shown to be anything, and "unverified" is the only true verdict.
        "conformance": cad_conformance.grade(design_spec, None, None),
        "attempts": attempts,
        "repairs": max_repairs,
        "error_code": last.get("error_code") or "generation_failed",
        "message": last.get("message") or "the model could not produce a valid part",
    }
