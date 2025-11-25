Great progress. You’ve already built the context pipeline and a dedicated /api/ide/copilot/suggest—that’s the right architecture. Now let’s (1) harden the prompt engineering so models return code‑only, useful, and more frequent ghost completions, and (2) fix the tab bar layout bug that pushes the IDE off‑screen.

Below you’ll get:

Drop‑in prompt builder improvements (system + user messages, stop‑sequences, options)

Cleaner post‑processing for “no apologies, code‑only” + indentation/length control

Trigger heuristics so you don’t call the model when signal is poor (and call more aggressively when signal is strong)

FE context packaging (neighbor files, language)

UI fixes for the “tabs curve left / background shows” bug (Tailwind + CSS)

A master prompt for Claude to implement it end‑to‑end in your repo

1) Prompt engineering: make suggestions accurate, code‑only, and frequent
A. System & user prompt contract (tight + language‑aware)

In ide_ai.py, replace your current system/user builders with this stricter contract (keeps your context window):
# ---- Prompt contract (tight) ----------------------------------------------

SYSTEM_INLINE = (
    "You are a code completion engine for an IDE.\n"
    "TASK: Predict only the next code the user is likely to type.\n"
    "HARD RULES:\n"
    "  - OUTPUT CODE ONLY. No prose. No markdown fences. No apologies.\n"
    "  - Do not repeat existing text in the suffix.\n"
    "  - Respect the language and indentation exactly.\n"
    "  - Prefer short, incremental continuations for inline suggestions.\n"
    "  - If there is not enough signal to continue safely, return nothing.\n"
)

def build_copilot_messages(language: str, safe_path: str,
                           context_window: dict,
                           neighbor_summary: str | None) -> list[dict]:
    # Tight, structured user message:
    user_payload = {
        "file": safe_path,
        "language": language,
        "indentation": context_window["indentation"],
        "before_lines": context_window["before_line_count"],
        "after_lines": context_window["after_line_count"],
        # only small but salient slices
        "prefix": context_window["before"][-2000:],        # budget
        "suffix": context_window["after"][:400],           # guard repetition
        "surrounding": context_window["surrounding_snippet"],
        "neighbors": neighbor_summary or "",
        "instruction": (
            "Return ONLY the characters to insert at the cursor.\n"
            "No backticks or markdown. No commentary. No apologies.\n"
            "If unsure, return empty string."
        ),
    }

    return [
        {"role": "system", "content": SYSTEM_INLINE},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
B. Language‑ & suffix‑aware stop sequences

Stopping early prevents rambling/apologies and keeps results snappy:

# ---- Stop sequences --------------------------------------------------------

def stops_for(language: str, suffix: str) -> list[str]:
    base = ["```", "\n\n\n"]  # break long rambles or fenced output quickly

    # Stop near the suffix to avoid repeating the future
    suffix_hint = suffix[:24].strip()
    if suffix_hint:
        base.append(suffix_hint)

    lang_stops = {
        "python": ["\n\n", "# ", '"""', "'''"],
        "javascript": ["\n\n", "/*", "//"],
        "typescript": ["\n\n", "/*", "//"],
        "go": ["\n\n", "/*", "//"],
        "java": ["\n\n", "/*", "//"],
        "c": ["\n\n", "/*", "//"],
        "cpp": ["\n\n", "/*", "//"],
        "csharp": ["\n\n", "/*", "//"],
        "rust": ["\n\n", "/*", "//"],
        "php": ["\n\n", "/*", "//", "?>"],
        "ruby": ["\n\n", "# "],
        "shell": ["\n\n", "# "],
        "sql": ["\n\n", "-- "],
        "html": ["\n\n", "<!--"],
        "css": ["\n\n"],
        "json": ["\n\n", "}"],
        "yaml": ["\n\n", "- "],
        "markdown": ["\n\n"],
        "plaintext": ["\n\n"],
    }
    return list(dict.fromkeys(base + lang_stops.get(language.lower(), ["\n\n"])))

Pass these into your existing collect_text_from_ollama call (extend it to accept options and include them in both /api/chat and /api/generate payloads).

2) Post‑processing: always return code‑only, well‑formed, not repetitive

