"""The CadIR document — a declarative, human-readable parametric source.

Gate 5 scoped this to "only the operations the two tested recipes justify" — ``box``,
``cylinder``, ``fillet``, a grid and an explicit point list — because that is all the
helmet hanger and the studded brick use, and a schema promising more would have been
lying about what the interpreter could do.

**Gate 7D widens it, and the reason is a measurement rather than a wish.** The Gate 7B
benchmark scored 3/25 exactly-dimensioned parts, and reading the failures showed the
number was partly an artefact of the grammar: prompts asking for a flanged bushing, a
bracket with a slotted foot or a turned spindle had no expression in a language of
boxes and cylinders, so the models were being scored on parts they could not describe.
Widening the vocabulary changes what that benchmark measures, which is why re-running
it belongs to this gate rather than the last one.

What 7D adds, and nothing beyond it:

* three more primitives — ``sphere``, ``cone``, ``torus``
* a 2-D **profile** (rect, circle, ellipse, polygon, regular polygon, slot) that
  ``extrude`` and ``revolve`` turn into a solid, which is what covers the parts a
  primitive cannot approximate
* ``chamfer``, which is ``fillet`` with a different kernel call and the same selector
* ``polar`` placement — the bolt circle a rectangular grid cannot express

Union and cut were already here as ``mode: add | subtract``, and translation as ``at``;
7D does not re-add them under new names. Rotation stays a per-operation literal triple.
``intersect`` completes that trio — the third boolean, and the one that a "keep only
where the two overlap" request had no way to say.

**Named components** are the other half, and they are what makes the scene tree mean
something. Until now a document produced exactly one body however many separate lumps of
material it described, because ``BuildPart`` fuses everything it is handed and the
exporter writes one mesh subtree per *child*, not per disjoint solid. A housing and its
lid came back as a single row called "Body", and clicking it selected both. Giving an
operation a ``component`` name puts it in its own build: operations sharing a name build
together, each component becomes a labelled child of the result, and the manifest gets
one selectable body per component with the features that made it parented underneath.

The rule is all-or-nothing — either every operation names a component or none do — and
that is deliberate rather than lazy. An unnamed operation in a document that has names
would have to mean either "cut every component" or "cut some default one", both
defensible and neither guessable, and a subtract that quietly chose wrong would remove
material from the wrong part while still reporting a perfectly valid solid.

One limit stated rather than discovered: a ``polar`` placement **positions** instances
around a circle and does not re-orient them. A flange's axial bolt holes are the common
case and need no orientation; a radially-drilled hole does, and cannot be written yet.

Every dimension is a **formula** — either a number or a string parsed by
:mod:`cadir.expr`. A document is rejected at parse time if any formula fails to
compile, so a malformed dimension can never reach geometry.

``op_id`` is required and unique. The Gate 5a spike found that a positional index is
stable under parameter changes but is *not* an author-stable key on its own: it means
"the Nth face of this operation's primitive", which only holds while that primitive
keeps its kind. ``op_id`` is the half the author controls and never renumbers, and
face ids are ``{op_id}[{index}]``. See
``docs/design/2026-08-03-cad-topological-naming-spike.md``.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import expr as expr_mod

# 0.2 adds ``component`` to every operation and ``intersect`` to ``mode`` (Gate 7D).
# Both are additive and both changed the normalized form of *every* document, because
# ``model_dump(exclude_defaults=False)`` writes the new key into operations that never
# mention it — which is exactly what ``test_cadir_migration`` is there to catch, and a
# version bump rather than a regenerated fixture is what that test asks for.
#
# 0.1 documents are still accepted and still mean what they meant: an operation with no
# component builds the one body it always built. They keep declaring ``"0.1"`` — parsing
# does not rewrite what an author stored.
# 0.3 adds ``placements`` — a per-component rigid transform, and the thing that makes
# "drag this part" expressible at all. Before it, a component's position lived only in
# its operations' own ``at``/``rotation``, so moving a body meant rewriting every one of
# them and baking symbolic origins into numbers. The document-level transform leaves the
# formulas exactly as the author wrote them. Additive and defaulted, so 0.1 and 0.2
# documents keep meaning what they meant; the bump is for the same reason 0.2 needed one
# — ``exclude_defaults=False`` writes the new key into the normalized form of every
# document, which moves the canonical hash.
SCHEMA_VERSION = "0.3"
KNOWN_SCHEMA_VERSIONS = ("0.1", "0.2", "0.3")

MAX_PARAMETERS = 64
MAX_OPERATIONS = 128

# A formula is a number or a restricted expression. Numbers are allowed because
# ``"size": [10, 20, 30]`` should not have to be written as three quoted strings.
Formula = Union[float, int, str]

# The name of a body an operation contributes to. Same character set as ``op_id`` and
# for the same reason: it is an author-chosen key that ends up in a node label and in
# model-facing context, so it stays lowercase, boring and free of anything that would
# need escaping on the way out.
ComponentName = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Parameter(StrictModel):
    """A named input with a declared range, mirroring ``recipes.PARAM_SPEC`` so the
    two sources of truth cannot drift into disagreeing about what is legal."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["float", "int"] = "float"
    default: float
    min: float
    max: float

    @model_validator(mode="after")
    def _range_is_orderable(self):
        if self.min > self.max:
            raise ValueError(f"{self.name}: min ({self.min}) exceeds max ({self.max})")
        if not (self.min <= self.default <= self.max):
            raise ValueError(
                f"{self.name}: default ({self.default}) is outside [{self.min}, {self.max}]"
            )
        return self


