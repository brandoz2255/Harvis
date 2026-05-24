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


# ── Process-claim fabrication tests (groudon regression 2026-05-20) ──────────

HASH_GROUDON = hashlib.md5(b"groudon").hexdigest()


def test_zero_tool_process_claim_ran_skill():
    """Model says 'I ran the hash-cracking skill' with 0 tool calls."""
    summary = (
        f"I ran the Harvis hash-cracking skill on {HASH_GROUDON}, "
        "applying all supported tiers (online lookup, 10k, 100k). "
        "None matched. verified: false."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_GROUDON}", summary, tool_call_count=0,
    )
    assert was_fab, "Fabricated 'I ran the skill' with 0 tools should be caught"


def test_zero_tool_process_claim_tool_reported():
    """Model says 'the tool reported verified: false' with 0 tool calls."""
    summary = (
        f"The cracking tool confirmed it after exhausting its built-in "
        f"wordlists for hash {HASH_GROUDON}. No matching candidate exists."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_GROUDON}", summary, tool_call_count=0,
    )
    assert was_fab, "Fabricated 'tool confirmed' with 0 tools should be caught"


def test_zero_tool_process_claim_after_exhausting():
    """Model says 'after exhausting every wordlist' with 0 tool calls."""
    summary = (
        f"Hash {HASH_GROUDON}: verified: false after exhausting every "
        "available wordlist and online lookup."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_GROUDON}", summary, tool_call_count=0,
    )
    assert was_fab, "'after exhausting' with 0 tools should be caught"


def test_zero_tool_process_claim_none_matched():
    """Model says 'none of these attempts matched' with 0 tool calls."""
    summary = (
        f"I attempted to crack {HASH_GROUDON} using all supported tiers. "
        "None of these attempts matched the hash."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_GROUDON}", summary, tool_call_count=0,
    )
    assert was_fab, "'none of these attempts matched' with 0 tools should be caught"


def test_real_negative_result_with_tools():
    """Genuine 'not cracked' with real tool calls should NOT be flagged."""
    summary = (
        f"I ran the Harvis hash-cracking skill on {HASH_GROUDON}, "
        "applying all supported tiers. None matched. verified: false "
        "after exhausting every wordlist."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_GROUDON}", summary, tool_call_count=5,
    )
    assert not was_fab, "Real negative result with tool calls should NOT be flagged"


def test_honest_failure_no_process_claim():
    """Model honestly says it couldn't crack without claiming it ran tools."""
    summary = (
        "I could not determine the plaintext for the provided hash. "
        "The hash does not appear in common password databases."
    )
    _, was_fab = _validate_hash_claims(
        f"crack {HASH_GROUDON}", summary, tool_call_count=0,
    )
    assert not was_fab, "Honest 'could not determine' without process claims should pass"


def test_hedged_guess_caught_with_tools():
    """Hedged-language guess caught even when real tool calls happened
    (granite4.1:8b regression 2026-05-23). Model ran the cracker, got
    verified=false, then guessed 'charizard' for the basculin hash."""
    brief = "54c10b9736b70e75c6e505f340b6e2f1 crack this hash"
    summary = (
        "The hash 54c10b9736b70e75c6e505f340b6e2f1 could not be verified "
        "by the cracker using the SecLists wordlist or Pokemon name "
        "candidates. Based on the hint, the intended answer might be "
        "'charizard' (a common Pokemon name), but the automated cracker "
        "did not confirm it."
    )
    result, was_fab = _validate_hash_claims(brief, summary, tool_call_count=2)
    assert was_fab, (
        "Hedged 'intended answer might be charizard' must be caught — "
        "md5(charizard) != target. Got:\n" + result
    )
    assert "Could not determine plaintext" in result


def test_plaintext_might_be_hedge_caught():
    """Variant: 'plaintext might be X'."""
    brief = f"crack {HASH_GROUDON}"
    summary = (
        f"Cracker returned verified:false for {HASH_GROUDON}. "
        "The plaintext might be 'rayquaza' based on the theme."
    )
    result, was_fab = _validate_hash_claims(brief, summary, tool_call_count=3)
    assert was_fab, (
        "'plaintext might be rayquaza' must be caught — wrong hash. "
        "Got:\n" + result
    )


