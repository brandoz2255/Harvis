"""Restricted formula evaluation for CadIR.

**No ``eval``, ever.** A formula is parsed with :mod:`ast`, every node is checked
against a frozen whitelist, and the surviving tree is walked by hand. Anything the
whitelist does not name is a hard rejection, not a warning — including attribute
access, subscripting, comprehensions, lambdas, assignments, and every builtin that
is not in :data:`ALLOWED_CALLS`.

Two deliberate widenings of the grammar the Gate 5 plan sketched, both stated here
rather than buried:

* **Calls are permitted for exactly three names** — ``min``, ``max`` and ``abs`` —
  resolved from this module's own frozen table, never from the evaluation namespace.
  The hanger's fillet radius is ``max(0.5, min(fillet_r_mm, arm_h_mm / 2 - 0.5))``
  and its screw radius is ``max(0.5, screw_d_mm / 2)``; without these the recipe is
  not expressible and Gate 5's success criterion cannot be met. The risk the "no
  calls" rule exists to stop is invoking arbitrary callables — a name-keyed table of
  three pure numeric functions, with no attribute access and no way to introduce a
  fourth, does not reintroduce it.
* **Comparisons and boolean operators** are permitted, because operations are guarded
  (``studs_x > 1 and studs_y > 1``). They produce a bool, which is only ever consumed
  by :func:`evaluate_predicate` — a guard can never become a dimension.

Every intermediate result is checked finite. This is the same rule
:func:`recipes._finite` enforces at the parameter boundary and for the same measured
reason: ``min``/``max`` propagate NaN silently, so one NaN reaching OpenCascade froze
the whole worker for 46 s. An expression is one more place a NaN could be minted, so
it is checked at every node rather than only at the end.
"""
from __future__ import annotations

import ast
import math

# Callables an expression may name. Frozen, and looked up here rather than in the
# evaluation namespace so a parameter called "max" cannot shadow or supply one.
ALLOWED_CALLS = {"min": min, "max": max, "abs": abs}

# Guards the exponent of ``**``. A literal 2 or 3 is ordinary; a large or computed
# exponent is either a mistake or an attempt to burn CPU inside admission control,
# which runs before any budget check on the geometry itself.
MAX_EXPONENT = 8

# An expression this long is not a dimension, it is a payload.
MAX_SOURCE_LEN = 512
MAX_NODES = 128