class Derived(StrictModel):
    """A value computed once from parameters and earlier derived values.

    These exist so the operations read like the recipe they replace. ``length`` is
    written once and referred to five times, instead of five copies of
    ``studs_x * pitch_mm - 2 * clearance_mm`` that can drift apart.
    """

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    value: Formula


class Grid(StrictModel):
    """A rectangular array of positions centred on ``center``.

    Both recipes' location lists are this shape. The brick's stud grid is
    ``count=(nx, ny, 1)``; its interlock tubes are ``count=(nx-1, ny-1, 1)`` at the
    same pitch, which lands on the diagonals between four studs because a centred
    grid of ``n-1`` items at pitch ``p`` is exactly the half-step offset the recipe
    computed by hand. The hanger's screw holes are ``count=(1, 1, screw_count)``.
    """

    count: list[Formula] = Field(min_length=3, max_length=3)
    pitch: list[Formula] = Field(min_length=3, max_length=3)
    center: list[Formula] = Field(default=[0, 0, 0], min_length=3, max_length=3)


class Points(StrictModel):
    """Explicit positions, for the cases a grid does not describe."""

    # The inner triple is enforced by the validator below rather than by a length
    # constraint, so it is invisible to anything reading field metadata — including
    # the grammar description the authoring models read. Hence the description.
    positions: list[list[Formula]] = Field(
        min_length=1, max_length=64,
        description="each entry is exactly [x, y, z]")

    @field_validator("positions")
    @classmethod
    def _each_is_xyz(cls, v):
        for p in v:
            if len(p) != 3:
                raise ValueError("each position must be [x, y, z]")
        return v


class Polar(StrictModel):
    """Instances evenly spaced around a circle in the XY plane — the bolt circle.

    ``angle_span`` divides by ``count`` on a full turn and by ``count - 1`` otherwise,
    which is build123d's own ``PolarLocations`` rule and the one that gives both the
    expected answers: six holes over 360° land 60° apart with none doubled at the seam,
    and three holes over 90° land on 0°, 45° and 90° with the endpoints included.

    It places and does not orient — see the module docstring.
    """

    count: Formula
    radius: Formula
    start_angle: Formula = 0
    angle_span: Formula = 360
    center: list[Formula] = Field(default=[0, 0, 0], min_length=3, max_length=3)