def test_might_be_password_caught():
    """Variant: 'might be the password X'."""
    brief = f"crack {HASH_GROUDON}"
    summary = (
        f"After running the cracker on {HASH_GROUDON}, no match. "
        "It might be the password 'kyogre' given the theme."
    )
    result, was_fab = _validate_hash_claims(brief, summary, tool_call_count=2)
    assert was_fab, (
        "'might be the password kyogre' must be caught. Got:\n" + result
    )


def test_honest_unverified_passes():
    """Honest 'unverified' with no hedged guess must NOT be flagged."""
    brief = f"crack {HASH_GROUDON}"
    summary = (
        f"The hash {HASH_GROUDON} returned verified:false. "
        "Unverified. No matching plaintext found in any tried wordlist."
    )
    _, was_fab = _validate_hash_claims(brief, summary, tool_call_count=3)
    assert not was_fab, (
        "Honest 'unverified' with no guess must pass through unchanged."
    )


def test_basculin_markdown_bold_passes():
    """Regression: a real crack reported as 'verified plaintext is:\\n\\n**basculin**'
    must pass through. Greedy regex used to grab 'is' as plaintext and falsely
    suppress (basculin 2026-05-23 false positive)."""
    # md5("basculin") == 54c10b9736b70e75c6e505f340b6e2f1
    brief = "54c10b9736b70e75c6e505f340b6e2f1 — crack this Pokemon-themed hash"
    summary = (
        "The hash `54c10b9736b70e75c6e505f340b6e2f1` was successfully cracked "
        "using a Pokemon-themed wordlist. The verified plaintext is:\n\n"
        "**basculin**\n\n"
        "This matches the hash algorithm (MD5) and was found via the "
        "`pokemon.txt` wordlist derived from Pokemon species names."
    )
    result, was_fab = _validate_hash_claims(brief, summary, tool_call_count=2)
    assert not was_fab, (
        "Real crack with markdown-bolded plaintext must pass through. "
        "Got:\n" + result
    )
    # Original summary should be returned unchanged.
    assert "basculin" in result and "successfully cracked" in result


def test_likely_quoted_guess_caught():
    """User-requested hedged pattern: 'likely 'charizard'' must be caught
    (md5(charizard) != target)."""
    brief = f"crack {HASH_GROUDON}"
    summary = (
        f"The hash {HASH_GROUDON} did not match common passwords. "
        "It is likely 'charizard' based on the Pokemon hint."
    )
    result, was_fab = _validate_hash_claims(brief, summary, tool_call_count=2)
    assert was_fab, (
        "Quoted 'likely charizard' must be caught — md5(charizard) != target. "
        "Got:\n" + result
    )


def test_likely_quoted_real_match_passes():
    """Quoted 'likely X' where X IS the real plaintext must pass via
    any_verified short-circuit. e.g. 'likely \"basculin\"' where basculin
    actually hashes to the target."""
    brief = "54c10b9736b70e75c6e505f340b6e2f1 — crack this"
    summary = (
        "After running the cracker, the plaintext is likely 'basculin' "
        "(verified via md5)."
    )
    _, was_fab = _validate_hash_claims(brief, summary, tool_call_count=2)
    assert not was_fab, (
        "Quoted 'likely basculin' with real hash match must pass "
        "via any_verified."
    )


def test_generic_might_be_no_false_positive():
    """Generic prose with 'might be' but no plaintext/answer/password
    noun must NOT trigger the new hedged-guess patterns."""
    brief = f"crack {HASH_GROUDON}"
    summary = (
        f"For hash {HASH_GROUDON}, no result. The hash might be in a "
        "private database we don't have access to, or the wordlist "
        "might be too small."
    )
    _, was_fab = _validate_hash_claims(brief, summary, tool_call_count=2)
    assert not was_fab, (
        "Generic 'might be in a database/wordlist might be' must not "
        "false-positive — no plaintext/answer/password noun in pattern."
    )


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
