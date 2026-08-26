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

from build123d import Axis, Box, BuildPart, Cylinder, Locations, Mode, add, fillet

from . import budget as budget_mod
from .schema import CadDocument

_AXIS = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}
_MODE = {"add": Mode.ADD, "subtract": Mode.SUBTRACT}


def _value(formula, env):
    return budget_mod._value(formula, env)


def _emit(op, positions, env) -> None:
    """Place one operation's primitives inside the enclosing BuildPart context."""
    mode = _MODE[op.mode]
    rotation = tuple(float(r) for r in op.rotation)
    kwargs = {"mode": mode}
    if any(rotation):
        kwargs["rotation"] = rotation

    with Locations(*positions):
        if op.op == "box":
            Box(*[_value(s, env) for s in op.size], **kwargs)
        else:
            Cylinder(radius=_value(op.radius, env), height=_value(op.height, env), **kwargs)


def _apply_fillet(part, op, env):
    """Fillet edges chosen declaratively — filter by an axis, sort by an axis, slice.

    ``optional`` reproduces the hanger's ``try/except`` rather than reinventing it: a
    radius the local geometry cannot take yields a part without that fillet, which is a
    degraded result, not a failed build. A non-optional fillet that fails is an error,
    because silently dropping a feature the author declared as required would be the
    "cheerful 200 for the wrong part" failure in a new costume.
    """
    radius = _value(op.radius, env)
    sel = op.select
    try:
        edges = part.edges().filter_by(_AXIS[sel.filter_by]).sort_by(_AXIS[sel.sort_by])
        chosen = edges[sel.take[0]:sel.take[1]]
        if not chosen:
            raise ValueError(f"{op.op_id}: the edge selector matched nothing")
        return fillet(chosen, radius=radius)
    except Exception:
        if op.optional:
            return part
        raise


def build(doc: CadDocument, resolved: dict, *, steps=None, env=None):
    """Build the part described by ``doc``.

    ``steps``/``env`` may be passed in when the caller has already run
    :func:`cadir.budget.check`, so admission control and geometry act on exactly the
    same plan instead of re-deriving it and risking disagreement.
    """
    if steps is None or env is None:
        env, steps, _cost = budget_mod.check(doc, resolved)

    part = None
    pending = []

    def flush():
        """Run the accumulated add/subtract operations as one BuildPart."""
        nonlocal part, pending
        if not pending:
            return
        with BuildPart() as bp:
            if part is not None:
                add(part)
            for op, positions in pending:
                _emit(op, positions, env)
        part = bp.part
        pending = []

    for op, positions in steps:
        if op.op == "fillet":
            flush()
            if part is None:
                raise ValueError(f"{op.op_id}: nothing to fillet")
            part = _apply_fillet(part, op, env)
        else:
            pending.append((op, positions))
    flush()

    if part is None:
        raise ValueError(f"{doc.name}: produced no geometry")
    return part
