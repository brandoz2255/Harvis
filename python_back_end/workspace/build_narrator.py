"""Build Result Narrator — composes a full written assistant-style analysis of a finished
Build/VibeCode run.

Instead of a one-line engine summary, Harvis answers like a senior engineer reviewing the
work: a status headline, what was requested, what was done, the files changed (explained),
how to test it, and review notes — rendered as the assistant message in the chat thread, with
PR/diff actions below and the raw diff/logs collapsed.

Pass 1 (this module, default ON) is fully DETERMINISTIC — it builds the markdown from the run
metadata + the diff/changed-files we already have. No model call, instant, offline-safe.

Pass 2 (`narrate_build_ai`, default OFF behind a flag) optionally asks a model to write a richer
per-file "why it matters" narrative; ANY failure falls back to the deterministic text. It uses a
direct Ollama call (the bg task has no Request to route `execute_chat_completion`), so enabling it
only needs a reachable model — see `build_narrator_ai_enabled()`.

Scope: the caller narrates only Build-like runs (a git diff exists, or it's a VibeCode turn) —
not CTF/decode (no diff) or research/document (structured source-card output). See workspace_router.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ── Flags ────────────────────────────────────────────────────────────────────────────────────
def _env_true(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_narrator_enabled() -> bool:
    """Deterministic Build narration (default ON). Set HARVIS_OWUI_BUILD_NARRATOR=0 to disable."""
    return _env_true("HARVIS_OWUI_BUILD_NARRATOR", True)


def build_narrator_ai_enabled() -> bool:
    """Pass-2 AI narration (default OFF). Set HARVIS_OWUI_BUILD_NARRATOR_AI=1 to enable."""
    return _env_true("HARVIS_OWUI_BUILD_NARRATOR_AI", False)


# ── Language + diff parsing ───────────────────────────────────────────────────────────────────
_LANG_BY_EXT = {
    "py": "Python", "ts": "TypeScript", "tsx": "TypeScript", "js": "JavaScript",
    "jsx": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript", "svelte": "Svelte",
    "vue": "Vue", "go": "Go", "rs": "Rust", "rb": "Ruby", "java": "Java", "kt": "Kotlin",
    "c": "C", "h": "C header", "cpp": "C++", "cc": "C++", "cs": "C#", "php": "PHP",
    "swift": "Swift", "sh": "shell", "bash": "shell", "sql": "SQL", "json": "JSON",
    "yaml": "YAML", "yml": "YAML", "toml": "TOML", "md": "documentation",
    "mdx": "documentation", "markdown": "documentation", "rst": "documentation",
    "txt": "text", "html": "HTML", "css": "CSS", "scss": "CSS",
}
_TEST_RE = re.compile(r"(^|/)(tests?|specs?|__tests__)(/|$)|\.(test|spec)\.[a-z]+$", re.I)
_CODE_EXTS = {
    "py", "ts", "tsx", "js", "jsx", "mjs", "cjs", "go", "rs", "rb", "java", "kt",
    "c", "h", "cpp", "cc", "cs", "php", "swift", "svelte", "vue",
}
_DOC_EXTS = {"md", "mdx", "markdown", "rst", "txt"}


def _ext(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def _lang_for(path: str) -> str:
    return _LANG_BY_EXT.get(_ext(path), "file")


def _parse_diff_files(diff_text: str) -> list[dict]:
    """Parse a unified git diff into per-file {path, status, add, del, lang}."""
    files: list[dict] = []
    cur: Optional[dict] = None
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            if cur:
                files.append(cur)
            # "diff --git a/<path> b/<path>"
            seg = line.split(" b/", 1)
            path = seg[1].strip() if len(seg) > 1 else line.split("/", 1)[-1].strip()
            cur = {"path": path, "status": "modified", "add": 0, "del": 0}
        elif cur is None:
            continue
        elif line.startswith("new file mode"):
            cur["status"] = "new file"
        elif line.startswith("deleted file mode"):
            cur["status"] = "deleted"
        elif line.startswith("rename to "):
            cur["status"] = "renamed"
            cur["path"] = line[len("rename to "):].strip() or cur["path"]
        elif line.startswith("+++ b/"):
            p = line[len("+++ b/"):].strip()
            if p and p != "/dev/null":
                cur["path"] = p
        elif line.startswith("+") and not line.startswith("+++"):
            cur["add"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            cur["del"] += 1
    if cur:
        files.append(cur)
    for f in files:
        f["lang"] = _lang_for(f["path"])
    return files


# A fenced block opens with ``` or ~~~ (markdown allows up to three leading spaces).
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _fence_segments(text: str) -> list[tuple[bool, str]]:
    """Split into ``(is_fenced, chunk)`` runs, delimiters kept with their fence.

    An unterminated fence — the streaming tail, or a model that forgot to close —
    counts as fenced, so a half-written block is preserved rather than mangled.
    """
    segs: list[tuple[bool, str]] = []
    cur: list[str] = []
    marker = ""
    for ln in text.split("\n"):
        if not marker:
            m = _FENCE_RE.match(ln)
            if m:
                if cur:
                    segs.append((False, "\n".join(cur)))
                cur, marker = [ln], m.group(1)[0]
                continue
            cur.append(ln)
        else:
            cur.append(ln)
            m = _FENCE_RE.match(ln)
            if m and m.group(1)[0] == marker and len(cur) > 1:
                segs.append((True, "\n".join(cur)))
                cur, marker = [], ""
    if cur:
        segs.append((bool(marker), "\n".join(cur)))
    return segs


def _dedupe_prose(v: str) -> str:
    """Normalise + de-repeat ordinary prose. Never called on fenced content."""
    v = "\n".join(re.sub(r"[ \t]+", " ", ln).rstrip() for ln in v.split("\n"))
    v = re.sub(r"\n{3,}", "\n\n", v)
    out: list[str] = []
    for line in v.split("\n"):
        if not line.strip():
            # Keep paragraph breaks, but never lead with one or stack them.
            if out and out[-1].strip():
                out.append("")
            continue
        if out and out[-1].strip().lower() == line.strip().lower():
            continue  # the same line twice in a row is a repeat — in PROSE
        sents = re.split(r"(?<=[.!?])\s+", line)
        kept: list[str] = []
        for sent in sents:
            if not kept or kept[-1].strip().lower() != sent.strip().lower():
                kept.append(sent)
        out.append(" ".join(kept))
    return "\n".join(out)


def _dedupe(s: str) -> str:
    """Drop consecutive duplicate sentences (some engines, e.g. Claude Code, emit the summary —
    or a trailing sentence — twice). Handles both whole-string doubles and trailing repeats.

    Fenced blocks are passed through byte-for-byte. Everything here is destructive to code:
    `[ \t]+ → " "` flattens leading indentation, and the consecutive-identical-line rule
    deletes real content — two rules that between them turned a requested ASCII tree into a
    left-aligned smear with lines missing. It kept its shape while streaming and lost it on
    the way to the transcript, because the stream is the model's text and this is not.

    Outside a fence the collapsing stays: it is what stops a one-line summary arriving with
    ragged spacing, and prose has no load-bearing indentation."""
    raw = (s or "").replace("\r\n", "\n")
    if not raw.strip():
        return ""

    segs = _fence_segments(raw)
    if not any(fenced for fenced, _ in segs):
        v = _dedupe_prose(raw).strip()
        # Whole-string double: some engines emit the entire summary twice, back to back.
        # Only attempted without fences — slicing at the midpoint can cut through one.
        half, rem = divmod(len(v), 2)
        if rem in (0, 1) and half > 20:
            a, b = v[:half].strip(), v[half:].strip()
            if a and a.lower() == b.lower():
                v = a
        return v

    return "\n".join(
        chunk if fenced else _dedupe_prose(chunk) for fenced, chunk in segs
    ).strip()


def _test_command(paths: list[str]) -> Optional[str]:
    if any(p.rsplit("/", 1)[-1] == "package.json" for p in paths):
        return "npm test"
    non_test = [p for p in paths if not _TEST_RE.search(p)]
    pool = non_test or paths
    for ext, cmd in (("py", "python"), ("js", "node"), ("mjs", "node"), ("sh", "bash")):
        for p in pool:
            if p.endswith("." + ext):
                return f"{cmd} {p}"
    return None


def _fmt_duration(ms: Optional[int]) -> str:
    if not ms or ms < 0:
        return ""
    s = ms // 1000
    if s < 60:
        return f"{s}s"
    m = s // 60
    return f"{m}m" if m < 60 else f"{m // 60}h {m % 60}m"


def _engine_phrase(engine_label: str) -> str:
    e = (engine_label or "").strip()
    return e or "Harvis"


# ── Deterministic composer (Pass 1) ────────────────────────────────────────────────────────────
def compose_build_analysis(
    *,
    task_brief: str,
    engine_label: str,
    model_name: str = "",
    status: str = "done",
    raw_summary: str = "",
    changed_files: Optional[list[str]] = None,
    diff_text: str = "",
    file_count: int = 0,
    tool_calls: int = 0,
    duration_ms: Optional[int] = None,
    error_message: str = "",
    fix_hint: str = "",
    repo_name: str = "",
) -> str:
    """Build the multi-section markdown analysis from run metadata + the diff. Deterministic."""
    engine = _engine_phrase(engine_label)
    brief = (task_brief or "").strip()
    summary = _dedupe(raw_summary)

    # ---- error / cancelled branches ----
    if status == "error":
        parts = [f"**Build failed** — {engine} hit an error before finishing."]
        if brief:
            parts += ["", "**What you asked**", brief]
        parts += ["", "**What went wrong**", (error_message or "The run ended with an error.").strip()]
        if fix_hint:
            parts.append(fix_hint.strip())
        # A failed run often still produced real work before it died. Dropping it
        # here leaves the user with a bare error and nothing to act on.
        if summary:
            parts += ["", "**What I got before it stopped**", summary]
        parts += [
            "",
            "**What to try next**",
            "- Re-run the turn, or refine the request with more detail.",
            "- Open **View run details** to read the logs.",
        ]
        return "\n".join(parts)

    if status == "cancelled":
        parts = [f"**Build stopped** — this run was cancelled before finishing."]
        if brief:
            parts += ["", "**What you asked**", brief]
        parts += ["", "Start a new turn to pick up where you left off."]
        return "\n".join(parts)

    # ---- done: file analysis ----
    diff_files = _parse_diff_files(diff_text)
    if not diff_files and changed_files:
        diff_files = [
            {"path": p, "status": "changed", "add": 0, "del": 0, "lang": _lang_for(p)}
            for p in changed_files
        ]
    n = len(diff_files)
    total_add = sum(f["add"] for f in diff_files)
    total_del = sum(f["del"] for f in diff_files)
    where = f"a clone of `{repo_name}`" if repo_name else "a temporary workspace"

    # No files changed → a lighter "answered without editing" analysis.
    if n == 0:
        parts = [f"**Build complete** — {engine} answered without changing any files."]
        if brief:
            parts += ["", "**What you asked**", brief]
        parts += ["", "**What I did**", summary or "Completed the request without editing the workspace."]
        return "\n".join(parts)

    paths = [f["path"] for f in diff_files]

    # ---- CHAT mode (no attached repo): a plain, friendly report — NOT a repo/PR narrative. A
    #      regular chat just made file(s) in a temp workspace: there's nothing to PR, "Files changed"
    #      is the wrong frame, and for a renderable file the auto-opened PREVIEW is the deliverable.
    #      Keep it short + clean. (Build-area runs carry a repo_name → the full analysis below.)
    if not repo_name:
        _KIND = {
            "html": "an HTML page", "htm": "an HTML page", "svg": "an SVG image",
            "css": "a stylesheet", "js": "a JavaScript file", "ts": "a TypeScript file",
            "jsx": "a React component", "tsx": "a React component", "py": "a Python script",
            "json": "a JSON file", "yaml": "a YAML file", "yml": "a YAML file",
            "md": "a Markdown doc", "markdown": "a Markdown doc", "txt": "a text file",
            "csv": "a CSV file", "pdf": "a PDF", "png": "an image", "jpg": "an image",
            "jpeg": "an image", "gif": "an image", "webp": "an image",
        }
        _RENDERABLE = {"html", "htm", "svg", "md", "markdown", "pdf", "png", "jpg", "jpeg", "gif", "webp", "csv"}
        renderable = [p for p in paths if _ext(p) in _RENDERABLE]
        if n == 1:
            p = paths[0]
            parts = [f"**Created `{p}`** — {_KIND.get(_ext(p), 'a file')}."]
            if _ext(p) in _RENDERABLE:
                parts += ["", "The preview is open on the right — use **Download** to save it."]
        else:
            parts = [f"**Created {n} files:**", ""]
            parts += [f"- `{p}` — {_KIND.get(_ext(p), 'a file')}" for p in paths[:12]]
            if n > 12:
                parts.append(f"- …and {n - 12} more")
            if renderable:
                parts += ["", f"The preview for `{renderable[0]}` is open on the right — **Download** to save."]
        # The agent's own account of what it made. The repo branch below already keeps it;
        # this branch threw it away, so a chat turn that produced a file left the transcript
        # holding one line of filing metadata and nothing about the thing itself. The next
        # turn reads that transcript, which is why "make another tree" had no tree to go on.
        if summary:
            parts += ["", summary]
        return "\n".join(parts)

    # Headline + lead. (A VibeCode session's diff is cumulative vs the session base, so the file
    # set reflects the session's accumulated changes — avoid claiming "this turn".)
    plural = "file" if n == 1 else "files"
    stat = f" (+{total_add} −{total_del})" if (total_add or total_del) else ""
    head = f"**Build complete** — {engine} changed {n} {plural}{stat}."

    did = (
        f"{engine} ran on {where} and the changes now span {n} {plural}{stat}"
        + (f" using {tool_calls} tool call{'s' if tool_calls != 1 else ''}" if tool_calls else "")
        + (f", finishing in {_fmt_duration(duration_ms)}" if _fmt_duration(duration_ms) else "")
        + "."
    )
    if summary:
        # A one-liner reads best continuing the sentence; anything with its own line structure
        # (a list, several paragraphs) has to start a new block or the markdown collapses into
        # the run stats.
        did += f"\n\n{summary}" if "\n" in summary else f" {summary}"

    # Files changed — explained.
    file_lines = []
    for f in diff_files[:12]:
        st = f["status"]
        cnt = (
            f", +{f['add']}" if st == "new file" and f["add"]
            else f", −{f['del']}" if st == "deleted" and f["del"]
            else f", +{f['add']} −{f['del']}" if (f["add"] or f["del"])
            else ""
        )
        verb = {"new file": "added", "deleted": "deleted", "renamed": "renamed", "modified": "modified"}.get(st, "changed")
        file_lines.append(f"- `{f['path']}` — {verb} ({f['lang']}{cnt})")
    if n > 12:
        file_lines.append(f"- …and {n - 12} more")

    paths = [f["path"] for f in diff_files]
    has_code = any(_ext(p) in _CODE_EXTS and not _TEST_RE.search(p) for p in paths)
    has_test = any(_TEST_RE.search(p) for p in paths)
    only_docs = all(_ext(p) in _DOC_EXTS for p in paths)
    has_del = total_del > 0 or any(f["status"] == "deleted" for f in diff_files)
    all_new = all(f["status"] in ("new file", "changed") for f in diff_files) and not has_del

    # Review notes.
    notes = []
    if all_new:
        notes.append("Low-risk: only new files/lines were added — nothing existing was removed.")
    elif has_del:
        notes.append("This run removed or rewrote existing lines — review the diff carefully before shipping.")
    if only_docs:
        notes.append("Documentation-only change — no code paths were touched.")
    elif has_code and not has_test:
        notes.append("No automated tests were added — consider adding coverage if this grows.")
    notes.append("Review the diff under **View run details**, then **Create PR** to ship it.")

    out = [head, "", "**What you asked**", brief or "_(no prompt recorded)_", "", "**What I did**", did,
           "", "**Files changed**", *file_lines]

    cmd = _test_command(paths)
    if cmd:
        out += ["", "**How to test**", "```bash", cmd, "```"]

    out += ["", "**Review notes**", *[f"- {x}" for x in notes]]
    return "\n".join(out)


# ── Optional AI narrator (Pass 2 — default OFF) ────────────────────────────────────────────────
async def narrate_build_ai(*, deterministic_md: str, task_brief: str, engine_label: str,
                           raw_summary: str, diff_text: str) -> Optional[str]:
    """Ask a model to rewrite the analysis richer (per-file 'why it matters'). Returns None on ANY
    failure → caller keeps the deterministic text. Uses a direct Ollama call (the bg task has no
    Request); point HARVIS_OWUI_BUILD_NARRATOR_AI_MODEL + OLLAMA_URL at a capable model."""
    try:
        import httpx  # local import: only touched when the flag is on
        base = (os.getenv("OLLAMA_URL") or "http://ollama:11434").rstrip("/")
        model = os.getenv("HARVIS_OWUI_BUILD_NARRATOR_AI_MODEL", "llama3.1:8b")
        diff_excerpt = (diff_text or "")[:6000]
        sys_prompt = (
            "You are a senior engineer summarising a completed build run for the developer who "
            "requested it. Write a clear markdown analysis with these sections, in order: a one-line "
            "**Build complete** headline; **What you asked**; **What I did** (explain the work, not "
            "just file names); **Files changed** (a bullet per file with a short plain-English purpose); "
            "**How to test** (a fenced command when there's a runnable entry point); **Review notes** "
            "(risks, missing tests, next steps). Be concise and concrete. Do NOT invent files or claims "
            "not supported by the diff. Output ONLY the markdown."
        )
        user = (
            f"Engine: {engine_label}\n\nRequest:\n{task_brief}\n\n"
            f"Engine's own summary:\n{raw_summary}\n\nUnified diff (may be truncated):\n{diff_excerpt}\n\n"
            f"Here is a deterministic draft to improve (keep its structure, enrich the prose):\n\n{deterministic_md}"
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
            resp = await client.post(
                f"{base}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.4, "num_ctx": 8192, "num_predict": 1200},
                },
            )
            resp.raise_for_status()
            content = ((resp.json() or {}).get("message") or {}).get("content") or ""
        content = content.strip()
        # Guard: only accept a plausibly-complete analysis (has the headline + multiple sections).
        if len(content) > 120 and content.count("**") >= 6:
            return content
        logger.warning("Build narrator AI returned a thin result; using deterministic.")
        return None
    except Exception as exc:
        logger.warning("Build narrator AI failed (%s); using deterministic.", exc)
        return None
