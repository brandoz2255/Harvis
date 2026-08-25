"""Every workspace lane that accepts prior turns must actually read them.

`run_orchestrated` took `chat_history`, threaded it through nothing, and shipped.
The bridge passed it, the router passed it, and it died in the argument list — so
every Harvis Agent turn started with an empty head and told users, truthfully from
where it sat, "I have no context from any previous sessions." Nothing failed: the
run succeeded, the card rendered, the answer was fluent and contextless.

An accepted-then-dropped parameter is invisible to every other kind of test, because
the caller looks correct and the callee looks correct. This one reads the ASTs.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parent.parent

# Documented exceptions, not a silencer: add a name here only when a function takes
# `chat_history` purely to forward it under a different name, and say where it goes.
_ALLOWED_TO_DROP: dict[str, str] = {}


def _functions_taking_chat_history():
    for path in sorted(_BACKEND.rglob("*.py")):
        if "/tests/" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
            if args.vararg:
                names.append(args.vararg.arg)
            if args.kwarg:
                names.append(args.kwarg.arg)
            if "chat_history" not in names:
                continue
            loads = sum(
                1
                for n in ast.walk(node)
                if isinstance(n, ast.Name)
                and n.id == "chat_history"
                and isinstance(n.ctx, ast.Load)
            )
            yield path.relative_to(_BACKEND), node.lineno, node.name, loads


def test_no_lane_accepts_chat_history_and_drops_it():
    dropped = [
        f"{rel}:{line} {name}() accepts chat_history and never reads it"
        for rel, line, name, loads in _functions_taking_chat_history()
        if loads == 0 and name not in _ALLOWED_TO_DROP
    ]
    assert not dropped, (
        "These functions take prior conversation turns and throw them away, so the "
        "model they drive starts every turn with an empty head:\n  "
        + "\n  ".join(dropped)
        + "\n\nFix: build the prompt with "
        "workspace.orchestration.conversation.conversation_prefix(task_brief, chat_history)."
    )


def test_the_audit_actually_finds_something():
    """Guard the guard: a scan that silently matches nothing always passes."""
    found = list(_functions_taking_chat_history())
    assert len(found) >= 15, f"AST scan found only {len(found)} functions — it is broken"


@pytest.mark.parametrize(
    "module,func",
    [
        ("workspace.orchestration.orchestrator", "run_orchestrated"),
        ("workspace.orchestration.session_turn", "run_vibecode_turn"),
        ("workspace.orchestration.review", "run_review_conversation"),
        ("workspace.orchestration.engine_adapter", "run_external_engine_adapter"),
        ("workspace.orchestration.engine_adapter", "run_claude_chat_workspace"),
        ("workspace.kimi_workspace", "stream_local_ollama_workspace"),
        ("workspace.openclaw_client", "stream"),
    ],
)
def test_named_lanes_still_take_history(module, func):
    """The lanes the dispatch table in workspace_router routes to, by name.

    A lane that stops accepting `chat_history` passes the AST test above by omission;
    this one notices the parameter disappearing.
    """
    import importlib

    mod = importlib.import_module(module)
    target = getattr(mod, func, None)
    if target is None:  # e.g. `stream` is a method on the client class
        cls = getattr(mod, "OpenClawClient", None)
        target = getattr(cls, func, None)
    assert target is not None, f"{module}.{func} is gone"
    import inspect

    assert "chat_history" in inspect.signature(target).parameters


def test_conversation_prefix_is_a_noop_without_history():
    """A first turn and a caller with no history must behave exactly as before."""
    from workspace.orchestration.conversation import conversation_prefix

    assert conversation_prefix("build a thing", []) == "build a thing"
    assert conversation_prefix("build a thing", None) == "build a thing"
    # A trailing user turn identical to the brief is not restated.
    assert (
        conversation_prefix("build a thing", [{"role": "user", "content": "build a thing"}])
        == "build a thing"
    )


def test_conversation_prefix_carries_the_previous_assistant_turn():
    from workspace.orchestration.conversation import conversation_prefix

    out = conversation_prefix(
        "make another tree",
        [
            {"role": "user", "content": "make a tree using ascii"},
            {"role": "assistant", "content": "Created ascii_tree.txt — an oak."},
            {"role": "user", "content": "make another tree"},
        ],
    )
    assert "Created ascii_tree.txt — an oak." in out
    assert out.rstrip().endswith("make another tree")
    assert out.index("make a tree using ascii") < out.index("Created ascii_tree.txt")
