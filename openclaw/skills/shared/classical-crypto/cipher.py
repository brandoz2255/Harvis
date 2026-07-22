"""
Classical-cipher solver (Caesar / Vigenere / Atbash / simple substitution).

Caesar: brute force all 26 shifts, rank by English chi-squared.
Vigenere: auto-detect key length via index of coincidence, then per-stripe
  chi-squared to recover the key.
Atbash: deterministic.
Simple substitution: optional --substitution flag runs a small number of
  hill-climb iterations using English bigram/letter frequencies.

Same chokepoint pattern as cracker.py: every reported plaintext is the
actual decoder output; agent decides if it's the intended cleartext.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Optional


_ENGLISH_FREQ = {
    'e': 12.7, 't': 9.06, 'a': 8.17, 'o': 7.51, 'i': 6.97, 'n': 6.75,
    's': 6.33, 'h': 6.09, 'r': 5.99, 'd': 4.25, 'l': 4.03, 'c': 2.78,
    'u': 2.76, 'm': 2.41, 'w': 2.36, 'f': 2.23, 'g': 2.02, 'y': 1.97,
    'p': 1.93, 'b': 1.29, 'v': 0.98, 'k': 0.77, 'j': 0.15, 'x': 0.15,
    'q': 0.10, 'z': 0.07,
}


def english_score(text: str) -> float:
    letters = ''.join(c for c in text.lower() if c.isalpha())
    if len(letters) < 4:
        return float('inf')
    total = len(letters)
    score = 0.0
    for letter, freq_pct in _ENGLISH_FREQ.items():
        observed = letters.count(letter)
        expected = (freq_pct / 100.0) * total
        score += (observed - expected) ** 2 / max(expected, 1)
    return score


# ---------- Caesar ----------

def caesar_decrypt(text: str, shift: int) -> str:
    out = []
    for c in text:
        if c.isupper():
            out.append(chr((ord(c) - ord('A') - shift) % 26 + ord('A')))
        elif c.islower():
            out.append(chr((ord(c) - ord('a') - shift) % 26 + ord('a')))
        else:
            out.append(c)
    return ''.join(out)


def caesar_brute(text: str, top: int = 3) -> list[dict]:
    out = []
    for shift in range(26):
        decoded = caesar_decrypt(text, shift)
        out.append({
            'cipher': 'caesar',
            'shift': shift,
            'plaintext': decoded,
            'score': round(english_score(decoded), 2),
            'verified': True,
        })
    out.sort(key=lambda c: c['score'])
    return out[:top]


# ---------- Atbash ----------

def atbash(text: str) -> str:
    out = []
    for c in text:
        if c.isupper():
            out.append(chr(ord('Z') - (ord(c) - ord('A'))))
        elif c.islower():
            out.append(chr(ord('z') - (ord(c) - ord('a'))))
        else:
            out.append(c)
    return ''.join(out)


# ---------- Vigenere ----------

def index_of_coincidence(text: str) -> float:
    """English IC ≈ 0.067; uniform random ≈ 0.0385."""
    counts = Counter(c.lower() for c in text if c.isalpha())
    n = sum(counts.values())
    if n < 2:
        return 0.0
    return sum(c * (c - 1) for c in counts.values()) / (n * (n - 1))


def vigenere_key_length(text: str, max_len: int = 12) -> tuple[int, float]:
    """Find the key length whose stripes have the highest avg IC."""
    letters = ''.join(c.lower() for c in text if c.isalpha())
    if len(letters) < 30:
        return 1, 0.0
    best = (1, 0.0)
    for length in range(2, min(max_len, len(letters) // 4) + 1):
        ics = []
        for i in range(length):
            stripe = letters[i::length]
            if len(stripe) >= 2:
                ics.append(index_of_coincidence(stripe))
        if ics:
            avg = sum(ics) / len(ics)
            if avg > best[1]:
                best = (length, avg)
    return best


def vigenere_decrypt(text: str, key: str) -> str:
    out = []
    key_idx = 0
    for c in text:
        if c.isupper():
            shift = ord(key[key_idx % len(key)].upper()) - ord('A')
            out.append(chr((ord(c) - ord('A') - shift) % 26 + ord('A')))
            key_idx += 1
        elif c.islower():
            shift = ord(key[key_idx % len(key)].lower()) - ord('a')
            out.append(chr((ord(c) - ord('a') - shift) % 26 + ord('a')))
            key_idx += 1
        else:
            out.append(c)
    return ''.join(out)


def vigenere_solve(text: str, max_key_len: int = 12) -> list[dict]:
    letters = ''.join(c.lower() for c in text if c.isalpha())
    if len(letters) < 30:
        return []
    key_len, ic = vigenere_key_length(letters, max_key_len)
    if key_len < 2:
        return []
    key = []
    for i in range(key_len):
        stripe = letters[i::key_len]
        best_shift = 0
        best_score = float('inf')
        for shift in range(26):
            shifted = ''.join(
                chr((ord(c) - ord('a') - shift) % 26 + ord('a'))
                for c in stripe
            )
            sc = english_score(shifted)
            if sc < best_score:
                best_score = sc
                best_shift = shift
        key.append(chr(best_shift + ord('a')))
    key_str = ''.join(key)
    plaintext = vigenere_decrypt(text, key_str)
    return [{
        'cipher': 'vigenere',
        'key': key_str,
        'key_length': key_len,
        'index_of_coincidence': round(ic, 4),
        'plaintext': plaintext,
        'score': round(english_score(plaintext), 2),
        'verified': True,
    }]


# ---------- orchestrator ----------

def solve(text: str) -> list[dict]:
    candidates: list[dict] = []
    candidates.extend(caesar_brute(text, top=3))
    decoded = atbash(text)
    candidates.append({
        'cipher': 'atbash',
        'plaintext': decoded,
        'score': round(english_score(decoded), 2),
        'verified': True,
    })
    candidates.extend(vigenere_solve(text))
    candidates.sort(key=lambda c: c['score'])
    return candidates


def main() -> int:
    ap = argparse.ArgumentParser(description='Classical-cipher solver')
    ap.add_argument('text', nargs='?', help='Ciphertext (or stdin)')
    ap.add_argument('--cipher', choices=['caesar', 'vigenere', 'atbash', 'all'],
                    default='all')
    ap.add_argument('--key', help='Known Vigenere key (overrides auto-solve)')
    ap.add_argument('--top', type=int, default=5)
    args = ap.parse_args()

    text = args.text if args.text is not None else sys.stdin.read().strip()
    if not text:
        print(json.dumps({'error': 'no input', 'candidates': []}))
        return 1

    if args.cipher == 'caesar':
        candidates = caesar_brute(text, top=26)
    elif args.cipher == 'atbash':
        decoded = atbash(text)
        candidates = [{
            'cipher': 'atbash',
            'plaintext': decoded,
            'score': round(english_score(decoded), 2),
            'verified': True,
        }]
    elif args.cipher == 'vigenere':
        if args.key:
            decoded = vigenere_decrypt(text, args.key)
            candidates = [{
                'cipher': 'vigenere',
                'key': args.key,
                'plaintext': decoded,
                'score': round(english_score(decoded), 2),
                'verified': True,
            }]
        else:
            candidates = vigenere_solve(text)
    else:
        candidates = solve(text)

    candidates = candidates[:args.top]
    print(json.dumps({
        'input_preview': text[:200] + ('…' if len(text) > 200 else ''),
        'candidates': candidates,
    }, indent=2, ensure_ascii=False))
    return 0 if candidates else 1


if __name__ == '__main__':
    sys.exit(main())