Placement = Union[Grid, Points, Polar]


class _Profile(StrictModel):
    """Shared 2-D placement for every profile kind.

    ``origin`` moves the profile inside its own plane. It exists for ``revolve``, where
    the distance from the axis of rotation *is* the part: a bushing is a rectangle at
    x = bore/2, and without an offset every profile would straddle the axis and produce
    a self-intersecting solid.
    """

    origin: list[Formula] = Field(default=[0, 0], min_length=2, max_length=2)


class RectProfile(_Profile):
    kind: Literal["rect"]
    size: list[Formula] = Field(min_length=2, max_length=2)
    corner_radius: Formula | None = None


class CircleProfile(_Profile):
    kind: Literal["circle"]
    radius: Formula


class EllipseProfile(_Profile):
    kind: Literal["ellipse"]
    radii: list[Formula] = Field(min_length=2, max_length=2)


class PolygonProfile(_Profile):
    kind: Literal["polygon"]
    points: list[list[Formula]] = Field(min_length=3, max_length=64)

    @field_validator("points")
    @classmethod
    def _each_is_xy(cls, v):
        for p in v:
            if len(p) != 2:
                raise ValueError("each polygon point must be [x, y]")
        return v


class RegularPolygonProfile(_Profile):
    kind: Literal["regular_polygon"]
    radius: Formula
    sides: int = Field(ge=3, le=64)


class SlotProfile(_Profile):
    kind: Literal["slot"]
    length: Formula
    height: Formula


Profile = Annotated[
    Union[RectProfile, CircleProfile, EllipseProfile, PolygonProfile,
          RegularPolygonProfile, SlotProfile],
    Field(discriminator="kind"),
]


