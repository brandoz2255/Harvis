"""
Multi-format string decoder for CTF / quick-decode tasks.

Try every common encoding/cipher on the input and return ranked
candidates. The agent never claims a decoded plaintext that didn't
flow through this tool — same chokepoint pattern as cracker.py.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import string
import sys
import urllib.parse


# English letter frequency (per 100 chars) for chi-squared scoring.
_ENGLISH_FREQ = {
    'e': 12.7, 't': 9.06, 'a': 8.17, 'o': 7.51, 'i': 6.97, 'n': 6.75,
    's': 6.33, 'h': 6.09, 'r': 5.99, 'd': 4.25, 'l': 4.03, 'c': 2.78,
    'u': 2.76, 'm': 2.41, 'w': 2.36, 'f': 2.23, 'g': 2.02, 'y': 1.97,
    'p': 1.93, 'b': 1.29, 'v': 0.98, 'k': 0.77, 'j': 0.15, 'x': 0.15,
    'q': 0.10, 'z': 0.07,
}


def is_mostly_printable(b: bytes | str, threshold: float = 0.85) -> bool:
    if not b:
        return False
    if isinstance(b, bytes):
        try:
            s = b.decode('utf-8')
        except UnicodeDecodeError:
            return sum(1 for x in b if 32 <= x < 127 or x in (9, 10, 13)) / len(b) >= threshold
    else:
        s = b
    if not s:
        return False
    return sum(1 for c in s if c in string.printable) / len(s) >= threshold


def english_score(text: str) -> float:
    """Lower = more English-like. For short outputs (< 6 letters) we
    fall back to a printability-based score so a 5-letter legit hex
    decode like "Hello" doesn't get sorted below 12-letter noisy ROTs.
    """
    letters = ''.join(c for c in text.lower() if c.isalpha())
    if len(letters) < 6:
        # Short outputs: score by inverse printability ratio.
        # All-printable + has at least one letter → ~10 (good rank).
        # Garbage / non-letters → much higher.
        printable = sum(1 for c in text if c in string.printable)
        if not text or printable / len(text) < 0.85:
            return 1000.0
        if letters:
            return 10.0 + (6 - len(letters))  # short but English-y
        return 100.0  # printable but no letters at all
    total = len(letters)
    chi = 0.0
    for letter, freq_pct in _ENGLISH_FREQ.items():
        observed = letters.count(letter)
        expected = (freq_pct / 100.0) * total
        chi += (observed - expected) ** 2 / max(expected, 1)
    return chi


# ---------- decoders ----------

def try_base64(s: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cleaned = re.sub(r'\s+', '', s.strip())
    if len(cleaned) < 4:
        return out
    # Standard base64 + try with auto-padding
    for variant_name, variant in [
        ('base64', cleaned),
        ('base64-padded', cleaned + '=' * (-len(cleaned) % 4)),
    ]:
        try:
            decoded = base64.b64decode(variant, validate=False)
            if is_mostly_printable(decoded):
                out.append((variant_name, decoded.decode('utf-8', errors='replace')))
                break
        except (binascii.Error, ValueError):
            pass
    # base64url
    try:
        padded = cleaned + '=' * (-len(cleaned) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
        if is_mostly_printable(decoded):
            text = decoded.decode('utf-8', errors='replace')
            # only add if different from standard b64 result
            if not any(r[1] == text for r in out):
                out.append(('base64url', text))
    except (binascii.Error, ValueError):
        pass
    # base32
    try:
        decoded = base64.b32decode(cleaned + '=' * (-len(cleaned) % 8), casefold=True)
        if is_mostly_printable(decoded):
            out.append(('base32', decoded.decode('utf-8', errors='replace')))
    except (binascii.Error, ValueError):
        pass
    return out


def try_hex(s: str) -> list[tuple[str, str]]:
    cleaned = re.sub(r'[\s:_\-]', '', s.strip())
    if not re.fullmatch(r'[0-9a-fA-F]+', cleaned) or len(cleaned) < 4 or len(cleaned) % 2:
        return []
    try:
        decoded = bytes.fromhex(cleaned)
        if is_mostly_printable(decoded):
            return [('hex', decoded.decode('utf-8', errors='replace'))]
    except ValueError:
        pass
    return []


def try_binary(s: str) -> list[tuple[str, str]]:
    cleaned = re.sub(r'\s+', '', s.strip())
    if not re.fullmatch(r'[01]+', cleaned) or len(cleaned) % 8 or len(cleaned) < 8:
        return []
    try:
        decoded = bytes(int(cleaned[i:i + 8], 2) for i in range(0, len(cleaned), 8))
        if is_mostly_printable(decoded):
            return [('binary', decoded.decode('utf-8', errors='replace'))]
    except ValueError:
        pass
    return []


def try_decimal(s: str) -> list[tuple[str, str]]:
    nums = re.findall(r'\b\d{1,3}\b', s)
    if len(nums) < 3:
        return []
    try:
        ints = [int(n) for n in nums if 0 <= int(n) < 256]
        if len(ints) < 3:
            return []
        decoded = bytes(ints)
        if is_mostly_printable(decoded):
            return [('ascii-decimal', decoded.decode('utf-8', errors='replace'))]
    except (ValueError, OverflowError):
        pass
    return []


def try_url(s: str) -> list[tuple[str, str]]:
    if '%' not in s:
        return []
    try:
        decoded = urllib.parse.unquote(s)
        if decoded != s and is_mostly_printable(decoded):
            return [('url', decoded)]
    except Exception:
        pass
    return []


def _rot_n(s: str, n: int) -> str:
    out: list[str] = []
    for c in s:
        if c.isupper():
            out.append(chr((ord(c) - ord('A') + n) % 26 + ord('A')))
        elif c.islower():
            out.append(chr((ord(c) - ord('a') + n) % 26 + ord('a')))
        else:
            out.append(c)
    return ''.join(out)


def try_rot_brute(s: str) -> list[tuple[str, str]]:
    """Try ROT-1..25, return top 3 by English-likeness."""
    if not any(c.isalpha() for c in s):
        return []
    candidates = []
    for n in range(1, 26):
        decoded = _rot_n(s, n)
        candidates.append((f'rot{n}', decoded, english_score(decoded)))
    candidates.sort(key=lambda x: x[2])
    return [(name, text) for name, text, _ in candidates[:3]]


def try_rot47(s: str) -> list[tuple[str, str]]:
    out = []
    for c in s:
        o = ord(c)
        if 33 <= o <= 126:
            out.append(chr(33 + (o - 33 + 47) % 94))
        else:
            out.append(c)
    decoded = ''.join(out)
    if decoded != s and is_mostly_printable(decoded):
        return [('rot47', decoded)]
    return []


def try_atbash(s: str) -> list[tuple[str, str]]:
    if not any(c.isalpha() for c in s):
        return []
    out = []
    for c in s:
        if c.isupper():
            out.append(chr(ord('Z') - (ord(c) - ord('A'))))
        elif c.islower():
            out.append(chr(ord('z') - (ord(c) - ord('a'))))
        else:
            out.append(c)
    return [('atbash', ''.join(out))]


_MORSE_TABLE = {
    '.-':'A','-...':'B','-.-.':'C','-..':'D','.':'E','..-.':'F','--.':'G',
    '....':'H','..':'I','.---':'J','-.-':'K','.-..':'L','--':'M','-.':'N',
    '---':'O','.--.':'P','--.-':'Q','.-.':'R','...':'S','-':'T','..-':'U',
    '...-':'V','.--':'W','-..-':'X','-.--':'Y','--..':'Z',
    '-----':'0','.----':'1','..---':'2','...--':'3','....-':'4',
    '.....':'5','-....':'6','--...':'7','---..':'8','----.':'9',
}


def try_morse(s: str) -> list[tuple[str, str]]:
    cleaned = s.strip()
    # Must look mostly like morse: only . - / and whitespace
    if not re.fullmatch(r'[\.\-/\s]+', cleaned) or '.' not in cleaned and '-' not in cleaned:
        return []
    try:
        words = re.split(r'\s*/\s*|\s{2,}', cleaned)
        decoded = []
        for w in words:
            chars = [_MORSE_TABLE.get(t.strip()) for t in w.split() if t.strip()]
            if any(c is None for c in chars):
                return []
            decoded.append(''.join(chars))
        result = ' '.join(d for d in decoded if d)
        if result:
            return [('morse', result)]
    except Exception:
        pass
    return []


# ---------- orchestrator ----------

def decode_all(s: str) -> list[dict]:
    """Run every decoder, return ranked candidates with verified=True
    (decoder ran cleanly) — agent decides if any candidate makes sense."""
    candidates: list[dict] = []
    for fn in (try_base64, try_hex, try_binary, try_decimal,
               try_url, try_rot47, try_atbash, try_morse):
        try:
            for method, text in fn(s):
                candidates.append({
                    'method': method,
                    'plaintext': text if len(text) < 500 else text[:500] + '…[truncated]',
                    'score': round(english_score(text), 2),
                    'verified': True,
                })
        except Exception as exc:
            # Decoder bug should not break the whole run
            candidates.append({'method': fn.__name__, 'error': str(exc)[:120]})

    for method, text in try_rot_brute(s):
        candidates.append({
            'method': method,
            'plaintext': text if len(text) < 500 else text[:500] + '…[truncated]',
            'score': round(english_score(text), 2),
            'verified': True,
        })

    # Sort by English-score (lower = more English-like). inf-scored sink to end.
    candidates.sort(key=lambda c: c.get('score', float('inf')))
    return candidates


def main() -> int:
    ap = argparse.ArgumentParser(description='Multi-format string decoder')
    ap.add_argument('input', nargs='?', help='Encoded string (or read from stdin)')
    ap.add_argument('--top', type=int, default=5, help='Top N results (default 5)')
    ap.add_argument('--all', action='store_true', help='Show all candidates')
    args = ap.parse_args()

    inp = args.input if args.input is not None else sys.stdin.read().strip()
    if not inp:
        print(json.dumps({'error': 'no input', 'candidates': []}))
        return 1

    candidates = decode_all(inp)
    if not args.all:
        candidates = candidates[:args.top]

    print(json.dumps({
        'input_preview': inp[:200] + ('…' if len(inp) > 200 else ''),
        'input_length': len(inp),
        'candidates': candidates,
    }, indent=2, ensure_ascii=False))
    return 0 if candidates else 1


if __name__ == '__main__':
    sys.exit(main())
