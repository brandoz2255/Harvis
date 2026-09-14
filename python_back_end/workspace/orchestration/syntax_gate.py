"""Does the code the agent just wrote actually parse?

A Build turn used to report "Done." over a page that could not run. The model
wrote an Asteroids game whose ``<script>`` opened ``(() => {`` and never closed
it; the browser threw ``SyntaxError: Unexpected end of input``, so not one line
of that script executed and the START GAME button did nothing but flash its CSS
``:active`` state. Every tool call succeeded, the diff was clean, the summary was
confident, and the artifact was dead on arrival. Nothing in the pipeline looked.

So this looks. It is deliberately a **balance checker, not a parser**: there is no
node binary and no JS parser in the backend image, and the failure mode worth
catching — a block that is opened and never closed — is exactly what balance
catches. It will happily miss a genuine type error or a bad `await`. That is the
right trade: a missed defect costs nothing that isn't already lost, while a FALSE
alarm would fail a working build, so every ambiguity here resolves to "silent".

The one real ambiguity in JS is ``/``: regex literal or division? Guessing wrong
corrupts the scan (``/[{]/`` read as division counts a brace that isn't there).
Rather than guess well, we scan TWICE — once treating an ambiguous slash as a
regex, once as division — and report only when **both** readings are broken. A
regex-driven miscount can never fail both; an unclosed IIFE always does.
"""
from __future__ import annotations

import ast
import json
import os
import re
from typing import Optional

_JS_EXT = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}
_HTML_EXT = {".html", ".htm"}
_JSON_EXT = {".json"}
_PY_EXT = {".py"}

# Files past this size are skipped: a vendored bundle or a minified blob is not
# something the agent authored, and scanning it buys nothing.
_MAX_BYTES = 512 * 1024

_OPEN = {"{": "}", "(": ")", "[": "]"}
_CLOSE = {"}": "{", ")": "(", "]": "["}

# After one of these, a `/` is division. After anything else it may open a regex.
_DIV_AFTER = set(")]_$")

# ...unless the token before it is a keyword, because `return /ab+/.test(s)` is a
# regex even though the previous character is a letter.
_REGEX_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await", "throw",
}


def _line_of(src: str, index: int) -> int:
    return src.count("\n", 0, index) + 1


def _skip_quoted(src: str, i: int) -> Optional[int]:
    """Index just past the string starting at ``i``; None if it never closes."""
    quote = src[i]
    j, n = i + 1, len(src)
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            return j + 1
        if ch == "\n":
            return None  # a plain string cannot span a line
        j += 1
    return None


def _template_text(src: str, j: int) -> tuple[str, Optional[int]]:
    """Walk the RAW text of a template literal from ``j``.

    Returns ``("close", k)`` past the closing backtick, ``("expr", k)`` past a
    ``${`` (the caller then scans the interpolation as ordinary code — it can hold
    regexes, strings and further templates, so it must not be scanned by hand),
    or ``("eof", None)`` when the literal never ends.
    """
    n = len(src)
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "`":
            return ("close", j + 1)
        if ch == "$" and j + 1 < n and src[j + 1] == "{":
            return ("expr", j + 2)
        j += 1
    return ("eof", None)


def _skip_regex(src: str, i: int) -> Optional[int]:
    """Index just past the regex literal at ``i`` (flags included), else None."""
    j, n = i + 1, len(src)
    in_class = False
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "\n":
            return None  # a regex literal cannot span a line — so it wasn't one
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            while j < n and (src[j].isalpha()):
                j += 1
            return j
        j += 1
    return None


def _prev_word(src: str, i: int) -> str:
    """The identifier ending just before ``i`` (skipping nothing) — '' if none."""
    j = i
    while j > 0 and (src[j - 1].isalnum() or src[j - 1] in "_$"):
        j -= 1
    return src[j:i]


