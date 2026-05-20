"""Regression tests for _validate_hash_claims in workspace_router.

Each test case maps to a live failure observed in Discord + Ollama:
- Channel 2: cross-contamination (model answers with WRONG hash from session memory)
- Zero-tool_call memorization (model "knows" md5("hello") without exec)
- Correct answer (should NOT be flagged)

Import strategy: workspace_router has heavy deps (httpx, asyncpg, etc.) that
aren't available outside Docker. We use AST to extract just the validator function.
"""
import ast
import hashlib
import sys
import textwrap
from pathlib import Path

# ── Bootstrap: load _validate_hash_claims without the full import chain ──────
_WR_PATH = Path(__file__).resolve().parent.parent / "workspace" / "workspace_router.py"


def _load_validator():
    """Extract _validate_hash_claims from workspace_router.py using AST,
    then exec only that function (which uses only stdlib: hashlib, re)."""
    source = _WR_PATH.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_hash_claims":
            func_source = ast.get_source_segment(source, node)
            if func_source is None:
                raise RuntimeError("AST get_source_segment returned None")
            ns = {"__builtins__": __builtins__}
            exec(compile(func_source, str(_WR_PATH), "exec"), ns)
            return ns["_validate_hash_claims"]
    raise RuntimeError("_validate_hash_claims not found in workspace_router.py")


_validate_hash_claims = _load_validator()

# ── Hashes used across tests ─────────────────────────────────────────────────
HASH_JORDAN23 = hashlib.md5(b"jordan23").hexdigest()   # 1c885e23b850f482244d2d726dccdf19
HASH_HELLO = hashlib.md5(b"hello").hexdigest()          # 5d41402abc4b2a76b9719d911017c592


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_zero_tool_verified_via():
    """Model claims 'verified via' with zero tool calls."""
    summary = (
        "The hash 1c885e23b850f482244d2d726dccdf19 was verified via "
        "direct computation. The plaintext is `jordan23`."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_JORDAN23}", summary, tool_call_count=0,
    )
    assert was_fab, "Zero-tool_call 'verified via' should be caught"


def test_zero_tool_corresponds_to_plaintext():
    """Channel 2 regression: 'corresponds to the plaintext'."""
    summary = (
        "The MD5 hash 5d41402abc4b2a76b9719d911017c592 corresponds to "
        "the plaintext 'hello'. No additional tool calls were needed "
        "as this is a well-known hash."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_HELLO}", summary, tool_call_count=0,
    )
    assert was_fab, "'corresponds to the plaintext' with 0 tools should be caught"


def test_zero_tool_directly_computing():
    summary = (
        "I verified by running hashlib.md5('hello') and the hex digest "
        "matches. The plaintext is `hello`."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_HELLO}", summary, tool_call_count=0,
    )
    assert was_fab, "'I verified by running' with 0 tools should be caught"


def test_zero_tool_running_in_python():
    summary = (
        "Running this in Python gives: hashlib.md5(b'hello').hexdigest() "
        "== '5d41402abc4b2a76b9719d911017c592'. The answer is hello."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_HELLO}", summary, tool_call_count=0,
    )
    assert was_fab, "'Running this in Python gives' with 0 tools should be caught"


def test_stray_hash_channel2():
    """Brief has 1c885e... but model answers about 5d4140... (cross-contamination)."""
    summary = (
        "The MD5 hash 5d41402abc4b2a76b9719d911017c592 corresponds to "
        "the plaintext 'hello'. This was confirmed by directly computing "
        "hashlib.md5(b'hello').hexdigest()."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_JORDAN23}",  # brief has jordan23's hash
        summary,                     # model answers about hello's hash
        tool_call_count=0,
    )
    assert was_fab, "Stray-hash (model answered wrong hash) should be caught"


def test_stray_hash_with_tool_calls():
    """Even with tool calls, answering about the wrong hash is fabrication."""
    summary = (
        "I cracked 5d41402abc4b2a76b9719d911017c592 — the plaintext is "
        "`hello`. verified=true from cracker.py."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_JORDAN23}",  # brief has jordan23's hash
        summary,                     # model answers about hello's hash
        tool_call_count=3,
    )
    assert was_fab, "Answering wrong hash even with tool calls should be caught"


def test_correct_hash_correct_plaintext():
    """Genuine verified answer should NOT be flagged."""
    summary = (
        f"The hash {HASH_JORDAN23} was cracked. "
        "plaintext is `jordan23`. verified=true."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_JORDAN23}", summary, tool_call_count=4,
    )
    assert not was_fab, "Correct answer with tool calls should NOT be flagged"


def test_correct_hello():
    summary = (
        f"Hash {HASH_HELLO} cracked with cracker.py. "
        "The plaintext is `hello`. verified=true."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_HELLO}", summary, tool_call_count=2,
    )
    assert not was_fab, "Correct 'hello' with tool calls should NOT be flagged"


def test_no_hash_in_brief():
    """Non-hash tasks should pass through untouched."""
    summary = "The weather today is sunny."
    result, was_fab = _validate_hash_claims(
        "what is the weather", summary, tool_call_count=0,
    )
    assert not was_fab
    assert result == summary


def test_correct_answer_colon():
    summary = f"Answer: jordan23\n\nHash: {HASH_JORDAN23}"
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_JORDAN23}", summary, tool_call_count=3,
    )
    assert not was_fab, "Correct 'Answer: jordan23' should pass"


def test_wrong_plaintext_with_tools():
    """Model ran tools but claims wrong plaintext."""
    summary = (
        f"Hash {HASH_JORDAN23} cracked. "
        "The plaintext is `wrongguess`. verified=true."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_JORDAN23}", summary, tool_call_count=4,
    )
    assert was_fab, "Wrong plaintext even with tool calls should be caught"


# ── Runner ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed out of {passed + failed}")
    sys.exit(1 if failed else 0)
