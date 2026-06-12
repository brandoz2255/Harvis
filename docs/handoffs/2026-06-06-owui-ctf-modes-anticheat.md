# Handoff — OWUI: live-stream card, CTF routing, mode toggle, hash anti-cheat (2026-06-06)

Branch `harvis1.1`. Everything below is **shipped to the running stack (:9000) and verified**,
but **uncommitted** (standing rule: no commit/push until the user asks). All work is on the
OWUI-on-Harvis facade. Deploy flow recap at the bottom.

## What shipped today (in order)

### 1. Live thinking-stream run card — `WorkspaceRunCard.svelte`
The card jumped straight from "starting" to final output. Now it renders a **live feed**:
`handle()` rewritten to populate a `steps[]` model — `token`→accumulating thinking text,
`tool_call`→a running tool entry (spinner→✓/✗ + output), `log`→executor parse + narrative;
`afterUpdate` auto-scroll. Header shows an **`OpenClaw` executor chip** (parsed from the
"Connected to OpenClaw gateway" log) + model. Tool output is the **clean `[exec]` text**, not
the raw `{'content':[…]}` envelope. Feed stays visible on `done` with the summary below.
**Gotcha:** OWUI HTTP-caches `index.html` — a plain navigate can serve a stale bundle;
`location.reload()` pulls the new one (it is NOT a service worker).

### 2. Removed the top web-search button — `Navbar.svelte`
Deleted the `Web Research` globe toggle (kept Agent Mode + Voice). Deep-research magnifying
glass in the `+` menu still works (shares `researchEnabled`).

### 3. Web search verified working
Direct OpenClaw test: model calls `web_search`, gets real results, answers **with a source URL**.
⚠️ **Caveat:** one query returned a stale version ("Python 3.11.0") — reasoning-override
(model trusting training over retrieved evidence), the same lever from the OWASP-MCQ saga.
Plumbing is fine; accuracy depends on the model weighting sources over priors.

### 4. Cookbook "Installed models" tab — `Cookbook.svelte` + `cookbook/router.py` + `apis/cookbook/index.ts`
New tab beside Recommend: lists what's actually pulled into the selected node's Ollama
(`GET /api/cookbook/installed` → proxies Ollama `/api/tags`), with params/quant/family/size +
a **`Use`** button (sets `sessionStorage.selectedModels` → opens with new chats; shows `active`).
Per-node (main-host / rig). Verified: 11 installed models listed, Use→active works.

### 5. Stop button actually cancels everything — `openclaw_client.py` + `WorkspaceRunCard.svelte`
- **Frontend `stop()`**: now `controller.abort()` + flips card to `cancelled` **instantly**.
- **Backend `cancel()`**: was only closing the WebSocket (detaches Harvis, OpenClaw keeps
  generating server-side). Now sends **`sessions.abort` + `chat.abort`** RPCs to the gateway
  *before* closing. Fixed a race (stream cleanup nulled `self._ws`) by passing a **captured ws
  ref** to `_abort_then_close(ws)`/`_send_abort(ws)`. Verified: cancel→stop latency 0.01s,
  both abort RPCs fire, OpenClaw logs "embedded abort settle".

### 6. Two-gemma differentiation — `main.py`
`displayName` used `model_name.split(':')[0]` → `gemma4:e4b` and `gemma4:e2b` both collapsed to
"gemma4 (Ollama)". Added `_pretty_ollama_name()` — keeps the variant tag, drops only redundant
`:latest`. Applied to all 3 label sites (Ollama / Desktop 5080 / Cloud). Verified in the picker:
`gemma4:e4b (Ollama)` vs `gemma4:e2b (Ollama)`. General (no hardcoded names).

### 7. ★ CTF tasks now reliably launch the workspace (the big one) — `task_detector.py` + `workspace_bridge.py`
**Symptom:** "crack this MD5 hash…" either (a) went to **plain chat** where the model refused
("I'm a text AI…"), or (b) launched a workspace that **narrated/fabricated** an answer (claimed
`0d107d… → "hello"`, wrong) with **0 tool calls**.
**Two root causes, both fixed:**
- The detector is **LLM-based** and returned `should_suggest=False` for *every* hash/decode/
  crypto message → fell through to chat. **Fix:** `_ctf_override()` in `task_detector.py` — a
  deterministic pattern (hash hex 32/40/64, OR `crack|decode|decrypt…` intent + an
  encoding/cipher keyword) forces `should_suggest=True, confidence=1.0`. Fires *before* the LLM
  classifier. Verified: 5 CTF prompt types fire; "crack a joke" + normal questions don't.
  This is **TASK** detection (workspace vs chat), not model routing — respects the no-keyword-
  model-routing rule.
- The bridge passed the detector's **paraphrase** ("Find the MD5 hash values…") as the brief,
  stripping the literal hashes the cracking hint scans for. **Fix:** `workspace_bridge.py` now
  passes the **raw user message** as the brief (`_resolve_task_brief(message, history)`).