def _scan(src: str, allow_regex: bool) -> Optional[tuple[int, str]]:
    """Bracket-balance ``src``. Returns (index, message) on the first defect.

    A ``${`` inside a template literal is pushed onto the same bracket stack as a
    marker, so its interpolation is scanned as ordinary code and its matching
    ``}`` drops back into template TEXT. Scanning interpolations by hand is what
    made an earlier version choke on ``` `"${y.replace(/"/g,'""')}"` ``` — the
    quote inside the regex read as the start of a string.
    """
    stack: list[tuple[str, int]] = []
    i, n = 0, len(src)
    prev = ""
    prev_at = 0

    def _enter_template(at: int, from_index: int):
        """Consume template text; returns (next_i, done) or None on an unclosed one."""
        kind, k = _template_text(src, from_index)
        if kind == "eof":
            return None
        if kind == "close":
            return (k, True)
        stack.append(("$", at))
        return (k, False)

    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                return (i, "a /* comment block is opened and never closed")
            i = j + 2
            continue
        if c == "/" and allow_regex:
            divides = prev in _DIV_AFTER or prev.isalnum()
            if divides and prev.isalnum():
                # `return /re/` is a regex even though `n` is alphanumeric.
                divides = _prev_word(src, prev_at + 1) not in _REGEX_KEYWORDS
            if not divides:
                j = _skip_regex(src, i)
                if j is not None:
                    i, prev, prev_at = j, "x", j - 1
                    continue
            i += 1
            prev, prev_at = c, i - 1
            continue
        if c in "\"'":
            j = _skip_quoted(src, i)
            if j is None:
                return (i, f"a {c}…{c} string literal is opened and never closed")
            i, prev, prev_at = j, "x", j - 1
            continue
        if c == "`":
            step = _enter_template(i, i + 1)
            if step is None:
                return (i, "a `…` template literal is opened and never closed")
            i = step[0]
            prev, prev_at = ("x" if step[1] else "{"), i - 1
            continue
        if c in _OPEN:
            stack.append((c, i))
            i += 1
            prev, prev_at = c, i - 1
            continue
        if c in _CLOSE:
            if not stack:
                return (i, f"a stray '{c}' closes a block that was never opened")
            opener, at = stack.pop()
            if opener == "$":
                if c != "}":
                    return (
                        i,
                        f"'{c}' closes the ${{…}} opened on line {_line_of(src, at)} "
                        "— the brackets are crossed",
                    )
                step = _enter_template(at, i + 1)
                if step is None:
                    return (at, "a `…` template literal is opened and never closed")
                i = step[0]
                prev, prev_at = ("x" if step[1] else "{"), i - 1
                continue
            if _OPEN[opener] != c:
                return (
                    i,
                    f"'{c}' closes the '{opener}' opened on line {_line_of(src, at)} "
                    "— the brackets are crossed",
                )
            i += 1
            prev, prev_at = c, i - 1
            continue
        i += 1
        prev, prev_at = c, i - 1
    if stack:
        opener, at = stack[0]
        if opener == "$":
            return (at, "a `…` template literal is opened and never closed")
        return (at, f"'{opener}' opened on line {_line_of(src, at)} is never closed")
    return None


def _check_js(src: str, line_offset: int = 0) -> Optional[str]:
    """A one-line defect description, or None when the source looks structurally sound.

    Reported only when BOTH slash readings agree it is broken — see the module
    docstring. The regex-friendly reading supplies the message, since its line
    numbers are the ones a person reading the file would recognise.
    """
    lenient = _scan(src, allow_regex=True)
    if lenient is None:
        return None
    if _scan(src, allow_regex=False) is None:
        return None  # only the no-regex reading is unhappy → our own ambiguity
    idx, msg = lenient
    return f"line {_line_of(src, idx) + line_offset}: {msg}"


# `<script>` blocks that hold JavaScript. A `src=` script has no body to check, and
# json/importmap/template types are not JS at all.
_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_TYPE_RE = re.compile(r"""type\s*=\s*["']?([^"'\s>]+)""", re.I)
_JS_TYPES = {"", "module", "text/javascript", "application/javascript", "text/babel"}


def _check_html(src: str) -> Optional[str]:
    for m in _SCRIPT_RE.finditer(src):
        attrs, body = m.group(1) or "", m.group(2) or ""
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        tm = _TYPE_RE.search(attrs)
        if (tm.group(1).lower() if tm else "") not in _JS_TYPES:
            continue
        if not body.strip():
            continue
        err = _check_js(body, line_offset=src.count("\n", 0, m.start(2)))
        if err:
            return f"the inline <script> is broken — {err}"
    return None