Improve clean_copilot_suggestion:

CODEISH_PAT = re.compile(r"[;{}\[\]()=]|^\s*(def|class|return|if|for|while|try|catch|import|from|const|let|var)\b", re.I)

APOLOGY_PAT = re.compile(r"\b(sorry|apolog|as an ai|i can’t|i cannot|i'm unable)\b", re.I)
FENCE_PAT = re.compile(r"^```[\w-]*\s*|\s*```$", re.M)
BACKTICK_PAT = re.compile(r"`{1,3}")

def clean_copilot_suggestion(text: str, language: str = "") -> str:
    if not text:
        return ""

    # strip fences / backticks
    text = FENCE_PAT.sub("", text)
    text = BACKTICK_PAT.sub("", text)

    # drop apologies / prose
    if APOLOGY_PAT.search(text):
        return ""

    # keep only first 'code-ish' paragraph
    parts = [p.strip("\n") for p in text.split("\n\n") if p.strip()]
    for p in parts:
        if CODEISH_PAT.search(p) or language.lower() in ("python","javascript","typescript"):
            text = p
            break

    # trim to a reasonable inline length
    max_chars = int(os.getenv("IDE_INLINE_MAX_CHARS", "240"))
    text = text[:max_chars].rstrip()

    # normalize indentation for multi-line blocks (respect current indentation)
    text = text.replace("\r\n", "\n")

    return text


Optional: truncate to a sane boundary (no half tokens / open quotes):

def truncate_safely(text: str) -> str:
    # stop at end of line or before an obvious break
    for marker in ["\n\n", "\n# ", "\n// ", "\n/*"]:
        i = text.find(marker)
        if i != -1:
            return text[:i]
    return text


Call clean_copilot_suggestion(...) → truncate_safely(...) before returning.

3) Trigger heuristics: call more when signal is strong, less when weak

Front‑end (already logging heuristics). Tighten it:

Call when any is true:

line ends with . -> . in JS/TS, . or : in Python, {/( just typed

prefix contains function signature/incomplete call foo(, def , class , if , for

just typed a dot, ::, ->, or after an equals =

Skip when:

file is empty or whitespace only

you’re in comments/strings (you can cheaply detect by scanning the prefix line)

the last suggestion was just accepted < 1s ago (cooldown)

Debounce idle: 450–700 ms (you’re at 650ms; that’s fine).

Abort previous inflight /suggest with AbortController on each new keystroke to avoid piling up responses.

4) FE context packaging (neighbor files + language)

From the editor:

Send language = model.getLanguageId() (you are).

Buffer slices:

prefix last 2000 chars

suffix first 400 chars

Neighbor files: send the top 2–3 relevant (open tabs / same directory / same module) as {path, snippet} (first ~200 lines or a 2–3 paragraph summary); you already have a placeholder—wire it in now.

5) UI fix: tabs overflow pushes the IDE off‑screen

This is a flex/min-width/overflow issue. Fix the containers so the editor region never “curves left”.

A. Ensure every flex child in the chain has min-width: 0

// e.g., in /ide page layout
<main className="h-full w-full flex flex-col overflow-hidden">
  <div className="flex h-10 items-center border-b min-w-0 overflow-x-auto">
    {/* tabs row */}
  </div>
  <div className="flex-1 min-w-0 flex overflow-hidden">
    {/* left explorer */}
    <aside className="w-64 shrink-0 border-r overflow-auto">…</aside>

    {/* editor + right pane */}
    <section className="flex-1 min-w-0 flex overflow-hidden">
      <div className="flex-1 min-w-0 relative">
        <div id="editor" className="absolute inset-0" />
      </div>
      <div className="w-96 shrink-0 border-l overflow-auto">{/* right tabs */}</div>
    </section>
  </div>
</main>


B. Tab strip styles

<div className="flex h-10 items-center gap-1 overflow-x-auto overscroll-contain min-w-0 flex-shrink-0">
  {/* each tab */}
  <button className="shrink-0 px-3 h-8 rounded hover:bg-neutral-800 whitespace-nowrap">code.py</button>
</div>


Critical pieces: min-w-0 on every flex item that should shrink, overflow-hidden/overflow-x-auto on containers, and avoid flex-shrink-0 on the central editor area (give it flex-1 min-w-0).

C. One CSS affordance (global.css)

/* Ensure flex containers don't expand children beyond viewport */
.vibe-ide-root, .vibe-ide-root * { min-width: 0; }

(You can also add max-w-none to any element that previously used max-w-screen utilities.)

6) Master Prompt for Claude (copy‑paste)

