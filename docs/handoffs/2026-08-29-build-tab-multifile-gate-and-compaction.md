# Handoff — 2026-08-29

Build/Code tab session, continuing from `2026-08-28-vibecode-run-and-preview.md`.
Six defects fixed, all deployed and verified live. **Nothing committed or pushed.**

Headline: **the Build tab now writes a real multi-file project, and refuses to
report success over a page that cannot run.** It also stops leaking one Build
chat's state into another, reads its answers aloud, and shrinks its own context
before a long turn walks into the model's limit.

---

## Where things stand

| Branch | Head | State |
|---|---|---|
| `fixes` | `1124e9d5` | The running stack's checkout. Everything below is uncommitted on top of it. |
| `harvis1.3` | untouched | Still separate from `main` on purpose. |
| `main` | untouched | |

```
 M front_end/owui/src/lib/agent-studio/ArtifactPreview.svelte
 M front_end/owui/src/lib/agent-studio/BuildActions.svelte
 M front_end/owui/src/lib/agent-studio/RunView.svelte
 M front_end/owui/src/lib/apis/agent-runs/index.ts
 M front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte
 M python_back_end/workspace/orchestration/runner.py
 M python_back_end/workspace/orchestration/session_turn.py
 M python_back_end/workspace/orchestration/tools.py
 M python_back_end/workspace/workspace_router.py
?? front_end/owui/src/lib/agent-studio/build/TurnFiles.svelte
?? front_end/owui/src/lib/utils/speakText.ts
?? python_back_end/tests/test_syntax_gate.py
?? python_back_end/workspace/orchestration/syntax_gate.py
```

968 insertions across 9 tracked files, plus 4 new ones. The tree is otherwise
clean — the earlier session's unrelated dirt landed in `1124e9d5`.

---

## 1. The agent writes one giant index.html — fixed

**Symptom:** every build came back as a single 900-line `index.html` with the
styles and the whole game inlined. Unreadable in the editor, unreviewable in the
diff, and one stray brace from taking the page down.

**Cause was one phrase.** `_VIBECODE_SYSTEM_SCRATCH` said the project should be
*"self-contained (inline CSS and JS, or plain sibling files)"*. Models read
"self-contained" as "one file". The real constraint was never one file — the Run
lane is `python3 -u -m http.server 3000` with **no install step**, so sibling
`.css` and `.js` files load over plain HTTP exactly as well as inlined ones. Plain
ES modules work too.

**Fix:** the scratch prompt now asks for the project a person would actually
write — `index.html` for markup, `styles.css` for styling, one or more `.js` files
for behaviour, as siblings at the workspace root — and states the two limits that
genuinely matter: an `index.html` must exist at the root, and the whole thing must
open with no build step and no packages (the sandbox has no internet, so no CDN
either).

`python_back_end/workspace/orchestration/session_turn.py`

---

## 2. The page still didn't run — fixed, with a caveat

Asking for siblings makes this failure **more** likely, not less, which is why
§2 had to ship with §1. A measured `gpt-oss:20b` run wrote a *correct* 240-byte
`index.html` linking `styles.css` and `main.js`, then rewrote that same
`index.html` seven times and never created either sibling. The workspace ended
with `index.html` alone: a page that loads, renders a canvas, and does nothing.
The old monolith at least ran.

Nothing in the stack noticed, because nothing was wrong in any single-file sense.
`index.html` parses. The browser renders it. The 404s are invisible without
devtools.

### The gate

`python_back_end/workspace/orchestration/syntax_gate.py` (new) now covers **two**
independent ways to end up with a dead page, merged into one defect map:

- `check_files()` — a file that cannot be parsed at all (the unclosed IIFE from
  the previous session).
- `check_links()` — a page pointing at a local `<script src>` or stylesheet
  `<link>` that nobody wrote.

Only those two reference kinds are checked, deliberately. A missing script means
none of the program runs; a missing stylesheet means the page is unstyled. **A
missing `<img>` degrades a page that still works**, so failing a build over one
would be the false alarm this module refuses to raise. Remote URLs, protocol-
relative URLs, `data:` URIs, fragments and query-only refs are all skipped. A path
in `known` (collected but not snapshotted — too big, or binary) counts as written.

### The repair loop

`session_turn.py:584`. After every turn the gate runs; if it finds anything, the
turn spends repair rounds on it and nothing else. The loop stops on the first of:

1. the gate comes back clean,
2. a round fails to reduce the defect count,
3. the ceiling is hit — `HARVIS_BUILD_SYNTAX_REPAIR_ROUNDS`, default **1**.

The brief branches on defect kind, because they need opposite instructions: a file
that will not parse is repaired in place with `str_replace`, while a file that was
promised and never written has to actually be created. Telling a model to "find
the unbalanced bracket" in a file that does not exist is how a repair round burns
itself.

