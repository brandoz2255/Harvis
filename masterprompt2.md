wesome — here’s a build plan you can follow today and a copy‑paste master prompt for Claude that tells it to actually code the Copilot features (inline suggestions + propose/compare/accept/merge) inside your /ide page, using your Harvis AI stack and conventions.

🔨 What we’re building (concise)

AI → Propose changes for the current file/selection

Backend generates a draft (or unified diff) with an LLM.

Frontend opens a Monaco DiffEditor: Left = your file, Right = AI draft.

Buttons: Accept, Reject, Merge (per hunk) → write to /workspace.

Inline ghost suggestions in Monaco

On idle pause or Ctrl/Cmd+Space, call backend for a suggestion.

Render faded ghost text; Tab accepts, Esc dismisses.

Assistant (right pane) reuses home chat’s file-attachment model

Can trigger “Propose changes” or “Insert snippet (draft first)”.

Uses your Ollama compat (chat → fallback generate), streams via SSE.

Everything must use relative /api/... calls, JWT (cookie or header), and remain backwards-compatible with your working sessions, explorer, terminal, multi‑language exec, and “Interactive On”.

🧭 Plan of action (step‑by‑step)
Phase 1 — Backend (FastAPI)

A. Contracts (new under /api/ide/*)

POST /api/ide/diff/propose
Body: { session_id, filepath, base_content?, selection?, instructions, mode?: "draft"|"unified_diff" }
Returns: { draft_content|null, diff|null, stats: {lines_added,lines_removed,hunks}, base_etag }

POST /api/ide/diff/apply
Body: { session_id, filepath, base_etag, draft_content }
Returns: { saved:true, updated_at, new_etag } or 409 { conflict:true, current_etag, current_content }

(Optional for inline) POST /api/ide/copilot/suggest
Body: { session_id, filepath, language, content, cursor_offset }
Returns: { suggestion, range:{start,end} }

B. Core helpers

ETag utility: hash file contents (e.g., SHA256) to do optimistic concurrency on apply.

Path guard: reject .. / absolute paths; only operate under /workspace.

Ollama compat: try /api/chat; if 404, fallback to /api/generate; always stream SSE to FE.

Neighbor context (optional): include a few small related files.

C. Skeleton (drop‑in)

# api/ide_diff.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import hashlib, os, time

router = APIRouter(prefix="/api/ide")

WORKSPACE = "/workspace"

def sanitize_path(path: str) -> str:
    if path.startswith("/") or ".." in path:
        raise HTTPException(400, "Invalid path")
    return os.path.join(WORKSPACE, path)

def etag_of(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

class Selection(BaseModel):
    start: int
    end: int
    text: Optional[str] = None

class ProposeIn(BaseModel):
    session_id: str
    filepath: str
    base_content: Optional[str] = None
    selection: Optional[Selection] = None
    instructions: str
    mode: Optional[str] = "draft"

class ProposeOut(BaseModel):
    draft_content: Optional[str] = None
    diff: Optional[str] = None
    stats: Dict[str, int] = {"lines_added":0,"lines_removed":0,"hunks":0}
    base_etag: str

class ApplyIn(BaseModel):
    session_id: str
    filepath: str
    base_etag: str
    draft_content: str

@router.post("/diff/propose", response_model=ProposeOut)
async def propose(body: ProposeIn, user=Depends(get_current_user)):
    target = sanitize_path(body.filepath)
    if body.base_content is None:
        try:
            with open(target, "r", encoding="utf-8") as f:
                base = f.read()
        except FileNotFoundError:
            base = ""
    else:
        base = body.base_content
    base_etag = etag_of(base)

    # Build prompt/context for LLM
    context = {
        "filepath": body.filepath,
        "base": base,
        "selection": body.selection.dict() if body.selection else None,
        "instructions": body.instructions,
        "mode": body.mode or "draft",
    }
    # Call Ollama via compat (prefer /api/chat; fallback /api/generate)
    draft_content, diff, stats = await llm_propose_change(context)

    return ProposeOut(
        draft_content=draft_content,
        diff=diff,
        stats=stats or {"lines_added":0,"lines_removed":0,"hunks":0},
        base_etag=base_etag,
    )

@router.post("/diff/apply")
async def apply(body: ApplyIn, user=Depends(get_current_user)):
    target = sanitize_path(body.filepath)
    current = ""
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as f:
            current = f.read()
    if etag_of(current) != body.base_etag:
        return {"conflict": True, "current_etag": etag_of(current), "current_content": current}

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(body.draft_content)
    return {"saved": True, "updated_at": int(time.time()), "new_etag": etag_of(body.draft_content)}

Wire get_current_user to your existing JWT dependency (cookie or header). Implement llm_propose_change(context) using your Ollama compat function (you already sketched this earlier for /api/chat → /api/generate fallback).

D. Optional inline suggestions endpoint

class SuggestIn(BaseModel):
    session_id: str
    filepath: str
    language: str
    content: str
    cursor_offset: int

class SuggestOut(BaseModel):
    suggestion: str
    range: Dict[str,int]  # {start, end}

@router.post("/copilot/suggest", response_model=SuggestOut)
async def suggest(body: SuggestIn, user=Depends(get_current_user)):
    # Build a compact prompt from content around cursor + file header/context
    suggestion, start, end = await llm_suggest_inline(body)
    return {"suggestion": suggestion, "range": {"start": start, "end": end}}


vPhase 2 — Frontend (Next.js + Monaco)

A. “AI → Propose changes…” action

// call from command palette / context menu
async function proposeChanges({ sessionId, filepath, selection, instructions }: {
  sessionId: string; filepath: string;
  selection?: { start:number; end:number; text?:string };
  instructions: string;
}) {
  const res = await fetch("/api/ide/diff/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ session_id: sessionId, filepath, selection, instructions, mode: "draft" }),
  });
  const data = await res.json();
  openDiffViewer({
    filepath,
    baseEtag: data.base_etag,
    leftText: getCurrentEditorText(), // your current buffer
    rightText: data.draft_content ?? applyUnifiedDiff(getCurrentEditorText(), data.diff),
    stats: data.stats
  });
}
B. Diff viewer (Monaco DiffEditor)
|
import * as monaco from "monaco-editor";

let diffEditor: monaco.editor.IStandaloneDiffEditor | null = null;

function openDiffViewer({ filepath, baseEtag, leftText, rightText, stats }:{
  filepath:string; baseEtag:string; leftText:string; rightText:string; stats:any
}) {
  // render toolbar + stats (+X -Y, hunks)
  diffEditor = monaco.editor.createDiffEditor(document.getElementById("diff-pane")!, {
    readOnly: false,
    renderSideBySide: true,
    automaticLayout: true,
    originalEditable: false,
  });
  const originalModel = monaco.editor.createModel(leftText, undefined, monaco.Uri.parse(`file:///${filepath}`));
  const modifiedModel = monaco.editor.createModel(rightText, undefined, monaco.Uri.parse(`file:///${filepath}.draft`));
  diffEditor.setModel({ original: originalModel, modified: modifiedModel });

  // Wire toolbar
  (document.getElementById("acceptAllBtn")!).onclick = async () => {
    const merged = diffEditor!.getModel()!.modified.getValue();
    const res = await fetch("/api/ide/diff/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ session_id: currentSessionId, filepath, base_etag: baseEtag, draft_content: merged }),
    });
    const data = await res.json();
    if (data.conflict) {
      // show conflict dialog; offer re-propose with latest content
      showConflictDialog(data);
      return;
    }
    // refresh main editor buffer with merged result
    replaceActiveEditorBuffer(filepath, merged);
    closeDiffViewer();
  };

  (document.getElementById("rejectBtn")!).onclick = () => closeDiffViewer();

  (document.getElementById("mergeBtn")!).onclick = () => {
    // per-hunk accept is built into DiffEditor via inline commands; user resolves then clicks Accept All
  };
}

C. Inline ghost suggestions (Monaco)

// If your monaco version supports inline completions:
monaco.languages.registerInlineCompletionsProvider("typescript", {
  async provideInlineCompletions(model, position, context, token) {
    const content = model.getValue();
    const offset = model.getOffsetAt(position);
    const res = await fetch("/api/ide/copilot/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        session_id: currentSessionId,
        filepath: currentFilePath,
        language: "typescript",
        content,
        cursor_offset: offset
      }),
    });
    const data = await res.json();
    const start = model.getPositionAt(data.range.start);
    const end   = model.getPositionAt(data.range.end);
    return {
      items: [{
        insertText: data.suggestion,
        range: new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column),
      }]
    };
  },
  freeInlineCompletions() {}
});

// Fallback (older monaco): render “ghost” via a decoration and accept on Tab (custom)

Make sure your global keybindings use Tab to accept and Esc to dismiss your ghost.

D. Assistant (right pane)
Reuse your home chat component; ensure calls are /api/ide/chat/send/stream with credentials:"include". Add quick actions on a message: Propose changes → calls proposeChanges(...) with prefilled instructions; Insert snippet → stage in a draft buffer first.

Phase 3 — Validation

npm run type-check and npm run dev (frontend).

Exercise flows: Propose → Diff → Accept/Reject/Merge; inline ghost suggestion accept with Tab; Assistant triggers propose.

Confirm no regressions in sessions, explorer, terminal, multi‑language execution, “Interactive On”.

Confirm all calls are /api/... and auth works via cookie or header; SSE streaming stable.

🧩 MASTER PROMPT FOR CLAUDE (copy‑paste)

System / Context
You are coding in the Harvis AI monorepo.
Stack: Next.js 14 (App Router) + Tailwind + Monaco + xterm.js (frontend), FastAPI (backend), PostgreSQL, Docker sessions (workspace at /workspace), Nginx proxy at http://localhost:9000, Ollama as local LLM (with /api/chat → fallback to /api/generate).
Rules: All browser calls use relative paths /api/...; backend handles JWT via Authorization: Bearer or access_token cookie. Do not break existing sessions, explorer, terminal, multi‑language execution, or “Interactive On”. Do not add heavy new Dockerfiles.

Goal
Implement a Copilot-style experience in /ide:

AI → Propose changes for the active file/selection and open a Monaco DiffEditor with Accept / Reject / Merge.

Inline ghost suggestions in Monaco (accept with Tab, dismiss with Esc).

Assistant (right pane) reusing the home chat file-attachment model that can trigger proposals or insert snippets.

Deliverables

Backend (FastAPI):

POST /api/ide/diff/propose and POST /api/ide/diff/apply with path sanitization (only under /workspace) and ETag (SHA256) optimistic concurrency.

(Optional) POST /api/ide/copilot/suggest for ghost suggestions.

LLM compat: use Ollama; try /api/chat, fallback to /api/generate, stream via SSE (text/event-stream).

Mirror home chat as /api/ide/chat/send (+ /stream) keeping the same messages+attachments schema.

Frontend (Next.js):

Command palette + editor context menu: AI → Propose changes… (with optional selection).

Monaco DiffEditor: Left=current file (read-only), Right=draft; toolbar Accept / Reject / Merge (per hunk).

Wire apply to write accepted content and refresh the main editor; handle 409 conflict gracefully with “Rebase Draft”.

InlineCompletionProvider (or decoration fallback) to render ghost suggestions, Tab accept, Esc dismiss.

Assistant tab reusing home chat UI; quick actions Propose changes and Insert snippet (draft-first).

Constraints

All fetches are relative and include credentials:"include".

Keep terminal/websocket and /api/vibecode/* endpoints intact.

Path guard: reject .. and absolute paths; only touch /workspace.

Update front_end/jfrontend/changes.md with timestamp, problem, root cause, solution, files, status.

Acceptance Criteria

From the editor, I can request AI → Propose changes, see a side-by-side diff, and Accept / Reject / Merge. Accepted changes persist to /workspace.

Inline ghost suggestions appear on idle/shortcut and accept with Tab.

The Assistant reuses the home chat file-attachment model and can trigger proposals/snippets.

No regressions in sessions, explorer, terminal, execution, or “Interactive On”.

All /api/... calls succeed with JWT (cookie or header); SSE streams; Ollama compat works.

Now implement the above: create/modify backend endpoints, FE components, and wiring as needed, keeping code idiomatic for this repo and updating changes.md.

make sure it can do an npm run build successfully and also make sure theres no messed up imported modules that might effect the backend 

DO NOT MESS WITH DOCKER TOO MUCH