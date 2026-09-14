"""Execute a CadIR document against build123d.

This is the only module in the package that imports the geometry kernel, and it runs
in the killable child process. Everything it receives has already been validated,
resolved and charged by :mod:`cadir.schema` and :mod:`cadir.budget` — it never parses a
formula it has not been handed, and it has no path back to arbitrary code.

**What it deliberately does not do yet: carry OCCT history.** The Gate 5a spike proved
per-face attribution works, and also proved build123d discards the builder that carries
it — ``Shape.fuse`` constructs ``BRepAlgoAPI_Fuse()`` as a local and returns only the
shape. Owning those builders here means replacing build123d's boolean path, which is
the one change most likely to perturb the golden geometry Gate 5 requires to stay
unchanged. So the interpreter uses build123d's own operators, reproduces the recipes
exactly, and the history-carrying variant is Gate 6's problem, alongside the selection
UI that is the only thing which needs it. See
``docs/design/2026-08-03-cad-topological-naming-spike.md`` §7.
"""
from __future__ import annotations

from build123d import (
    Axis, Box, BuildPart, Circle, Compound, Cone, Cylinder, Ellipse, Kind, Locations,
    Mode, Plane, Polygon, Pos, RegularPolygon, Rectangle, RectangleRounded, Rotation,
    SlotOverall, Sphere, Torus, add, chamfer, extrude, fillet, mirror, offset, revolve,
)

from . import budget as budget_mod
from .schema import CONSUMING_OPS, EDGE_OPS, CadDocument


class CadIRRuntimeError(ValueError):
    """A geometry failure this module itself diagnosed.

    Distinct from an arbitrary OCCT exception because the message is one we wrote:
    it names an op_id the caller already sent us and nothing else, so it is safe to
    return, and it is the only thing a repair attempt can act on. Anything raised by
    the kernel stays anonymous — those strings carry paths and internal state.
    """

_AXIS = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}
_MODE = {"add": Mode.ADD, "subtract": Mode.SUBTRACT, "intersect": Mode.INTERSECT}
_PLANE = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}


def _value(formula, env):
    return budget_mod._value(formula, env)


def _face(profile, env):
    """Build a 2-D profile in algebra mode, offset by its own ``origin``.

    Algebra rather than ``BuildSketch`` because the result has to be a value this
    module can rotate and hand to ``add`` inside a ``Locations`` context; a sketch
    builder nested three deep inside ``BuildPart`` and ``Locations`` is the same
    geometry with a context stack that decides where it lands.
    """
    if profile.kind == "rect":
        w, h = (_value(s, env) for s in profile.size)
        r = _value(profile.corner_radius, env) if profile.corner_radius is not None else 0.0
        face = RectangleRounded(w, h, r) if r > 0 else Rectangle(w, h)
    elif profile.kind == "circle":
        face = Circle(_value(profile.radius, env))
    elif profile.kind == "ellipse":
        a, b = (_value(r, env) for r in profile.radii)
        face = Ellipse(a, b)
    elif profile.kind == "regular_polygon":
        face = RegularPolygon(radius=_value(profile.radius, env), side_count=profile.sides)
    elif profile.kind == "slot":
        face = SlotOverall(width=_value(profile.length, env), height=_value(profile.height, env))
    else:
        pts = [(_value(p[0], env), _value(p[1], env)) for p in profile.points]
        face = Polygon(*pts, align=None)

    ox, oy = (_value(c, env) for c in profile.origin)
    if ox or oy:
        face = Pos(ox, oy, 0) * face
    return face


def _profiled_solid(op, env):
    """Turn a profiled operation into one solid, before it is placed or combined.

    Every kernel failure here is re-authored from values the caller already sent us,
    for the reason :func:`_apply_edge_op` states: a repair attempt can act on "a 0 mm
    wide rectangle has no area", and cannot act on a boolean-algorithm traceback.
    """
    try:
        face = _face(op.profile, env)
        if op.op == "extrude":
            return extrude(_PLANE[op.plane] * face,
                           amount=_value(op.amount, env), both=op.both)
        return revolve(Plane.XZ * face, axis=Axis.Z,
                       revolution_arc=_value(op.angle, env))
    except CadIRRuntimeError:
        raise
    except Exception:
        raise CadIRRuntimeError(
            f"{op.op_id}: the {op.profile.kind} profile could not be turned into a "
            f"solid — check that every dimension is greater than zero and that the "
            f"outline does not cross itself"
        ) from None