If it still fails, the summary says so by name instead of claiming success:

> ⚠ Heads up: index.html (references game.js, which was never written…). The page
> will not work in a browser until that is resolved — I tried 1 time and could
> not. Ask me to try again, or open the files and fix it directly.

**The bug inside the fix, worth remembering.** The first progress guard counted
*broken files*. A page short of two siblings that gets one of them written is
still one broken file — 1 ≥ 1, "no progress", loop stops with the page still dead.
Watched it happen live: round 1 wrote `styles.css`, the guard called it a wash,
the run ended reporting `main.js` missing. The metric now counts **defects**, not
the files reporting them, which meant splitting `missing_refs()` out of
`check_links()` so individual missing targets are countable.

**The ceiling is 1, by your decision** ("auto-repair, capped at 1 retry"). It
shipped at 2 for a round and has been corrected. For the syntax case 1 is plainly
right — a model that cannot close its own brace on the first re-read will not
close it on the third, and the no-progress guard ends that after one round anyway.

The counter-evidence, recorded so raising it later is an informed choice: a
missing file is *additive*, not a fix-in-place. A measured `gpt-oss:20b` run wrote
the `styles.css` it had forgotten on round one and would have written `main.js` on
round two; at a cap of 1 that page loads and does nothing. If forgotten-sibling
repairs start showing up, `HARVIS_BUILD_SYNTAX_REPAIR_ROUNDS=2` is the whole fix —
no code change.

### Also, in-loop

`tools.py` appends a loud imperative suffix to any `edit_file`/`str_replace`
whose result no longer parses. The write itself succeeded (the bytes are on disk),
so it never becomes a tool error — it rides along on the success message. Most
breakage dies here before the gate ever sees it.

### Caveat, stated plainly

The gate proves a page **loads and runs its own code**. It cannot judge whether
the game is any good. `gpt-oss:20b` finished with a 203-byte `game.js` that draws
a white rectangle. That is model capability, not plumbing — Sonnet 5 on the same
prompt produces a real game. The plumbing now guarantees the files exist and the
page is not dead on arrival.

---

## 3. Opening one Build chat took over another — fixed

**Symptom, in your words:** *"i opened a new chat went back to the old one and it
took over the new chat and changed the old one too."*

Two halves, one on each side of the wire.

**Frontend.** `resetSessionView()` now blanks the diff, file tree, open file,
artifacts, verify frames, expanded runs, send error, prompt draft and attached
images **before** the fetch for the new session starts, and `adoptSessionModel()`
picks up the session's own last-used model after it lands (never blanking the
picker if the session has none). The existing reactive on `doneTurns/sessionId/
latestTurnId` refills the panels for whichever session actually finished loading.
Request-id guards drop the responses of a fetch you already navigated away from.

**Backend.** Picking Claude in a session that was created as `native` used to
leave the session's engine untouched, so the next turn ran on the wrong lane.
`_engine_for_model()` + `_engine_runnable()` in `workspace_router.py` reconcile
the session's engine against the selected model at turn start. Verified live:

```
anthropic/claude-sonnet-5  -> claude-code   runnable=True
qwen3:14b                  -> native        runnable=True
openrouter/x/y             -> native        runnable=True
kimi-code/k2               -> kimi-code     runnable=True    (tested BEFORE generic kimi)
moonshot/kimi-k2           -> kimi          runnable=True
hermes/x                   -> hermes-agent  runnable=True
openai/gpt-5               -> codex         runnable=True
```

---

## 4. The Build tab now has the main chat's sound — new

`front_end/owui/src/lib/utils/speakText.ts` (new) plus Copy / Read-aloud buttons
on `BuildActions.svelte`, gated on the answer actually having text.

**Why it needed a new module.** `<audio id="audioElement">` exists only inside
`Chat.svelte:4241`, and `$audioQueue` is instantiated only in that component's
`onMount`. On any other route it is either null or pointing at an element that was
destroyed on navigation — which is why the Build tab had **no** voice rather than
a broken one. `speakText.ts` owns its own hidden `<audio id="harvis-speak-audio">`
and covers all three engine paths (system speech synthesis, browser Kokoro, server
TTS), reading the user's real settings so a voice chosen in Settings is the voice
the Build tab uses.

**Trap:** `console.error` is stripped from the production bundle by esbuild's
`pure` array in `vite.config.ts`. `console.warn` survives — use it for anything
that must be visible in production.

---

## 5. Context compaction inside a turn — new

**Your ask:** *"it needs to be able to compress the context if it goes over the
bar. cause if not there will be context rot."*

