"""
Hash cracking tools for HARVIS.

Design principle: the LLM never produces a plaintext directly. Every plaintext
flows out of a function in this module and through verify() before being
returned. The orchestrator crack() chains tiers in order.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

# Length (hex chars) -> candidate algorithms, ranked by how common they are
# in real-world dumps.
LENGTH_TO_ALGOS = {
    32: ["md5", "ntlm", "md4"],
    40: ["sha1"],
    56: ["sha224"],
    64: ["sha256"],
    96: ["sha384"],
    128: ["sha512"],
}

# Hashcat mode codes for common algorithms.
HASHCAT_MODES = {
    "md5": "0",
    "sha1": "100",
    "sha224": "1300",
    "sha256": "1400",
    "sha384": "10800",
    "sha512": "1700",
    "ntlm": "1000",
    "md5crypt": "500",
    "bcrypt": "3200",
    "sha256crypt": "7400",
    "sha512crypt": "1800",
}


# ---------- identification ----------

def identify_hash(target: str) -> list[str]:
    """Return candidate algorithms for a hash string. Empty list if not recognized."""
    t = target.strip().lower()

    # Salted formats
    if t.startswith("$1$"):
        return ["md5crypt"]
    if t.startswith(("$2a$", "$2b$", "$2y$")):
        return ["bcrypt"]
    if t.startswith("$5$"):
        return ["sha256crypt"]
    if t.startswith("$6$"):
        return ["sha512crypt"]
    if t.startswith("$argon2"):
        return ["argon2"]

    # Plain hex
    if re.fullmatch(r"[0-9a-f]+", t):
        return LENGTH_TO_ALGOS.get(len(t), [])

    return []


# ---------- forward hashing (the truth) ----------

def compute_hash(plaintext: str, algo: str) -> str:
    """Compute hash of plaintext under algo. Returns lowercase hex digest."""
    algo = algo.lower()
    if algo == "ntlm":
        # NTLM = MD4(UTF-16LE)
        return hashlib.new("md4", plaintext.encode("utf-16le")).hexdigest()
    if algo in {"md5crypt", "bcrypt", "sha256crypt", "sha512crypt", "argon2"}:
        raise ValueError(f"{algo} is salted; use hashcat tier instead")
    return hashlib.new(algo, plaintext.encode("utf-8")).hexdigest()


def verify(plaintext: str, target: str, algo: str) -> bool:
    """The single chokepoint. Every claimed plaintext MUST go through this."""
    try:
        return compute_hash(plaintext, algo).lower() == target.strip().lower()
    except (ValueError, TypeError):
        return False


# ---------- Tier 1 / 2: wordlist iteration ----------

def crack_wordlist(
    target: str,
    algo: str,
    wordlist_path: str,
    encoding: str = "utf-8",
) -> Optional[str]:
    """Iterate a wordlist, return the first plaintext whose hash matches the target."""
    target = target.strip().lower()
    p = Path(wordlist_path)
    if not p.exists():
        return None

    # Latin-1 fallback handles the binary garbage that creeps into rockyou.txt
    for enc in (encoding, "latin-1"):
        try:
            with open(p, "r", encoding=enc, errors="strict") as f:
                for line in f:
                    pw = line.rstrip("\r\n")
                    if not pw:
                        continue
                    try:
                        if compute_hash(pw, algo) == target:
                            return pw
                    except UnicodeEncodeError:
                        continue
            return None
        except UnicodeDecodeError:
            continue
    return None


# ---------- Tier 3: hashcat ----------

def crack_hashcat(
    target: str,
    algo: str,
    wordlist: str,
    rules: Optional[str] = None,
    timeout: int = 600,
) -> Optional[str]:
    """Spawn hashcat as a subprocess, parse the result, verify before returning."""
    mode = HASHCAT_MODES.get(algo.lower())
    if not mode:
        return None
    if not Path(wordlist).exists():
        return None

    cmd = [
        "hashcat", "-m", mode, "-a", "0",
        "--quiet", "--potfile-disable",
        target, wordlist,
    ]
    if rules:
        cmd += ["-r", rules]

    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        # --show reads the potfile-style output even with --potfile-disable
        # writing one. Use a temp potfile to make this deterministic in prod.
        show = subprocess.run(
            ["hashcat", "-m", mode, target, wordlist, "--show"],
            capture_output=True, text=True, timeout=10,
        )
        for line in show.stdout.splitlines():
            if ":" in line:
                _, pw = line.split(":", 1)
                if verify(pw, target, algo):
                    return pw
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return None


# ---------- Tier 4: online reverse lookup ----------

def lookup_online(target: str, algo: str = "md5", timeout: int = 10) -> Optional[str]:
    """Query public reverse-lookup indexes. Always verify the returned plaintext."""
    target = target.strip().lower()
    if algo != "md5":
        return None  # extend per service as needed

    candidates: list[str] = []

    # md5hashing.net — HTML scrape
    try:
        url = f"https://md5hashing.net/hash/md5/{target}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="ignore")
        m = re.search(
            r"Reversed hash value\s*</?\w*>\s*```\s*([^\n`]+?)\s*```",
            html, re.S,
        )
        if not m:
            # Looser pattern
            m = re.search(r"```\s*([A-Za-z0-9_.\-@!#$%]{2,64})\s*```\s*Copy Value", html)
        if m:
            candidates.append(m.group(1).strip())
    except Exception:
        pass

    # hashes.com — JSON API (free tier, rate-limited)
    try:
        url = f"https://hashes.com/en/api/search?hash={target}"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            import json
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        if isinstance(data, dict) and data.get("found"):
            candidates.append(data.get("plaintext", ""))
    except Exception:
        pass

    for c in candidates:
        if c and verify(c, target, algo):
            return c
    return None


# ---------- orchestrator ----------

def crack(
    target: str,
    algo: Optional[str] = None,
    wordlists: Optional[list[str]] = None,
    use_hashcat: bool = False,
    use_online: bool = False,
    hashcat_rules: Optional[str] = None,
) -> dict:
    """
    Run all tiers in order. Return at the first verified match.

    If algo is None, identify_hash is used and the first candidate is tried.
    """
    target = target.strip().lower()
    tiers_tried: list[str] = []

    if algo is None:
        algos = identify_hash(target)
        if not algos:
            return {
                "hash": target, "algo": None, "plaintext": None,
                "method": None, "verified": False,
                "tiers_tried": [], "error": "unrecognized hash format",
            }
        algo = algos[0]

    wordlists = wordlists or []

    # Tiers 1 / 2
    for wl in wordlists:
        tag = f"wordlist:{Path(wl).name}"
        tiers_tried.append(tag)
        pw = crack_wordlist(target, algo, wl)
        if pw and verify(pw, target, algo):
            return {
                "hash": target, "algo": algo, "plaintext": pw,
                "method": tag, "verified": True, "tiers_tried": tiers_tried,
            }

    # Tier 3
    if use_hashcat and wordlists:
        tiers_tried.append("hashcat")
        pw = crack_hashcat(target, algo, wordlists[-1], rules=hashcat_rules)
        if pw and verify(pw, target, algo):
            return {
                "hash": target, "algo": algo, "plaintext": pw,
                "method": "hashcat", "verified": True, "tiers_tried": tiers_tried,
            }

    # Tier 4
    if use_online:
        tiers_tried.append("online_lookup")
        pw = lookup_online(target, algo)
        if pw and verify(pw, target, algo):
            return {
                "hash": target, "algo": algo, "plaintext": pw,
                "method": "online_lookup", "verified": True, "tiers_tried": tiers_tried,
            }

    # Tier 5
    return {
        "hash": target, "algo": algo, "plaintext": None,
        "method": None, "verified": False, "tiers_tried": tiers_tried,
    }


# ---------- CLI for quick agent invocation ----------

if __name__ == "__main__":
    import argparse, json, sys

    ap = argparse.ArgumentParser(description="HARVIS hash cracker")
    ap.add_argument("hash")
    ap.add_argument("--algo", default=None)
    ap.add_argument("--wordlist", action="append", default=[])
    ap.add_argument("--hashcat", action="store_true")
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--rules", default=None)
    ap.add_argument(
        "--no-auto-wordlists", action="store_true",
        help="Disable auto-discovery of wordlists/ next to this script."
    )
    args = ap.parse_args()

    # Auto-discovery: if no --wordlist is given, use every *.txt in
    # wordlists/ next to this script. This makes the agent prompt
    # bulletproof — the model can drop the --wordlist flags without
    # silently losing rockyou.txt coverage.
    wordlists = list(args.wordlist)
    if not wordlists and not args.no_auto_wordlists:
        _wl_dir = Path(__file__).parent / "wordlists"
        if _wl_dir.exists():
            # Order: top1k.txt first (sub-second commons), then everything
            # else by size ascending (small lists fail fast before rockyou).
            preferred = ["top1k.txt", "top10k.txt", "top100k.txt"]
            preferred_paths = [_wl_dir / n for n in preferred if (_wl_dir / n).exists()]
            other_paths = sorted(
                (p for p in _wl_dir.glob("*.txt") if p not in preferred_paths),
                key=lambda p: p.stat().st_size,
            )
            # rockyou symlink may resolve to a large file; keep it last
            other_paths.sort(key=lambda p: ("rockyou" in p.name.lower(), p.stat().st_size))
            wordlists = [str(p) for p in preferred_paths + other_paths]

    result = crack(
        args.hash,
        algo=args.algo,
        wordlists=wordlists,
        use_hashcat=args.hashcat,
        use_online=args.online,
        hashcat_rules=args.rules,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("verified") else 1)