def _emit(op, positions, env, solid=None) -> None:
    """Place one operation's primitives inside the enclosing BuildPart context.

    ``solid`` is the already-built body for a profiled operation, constructed by
    :func:`_prebuild_profiles` with **no builder context active at all**. That is not a
    stylistic preference: build123d's sketch primitives call ``validate_inputs``, which
    refuses a ``Rectangle`` inside a ``BuildPart`` outright — "Rectangle applies to
    ['BuildSketch']" — so a profile cannot be constructed anywhere inside the part
    builder, let alone inside a ``Locations`` context that would then re-place the solid
    it becomes.
    """
    mode = _MODE[op.mode]
    rotation = tuple(float(r) for r in op.rotation)
    kwargs = {"mode": mode}
    if any(rotation):
        kwargs["rotation"] = rotation

    with Locations(*positions):
        if op.op == "box":
            Box(*[_value(s, env) for s in op.size], **kwargs)
        elif op.op == "cylinder":
            Cylinder(radius=_value(op.radius, env), height=_value(op.height, env), **kwargs)
        elif op.op == "sphere":
            Sphere(radius=_value(op.radius, env), **kwargs)
        elif op.op == "cone":
            Cone(bottom_radius=_value(op.bottom_radius, env),
                 top_radius=_value(op.top_radius, env),
                 height=_value(op.height, env), **kwargs)
        elif op.op == "torus":
            Torus(major_radius=_value(op.major_radius, env),
                  minor_radius=_value(op.minor_radius, env), **kwargs)
        else:
            add(solid, mode=mode)


def _prebuild_profiles(pending, env):
    """Every profiled operation's solid, built while no builder context is open.

    Returns a list parallel to ``pending`` holding the solid for each profiled op and
    ``None`` for the primitives, so :func:`_emit` places a value rather than building
    one. Rotation is applied here for the same reason: ``Rotation(...) * solid`` is
    algebra on a finished shape, and doing it inside ``Locations`` would compose the
    placement into the rotation.
    """
    out = []
    for op, _positions in pending:
        if op.op not in ("extrude", "revolve"):
            out.append(None)
            continue
        solid = _profiled_solid(op, env)
        rotation = tuple(float(r) for r in op.rotation)
        if any(rotation):
            solid = Rotation(*rotation) * solid
        out.append(solid)
    return out


def _apply_edge_op(part, op, env):
    """Fillet or chamfer edges chosen declaratively — filter by an axis, sort, slice.

    ``optional`` reproduces the hanger's ``try/except`` rather than reinventing it: a
    radius the local geometry cannot take yields a part without that fillet, which is a
    degraded result, not a failed build. A non-optional fillet that fails is an error,
    because silently dropping a feature the author declared as required would be the
    "cheerful 200 for the wrong part" failure in a new costume.

    Chamfer shares the whole body of this function because it shares the whole failure
    mode: the same selector matching nothing, the same dimension not fitting the
    material. Two copies would have drifted the moment one of them was fixed.
    """
    size = _value(op.length if op.op == "chamfer" else op.radius, env)
    sel = op.select
    try:
        edges = part.edges().filter_by(_AXIS[sel.filter_by]).sort_by(_AXIS[sel.sort_by])
        chosen = edges[sel.take[0]:sel.take[1]]
        if not chosen:
            raise CadIRRuntimeError(f"{op.op_id}: the edge selector matched nothing")
        try:
            if op.op == "chamfer":
                return chamfer(chosen, length=size)
            return fillet(chosen, radius=size)
        except CadIRRuntimeError:
            raise
        except Exception:
            # build123d's own message here is the best one in the whole failure
            # surface — it names the radius and says to try a smaller value — and
            # the generic handler in worker_main was flattening it to "geometry
            # engine failed (ValueError)", which tells a repair attempt to guess.
            # Re-authored rather than echoed, from two values the caller already
            # sent us, so the rule that no kernel string escapes still holds.
            # Measured: this was granite4.1:8b's only geometry failure in the
            # Gate 7B benchmark.
            word = "chamfer" if op.op == "chamfer" else "fillet"
            raise CadIRRuntimeError(
                f"{op.op_id}: a {word} of {size:g} mm does not fit the "
                f"edges it selected — it has to be smaller than half the "
                f"thinnest material it cuts into"
            ) from None
    except Exception:
        if op.optional:
            return part
        raise


def _mirrored(part, op):
    """Reflect the body and keep both halves.

    Always a union, because that is the operation authors actually want: a symmetric
    bracket is drawn once and completed once. ``mirror`` alone would *replace* the
    original with its reflection, which looks identical for a symmetric solid and is
    silently wrong for every asymmetric one — the failure would only show up in the
    finished part.
    """
    try:
        return part + mirror(part, about=_PLANE[op.plane])
    except CadIRRuntimeError:
        raise
    except Exception:
        raise CadIRRuntimeError(
            f"{op.op_id}: the body could not be mirrored about the {op.plane} plane"
        ) from None


