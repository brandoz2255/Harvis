"""Parameter resolution, placement expansion, and the static complexity budget.

This module must stay importable **without build123d**, because it runs in the server
process during admission control while geometry runs in a killable child. Everything
here is arithmetic on already-validated numbers: no geometry, no OCCT, no imports that
pull in the kernel.

The cost unit is one **boolean instance** — one primitive fused into or cut from the
part. Gate 2 measured that this, and not any dimension, is what decides whether a
build finishes:

    grid    instances   solo wall   verdict
    10x10         305      7.30 s   fine
    12x12         387      8.60 s   fine
    14x14         535     15.88 s   too close to the 20 s deadline
    16x16         706   killed at the deadline, having produced nothing

:data:`MAX_COST` is 400.0 for exactly that reason: it is the last value that admits
12x12 and refuses 14x14. A cap that admits work which cannot finish is not a cap — it
burns a concurrency slot for the full deadline and answers with a timeout, where the
whole point is an immediate, honest refusal.
"""
from __future__ import annotations

import math

from . import expr as expr_mod
from .schema import CadDocument, Grid, Points

# Per-instance weights. A cylinder costs more than a box because its curved surface is
# what the mesher spends its time on; a fillet costs more than either because it
# rebuilds the topology around every edge it touches.
WEIGHT = {"box": 0.5, "cylinder": 1.0, "fillet": 5.0}

MAX_COST = 400.0

# A single operation may not expand past this many instances, whatever the total cost
# says. It bounds the loop that builds the position list, which runs before the cost is
# known.
MAX_INSTANCES_PER_OP = 1024


class BudgetError(ValueError):
    """Admission control refused the document before geometry started. Mirrors
    :class:`recipes.BudgetError` so the HTTP layer answers identically for both."""

    def __init__(self, message: str, cost: float, cap: float):
        super().__init__(message)
        self.message = message
        self.cost = cost
        self.cap = cap


class ParamError(ValueError):
    """A parameter the caller can fix. Mirrors :class:`recipes.ParamError`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_params(doc: CadDocument, params: dict | None) -> dict:
    """Validated, defaulted, in-range parameters.

    Unknown names are an error rather than a shrug, for the reason
    :func:`recipes.resolve_params` already states: silently ignoring them let a caller
    ask for ``arm_length_mm`` and get the default part back with a cheerful 200.

    Non-finite values are rejected before any clamp, because ``min``/``max`` propagate
    NaN — ``max(nan, 10)`` is ``nan`` — and one NaN reaching OpenCascade froze the
    worker for 46 s during the Gate 0 baseline.
    """
    params = params or {}
    spec = {p.name: p for p in doc.parameters}

    unknown = sorted(set(params) - set(spec))
    if unknown:
        raise ParamError(
            "unknown_param",
            f"unknown parameter(s) for {doc.name}: {', '.join(unknown[:8])}",
        )

    out: dict[str, float] = {}
    for name, p in spec.items():
        value = params.get(name)
        if value is None:
            value = p.default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParamError("invalid_param", f"{name} must be a number, got {type(value).__name__}")
        f = float(value)
        if not math.isfinite(f):
            raise ParamError(
                "invalid_param", f"{name} must be a finite number (NaN and Infinity are rejected)"
            )
        if f < p.min or f > p.max:
            raise ParamError(
                "param_out_of_range", f"{name} must be between {p.min} and {p.max} (got {f})"
            )
        if p.kind == "int":
            if int(f) != f:
                raise ParamError("invalid_param", f"{name} must be a whole number (got {f})")
            out[name] = int(f)
        else:
            out[name] = f
    return out


def _value(formula, env: dict[str, float]) -> float:
    if isinstance(formula, (int, float)) and not isinstance(formula, bool):
        return float(formula)
    return expr_mod.evaluate(expr_mod.compile_expr(formula), env)


def _truthy(formula, env: dict[str, float]) -> bool:
    if formula is None:
        return True
    if isinstance(formula, (int, float)) and not isinstance(formula, bool):
        return bool(formula)
    return expr_mod.evaluate_predicate(expr_mod.compile_expr(formula), env)


def build_env(doc: CadDocument, resolved: dict) -> dict[str, float]:
    """Parameters plus derived values, evaluated in declaration order."""
    env = dict(resolved)
    for d in doc.derived:
        env[d.name] = _value(d.value, env)
    return env


def _count(formula, env, where: str) -> int:
    v = _value(formula, env)
    n = int(round(v))
    if abs(v - n) > 1e-9:
        raise ParamError("invalid_param", f"{where}: a grid count must be a whole number (got {v})")
    if n < 0:
        raise ParamError("invalid_param", f"{where}: a grid count cannot be negative (got {n})")
    return n


def placements(op, env: dict[str, float]) -> list[tuple[float, float, float]]:
    """Expand an operation's placement into concrete positions.

    A ``fillet`` has no placement and answers with one implicit instance; an operation
    with no ``at`` sits at the origin, matching build123d's own default.
    """
    at = getattr(op, "at", None)
    if at is None:
        return [(0.0, 0.0, 0.0)]

    if isinstance(at, Points):
        return [tuple(_value(c, env) for c in p) for p in at.positions]

    assert isinstance(at, Grid)
    counts = [_count(c, env, op.op_id) for c in at.count]
    pitches = [_value(p, env) for p in at.pitch]
    center = [_value(c, env) for c in at.center]

    total = counts[0] * counts[1] * counts[2]
    if total > MAX_INSTANCES_PER_OP:
        raise BudgetError(
            f"{op.op_id} expands to {total} instances, over the {MAX_INSTANCES_PER_OP} limit "
            f"for a single operation",
            float(total), float(MAX_INSTANCES_PER_OP),
        )

    out = []
    for i in range(counts[0]):
        for j in range(counts[1]):
            for k in range(counts[2]):
                out.append((
                    center[0] + (i - (counts[0] - 1) / 2) * pitches[0],
                    center[1] + (j - (counts[1] - 1) / 2) * pitches[1],
                    center[2] + (k - (counts[2] - 1) / 2) * pitches[2],
                ))
    return out


def plan(doc: CadDocument, env: dict[str, float]) -> list[tuple[object, list[tuple[float, float, float]]]]:
    """The operations that will actually run, with their expanded positions.

    Guards are evaluated here, once, so admission control charges for the same work the
    interpreter performs — not for the branch it will skip. An operation whose grid
    resolves to zero instances is dropped, which is how a ``1×N`` brick correctly gets
    no interlock tubes.
    """
    steps = []
    for op in doc.operations:
        if not _truthy(op.when, env):
            continue
        pts = placements(op, env)
        if not pts:
            continue
        steps.append((op, pts))
    return steps


def estimate(steps) -> float:
    """Static complexity estimate over an already-planned document. Cheap arithmetic
    only — if this had to build anything to decide, it would not be admission control."""
    return round(sum(WEIGHT[op.op] * len(pts) for op, pts in steps), 3)


def check(doc: CadDocument, resolved: dict) -> tuple[dict[str, float], list, float]:
    """Resolve, plan and charge in one pass. Raises before any geometry is dispatched.

    Returns ``(env, steps, cost)`` so the caller does not have to redo the work the
    budget already did.
    """
    env = build_env(doc, resolved)
    steps = plan(doc, env)
    cost = estimate(steps)
    if cost > MAX_COST:
        raise BudgetError(
            f"{doc.name} scores {cost} against a cap of {MAX_COST}; reduce the counts "
            "that drive its boolean operations",
            cost, MAX_COST,
        )
    return env, steps, cost
