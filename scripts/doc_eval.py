#!/usr/bin/env python3
"""First-try pass rate of a local model on the harvis-doc prompts.

Runs INSIDE the backend container, where the real prompt code and exporters live:

    docker cp scripts/doc_eval.py harvis-backend:/tmp/
    docker exec -w /app harvis-backend python /tmp/doc_eval.py --model gemma3:4b --only 2

Each of the 20 fixed prompts goes through maybe_prepare_doc_turn (so the model sees
exactly what chat sends it), then Ollama /api/chat (OLLAMA_URL, num_ctx 8192, no
streaming). The reply is scored once, with no retry: a block was written, the header
kind is right, it parses, the outline matches the parts, every export of that kind
succeeds, sheet formulas evaluate and point at numbers, and every rich block parses
with no dropped line. A prompt passes when all its checks do. A failure you see here
belongs under Gotchas in owui_compat/doc_skills/<kind>/SKILL.md.

--only N     the first N prompts, taking one kind at a time (deck, doc, sheet, pdf, deck, ...)
--only 3,7   prompts by number, as the table prints them (--only 7, runs just prompt 7)
--models a,b run each model in turn (--model is the single-model form)
Results go to --out (default /tmp/doc_eval.json). Nothing is loaded or unloaded
except what the Ollama request itself loads.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.environ.get("APP_ROOT", os.getcwd()))

from owui_compat.doc_bridge import maybe_prepare_doc_turn  # noqa: E402
from owui_compat.doc_revision import find_fences  # noqa: E402
from plugins.hermes_ui.docs_check_rich import dropped_lines, scan_rich  # noqa: E402
from plugins.hermes_ui.docs_export import FORMATS, export_doc  # noqa: E402
from plugins.hermes_ui.docs_formula import FormulaError, evaluate, is_safe_formula, parse_number  # noqa: E402
from plugins.hermes_ui.docs_parse import parse_harvis_doc  # noqa: E402

# (kind, prompt, options). options: n = exact slide / sheet count, blocks = rich blocks the prompt asks for,
# marks = text the document must contain, limit = a spending cap the sheet must respect.
PROMPTS = [
    ("deck", "Make me a 5 slide status deck with a timeline", {"n": 5, "blocks": ["timeline"]}),
    ("deck", "Make a phishing awareness deck with 6 slides", {"n": 6}),
    ("deck", "Create an 8 slide deck on zero trust for the board", {"n": 8}),
    ("deck", "Make a 6 slide deck about our three lab servers with a card for each", {"n": 6, "blocks": ["cards"]}),
    ("deck", "Create a presentation on incident response with a diagram of the steps", {"blocks": ["flow"]}),
    ("deck", "Build a 7 slide pitch deck for a campus tutoring app", {"n": 7}),
    ("doc", "Write a report on the lab network upgrade with a table of tasks and their statuses", {"marks": ["in progress|done|blocked"]}),
    ("doc", "Write a runbook for restarting the web server, with the commands", {"marks": ["```"]}),
    ("doc", "Write a report on open security findings with a chart of findings by host", {"blocks": ["chart"]}),
    ("doc", "Draft a memo to the team about the outage with a timeline of what happened", {"blocks": ["timeline"]}),
    ("doc", "Write a project plan with a priority grid of tasks by impact and effort", {"blocks": ["quadrant"]}),
    ("doc", "Write a short guide to the lab network with a diagram of how traffic flows", {"blocks": ["flow"]}),
    ("sheet", "Create a 3 sheet budget for a student household", {"n": 3}),
    ("sheet", "Make a $2000 lab budget spreadsheet", {"limit": 2000}),
    ("sheet", "Build a spreadsheet of monthly expenses with totals", {"formulas": True}),
    ("sheet", "Create an excel tracker of lab devices with name, IP and owner", {}),
    ("sheet", "Make a grade calculator spreadsheet with weights", {"formulas": True}),
    ("pdf", "Make a pdf of the onboarding checklist for new SOC analysts", {"marks": [r"- \[ \]"]}),
    ("pdf", "Generate a PDF report on network segmentation", {}),
    ("pdf", "Make a one page PDF handout on password hygiene with a table of dos and don'ts", {"marks": [r"\|"]}),
]


# ---- model call -------------------------------------------------------------------------------

def ask(model: str, messages: list[dict], timeout: int) -> tuple[str, float]:
    url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/") + "/api/chat"
    payload = {"model": model, "messages": messages, "stream": False,
               "options": {"num_ctx": 8192, "num_predict": 3500}}
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    text = (data.get("message") or {}).get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip(), time.time() - started


# ---- sheets -----------------------------------------------------------------------------------

def _values(sheet):
    """value(row, col): the cell as a number (formulas evaluated), None when empty or text."""
    rows, cache, busy = sheet.rows, {}, set()

    def value(r: int, c: int):
        if (r, c) in cache:
            return cache[(r, c)]
        raw = rows[r][c].strip() if r < len(rows) and c < len(rows[r]) else ""
        if (r, c) in busy:
            raise FormulaError("circular")
        busy.add((r, c))
        try:
            if r > 0 and raw.startswith("=") and len(raw) > 1:
                result = evaluate(raw, value)
            else:
                parsed = parse_number(raw) if r > 0 else None
                result = parsed[0] if parsed else None
        finally:
            busy.discard((r, c))
        cache[(r, c)] = result
        return result

    return value


def _ref(ref: str) -> tuple[int, int]:
    m = re.match(r"\$?([A-Za-z]+)\$?(\d+)$", ref)
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)) - 1, col - 1


def _span(a: int, b: int) -> range:
    return range(min(a, b), max(a, b) + 1)


def _safe(fn, r: int, c: int):
    try:
        return fn(r, c)
    except (FormulaError, ZeroDivisionError, TypeError, IndexError):
        return None


def _sheet_problems(sheet) -> list[str]:
    value, problems = _values(sheet), []
    for r, row in enumerate(sheet.rows):
        for c, raw in enumerate(row):
            if r and "**" in raw:
                problems.append(f"markdown in cell {chr(65 + c)}{r + 1}")
            raw = raw.strip()
            if not (r and raw.startswith("=") and len(raw) > 1):
                continue
            name = f"{sheet.name}!{chr(65 + c)}{r + 1}"
            if not is_safe_formula(raw):
                problems.append(f"{name} uses a function that is not allowed")
                continue
            try:
                value(r, c)
            except (FormulaError, ZeroDivisionError, TypeError, IndexError):
                problems.append(f"{name} {raw} does not evaluate")
                continue
            unquoted = re.sub(r'"[^"]*"', '""', raw)
            for a, b in re.findall(r"(?<![A-Za-z0-9_.])\$?([A-Za-z]{1,2}\$?\d+)(?::\$?([A-Za-z]{1,2}\$?\d+))?(?![\w(])",
                                   unquoted):
                (r1, c1), (r2, c2) = _ref(a), _ref(b or a)
                cells = [(rr, cc) for rr in _span(r1, r2) for cc in _span(c1, c2)]
                if not any(_safe(value, rr, cc) is not None for rr, cc in cells):
                    problems.append(f"{name} {raw} points at {a}{':' + b if b else ''}, which holds no numbers")
    return problems


def _limit_ok(sheet, limit: float) -> bool:
    """The total stays at or under the limit, or a formula that names the limit shows the gap."""
    figure = re.compile(rf"(?<![\d.]){int(limit)}(?![\d.])")
    # The limit as an operand of a subtraction or comparison; =B2*2000 merely contains the digits.
    if any(c.strip().startswith("=") and figure.search(c.replace(",", "")) and re.search(r"[-<>]|\bIF\b", c, re.I)
           for row in sheet.rows for c in row):
        return True
    value = _values(sheet)
    totals = [r for r, row in enumerate(sheet.rows) if r and row and "total" in row[0].lower()]
    for r in totals:
        figures = [v for c in range(1, len(sheet.rows[r])) if (v := _safe(value, r, c)) is not None]
        if figures and max(figures) <= limit:
            return True
    return False


# ---- scoring ----------------------------------------------------------------------------------

def score(kind: str, opts: dict, reply: str) -> tuple[dict[str, str], str]:
    """({check: '' when it passed, else why}, the block source)."""
    checks: dict[str, str] = {}
    fences = find_fences(reply)
    lines = reply[fences[0][0]:fences[0][1]].rstrip().splitlines() if fences else []
    closed = len(lines) > 1 and bool(re.match(r"^\s*`{3,}\s*$", lines[-1]))
    source = fences[0][2] if fences else ""
    checks["block"] = "" if fences and closed else ("no harvis-doc block" if not fences else "fence never closed")
    if not fences:
        return checks, source
    doc = parse_harvis_doc(source)
    checks["kind"] = "" if doc.kind == kind else f"header says {doc.kind}"
    body_ok = any(s.rows for s in doc.sheets) if kind == "sheet" else any(s.title or s.body for s in doc.sections)
    checks["parses"] = "" if doc.header_complete and body_ok else "header or body did not parse"
    if kind == "sheet":
        parts = len(doc.sheets)
    elif kind == "deck":
        parts = len(doc.sections)
    else:
        parts = len([s for s in doc.sections if s.title])
    checks["outline"] = "" if abs(len(doc.outline) - parts) <= 1 else f"outline {len(doc.outline)} vs {parts} parts"
    if "n" in opts:
        checks["count"] = "" if parts == opts["n"] else f"asked for {opts['n']}, got {parts}"
    failed = []
    for fmt in FORMATS[kind]:
        try:
            if not export_doc(source, fmt).data:
                failed.append(fmt)
        except Exception as exc:  # noqa: BLE001 - any failure to export is the finding
            failed.append(f"{fmt} ({str(exc)[:60]})")
    checks["exports"] = "" if not failed else "export failed: " + ", ".join(failed)

    blocks, problems = scan_rich(source)
    for lang, body in blocks:
        problems += [f"{lang}: dropped line {ln[:50]!r}" for ln in dropped_lines(lang, body)]
    if kind == "sheet" and blocks:
        problems.append("rich block in a spreadsheet")
    if kind == "deck":
        for s in doc.sections:
            if len(scan_rich(s.body)[0]) > 1:
                problems.append(f"slide {s.title!r} has more than one block")
    checks["blocks"] = "" if not problems else "; ".join(problems[:3])
    asked = [b for b in opts.get("blocks", []) if b not in {lang for lang, _ in blocks}]
    if "blocks" in opts:
        checks["asked block"] = "" if not asked else "missing " + ", ".join(asked)
    missing = [p for p in opts.get("marks", []) if not re.search(p, source, re.I)]
    if "marks" in opts:
        checks["content"] = "" if not missing else f"nothing matching {missing[0]!r}"
    if kind == "deck":
        untitled = [i + 1 for i, s in enumerate(doc.sections) if not s.title]
        first = doc.sections[0] if doc.sections else None
        if untitled:
            checks["titles"] = f"slides without a title: {untitled}"
        else:
            checks["titles"] = "" if first and first.body.strip() else "slide 1 has no subtitle"
    if kind == "sheet":
        issues = [p for sh in doc.sheets for p in _sheet_problems(sh)]
        if opts.get("formulas") and not any(c.strip().startswith("=") for sh in doc.sheets for r in sh.rows[1:] for c in r):
            issues.append("no formulas")
        if "limit" in opts and not any(_limit_ok(sh, opts["limit"]) for sh in doc.sheets):
            issues.append(f"neither fits {opts['limit']} nor shows the gap")
        checks["sheet"] = "" if not issues else "; ".join(issues[:3])
    return checks, source


# ---- run --------------------------------------------------------------------------------------

def pick(only: str | None) -> list[int]:
    """``N`` prompts across the kinds, or ``3,7`` / ``7,`` prompts by number (a trailing comma picks one)."""
    ids = list(range(len(PROMPTS)))
    if not only:
        return ids
    parts = [p.strip() for p in only.split(",") if p.strip()]
    if not parts or not all(p.isdigit() for p in parts):
        raise SystemExit(f"--only wants a count like 4, or prompt numbers like 3,7 (got {only!r})")
    numbers = [int(p) for p in parts]
    bad = [n for n in numbers if not 0 < n <= len(PROMPTS)]
    if bad:
        raise SystemExit(f"--only: no prompt number {bad[0]}; there are {len(PROMPTS)}")
    if "," in only:
        return sorted({n - 1 for n in numbers})
    count = numbers[0]
    order = ["deck", "doc", "sheet", "pdf"]
    by_kind = {k: [i for i in ids if PROMPTS[i][0] == k] for k in order}
    out: list[int] = []
    while len(out) < count and any(by_kind.values()):
        for k in order:
            if by_kind[k] and len(out) < count:
                out.append(by_kind[k].pop(0))
    return sorted(out)


def run_one(model: str, index: int, timeout: int) -> dict:
    kind, text, opts = PROMPTS[index]
    body = {"messages": [{"role": "user", "content": text}]}
    detected = maybe_prepare_doc_turn(body)
    row = {"n": index + 1, "kind": kind, "prompt": text, "detected": detected, "seconds": 0.0, "checks": {}, "reply": ""}
    if detected != kind:
        row["checks"] = {"detected": f"chat saw {detected!r}, not {kind!r}"}
        return row
    try:
        reply, row["seconds"] = ask(model, body["messages"], timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        row["checks"] = {"model": f"request failed: {exc}"}
        return row
    row["reply"] = reply[:8000]
    row["checks"], _ = score(kind, opts, reply)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="gemma3:4b")
    ap.add_argument("--models", help="comma separated; overrides --model")
    ap.add_argument("--only", help="N prompts (mixed kinds) or a comma list of prompt numbers")
    ap.add_argument("--out", default="/tmp/doc_eval.json")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per model reply")
    args = ap.parse_args()
    models = [m.strip() for m in (args.models or args.model).split(",") if m.strip()]
    report: dict = {"ollama": os.environ.get("OLLAMA_URL", ""), "models": {}}
    for model in models:
        rows = []
        print(f"\n== {model} ==")
        for i in pick(args.only):
            row = run_one(model, i, args.timeout)
            row["pass"] = all(not why for why in row["checks"].values()) and bool(row["checks"])
            rows.append(row)
            fails = "; ".join(f"{k}: {v}" for k, v in row["checks"].items() if v)
            print(f"{row['n']:>2} {row['kind']:<5} {'PASS' if row['pass'] else 'FAIL'} {row['seconds']:>5.0f}s  "
                  f"{row['prompt'][:52]:<52} {fails}", flush=True)
        passed = sum(r["pass"] for r in rows)
        per_check: dict[str, list[bool]] = {}
        for r in rows:
            for name, why in r["checks"].items():
                per_check.setdefault(name, []).append(not why)
        rate = passed / len(rows) if rows else 0.0
        print(f"first-try pass rate: {passed}/{len(rows)} = {rate:.0%}")
        print("by check: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in per_check.items()))
        report["models"][model] = {"pass_rate": rate, "passed": passed, "total": len(rows), "rows": rows}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