def _shelled(part, op, env):
    """Hollow the body out, optionally opening some of its faces.

    Two paths, because build123d's ``offset`` means two different things depending on
    ``openings``. With openings it removes those faces and walls the rest — a cup.
    With none it returns *the shrunk inner solid*, not a hollow: measured, a 30×20×10
    box offset by −2 gives 2496 mm³, which is exactly the 26×16×6 block, where a hollow
    would be 3504. So the closed case is written as the subtraction it actually is.

    ``kind=Kind.INTERSECTION`` keeps the walls square at the corners rather than
    rounding them, which is what "3 mm wall" means to whoever asked for one.
    """
    thickness = _value(op.thickness, env)
    if thickness <= 0:
        raise CadIRRuntimeError(
            f"{op.op_id}: a wall thickness of {thickness:g} mm cannot be hollowed — "
            f"it has to be greater than zero"
        )

    openings = None
    if op.openings is not None:
        sel = op.openings
        faces = part.faces().filter_by(_AXIS[sel.filter_by]).sort_by(_AXIS[sel.sort_by])
        openings = faces[sel.take[0]:sel.take[1]]
        if not openings:
            raise CadIRRuntimeError(f"{op.op_id}: the face selector matched nothing")

    try:
        if openings is None:
            return part - offset(part, amount=-thickness, kind=Kind.INTERSECTION)
        return offset(part, amount=-thickness, openings=openings, kind=Kind.INTERSECTION)
    except CadIRRuntimeError:
        raise
    except Exception:
        # The kernel's own message here is "offset Error, an alternative kind may
        # resolve this error", which is both anonymous and misleading — the usual
        # cause is a wall thicker than half the material it is hollowing, not the
        # corner style. Re-authored from two values the caller already sent us.
        raise CadIRRuntimeError(
            f"{op.op_id}: a wall {thickness:g} mm thick does not fit inside this "
            f"body — it has to be less than half the thinnest section it hollows"
        ) from None


def _apply_body_op(part, op, env):
    """Mirror or shell, the operations that reshape a whole body rather than its edges."""
    if op.op == "mirror":
        return _mirrored(part, op)
    return _shelled(part, op, env)


def _build_body(steps, env):
    """Run one component's operations in order and return its solid, or ``None``.

    ``None`` rather than an exception because "this component's every operation was
    dropped by a guard" is a legitimate outcome the caller has to interpret in context:
    for the whole document it is a failure, for one component of several it is a part
    that was configured away.
    """
    part = None
    pending = []

    def flush():
        """Run the accumulated add/subtract operations as one BuildPart."""
        nonlocal part, pending
        if not pending:
            return
        solids = _prebuild_profiles(pending, env)
        with BuildPart() as bp:
            if part is not None:
                add(part)
            for (op, positions), solid in zip(pending, solids):
                _emit(op, positions, env, solid)
        part = bp.part
        pending = []

    for op, positions in steps:
        if op.op in CONSUMING_OPS:
            flush()
            if part is None:
                raise CadIRRuntimeError(f"{op.op_id}: nothing to {op.op}")
            part = (_apply_edge_op if op.op in EDGE_OPS else _apply_body_op)(part, op, env)
        else:
            pending.append((op, positions))
    flush()
    return part


def _placed(body, placement):
    """Apply a component's rigid transform: rotate about its own centre, then move.

    Its own centre, not the document origin. ``Rotation(*r) * solid`` turns the shape
    about (0, 0, 0), so a part sitting 200 mm out would swing 200 mm through an arc
    instead of turning in place — which is not what a gizmo shows and not what anyone
    dragging it means. Conjugating by the centre is the difference.
    """
    rotate = tuple(float(v) for v in placement.rotate)
    translate = tuple(float(v) for v in placement.translate)
    if any(rotate):
        c = body.bounding_box().center()
        body = Pos(c.X, c.Y, c.Z) * (Rotation(*rotate) * (Pos(-c.X, -c.Y, -c.Z) * body))
    if any(translate):
        body = Pos(*translate) * body
    return body


def build(doc: CadDocument, resolved: dict, *, steps=None, env=None):
    """Build the part described by ``doc``.

    ``steps``/``env`` may be passed in when the caller has already run
    :func:`cadir.budget.check`, so admission control and geometry act on exactly the
    same plan instead of re-deriving it and risking disagreement.

    A document whose operations name components builds each of them separately and
    returns a ``Compound`` of the results, one labelled child per component. That is
    what makes them separate bodies at all: a single ``BuildPart`` fuses everything it
    is handed, and the exporter writes one mesh subtree per *child*, not per disjoint
    solid — measured, two boxes that never touch still export as one node. A document
    with no components takes the original single-part path untouched, so the golden
    geometry cannot move.
    """
    if steps is None or env is None:
        env, steps, _cost = budget_mod.check(doc, resolved)

    order: list[str | None] = []
    groups: dict[str | None, list] = {}
    for op, positions in steps:
        name = getattr(op, "component", None)
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append((op, positions))

    if not any(order):
        part = _build_body(steps, env)
        if part is None:
            raise CadIRRuntimeError(f"{doc.name}: produced no geometry")
        return part

    placements = {p.component: p for p in doc.placements}
    bodies = []
    for name in order:
        body = _build_body(groups[name], env)
        if body is None:
            raise CadIRRuntimeError(f"{name}: produced no geometry")
        placement = placements.get(name)
        if placement is not None:
            body = _placed(body, placement)
        # After the transform, never before: ``Pos(...) * body`` returns a new shape and
        # the label does not survive the multiplication. Labelling first produced a
        # compound of unnamed children, which is the manifest losing every part name and
        # the explorer losing every selection.
        body.label = name
        bodies.append(body)
    return Compound(children=bodies)