Context
Harvis AI monorepo. Frontend: Next.js 14 + Monaco. Backend: FastAPI. Sessions mounted at /workspace. LLM: Ollama. The inline endpoint is /api/ide/copilot/suggest. We have a context pipeline (build_copilot_context, summarize_neighbor_files, build_copilot_messages, clean_copilot_suggestion) and want better, more frequent code‑only completions. There’s also a UI bug where tabs overflow pushes the IDE off‑screen on the left.

Goals

Improve prompt engineering and post‑processing so ghost suggestions are accurate, code‑only, and frequent (no “I’m sorry” responses).

Add language‑ & suffix‑aware stop sequences and tuned generation options for Ollama.

Tighten FE triggers & neighbor‑file packaging.

Fix the tab strip overflow so the IDE never “curves left”.

Tasks
Backend (FastAPI / ide_ai.py)

Replace the system/user prompt with the strict contract in this spec (OUTPUT CODE ONLY; no fences; no apologies; respect indentation; if unsure return empty).

Implement stops_for(language, suffix) and inline_options(language, suffix), pass options into both /api/chat and /api/generate payloads.

Improve clean_copilot_suggestion to strip fences/apologies, prefer code‑ish paragraphs, limit length, normalize indentation, and truncate safely.

Ensure the endpoint never 503s for ghost; on empty simply return suggestion: "".

Accept optional neighbor_files and include them via summarize_neighbor_files.

Frontend (Next.js / Monaco)

Add AbortController to cancel in‑flight suggest requests on new keystrokes.

Tighten trigger heuristics: call more often after . -> :: ( : =, or after keywords (def, class, if, for, etc.); skip if in comment/string.

Send language from model.getLanguageId(), and short prefix/suffix budgets (e.g., 2k/400).

Pass top 2–3 neighbor files (open tabs / same dir) as {path, snippet}.

Fix tab strip with min-w-0, overflow-x-auto, and ensure central editor area is flex-1 min-w-0 (no flex-shrink-0 on editor).

Ensure theme has a visible editorGhostText.foreground.

Acceptance

Inline suggestions appear more frequently and are code‑only; no apologetic prose.

Suggestions stop before repeating the suffix and respect indentation.

Latency stays low; no request pile‑ups during typing.

IDE tabs no longer push the layout left; the editor remains centered with horizontal tab scrolling.

changes.md updated (timestamp, problem, root cause, solution, files changed, status).

Constraints

Keep all browser calls relative (/api/...), JWT via cookie or header.

Do not break sessions, explorer, terminal, execution, or Interactive mode.

Reuse the existing Ollama client and SSE stream; just extend options.

Quick test commands

Backend:
curl -s -X POST http://localhost:9000/api/ide/copilot/suggest \
  -H 'Content-Type: application/json' \
  --data '{
    "session_id":"x",
    "filepath":"code.py",
    "language":"python",
    "content":"def add(a, b):\n    ",
    "cursor_offset":18
  }' | jq

Expected: { "suggestion": "return a + b", "range": { "start": 18, "end": 18 } }

Frontend:

Type def add(a, b):⏎␠␠ → pause → ghost should show return a + b.

Confirm the tab strip scrolls instead of shrinking the editor off‑screen.