class BoxOp(StrictModel):
    op: Literal["box"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    size: list[Formula] = Field(min_length=3, max_length=3)
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class CylinderOp(StrictModel):
    op: Literal["cylinder"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    radius: Formula
    height: Formula
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class SphereOp(StrictModel):
    op: Literal["sphere"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    radius: Formula
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class ConeOp(StrictModel):
    """A truncated cone. ``top_radius: 0`` is the point, which is how a countersink and
    a chamfered lead-in get written without a second operation kind."""

    op: Literal["cone"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    bottom_radius: Formula
    top_radius: Formula = 0
    height: Formula
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class TorusOp(StrictModel):
    op: Literal["torus"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    major_radius: Formula
    minor_radius: Formula
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class ExtrudeOp(StrictModel):
    """A profile pushed along the normal of the plane it sits on.

    ``both`` extrudes symmetrically about that plane, which is what "a 40 mm long rib
    centred on the origin" means and is otherwise two operations and an offset.
    """

    op: Literal["extrude"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    profile: Profile
    amount: Formula
    plane: Literal["XY", "XZ", "YZ"] = "XY"
    both: bool = False
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class RevolveOp(StrictModel):
    """A profile in the XZ plane turned about the Z axis — the lathe.

    The plane and the axis are fixed rather than configurable, because every other
    pairing is either a rotation of this one (write it as ``rotation``) or a profile
    that crosses its own axis, which is a self-intersecting solid the kernel reports
    with a message nobody can act on. ``x`` in the profile is therefore distance from
    the axis, and a profile with any negative ``x`` is refused before geometry starts.
    """

    op: Literal["revolve"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    profile: Profile
    angle: Formula = 360
    at: Placement | None = None
    mode: Literal["add", "subtract", "intersect"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None
    component: ComponentName | None = None


class EdgeSelector(StrictModel):
    """A declarative edge selection — never a callable, never a lambda.

    ``filter_by`` an axis, ``sort_by`` an axis, then take a slice. That is precisely
    what the hanger does to find its cantilever root, and keeping it declarative is
    what stops "select the edges to fillet" from becoming an evaluation hole.
    """

    filter_by: Literal["X", "Y", "Z"]
    sort_by: Literal["X", "Y", "Z"]
    take: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _slice_is_sane(self):
        lo, hi = self.take
        if lo < 0 or hi <= lo or hi > 64:
            raise ValueError(f"take must be [lo, hi] with 0 <= lo < hi <= 64 (got {self.take})")
        return self


class FaceSelector(StrictModel):
    """A declarative face selection, deliberately the same three fields as
    :class:`EdgeSelector`.

    ``filter_by`` keeps the faces whose **normal** is parallel to that axis — so ``Z``
    on a box is its top and bottom — then ``sort_by`` orders them along an axis and the
    slice takes some. Identical in shape to the edge selector because a model that has
    learned one should not have to learn a second spelling for the same idea, and
    because keeping it declarative is what stops "choose the faces to open" from
    becoming an evaluation hole.
    """

    filter_by: Literal["X", "Y", "Z"]
    sort_by: Literal["X", "Y", "Z"]
    take: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _slice_is_sane(self):
        lo, hi = self.take
        if lo < 0 or hi <= lo or hi > 64:
            raise ValueError(f"take must be [lo, hi] with 0 <= lo < hi <= 64 (got {self.take})")
        return self


class FilletOp(StrictModel):
    op: Literal["fillet"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    radius: Formula
    select: EdgeSelector
    when: Formula | None = None
    # The hanger wraps its fillet in try/except: a radius the local geometry cannot
    # take is a degraded part, not a failed build. Carrying that as a declared flag
    # keeps the behaviour identical instead of reinventing it as a silent except.
    optional: bool = False
    # Which body this rounds. An edge op works on whatever material is already there,
    # so in a multi-component document it has to say which pile of material it means —
    # the alternative is rounding every component's edges at once.
    component: ComponentName | None = None


class ChamferOp(StrictModel):
    """``fillet`` with a straight cut instead of a round one.

    Same declarative selector, same ``optional`` escape hatch, and deliberately the
    same shape: two features that differ only in the kernel call should not differ in
    how they are written, or a model that has learned one will get the other wrong.
    ``length`` rather than ``radius`` because that is the dimension a chamfer has.
    """

    op: Literal["chamfer"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    length: Formula
    select: EdgeSelector
    when: Formula | None = None
    optional: bool = False
    component: ComponentName | None = None


class MirrorOp(StrictModel):
    """Reflect everything built so far about a plane and keep both halves.

    Written as an operation rather than as a flag on each primitive because that is
    what makes it useful: a symmetric bracket is authored as one half — however many
    operations that takes — and mirrored once. A per-primitive flag would reflect the
    *placement* of each solid, which is a different thing entirely and silently wrong
    for anything rotated.

    It always unions. A mirror that replaced the original would just be a reflection,
    which no part needs and which would read as a mirror right up until someone looked
    at the result. What it reflects is the current **component**, so one half of a
    housing can be mirrored without touching the lid.
    """

    op: Literal["mirror"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    plane: Literal["XY", "XZ", "YZ"] = "YZ"
    when: Formula | None = None
    component: ComponentName | None = None


class ShellOp(StrictModel):
    """Hollow the solid out, leaving walls ``thickness`` thick.

    ``openings`` names the faces to remove, and is what turns a sealed void into a cup,
    a tray or an enclosure. It is optional: with no openings the result is a closed
    hollow — correct for a pressure vessel and useless for anything printed, which is
    why the grammar makes you say the word rather than defaulting to one of them.

    There is no ``optional`` escape hatch, unlike fillet and chamfer. A fillet that
    does not fit yields a part missing a cosmetic round; a shell that does not fit
    yields a *solid* part where a hollow one was asked for, and shipping that as a
    success is the mass-and-material lie this lane exists to refuse.
    """

    op: Literal["shell"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    thickness: Formula
    openings: FaceSelector | None = None
    when: Formula | None = None
    component: ComponentName | None = None


# Operations that consume the existing part rather than adding to it. They cannot come
# first, and :mod:`cadir.interpret` flushes the pending primitives before each one.
EDGE_OPS = ("fillet", "chamfer")
# The same rule, for the operations that reshape a whole body instead of its edges.
BODY_OPS = ("mirror", "shell")
CONSUMING_OPS = EDGE_OPS + BODY_OPS

Operation = Annotated[
    Union[BoxOp, CylinderOp, SphereOp, ConeOp, TorusOp, ExtrudeOp, RevolveOp,
          FilletOp, ChamferOp, MirrorOp, ShellOp],
    Field(discriminator="op"),
]


def _finite_triple(v):
    """Reject NaN and Infinity in a literal xyz triple.

    The formula compiler already refuses non-finite constants and the parameter
    resolver refuses non-finite inputs, but a *literal* float field went through
    neither — ``rotation: [NaN, 0, 0]`` parsed cleanly and reached the kernel, which is
    the Gate 1A hang under a different field name. One validator, both fields.
    """
    for f in v:
        if not math.isfinite(float(f)):
            raise ValueError("must be finite (NaN and Infinity are rejected)")
    return v


class ComponentPlacement(StrictModel):
    """Where a named component sits, as a rigid transform of the finished body.

    This exists because a drag in the viewport has to become something a document can
    *say*. A component is otherwise only a label shared by some operations, and each of
    those carries its own ``at``/``rotation``; shifting the body by rewriting all of
    them turns ``"wall_t + bore/2"`` into a baked number and loses the intent the author
    wrote. A transform applied after the body is built leaves every formula untouched,
    so a later parameter change still moves the part the way it was meant to.

    ``rotate`` is degrees about the component's **own bounding-box centre**, applied
    before ``translate``. Centre rather than the document origin because that is what a
    gizmo does and what a person means: rotating a part that happens to sit 200 mm out
    about the world origin would fling it across the scene.

    Both fields are literal numbers, not formulas. A drag produces a measured position,
    not an expression, and storing the number the user stopped at is what makes the
    rebuilt geometry match the preview they accepted.
    """

    component: ComponentName
    translate: list[float] = Field(default=[0.0, 0.0, 0.0], min_length=3, max_length=3)
    rotate: list[float] = Field(default=[0.0, 0.0, 0.0], min_length=3, max_length=3)

    @field_validator("translate", "rotate")
    @classmethod
    def _finite(cls, v):
        return _finite_triple(v)

    @field_validator("translate")
    @classmethod
    def _within_reach(cls, v):
        # A metre in any direction is far outside anything this lane builds, and the
        # cap is here so a runaway drag cannot hand the kernel a bounding box that
        # admission control then has to reason about.
        for f in v:
            if abs(float(f)) > 1000.0:
                raise ValueError("translate is limited to ±1000 mm per axis")
        return v


class CadDocument(StrictModel):
    schema_version: Literal["0.1", "0.2", "0.3"]
    units: Literal["mm"] = "mm"
    name: str = Field(min_length=1, max_length=64)
    parameters: list[Parameter] = Field(default=[], max_length=MAX_PARAMETERS)
    derived: list[Derived] = Field(default=[], max_length=MAX_PARAMETERS)
    operations: list[Operation] = Field(min_length=1, max_length=MAX_OPERATIONS)
    placements: list[ComponentPlacement] = Field(default=[], max_length=16)
    expected_solids: int = Field(default=1, ge=1, le=16)

    @model_validator(mode="after")
    def _names_are_unique(self):
        for label, names in (
            ("parameter", [p.name for p in self.parameters]),
            ("derived value", [d.name for d in self.derived]),
            ("op_id", [o.op_id for o in self.operations]),
        ):
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                raise ValueError(f"duplicate {label}(s): {', '.join(dupes)}")
        clash = sorted(set(n.name for n in self.parameters) & set(d.name for d in self.derived))
        if clash:
            raise ValueError(f"derived value(s) shadow a parameter: {', '.join(clash)}")
        # A literal rotation triple never went through the formula compiler or the
        # parameter resolver, so nothing was rejecting NaN on it. Checked here rather
        # than as a field validator on eleven separate operation classes.
        for o in self.operations:
            rot = getattr(o, "rotation", None)
            if rot is not None:
                try:
                    _finite_triple(rot)
                except ValueError as exc:
                    raise ValueError(f"{o.op_id}: rotation {exc}") from None

        named = [o for o in self.operations if o.component]
        if named and len(named) != len(self.operations):
            missing = [o.op_id for o in self.operations if not o.component]
            raise ValueError(
                "either every operation names a component or none do; these do not: "
                + ", ".join(missing)
            )
        # An edge op cannot invent a body. If it names a component no solid operation
        # builds, there is nothing there to round, and the alternative to saying so is
        # a build that succeeds having quietly filleted nothing.
        solid_components = {
            o.component for o in self.operations if o.op not in CONSUMING_OPS and o.component
        }
        for o in self.operations:
            if o.op in CONSUMING_OPS and o.component and o.component not in solid_components:
                raise ValueError(
                    f"{o.op_id} works on component '{o.component}', which no operation builds"
                )

        # "There is nothing to fillet yet" is per-component once components exist: an
        # early fillet on `lid` is still wrong even if `housing` was built first.
        seen: set[str | None] = set()
        for o in self.operations:
            if o.op in CONSUMING_OPS and o.component not in seen:
                what = "the first operation" if not o.component else f"the first operation on '{o.component}'"
                raise ValueError(
                    f"{what} cannot be a {o.op} — there is nothing to {o.op}"
                )
            seen.add(o.component)

        # A placement for a component nobody builds is a transform that silently does
        # nothing, and the shape of that mistake is a renamed part: the drag was
        # recorded, the rebuild succeeded, and the body did not move.
        placed = [p.component for p in self.placements]
        dupes = sorted({n for n in placed if placed.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate placement(s) for: {', '.join(dupes)}")
        built = {o.component for o in self.operations if o.component}
        unknown = sorted(set(placed) - built)
        if unknown:
            raise ValueError(
                "placement names component(s) no operation builds: " + ", ".join(unknown)
            )
        return self


# The scalar formula fields each operation carries. A table rather than an if/elif
# chain because the chain ended in a bare ``else: yield o.radius``, which meant every
# operation added after it silently inherited "has a radius" and had the rest of its
# dimensions compiled by nobody. A new op that forgets to appear here raises KeyError
# on the first parse instead of shipping unchecked formulas.
_SCALAR_FIELDS = {
    "box": (),
    "cylinder": ("radius", "height"),
    "sphere": ("radius",),
    "cone": ("bottom_radius", "top_radius", "height"),
    "torus": ("major_radius", "minor_radius"),
    "extrude": ("amount",),
    "revolve": ("angle",),
    "fillet": ("radius",),
    "chamfer": ("length",),
    "mirror": (),
    "shell": ("thickness",),
}


def _profile_formulas(profile, where: str):
    for i, c in enumerate(profile.origin):
        yield f"{where}.origin[{i}]", c
    if profile.kind == "rect":
        for i, s in enumerate(profile.size):
            yield f"{where}.size[{i}]", s
        if profile.corner_radius is not None:
            yield f"{where}.corner_radius", profile.corner_radius
    elif profile.kind in ("circle", "regular_polygon"):
        yield f"{where}.radius", profile.radius
    elif profile.kind == "ellipse":
        for i, r in enumerate(profile.radii):
            yield f"{where}.radii[{i}]", r
    elif profile.kind == "slot":
        yield f"{where}.length", profile.length
        yield f"{where}.height", profile.height
    else:
        for j, p in enumerate(profile.points):
            for i, c in enumerate(p):
                yield f"{where}.points[{j}][{i}]", c


def _formulas(doc: CadDocument):
    """Every formula in the document, with a human-readable location for errors."""
    for d in doc.derived:
        yield f"derived.{d.name}", d.value
    for o in doc.operations:
        where = f"{o.op_id}"
        if o.when is not None:
            yield f"{where}.when", o.when
        for field in _SCALAR_FIELDS[o.op]:
            yield f"{where}.{field}", getattr(o, field)
        if o.op == "box":
            for i, s in enumerate(o.size):
                yield f"{where}.size[{i}]", s
        profile = getattr(o, "profile", None)
        if profile is not None:
            yield from _profile_formulas(profile, f"{where}.profile")
        at = getattr(o, "at", None)
        if isinstance(at, Grid):
            for field in ("count", "pitch", "center"):
                for i, s in enumerate(getattr(at, field)):
                    yield f"{where}.at.{field}[{i}]", s
        elif isinstance(at, Points):
            for j, p in enumerate(at.positions):
                for i, s in enumerate(p):
                    yield f"{where}.at.positions[{j}][{i}]", s
        elif isinstance(at, Polar):
            for field in ("count", "radius", "start_angle", "angle_span"):
                yield f"{where}.at.{field}", getattr(at, field)
            for i, s in enumerate(at.center):
                yield f"{where}.at.center[{i}]", s


def parse(payload: dict) -> CadDocument:
    """Validate a document *and* every formula in it.

    Compiling up front is the point: a formula that only fails on the unlucky branch
    of a guard would otherwise surface as a mid-build crash instead of a 400 the
    caller can act on.
    """
    doc = CadDocument.model_validate(payload)
    known = {p.name for p in doc.parameters}
    for location, formula in _formulas(doc):
        if isinstance(formula, str):
            try:
                tree = expr_mod.compile_expr(formula)
            except expr_mod.ExprError as exc:
                raise expr_mod.ExprError(exc.code, f"{location}: {exc.message}") from None
            # Name resolution is checked here too, against the symbols visible at
            # that point — a typo'd parameter should be a parse error, not a runtime
            # one, and derived values are only visible after they are defined.
            unresolved = expr_mod.free_names(tree) - (known | _visible_derived(doc, location))
            if unresolved:
                raise expr_mod.ExprError(
                    "unknown_symbol",
                    f"{location}: unknown name '{sorted(unresolved)[0]}'",
                )
    return doc


def canonical_source_hash(doc: CadDocument, resolved: dict) -> str:
    """SHA-256 over the normalized (schema version + document + sorted parameters).

    The same identity :func:`recipes.canonical_source_hash` computes, extended to cover
    the document itself — a recipe name identified the geometry when the geometry lived
    in Python, but a CadIR document *is* the geometry, so two revisions that share
    parameter values and differ in operations are not the same build.

    Hashing the input rather than the exported bytes is not a stylistic choice: STEP
    embeds ``FILE_NAME(…,'2026-08-03T05:55:27',…)``, a wall-clock timestamp at
    one-second resolution, and 3MF is a ZIP that differed across two writes inside the
    same second. A byte-identity gate would have passed in CI and failed in production
    the first time a build straddled a second boundary.
    """
    params = {}
    for name in sorted(resolved):
        v = resolved[name]
        if isinstance(v, float):
            # -0.0 and 0.0 are equal but serialise differently, and a clamp at a lower
            # bound of 0 can produce either.
            v = 0.0 if v == 0 else float(v)
        params[name] = v
    payload = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "document": doc.model_dump(mode="json", exclude_defaults=False),
            "params": params,
        },
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _visible_derived(doc: CadDocument, location: str) -> set[str]:
    """Derived names in scope at ``location``. Inside ``derived.<name>`` only the
    values defined before it are visible, so a document cannot define a cycle."""
    if location.startswith("derived."):
        target = location.split(".", 1)[1]
        out = set()
        for d in doc.derived:
            if d.name == target:
                return out
            out.add(d.name)
        return out
    return {d.name for d in doc.derived}