def check_source(rel_path: str, text: str) -> Optional[str]:
    """One human-readable defect for ``text``, or None if it is fine or unchecked.

    Unknown extensions, oversized files and any internal failure all return None:
    this gate exists to catch a page that cannot run, never to block a build it
    does not understand.
    """
    try:
        ext = os.path.splitext(rel_path or "")[1].lower()
        if not text or len(text) > _MAX_BYTES:
            return None
        if ext in _JSON_EXT:
            try:
                json.loads(text)
            except ValueError as exc:
                return f"invalid JSON — {exc}"
            return None
        if ext in _PY_EXT:
            try:
                ast.parse(text)
            except SyntaxError as exc:
                return f"line {exc.lineno}: {exc.msg}"
            return None
        if ext in _HTML_EXT:
            return _check_html(text)
        if ext in _JS_EXT:
            return _check_js(text)
        return None
    except Exception:  # noqa: BLE001 — a checker must never break a build
        return None


# ── Dangling local references ────────────────────────────────────────────────
# A second way to ship a page that loads and does nothing, and the one the
# multi-file prompt makes MORE likely rather than less: the model writes a
# perfectly correct index.html that links styles.css and main.js, then never
# writes either file. Nothing here is a syntax error — index.html parses, the
# browser renders it, the canvas appears, and the 404s are invisible unless you
# open devtools. A measured run did exactly this: it wrote index.html seven times
# and produced no sibling at all.
#
# Three reference kinds are checked, and deliberately only three. A missing
# <script src> means none of the program runs; a missing stylesheet means the page
# is unstyled; and an <a href> to a local PAGE nobody wrote is a link that goes
# nowhere. A missing image degrades a page that still works, so failing a build
# over one would be the false alarm this module refuses to raise.
#
# The <a> case is the one a menu-shaped build lands on, and it was measured live:
# a Build turn wrote an arcade index.html whose two cards linked asteroids.html and
# galaga.html, and wrote neither. The menu renders perfectly and every card is a
# dead end. It is checked ONLY when the target names an .html file — a link to a
# directory, a download or an extensionless route may be served by something other
# than a file on disk, and guessing about those is how a checker starts crying wolf.
_REF_TAG_RE = re.compile(r"<(script|link|a)\b([^>]*)>", re.I)
_ATTR_RE = re.compile(r"""\b(src|href|rel)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
# A scheme, a protocol-relative URL, a fragment or a query is not a file we wrote.
_NOT_LOCAL_RE = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//|#|\?)", re.I)


def _attrs_of(raw: str) -> dict:
    out = {}
    for m in _ATTR_RE.finditer(raw or ""):
        out[m.group(1).lower()] = (m.group(2) or m.group(3) or m.group(4) or "").strip()
    return out


def missing_refs(contents: dict, known: set | None = None) -> dict:
    """``{html_path: [targets it links to that nobody wrote]}``.

    Split out from ``check_links`` so a caller can count the individual missing
    files rather than the pages naming them. The repair loop needs exactly that:
    one page short of two siblings becomes one page short of one after a good
    round, and a guard that only counted broken PAGES saw no progress and stopped
    while the fix was visibly half-done.

    ``contents`` is the workspace's file map; ``known`` may add paths whose bodies
    were not collected (a binary, an oversized file) so they are not reported as
    missing. Anything it cannot resolve confidently is left alone.
    """
    import posixpath

    out: dict = {}
    try:
        present = {str(k).lstrip("./") for k in (contents or {})}
        present |= {str(k).lstrip("./") for k in (known or set())}
        for rel, text in (contents or {}).items():
            if os.path.splitext(str(rel))[1].lower() not in _HTML_EXT:
                continue
            if not isinstance(text, str) or not text or len(text) > _MAX_BYTES:
                continue
            base = posixpath.dirname(str(rel).lstrip("./"))
            missing: list[str] = []
            for m in _REF_TAG_RE.finditer(text):
                tag, attrs = m.group(1).lower(), _attrs_of(m.group(2))
                html_only = False
                if tag == "script":
                    ref = attrs.get("src", "")
                elif tag == "a":
                    # Navigation, not an asset. Only a link that names a page file
                    # counts — see the note above on why the rest is left alone.
                    ref, html_only = attrs.get("href", ""), True
                elif "stylesheet" in (attrs.get("rel", "") or "").lower():
                    ref = attrs.get("href", "")
                else:
                    continue
                if not ref or _NOT_LOCAL_RE.match(ref):
                    continue
                target = ref.split("?", 1)[0].split("#", 1)[0].strip()
                if not target:
                    continue
                if html_only and os.path.splitext(target)[1].lower() not in _HTML_EXT:
                    continue
                target = posixpath.normpath(
                    posixpath.join(base, target.lstrip("/") if target.startswith("/") else target)
                ).lstrip("./")
                if target and target not in present and target not in missing:
                    missing.append(target)
            if missing:
                out[str(rel)] = missing
    except Exception:  # noqa: BLE001 — a checker must never break a build
        return out
    return out


def check_links(contents: dict, known: set | None = None) -> dict:
    """``{html_path: defect}`` for pages pointing at local files that do not exist."""
    out: dict = {}
    for rel, missing in missing_refs(contents, known).items():
        names = ", ".join(missing)
        out[rel] = (
            f"references {names}, which "
            + ("were" if len(missing) > 1 else "was")
            + " never written — the page itself loads, but everything it points at "
            "is a 404, so that code, styling or destination does not exist"
        )
    return out


def check_files(files: dict) -> dict:
    """``{rel_path: content}`` → ``{rel_path: defect}`` for the ones that are broken."""
    out: dict = {}
    for rel, content in (files or {}).items():
        if not isinstance(content, str):
            continue
        err = check_source(rel, content)
        if err:
            out[rel] = err
    return out


# ── The shared contract: what "it runs" means, and how to say it ─────────────
# Everything below is used by BOTH Build lanes. It lives beside the checkers on
# purpose: `PROJECT_LAYOUT_CONTRACT` states the rules and `gate_check` enforces
# them, so a change to one is impossible to make without seeing the other.
#
# Until now only the native lane had any of this. The CLI lanes (claude-code,
# kimi-code, codex, opencode, hermes-agent) launched with the user's brief and
# NOTHING else — no layout guidance and no gate — which is why a Claude Build turn
# answered every request with one self-contained index.html and nobody ever caught
# the dead links inside it.

# Tool-neutral by design: an external CLI has its own file tools under its own
# names, so naming Harvis's would be describing a toolbox the model does not have.
# What it must carry is the part no model can infer — how the Run tab serves what
# gets written.
PROJECT_LAYOUT_CONTRACT = (
    "Project layout for this workspace — these are hard requirements, not style "
    "preferences:\n"
    "- Write a REAL project laid out in SEPARATE FILES, the way you would in an "
    "editor. For anything web that means index.html for the markup, styles.css for "
    "the styling, and one or more .js files for the behaviour, as sibling files "
    "linked with relative paths. Do NOT put an entire application inside one "
    "enormous index.html. Once a piece of the program is big enough to have a name, "
    "give it its own file.\n"
    "- There MUST be an index.html at the workspace ROOT. It is what the Run tab "
    "serves.\n"
    "- The whole thing must open in a browser with NO build step and NO packages "
    "installed: no npm, no bundler, and no CDN — the sandbox has no internet, so a "
    "CDN <script> is a guaranteed blank page. Plain ES modules "
    "(<script type=\"module\" src=\"main.js\">) work and are preferred.\n"
    "- Every file you reference must exist when you finish. If index.html links "
    "styles.css, game.js, or another page like asteroids.html, WRITE that file. A "
    "page whose links 404 renders fine and does nothing, which is the single most "
    "common way a build looks finished and is not.\n"
    "- Wire every control you draw to real behaviour before you finish."
)


def on_disk(workspace_path: str, limit: int = 20000) -> set:
    """Every path the workspace actually holds — relative, posix-style.

    The gate's "what exists" set used to be the turn's CHANGED files. That is exactly
    right for a from-nothing build, where everything is changed, and wrong for a session
    attached to a real repo: an edited index.html linking a styles.css this turn never
    touched would be reported as pointing at a file nobody wrote. Failing a working build
    is the one thing this module is not allowed to do, so it asks the disk.

    Capped, and `.git`/`node_modules` are skipped: a vendored tree can hold a hundred
    thousand paths, and none of them are what an index.html links to.
    """
    out: set = set()
    try:
        for root, dirs, names in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
            for n in names:
                out.add(os.path.relpath(os.path.join(root, n), workspace_path).replace(os.sep, "/"))
                if len(out) >= limit:
                    return out
    except OSError:
        pass
    return out


# The ceiling on repair rounds, not a quota: the loop stops the moment the gate is
# clean OR a round fails to reduce the defect count, so a stuck model still costs
# exactly one extra request. Two, because the two defect kinds converge differently.
# ONE round by explicit choice — "auto-repair, capped at 1 retry". A model that cannot
# close its own brace on the first re-read will not close it on the third, and that case
# ends on the no-progress break either way. Every round is also a real request against a
# provider that has been rate-limiting this box.
#
# The counter-evidence, recorded so raising it is an informed decision rather than a
# rediscovery: a MISSING FILE is additive, not a fix-in-place. A measured gpt-oss:20b run
# wrote the styles.css it had forgotten on round one and would have written main.js on
# round two; at a cap of 1 that page loaded and did nothing. If forgotten-sibling repairs
# start showing up again, `HARVIS_BUILD_SYNTAX_REPAIR_ROUNDS=2` is the whole fix.
# Set to 0 to report without repairing.
SYNTAX_REPAIR_ROUNDS = int(os.getenv("HARVIS_BUILD_SYNTAX_REPAIR_ROUNDS", "1") or 0)


def gate_check(contents: dict, files, workspace_path: str = "") -> tuple[dict, int]:
    """Every reason this workspace will not run, plus how many defects that is.

    Two independent checks, merged: a file that cannot be parsed, and a page
    pointing at a local file nobody wrote. Both end with a browser that renders
    something and runs nothing, so both belong to the same repair round.

    The second return value is the repair loop's progress metric, and it counts
    DEFECTS rather than the files reporting them. That distinction is the whole
    reason it exists: one index.html short of both styles.css and game.js becomes
    the same single index.html short of game.js after a round that genuinely
    worked, so a guard counting broken files saw 1 → 1, called it no progress,
    and stopped one file from the finish line.
    """
    out = check_files(contents)
    weight = len(out)
    known = set(files or []) | (on_disk(workspace_path) if workspace_path else set())
    gaps = missing_refs(contents, known=known)
    for rel, err in check_links(contents, known=known).items():
        out[rel] = f"{out[rel]}; also {err}" if rel in out else err
    weight += sum(len(v) for v in gaps.values())
    return out, weight


def repair_task(broken: dict, *, native: bool = True) -> str:
    """The follow-up turn's brief: the exact defects, and nothing else to do.

    Two kinds land here and the instruction differs, so say both: a file that will
    not parse is repaired in place, while a file that was promised and never
    written has to actually be created. Telling a model to "find the unbalanced
    bracket" in a file that does not exist is how a repair round burns itself.

    ``native`` picks the vocabulary. The native lane has Harvis's own tools and is
    told to use them by name; an external CLI has its own and would only be
    confused by ours, so it gets the same instruction with the tool names removed.
    """
    lines = "\n".join(f"  - {rel}: {err}" for rel, err in sorted(broken.items()))
    n = len(broken)
    how = (
        "Where a file will not parse, read_file it, find the unbalanced bracket or "
        "malformed syntax at the line given, and repair it with str_replace. Where a "
        "file is referenced but was never written, WRITE IT NOW with edit_file, "
        if native else
        "Where a file will not parse, read it, find the unbalanced bracket or "
        "malformed syntax at the line given, and repair it in place. Where a file is "
        "referenced but was never written, WRITE IT NOW, "
    )
    return (
        f"Your last change left {n} file{'s' if n > 1 else ''} in a state where the "
        "code does not run:\n"
        f"{lines}\n\n"
        "Fix ONLY this, and nothing else. " + how +
        "complete and working, matching exactly the filename the page already links "
        "to — do not rename the reference to dodge the work, and do not inline it "
        "back into the page. Do not add features, do not restyle anything, do not "
        "rewrite working code."
        + (
            " When it all runs, call finish with a one-line summary of what was wrong."
            if native else ""
        )
    )
