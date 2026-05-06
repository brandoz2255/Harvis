"""
forensics-basics — wrap common file-analysis CLI tools for "what's in
this file" / CTF-flag-hunting tasks.

Runs a layered analysis on each input file:
  file → strings (with flag-pattern hunting) → exiftool → binwalk → xxd

Each tool's output is captured as a sub-result. Findings (CTF flag
patterns, URLs, emails, base64-looking blobs) are surfaced separately
so the agent can drill into them.

Tools probed (gracefully degrade if missing):
  - file (binutils, almost always present)
  - strings (binutils)
  - exiftool (libimage-exiftool-perl)
  - binwalk (binwalk package)
  - xxd or hexdump (almost always present)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], timeout: int = 30) -> tuple[str, str, int]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, check=False, errors='replace')
        return r.stdout, r.stderr, r.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return "", str(exc)[:240], -1


_FLAG_PATTERNS = [
    (re.compile(r'flag\{[^\}\n]{1,200}\}', re.I), 'CTF flag (flag{})'),
    (re.compile(r'CTF\{[^\}\n]{1,200}\}'), 'CTF flag (CTF{})'),
    (re.compile(r'HTB\{[^\}\n]{1,200}\}'), 'HTB flag'),
    (re.compile(r'picoCTF\{[^\}\n]{1,200}\}'), 'picoCTF flag'),
    (re.compile(r'NCAE\{[^\}\n]{1,200}\}'), 'NCAE flag'),
    (re.compile(r'https?://[^\s"\'<>]{6,256}'), 'URL'),
    (re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'), 'email'),
    (re.compile(r'\b[A-Za-z0-9+/]{40,}={0,2}\b'), 'long base64-like'),
    (re.compile(r'\b[a-fA-F0-9]{32}\b'), 'md5-like hex'),
    (re.compile(r'\b[a-fA-F0-9]{40}\b'), 'sha1-like hex'),
    (re.compile(r'\b[a-fA-F0-9]{64}\b'), 'sha256-like hex'),
]


def analyze_file(path: str, opts: dict) -> dict:
    p = Path(path)
    if not p.exists():
        return {'path': str(path), 'error': 'file not found'}
    if not p.is_file():
        return {'path': str(path), 'error': 'not a regular file'}

    result: dict = {
        'path': str(p),
        'size_bytes': p.stat().st_size,
        'tools': {},
        'findings': [],
    }

    # 1. file (type identification)
    if have('file'):
        out, _, _ = run(['file', '-b', str(p)])
        result['tools']['file'] = out.strip()

    # 2. strings (printable-char extraction + flag hunting)
    if opts.get('strings', True) and have('strings'):
        out, _, _ = run(['strings', '-n', str(opts.get('min_strings_len', 6)), str(p)],
                        timeout=60)
        all_lines = out.splitlines()
        result['tools']['strings_total_lines'] = len(all_lines)
        result['tools']['strings_first_30'] = all_lines[:30]
        seen: set[tuple[str, str]] = set()
        for line in all_lines:
            for pat, label in _FLAG_PATTERNS:
                for m in pat.finditer(line):
                    val = m.group(0)
                    val_short = val if len(val) <= 200 else val[:200] + '…'
                    key = (label, val_short)
                    if key in seen:
                        continue
                    seen.add(key)
                    result['findings'].append({
                        'type': label, 'value': val_short, 'source': 'strings',
                    })
        # cap finding count
        if len(result['findings']) > 50:
            result['findings'] = result['findings'][:50]
            result['findings'].append({'note': 'truncated to first 50 findings'})

    # 3. exiftool (metadata)
    if opts.get('exiftool', True) and have('exiftool'):
        out, _, _ = run(['exiftool', str(p)], timeout=20)
        meta: dict = {}
        for line in out.splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                k, v = k.strip(), v.strip()
                if k and v and len(v) < 500:
                    meta[k] = v
        result['tools']['exiftool'] = meta
        # Hunt flag patterns inside metadata values too
        for k, v in meta.items():
            for pat, label in _FLAG_PATTERNS:
                m = pat.search(v)
                if m:
                    result['findings'].append({
                        'type': label, 'value': m.group(0)[:200],
                        'source': f'exiftool:{k}',
                    })

    # 4. binwalk (embedded files / signatures)
    if opts.get('binwalk', True) and have('binwalk'):
        out, _, _ = run(['binwalk', str(p)], timeout=60)
        embedded = []
        for line in out.splitlines():
            m = re.match(r'(\d+)\s+(0x[0-9A-Fa-f]+)\s+(.+?)$', line)
            if m:
                embedded.append({
                    'offset_dec': int(m.group(1)),
                    'offset_hex': m.group(2),
                    'description': m.group(3).strip(),
                })
        if embedded:
            result['tools']['binwalk'] = embedded

    # 5. hexdump first 256 bytes — always useful for magic-number sanity check
    if opts.get('hexdump', True):
        if have('xxd'):
            out, _, _ = run(['xxd', '-l', '256', str(p)])
        elif have('hexdump'):
            out, _, _ = run(['hexdump', '-C', '-n', '256', str(p)])
        else:
            out = ''
        if out:
            result['tools']['hexdump_head'] = out

    # Tools-missing summary
    missing = [t for t in ('file', 'strings', 'exiftool', 'binwalk', 'xxd', 'hexdump')
               if not have(t)]
    if missing:
        result['tools_unavailable'] = missing

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description='Forensics-basics file analyzer')
    ap.add_argument('paths', nargs='+', help='File(s) to analyze')
    ap.add_argument('--no-strings', dest='strings', action='store_false')
    ap.add_argument('--no-exiftool', dest='exiftool', action='store_false')
    ap.add_argument('--no-binwalk', dest='binwalk', action='store_false')
    ap.add_argument('--no-hexdump', dest='hexdump', action='store_false')
    ap.add_argument('--min-strings-len', type=int, default=6)
    args = ap.parse_args()

    opts = {
        'strings': args.strings,
        'exiftool': args.exiftool,
        'binwalk': args.binwalk,
        'hexdump': args.hexdump,
        'min_strings_len': args.min_strings_len,
    }
    results = [analyze_file(p, opts) for p in args.paths]
    print(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    has_data = any(r.get('findings') or r.get('tools') for r in results)
    return 0 if has_data else 1


if __name__ == '__main__':
    sys.exit(main())