`conversation.py` already clipped **prior turns** before a run starts. **Inside** a
turn nothing clipped anything: `runner.py`'s `while steps < max_steps` loop
appended every tool result in full and the message list only ever grew, so a long
build walked its own prompt into the model's limit. What gets dropped at that
point is the provider's choice, and it is usually the head — the system prompt and
the actual task. That is the rot.

`_compact_messages()` in `runner.py` runs **before** each call, because
`last_prompt_tokens` is what *this* message list cost last time and is the only
honest reading of how full the window is about to be. It is mechanical on purpose:
a summarising model call costs another round-trip on a box that is already being
rate-limited, and a summariser can quietly rewrite what the agent did.

- Fires only once the provider's own `prompt_tokens` crosses **70%** of
  `ctx_window` (`HARVIS_BUILD_CTX_COMPACT_AT`), targets **50%**
  (`HARVIS_BUILD_CTX_COMPACT_TO`). Under the bar it is a byte-for-byte no-op.
- **Every message is kept.** Only old *tool results* shrink — that is where
  essentially all the bulk lives. The head of each survives, because "wrote
  index.html" and "exit 0" sit there.
- Indices 0 and 1 (system prompt, task) and the last 4 messages
  (`HARVIS_BUILD_CTX_KEEP_TAIL`) are never touched.
- An old multimodal turn keeps its text and drops its images — the model has
  already reacted to that screenshot, and the data URL is most of the prompt.
- The model is told plainly that detail was dropped, so it re-reads rather than
  assuming the file was short.
- Chars-per-token is calibrated from the provider's own last `prompt_tokens` for
  these exact characters, not a fixed guess — the ratio differs a lot between
  prose, JSON and base64.

`ctx_window` is literally the bar the UI draws (`runner.py:634`, the same number
yielded as `context_window` in the usage event). It is **not per-model**: a cloud
model with a 200k window still compacts at 70% of 24576. Conservative but safe —
it only trims old tool results earlier than strictly needed.

Measured in isolation: no-op under the bar; over it, 3 messages changed and 10,386
chars saved (24,648 → 14,262) with the system prompt, task, every assistant turn
and the last 4 messages byte-identical.

### 5b. The Claude lane compacts itself — but not where the meter said

**Your ask:** *"the claude should hit compaction when recommended … get a read on
how the compact works for claude."*

Claude Code's auto-compact triggers on an **absolute token count**, not a fraction
of the window. Knobs, in precedence order: `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (env,
plain integers), `--autocompact`, `/autocompact 500k`, `autoCompactWindow` in
settings.json. Range 100K–1M. Defaults are **per model**: Sonnet 5 ≈ **967K**
(≈1M native window), while Opus 5 / Opus 4.8 / Sonnet 4.6 / Opus 4.6 default to
**200K**. `/compact [instructions]` is the manual form, and a
`# Compact instructions` heading in CLAUDE.md steers what survives.

Three separate things were tangled up in the reported "1m out of 200k":

1. **The number was wrong.** On the CLI lanes `prompt_tokens` is the run's
   *cumulative billed input*, not window occupancy — it climbs past the window
   forever, and `Math.min(100, …)` turned that into a permanently full red bar.
   Fixed in this same batch: the gauge now reads `usage_detail.context_tokens`
   and falls back to `prompt_tokens` only when it is actually ≤ the window
   (`vibecode/+page.svelte`).
2. **`_compact_messages` correctly never fires here.** Its only caller is inside
   the native `SubAgentRunner.run` loop. On a CLI lane the message list lives
   inside the `claude` process — Harvis has nothing to compact, and the CLI does
   it itself. §5 above is the native lane only.
3. **The real gap: the denominator, not the CLI.** Claude Code's per-model tuned
   defaults *are* the recommendation — Sonnet 5 and Fable 5 have native 1M windows
   and compact at ~967K, Opus 5 / Opus 4.8 / Sonnet 4.6 / Opus 4.6 compact at the
   200K boundary, anything else at its own limit. `_CLAUDE_META` declared **every**
   Claude at `ctx: 200000`, understating those two by 5×. The meter was the broken
   half all along; the CLI had been doing the right thing unprompted.

