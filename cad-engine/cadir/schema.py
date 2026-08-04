"""The CadIR document — a declarative, human-readable parametric source.

Scope is set by the Gate 5 rule "only the operations the two tested recipes justify".
That is three operations (``box``, ``cylinder``, ``fillet``), two placement kinds
(explicit points and a centred grid), and a guard expression, because between them
the helmet hanger and the studded brick use exactly that and nothing else. Anything
richer is unbuilt and unmeasured, and a schema that promises it would be lying about
what the interpreter can do.

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
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import expr as expr_mod

SCHEMA_VERSION = "0.1"

MAX_PARAMETERS = 64
MAX_OPERATIONS = 128

# A formula is a number or a restricted expression. Numbers are allowed because
# ``"size": [10, 20, 30]`` should not have to be written as three quoted strings.
Formula = Union[float, int, str]


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

    positions: list[list[Formula]] = Field(min_length=1, max_length=64)

    @field_validator("positions")
    @classmethod
    def _each_is_xyz(cls, v):
        for p in v:
            if len(p) != 3:
                raise ValueError("each position must be [x, y, z]")
        return v


Placement = Union[Grid, Points]


class BoxOp(StrictModel):
    op: Literal["box"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    size: list[Formula] = Field(min_length=3, max_length=3)
    at: Placement | None = None
    mode: Literal["add", "subtract"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None


class CylinderOp(StrictModel):
    op: Literal["cylinder"]
    op_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    radius: Formula
    height: Formula
    at: Placement | None = None
    mode: Literal["add", "subtract"] = "add"
    rotation: list[float] = Field(default=[0, 0, 0], min_length=3, max_length=3)
    when: Formula | None = None


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


Operation = Annotated[Union[BoxOp, CylinderOp, FilletOp], Field(discriminator="op")]


class CadDocument(StrictModel):
    schema_version: Literal["0.1"]
    units: Literal["mm"] = "mm"
    name: str = Field(min_length=1, max_length=64)
    parameters: list[Parameter] = Field(default=[], max_length=MAX_PARAMETERS)
    derived: list[Derived] = Field(default=[], max_length=MAX_PARAMETERS)
    operations: list[Operation] = Field(min_length=1, max_length=MAX_OPERATIONS)
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
        if self.operations[0].op == "fillet":
            raise ValueError("the first operation cannot be a fillet — there is nothing to fillet")
        return self


def _formulas(doc: CadDocument):
    """Every formula in the document, with a human-readable location for errors."""
    for d in doc.derived:
        yield f"derived.{d.name}", d.value
    for o in doc.operations:
        where = f"{o.op_id}"
        if o.when is not None:
            yield f"{where}.when", o.when
        if o.op == "box":
            for i, s in enumerate(o.size):
                yield f"{where}.size[{i}]", s
        elif o.op == "cylinder":
            yield f"{where}.radius", o.radius
            yield f"{where}.height", o.height
        else:
            yield f"{where}.radius", o.radius
        at = getattr(o, "at", None)
        if isinstance(at, Grid):
            for field in ("count", "pitch", "center"):
                for i, s in enumerate(getattr(at, field)):
                    yield f"{where}.at.{field}[{i}]", s
        elif isinstance(at, Points):
            for j, p in enumerate(at.positions):
                for i, s in enumerate(p):
                    yield f"{where}.at.positions[{j}][{i}]", s


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
