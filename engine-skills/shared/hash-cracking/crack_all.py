#!/usr/bin/env python3
"""
Batch hash cracker — multi-hash + theme orchestration around cracker.py.

The model emits ONE short exec call:
    python3 /skills-shared/hash-cracking/crack_all.py [--theme=NAME] <h1> <h2> ...

All multi-tier orchestration lives here, on disk, properly indented once.
The model never authors Python — it only dispatches. This is the skill-
dispatch architecture used by decode/crypto/forensics; promoting hash to
match closes the indent-collapse failure class (see workspaces 8e60e5cd
gemma4, and earlier 31da2e56 hermes4 — both crashed in identical fashion
trying to author this same Python inside an exec heredoc body).

Lever 1, 2026-05-28. cracker.py provides single-hash multi-tier
(bundled wordlists + online lookup); crack_all.py adds multi-hash
batching + themed wordlist fetch (PokeAPI etc.). Self-contained:
the script knows its own resources.

CLI:
    python3 crack_all.py <hash1> <hash2> ...
    python3 crack_all.py --theme=pokemon <hash1> <hash2> ...

Output: one JSON dict {hash: cracker_result_or_unverified} to stdout.
Exit 0 if any hash verified, 1 if none.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
CRACKER = str(SCRIPT_DIR / "cracker.py")

# Themed wordlist sources. Add entries to extend — model never sees this
# dict, it just passes --theme=<key>. Each entry: a URL returning JSON
# with a `results: [{name: ...}, ...]` array shape (PokeAPI-compatible).
# For non-PokeAPI-shape sources, parametrize the response parser later.
THEMES: dict[str, dict] = {
    "pokemon": {
        "url": "https://pokeapi.co/api/v2/pokemon-species?limit=2000",
        "out": "/tmp/pokemon.txt",
    },
    # Future: "marvel", "cities", "movies", "anime" — same pattern.
}


def _try_cracker(
    target: str,
    *,
    wordlist: Optional[str] = None,
    use_online: bool = False,
    timeout_s: float = 300.0,
) -> dict:
    """Single-hash dispatch into cracker.py. Returns parsed JSON or an
    error dict matching cracker.py's failure shape."""
    cmd = ["python3", CRACKER, target]
    if wordlist:
        cmd.append(f"--wordlist={wordlist}")
    if use_online:
        cmd.append("--online")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return {"hash": target, "verified": False, "error": "cracker timeout"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "hash": target,
            "verified": False,
            "error": "cracker output not parseable",
            "stderr": (proc.stderr or "")[:240],
        }


def _build_themed_wordlist(theme: str) -> Optional[str]:
    """Fetch + write a themed wordlist. Always re-fetches: a prior crashed
    run could have left an empty file at the cache path that passes
    `os.path.getsize > 0` and silently poisons every subsequent crack
    (verified 2026-05-23 regression). PokeAPI is <1s; re-fetching is
    cheaper than the cache-poisoning blast radius.

    For each entry, writes three variants: lowercase, capitalized, and
    dehyphenated (handles `mr-mime`, `ho-oh`, `wo-chien`, etc. — small
    fraction but cheap to cover).

    Returns the wordlist path or None on failure (caller treats as
    'tier skipped').
    """
    cfg = THEMES.get(theme)
    if not cfg:
        return None
    req = urllib.request.Request(
        cfg["url"],
        headers={"User-Agent": "Mozilla/5.0 (HARVIS hash-cracking skill)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        sys.stderr.write(f"themed wordlist fetch failed for {theme}: {exc}\n")
        return None

    out_path = cfg["out"]
    try:
        with open(out_path, "w") as f:
            for entry in data.get("results", []):
                name = entry.get("name", "")
                if not name:
                    continue
                f.write(f"{name}\n")
                f.write(f"{name.capitalize()}\n")
                if "-" in name:
                    f.write(f"{name.replace('-', '')}\n")
    except Exception as exc:
        sys.stderr.write(f"themed wordlist write failed: {exc}\n")
        return None
    return out_path


def crack_all(hashes: list[str], theme: Optional[str] = None) -> dict[str, dict]:
    """Top-level: returns {hash: cracker_result_dict} for each input hash.

    Tier 1+2+4 (bundled wordlists + online lookup) runs first via
    cracker.py --online. Any hash unverified after that falls through to
    the themed tier IF a theme was supplied.
    """
    results: dict[str, dict] = {}

    # Tier 1+2+4: cracker.py auto-discovers bundled wordlists (top1k,
    # top10k, top100k) when no --wordlist flag is given, and --online
    # adds tier 4 (DDG-backed lookup). One call per hash, ~99% coverage
    # for common-password / known-public-leak hashes.
    for h in hashes:
        out = _try_cracker(h, use_online=True)
        if out.get("verified"):
            results[h] = out

    # Tier 3 (themed): if a theme is supplied AND any hash remains
    # unverified, fetch the themed corpus and retry.
    remaining = [h for h in hashes if h not in results]
    if remaining and theme:
        wl_path = _build_themed_wordlist(theme)
        if wl_path:
            for h in remaining:
                out = _try_cracker(h, wordlist=wl_path)
                if out.get("verified"):
                    results[h] = out

    # Honest recording: any hash we couldn't verify gets a clean
    # unverified entry. Downstream readers (the model summarizing for
    # Discord) can rely on `verified: true` as the sole truth gate.
    for h in hashes:
        results.setdefault(
            h,
            {"hash": h, "verified": False, "plaintext": None, "method": None},
        )

    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Batch hash cracker (Harvis skill, Lever 1).",
    )
    ap.add_argument("hashes", nargs="+", help="One or more hashes to crack")
    ap.add_argument(
        "--theme",
        default=None,
        choices=sorted(THEMES.keys()),
        help="Optional themed wordlist — fetched at runtime and used to "
             "retry hashes that didn't verify on the bundled-tier run.",
    )
    args = ap.parse_args()

    results = crack_all(args.hashes, theme=args.theme)
    print(json.dumps(results, indent=2))
    any_verified = any(r.get("verified") for r in results.values())
    return 0 if any_verified else 1


if __name__ == "__main__":
    sys.exit(main())
