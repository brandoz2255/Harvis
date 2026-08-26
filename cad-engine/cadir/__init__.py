"""CadIR — a declarative parametric source for the Harvis CAD lane.

Import layering matters here and is deliberate:

* :mod:`cadir.expr`, :mod:`cadir.schema`, :mod:`cadir.budget` and :mod:`cadir.templates`
  are **kernel-free**. They run in the server process, where admission control has to
  refuse a document *before* a child is spawned, and where importing OCP would undo the
  1.767 s-per-build saving the warm pool exists to deliver.
* :mod:`cadir.interpret` imports build123d and is loaded only inside the child.

So this package does not re-export the interpreter. ``from cadir import interpret`` in
the child is explicit; ``import cadir`` in the server stays cheap.
"""
from __future__ import annotations

from .expr import ExprError
from .budget import BudgetError, ParamError, check, resolve_params
from .schema import SCHEMA_VERSION, CadDocument, canonical_source_hash, parse
from .templates import TEMPLATES

__all__ = [
    "SCHEMA_VERSION",
    "BudgetError",
    "CadDocument",
    "ExprError",
    "ParamError",
    "TEMPLATES",
    "canonical_source_hash",
    "check",
    "parse",
    "resolve_params",
]