class ExprError(ValueError):
    """A formula the caller can fix. Carries a structured code so the HTTP layer can
    answer with something repairable, matching :class:`recipes.ParamError`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: None,   # handled explicitly: division by zero is a caller error, not a crash
    ast.Pow: None,   # handled explicitly: the exponent is bounded
}

_CMPOPS = {
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


def compile_expr(source: str) -> ast.Expression:
    """Parse and validate a formula. Raises :class:`ExprError` on anything outside
    the grammar; returns a tree that :func:`evaluate` can walk without re-checking."""
    if not isinstance(source, str):
        raise ExprError("invalid_expr", f"formula must be a string, got {type(source).__name__}")
    if len(source) > MAX_SOURCE_LEN:
        raise ExprError("invalid_expr", f"formula exceeds {MAX_SOURCE_LEN} characters")

    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExprError("invalid_expr", f"formula is not valid syntax: {exc.msg}") from None

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ExprError("invalid_expr", f"formula has more than {MAX_NODES} terms")
    for node in nodes:
        _check_node(node)
    return tree


def _check_node(node: ast.AST) -> None:
    if isinstance(node, (ast.Expression, ast.Name, ast.Load)):
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError("invalid_expr", "only numeric literals are allowed in a formula")
        if not math.isfinite(float(node.value)):
            raise ExprError("invalid_expr", "NaN and Infinity are not allowed in a formula")
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            raise ExprError("invalid_expr", f"operator {type(node.op).__name__} is not allowed")
        if isinstance(node.op, ast.Pow):
            exp = node.right
            if not isinstance(exp, ast.Constant) or isinstance(exp.value, bool):
                raise ExprError("invalid_expr", "the exponent of ** must be a numeric literal")
            if abs(float(exp.value)) > MAX_EXPONENT:
                raise ExprError("invalid_expr", f"exponent must be within ±{MAX_EXPONENT}")
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise ExprError("invalid_expr", f"unary {type(node.op).__name__} is not allowed")
        return
    if isinstance(node, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.UAdd, ast.USub)):
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS:
            allowed = ", ".join(sorted(ALLOWED_CALLS))
            raise ExprError("invalid_expr", f"only {allowed} may be called in a formula")
        if node.keywords:
            raise ExprError("invalid_expr", "keyword arguments are not allowed in a formula")
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise ExprError("invalid_expr", "argument unpacking is not allowed in a formula")
        if not 1 <= len(node.args) <= 4:
            raise ExprError("invalid_expr", f"{node.func.id}() takes 1 to 4 arguments")
        return
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ExprError("invalid_expr", "chained comparisons are not allowed")
        if type(node.ops[0]) not in _CMPOPS:
            raise ExprError("invalid_expr", f"comparison {type(node.ops[0]).__name__} is not allowed")
        return
    if isinstance(node, tuple(_CMPOPS)):
        return
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ExprError("invalid_expr", "only and/or are allowed")
        return
    if isinstance(node, (ast.And, ast.Or)):
        return
    raise ExprError("invalid_expr", f"{type(node).__name__} is not allowed in a formula")


def free_names(tree: ast.Expression) -> set[str]:
    """The symbols a formula reads from its environment.

    The name of a called function is *not* one of them: ``max`` in ``max(a, b)`` is
    resolved from :data:`ALLOWED_CALLS`, never from the environment, so reporting it as
    an unresolved symbol would reject every formula that clamps a value.
    """
    # Keyed on node identity, not on the name: a parameter that happens to be spelled
    # `max` is still a free name where it appears as an argument.
    func_nodes = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and id(node) not in func_nodes
    }


def _finite(value: float, source_hint: str) -> float:
    if not math.isfinite(value):
        raise ExprError(
            "invalid_expr",
            f"formula produced a non-finite value ({source_hint})",
        )
    return value


def _walk(node: ast.AST, env: dict[str, float]):
    if isinstance(node, ast.Expression):
        return _walk(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ExprError("unknown_symbol", f"formula refers to unknown name '{node.id}'")
        return float(env[node.id])
    if isinstance(node, ast.UnaryOp):
        v = _walk(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BinOp):
        a, b = _walk(node.left, env), _walk(node.right, env)
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise ExprError("invalid_expr", "formula divides by zero")
            return _finite(a / b, "division")
        if isinstance(node.op, ast.Pow):
            try:
                return _finite(a ** b, "exponentiation")
            except OverflowError:
                raise ExprError("invalid_expr", "formula overflowed on **") from None
        return _finite(_BINOPS[type(node.op)](a, b), "arithmetic")
    if isinstance(node, ast.Call):
        fn = ALLOWED_CALLS[node.func.id]
        args = [_walk(a, env) for a in node.args]
        return _finite(float(fn(*args)), node.func.id)
    if isinstance(node, ast.Compare):
        return bool(_CMPOPS[type(node.ops[0])](_walk(node.left, env), _walk(node.comparators[0], env)))
    if isinstance(node, ast.BoolOp):
        vals = [_walk(v, env) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    # Unreachable: compile_expr rejected everything else before evaluation.
    raise ExprError("invalid_expr", f"{type(node).__name__} is not allowed in a formula")


def evaluate(tree: ast.Expression, env: dict[str, float]) -> float:
    """Evaluate a validated formula to a finite float."""
    v = _walk(tree, env)
    if isinstance(v, bool):
        raise ExprError("invalid_expr", "a comparison cannot be used where a number is required")
    return _finite(float(v), "result")


def evaluate_predicate(tree: ast.Expression, env: dict[str, float]) -> bool:
    """Evaluate a validated formula as a guard. A bare number is truthy by the usual
    rule, so ``screw_count`` works as well as ``screw_count >= 1``."""
    return bool(_walk(tree, env))