**Verified end-to-end:** `dragon`/`monkey` (which failed before) now crack via `crack_all.py`,
wordlist-verified. Benefits the native/Discord path too (shared detector).

### 8. Auto/Chat/Agent mode toggle by the Send button — `MessageInput.svelte` + `Chat.svelte` + `stores/index.ts` + `workspace_bridge.py`
3-state pill (default **Auto**): **Chat** = force fast (never launch workspace), **Agent** =
force the workspace tool-loop. Persisted in localStorage. Rides on the chat request as
`harvis_mode`; the facade honors it (`'chat'`→return None, `'agent'`→forced suggestion,
`'auto'`→detector). Verified: Agent forced "what is 2+2" into a workspace; Chat forced a hash
into plain chat. (Toggle is `tabindex=-1` + blurs on click so Enter doesn't cycle it.)

### 9. Hash-crack anti-cheat — `workspace_router.py` `_validate_hash_claims`
Audited 3 cheat vectors: (A) **no answer-key file** — only `cracker.py` (hashlib compute) +
SecLists wordlists; (B) context-echo — guarded; (C) **memorization** — was a phrase-gated gap.
**Fix:** added a **phrase-independent zero-tool guard** — if `executing_tool_call_count == 0`
but the summary contains any string that hashes to a target, suppress it ("recalled from
training, not cracked — must run the cracker or a web search"). `web_search` counts as a real
tool (NOT in `_RETRIEVAL_ONLY_TOOLS`); pure `memory_search`/`sessions_history` lookups don't.
Verified: 6/6 anti-cheat cases + 25/25 existing validator tests.

## Files in flight (today's edits within the 21 modified on `harvis1.1`)
- `python_back_end/workspace/task_detector.py` — CTF override (#7)
- `python_back_end/owui_compat/workspace_bridge.py` — raw brief + `harvis_mode` (#7, #8)
- `python_back_end/workspace/workspace_router.py` — anti-cheat zero-tool guard (#9)
- `python_back_end/workspace/openclaw_client.py` — sessions.abort/chat.abort cancel (#5)
- `python_back_end/main.py` — `_pretty_ollama_name` (#6)
- `python_back_end/cookbook/router.py` — `/installed` endpoint (#4)
- `front_end/owui/src/lib/components/chat/Messages/WorkspaceRunCard.svelte` — live stream + stop() (#1, #5)
- `front_end/owui/src/lib/components/chat/Navbar.svelte` — remove web-search button (#2)
- `front_end/owui/src/lib/agent-studio/Cookbook.svelte` + `lib/apis/cookbook/index.ts` — Installed tab (#4)
- `front_end/owui/src/lib/components/chat/MessageInput.svelte` + `Chat.svelte` + `lib/stores/index.ts` — mode toggle (#8)
(+ the prior uncommitted pile from earlier sessions: Cookbook multi-device/GGUF/Odysseus table,
the `agent_id="main"` OpenClaw routing flip, Agent Studio surfaces, etc. — all on `harvis1.1`.)

## Deploy flow (when iterating)
- **Backend** (bind-mounted: `main.py`, `workspace/`, `owui_compat/`* , `cookbook/`): edit →
  `docker restart harvis-backend`. (*owui_compat is in the image but the running file showed
  edits live — restart picks them up.)
- **Frontend**: edit MAIN `front_end/owui/src` → `rsync -a MAIN/src/ WT/src/` (worktree
  `serene-driscoll-79137f`) → `(cd WT && npm run build)` → `rsync -a --delete WT/build/ MAIN/build/`
  → `docker restart nginx-proxy`. Hard-reload the browser (index.html cache).

## Open items / possible next steps
1. **Land the checkpoint commit** — offered repeatedly, deferred each time. The pile is large +
   fully verified. No push (standing rule); a local checkpoint on `harvis1.1` is overdue.
2. **Web-search freshness** (#3) — model anchors on training over retrieved sources. Same
   reasoning-override lever; fix is prompt/model-side, not backend.
3. **Anti-cheat hardening (optional)** — current guard requires ≥1 executing tool. A model could
   run a dummy `exec` (pwd) then state a memorized answer. Stronger: require the plaintext to
   appear in a **tool_result** (tool-receipts), not just the summary. Beyond the user's stated
   "at minimum a tool call" bar.
4. **Agent Studio visual polish** (task #71, still pending) — the one open task.
5. **gemma4:e4b is the current chat default** — I set it via the Installed-tab "Use" test. The
   workspace path uses `auto` regardless, but plain chat now defaults to gemma4:e4b (which
   refuses CTF in Chat mode — expected). Reset the default model if undesired.

## Verification summary (all green today)
exec/file/web_search workspace tasks · cancel (0.01s + abort RPCs) · two-gemma picker labels ·
CTF detection (5/5 fire, 2 controls don't) · live hash crack (dragon/monkey via cracker.py) ·
Agent/Chat toggle both directions · anti-cheat (6/6 + 25/25 regression).