**Fixed:** Sonnet 5 and Fable 5 now declare `ctx: 1_000_000`, so the gauge divides
by the window the engine actually gives the model. `_build_claude_command`
deliberately pins **nothing** — exporting `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from
Harvis's static table is exactly how a 1M Sonnet ends up compacting at 200K for no
reason. `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` on the sidecar is the supported way to
force the 200K boundary back if that is ever wanted. Kimi keeps its pin and must:
the CLI cannot infer a Kimi window from an Anthropic model id.

An interim version of this fix pinned the window to the catalog number in both
directions. It was wrong for the same reason and was replaced — recorded so it is
not reintroduced as a "consistency" improvement.

**Follow-up, not done here:** the direct-API lane (`/v1/messages`) needs the
`context-1m-2025-08-07` beta header to actually reach 1M on Sonnet — this module
sends only `_ANTHROPIC_VERSION`. Over 200K there Anthropic errors loudly rather
than truncating, so the failure is visible rather than silent, but the bar reads
low until then. Sending the header also opts into the above-200K pricing tier,
which is why it is a decision and not a one-liner.

---

## 6. Verification actually performed

Real backend, real model, real session workspace — no stubs.

| Check | Result |
|---|---|
| Asteroids build, `gpt-oss:20b`, fresh scratch session | gate caught `index.html` short of `styles.css` + `game.js` (weight 2), one repair round wrote both, gate clean, 3 files on disk |
| Forced dead page (`index.html` linking two files it was told not to write) | gate fired, repair round created both, summary replaced with the repair narrative |
| Progress guard | defect weight 2 → 1 now counts as progress; the file-count version stopped here with the page dead |
| `tests/test_syntax_gate.py` | **33 passed** (8 new for the link gate) |
| `+ tests/test_chat_history_reaches_lanes.py` | **44 passed** |
| Model → engine routing | 7 model shapes, all resolve to a runnable lane (table in §3) |
| In-turn compaction | no-op under the bar; over it, head/tail/assistant turns byte-identical |
| Deployed bundle | contains "Read aloud" and `harvis-speak-audio` |

Test workspaces created under `/data/artifacts/harvis-vibecode-sessions/` were
removed afterwards.

---

## 7. Found while working, NOT fixed

1. **`Reached step limit (N)` is a lie about half the time.**
   `runner.py:1210` uses that string as the fallback for *any* loop exit without a
   summary — including the identical-call guard firing. A run that stopped at step
   6 of 12 because the model rewrote the same file five times reports "step
   limit", which points at the wrong cause. The comment two lines above shows the
   author knew; the message just never got split. Cosmetic, but it cost a detour
   during this session's debugging.

2. **`saveControls()` in `Chat.svelte`** writes `params`/`chatFiles` to the raw
   `$chatId` with no ownership check — the same shape as the chat-swap bug fixed
   in §3, on a different surface. Not raised with the user yet.

3. **A test harness trap that wasted a run.** A Build session workspace **must**
   be created with `create_or_attach_session_workspace()`, not `mkdir`.
   `WorkspaceIsolationManager` defaults to `isolation_mode="scratch"` (baseline
   snapshot), but a session run constructs it with `isolation_mode="session"`,
   which takes the **git** path: `git add -A` in a non-git directory fails
   silently, `collect_changed_files` returns `[]`, and the entire diff/artifact/
   gate pipeline is dead with no error anywhere. Two runs looked like "the gate
   never fired" before this was the answer.

---

## 8. Next steps

1. **The click-through, which needs your login.** Build/Code tab on the Docker
   host → build an Asteroids game → press **Run** → play it. Then switch to
   another Build chat and back, and confirm the diff, file tree, editor and
   composer all follow the chat instead of bleeding across. Also press **Read
   aloud** on a Build answer.
2. **Then decide what to commit.** This is a coherent block — the gate, the
   multi-file prompt, the session isolation, the sound, the compaction — but it
   still wants grouping rather than one commit. Standing rule: no push until you
   verify E2E, then ask.
3. Optional: split the misleading step-limit message (§7.1) and the
   `saveControls()` ownership check (§7.2) into their own small fixes.

## 9. Carried over, still open

- Three dead files staged as deleted but uncommitted: `McpShop.svelte`,
  `McpWizard.svelte`, `plugins/mcp/routes.py` — splitting them out of `99596cda`
  needs `git reset`, which is off-limits.
- The HTTPS single-port change.
- Wiring MCP tools into plain chat.
- Uncommenting `NODE_OPTIONS` in `front_end/owui/Dockerfile:31`.
- `screenshot_preview` offered while `HARVIS_VISION_SELF_CHECK_ENABLED=false`.
- Moving the 429 response-body logging into the retry branch in
  `model_router._post_with_backoff` (deferred by you earlier).
- CAD remains explicitly set aside.

## 10. Deploy mechanics

All from the main checkout (branch `fixes`), **not** the worktree.

- `python_back_end/workspace` is bind-mounted → `docker compose restart backend`.
- An **env** change needs `docker compose up -d backend`; a plain restart will not
  pick it up.
- owui → `npm run build` in `front_end/owui/`, then
  `docker compose restart nginx`.
- `python_back_end/tests` is **not** bind-mounted — `docker cp` it in before
  running pytest, or you are testing the image's stale copy.
