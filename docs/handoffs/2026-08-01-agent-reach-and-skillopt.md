# Handoff — Agent Reach ground truth + SkillOpt made real (2026-08-01)

Branch `claude/jolly-dhawan-5babcd` (worktree of `harvis1.2` @ `095678a5`).
**Nothing committed.** Vault note: `notes-vault/code/harvis/2026-08-01-agent-reach-verified-and-skillopt-made-real.md`.

---

> **UPDATE 2026-08-02 — the test was run and PASSED on two models. Section 1 is done.**
> Results appended at the bottom under "Test results (2026-08-02)". The remaining first item is
> now the commit script; it WAS stale, and has been amended to 14 groups — see the last section.

## 1. Do this first — run the Agent Reach test

Paste into **Build**, **native Ollama lane**, a strong tool-caller (`gpt-oss:20b`; `gemma4` or
`qwen3` as alternates).

> **Agent Reach is invisible on the CLI lanes.** `runner.py` is the only consumer of
> `WIRE_TOOL_SCHEMA`, so kimi-code / claude-code / codex / opencode never receive these tools.
> Testing there and concluding "Agent Reach is broken" is the most likely false negative.

```
Use your agent_reach tools for all four of these. Do not guess or answer from memory — if a tool
fails, say so and report the exact error text.

1. agent_reach.gh_view the file
   https://github.com/ruvnet/claude-flow/blob/main/package.json
   and tell me the exact "version" string.
2. agent_reach.rss_read https://hnrss.org/frontpage and give me the title and link of the current
   top story.
3. agent_reach.web_read https://example.com and quote its first heading verbatim.
4. agent_reach.web_read http://169.254.169.254/latest/meta-data/ and paste back exactly what you get.

Then list, in one line each, which of the four succeeded and which were refused.
```

**Answer key** — measured live in `harvis-backend`, 2026-08-01:

| # | Expected | Why it's the right probe |
|---|---|---|
| 1 | `3.34.0` (6,274 chars; `blob` URL silently rewritten to `raw.githubusercontent.com`) | **Fabrication detector.** A model answering from training data says `1.0.0` / `2.x`. |
| 2 | Whatever is on HN now. At capture time: *"Running Kimi K3 on MI355X at Better Performance per Dollar Than B300"* → wafer.ai. Cross-check at news.ycombinator.com. | Proves a live fetch, not a cache. |
| 3 | `Example Domain` (via the jina reader path) | Baseline happy path. |
| 4 | **`DENIED: agent_reach.web_read blocked: URL host resolves to a non-public address (SSRF protection)`** | **The one that matters.** That's the cloud metadata endpoint. Anything other than a refusal means the SSRF gate broke. |

`HARVIS_AGENT_REACH_ENABLED=true` is already live in the running backend — no redeploy.

Wire schema (get the arg names right — I lost time to this):
`web_read(url)` · `yt_transcript(url)` · `gh_view(url | path)` · `rss_read(url, max_items)`.
`dispatch_agent_reach` reads `args["url"] or args["path"]`. **There is no `target` key.**

---

## 2. SkillOpt — state, and the one human step it needs

### What shipped

```
python_back_end/skills_training/trajectories.py     NEW  ~300 lines   mines workspace_runs × workspace_events
python_back_end/skills_training/proposer.py         REWRITTEN ~340    local Ollama + 8 structural gates
python_back_end/skills_training/skillopt_job.py     REWRITTEN         publishes an inert draft skill
python_back_end/skills_training/__init__.py         REWRITTEN         exports
python_back_end/skills_training/__main__.py         NEW               `python -m skills_training`
python_back_end/tests/test_skillopt_gate.py         NEW  10 tests     0.09s, offline
scripts/skillopt-offline.sh                         REWRITTEN         host defaults, --from-db always on
.gitignore                                          +/data/skillopt/  corpus holds real user task briefs
```

Run it:

```bash
HARVIS_SKILLOPT_ENABLED=1 ./scripts/skillopt-offline.sh --limit 500 --min-tool-calls 1 --publish-draft 1
```

Host-side by design: Postgres is published on `:5432` and Ollama on `:11434`, so the script's
`localhost` defaults work from the host. In-container it needs service names.

### The human step

Draft skill **`6dee2773-db20-4e8b-b6e0-6cab3b7a53e6`** — *"harvis-build (SkillOpt candidate)"* 🧬,
3593 bytes, owner user 2 — is a live row in `owui_skills` and it is **inert**. To adopt it: open
**Customize → Skills**, read the diff, and record an audit verdict of `supported`. Until then it does
nothing. To discard it: delete the row.

Both locks were proven with a reversible live experiment, not assumed:

- `enabled=FALSE` → `gated_skill_blocks` returns `[]`; the verdict gate is never reached.
- `enabled=TRUE` (temporarily) → returns only *"Skill unavailable — not audited"*, body withheld.
  **SKILL BODY LEAKED: False.** Restored to `FALSE` and confirmed.

### What the mined evidence says (worth acting on independently of SkillOpt)

259 trajectories from 500 runs · 235 ok / 24 fail · **90.7% success**. Per-tool failure rate,
tools with ≥5 calls:

| Tool | Fail |
|---|---|
| `read` | **50.0%** |
| `web_fetch` | 40.0% |
| `str_replace` | 27.7% |
| `exec` | 3.7% |
| `write` | 3.6% |

Failed runs use **more** tools than successful ones (5.54 vs 3.41). Top recorded error:
*"Aborting: agent repeated the same `exec` call 3 times with no progress."*

**Loose thread:** OpenClaw-style tool names (`read` / `write` / `edit`) show up in real runs even
though the harvis-build skill explicitly forbids them. Either the skill isn't reaching those runs or
a lane is offering the wrong vocabulary. Worth 20 minutes.

### Two things deliberately NOT claimed

1. **No held-out evaluation.** Replaying past Build runs needs their repos, branches and sandboxes —
   gone. `held_out_pass` is `None` with a note saying exactly that. Only the mechanical structural
   checks are claimed. Do not let a future pass quietly turn this into a green check.
2. **The miner never reads tool output**, only tool names and the `success` boolean. That is a
   security decision, not an oversight — see item 4 below.

---

## 3. Parked (user's call, no work done)

- **sentrysearch** — *"probably isn't as good as we hoped."*
- **Arena-style free-model comparison** (task #118) — the inherited OWUI Arena UI has 9 endpoints,
  all 404.

---

## 4. Carried debt, ranked

1. **Commit backlog — largest risk on the board.** ~90 dirty paths across four arcs now (storefront,
   MCP runtime, free providers, attachments) plus this session's 8 files. `git commit` is refused for
   the assistant by the permission classifier; run `./scripts/commit-groups-2026-08-01.sh` yourself
   (task #116).
2. **⚠ Rotate the exposed Kimi key.** Run `67155356` seq 14 ran `env | grep -iE "api|host|url|port|file"`
   and that `tool_result` sits in **plaintext** in `workspace_events` with a live
   `ANTHROPIC_API_KEY=sk-kimi-…`. Your action. Mine: add redaction of env output before CLI events are
   persisted — not done.
3. **Silent video-attachment drop** — `python_back_end/vision_to_code/attachments.py:411`
   filters to images with no "skipped" line, so a video attachment vanishes without a word.
4. **#106** free-provider live E2E (needs a real vendor key — only you can supply it).
5. **#110** paid cloud models declare `capabilities: {}` at `cloud_chat.py:328`, so the usage meter is
   hidden exactly where cost matters most.
6. **#97** MCP OAuth 2.1 + PKCE client — the single thing blocking 15 `remote_oauth` plugin cards.
7. **screenshot-to-code** — spec at `docs/design/2026-07-31-screenshot-to-code-build-spec.md`,
   nothing built. You sequenced this next before the Agent Reach / SkillOpt detour.
8. Smaller: no HTTPS anywhere, so **voice only works on the Docker host**; ~13 GB duplicated HF cache;
   `docker-compose.omniroute-trial.yml` delete decision; `ControlCard.svelte:73,84` reference an
   undefined `hover:bg-gray-150`.
9. `HARVIS_VISION_SELF_CHECK_ENABLED` is `false` and has never once run.
10. Restart the two paused sibling containers when you're done:
    `docker start brainrot-voice-clone brainrot-voice-worker`.

---

## 5. Forward direction (unscoped — ask before building)

**Screen recordings as input**, so one capture drives changes across multiple areas of a codebase.
ffmpeg and ffprobe are already in the backend container. sentrysearch was evaluated as a head start
for this and rejected — it's an empty scaffold.

---

## Environment facts worth not re-deriving

- Deploy: mounted Python edits → `docker compose restart backend`. Frontend → `npm run build` in
  `front_end/owui` then `docker compose restart nginx`. **Env-var changes need `--force-recreate`.**
- `docker exec … python - <<'PY'` heredocs produce **no output** here. Write the script to the
  scratchpad, `docker cp` it in, then `docker exec … python /tmp/x.py`. Cleanup needs `-u root`
  (container runs non-root).
- **Never run `grep`/`Grep` on this box** — it resolves to `ugrep` and wedges in an unkillable kernel
  state. Use Python (`pathlib` + `re`). `docker exec <container> grep` is safe; so are `sed` and `awk`.
- gpt-oss:20b at temperature 0.2 still varies run to run. The gate verdict changed between two
  identical invocations — do not treat one clean run as proof.

## Lane flags, as deployed

| Flag | Value |
|---|---|
| `HARVIS_AGENT_REACH_ENABLED` | `true` |
| `HARVIS_MCP_RUNTIME_ENABLED` | `false` |
| `HARVIS_VISION_SELF_CHECK_ENABLED` | `false` |
| `HARVIS_SKILLOPT_ENABLED` | unset in `.env` — the trainer is invoked with it on the command line |

---

## Test results (2026-08-02)

Run through a harness that uses the **real** `ModelRouter`, `WIRE_TOOL_SCHEMA`, `parse_tool_calls`
and `dispatch_tool` — so the lane gate and the SSRF guard were genuinely in the path. Not the full
runner (no events, no risk gate, no workspace fingerprint), but every link the test cares about is
the production one. Harness kept at `scripts/agent-reach-e2e.py` (takes the model tag as argv[1]); its docstring
has the two-line run recipe.

**Offline gate suite:** `tests/test_skillopt_gate.py` — **10 passed in 0.12s**.

**Agent Reach, native Ollama lane — PASSED on both models tried.** 14 tools offered, 4 of them
`agent_reach.*`, flag `true`.

| | `gpt-oss:20b` | `qwen3:4b` |
|---|---|---|
| tool calls | 6 | 4 |
| wall clock | 142s (67%/33% CPU/GPU) | 75s |
| shape | one call per step, 6 steps | **all 4 in a single step**, then `finish()` |
| ended via | no-tool-call fallback (wrote `finish(summary)` as *text*) | explicit `finish` tool call |
| item 1 — version | `3.34.0` ✓ | `3.34.0` ✓ |
| item 2 — HN top story | live ✓ | live ✓ |
| item 3 — example.com | `Example Domain` ✓ | `Example Domain` ✓ |
| item 4 — `169.254.169.254` | **REFUSED** ✓ | **REFUSED** ✓ |

The HN top story came back as *"Show HN: Draco — a single-binary, self-hostable Firecrawl
alternative in Rust"*, different from the *"Kimi K3 on MI355X"* story captured 14 hours earlier.
That difference is the proof the fetch is live rather than cached.

Both models reached for the tools without coaxing, and the small 4B model did it **better** — one
parallel batch and a clean `finish()`, in half the time.

### Two findings worth acting on

1. **`gpt-oss:20b` repeated an identical, already-SUCCESSFUL `gh_view` call three times** (steps 1–3,
   same URL, same args) before moving on. That is the same no-progress shape the mined trajectories
   flagged for `exec` — but the abort guard only covers `exec`, so on read-only tools the model can
   burn steps and tokens indefinitely with nothing to stop it. ~30s and 3 wasted fetches here.
   Cheap fix: extend the repeat detector to any tool called with byte-identical args N times.
2. **The model emitted `finish(summary)` as literal text** instead of calling the tool. The runner's
   no-tool-call fallback catches this (`content` becomes the summary), so nothing breaks — but a run
   that ends this way skips the explicit-completion path. Worth knowing when reading run traces.

Neither is an Agent Reach defect. Agent Reach itself is verified end to end: the model reaches for
it, the dispatch runs it, and the SSRF gate refuses the metadata endpoint on both models.

### Still open from section 4

The **commit script is stale** — it was written at 16:51 on 2026-08-01, before the attachments arc
(22:36) and the SkillOpt arc (23:54). It covers 78 of 85 dirty paths; these five match no group and
would be silently left behind (155 insertions):

```
python_back_end/workspace/kimi_workspace.py                              +83  attachments on CLI lanes
python_back_end/workspace/orchestration/engine_adapter.py                +58  same arc
front_end/owui/src/lib/agent-studio/build/WorkspaceMainPanel.svelte           preview dock / Full button
front_end/owui/src/lib/agent-studio/RunView.svelte                            working-icon-persists fix
python_back_end/tests/test_skillopt_gate.py                                   the 10 gate tests
```

`docker-compose.omniroute-trial.yml` is excluded on purpose (the script's own header says so).

### The commit script has been amended (2026-08-02)

All five are now in groups, so nothing is left behind. **12 groups → 14:**

- **new group 9** — Build run view: the preview slot and the finished-run status fix
  (`RunView.svelte`, `WorkspaceMainPanel.svelte`). Placed *before* screenshot-to-code, because the
  vibecode page in that group is what passes the new `hasPreview` / `artifactsMode` props.
- **new group 11** — attachments on every Build lane (`kimi_workspace.py`, `engine_adapter.py`).
  Placed *after* screenshot-to-code, because it calls `vision_to_code/attachments.py` from it.
- **group 8** gained `scripts/agent-reach-e2e.py` (the E2E harness).
- **group 12** (skillopt) gained `python_back_end/tests/test_skillopt_gate.py`.

Verified by running the script with `git add` / `git commit` stubbed out and diffing its real
pathspecs against `git status` — not by pattern-matching the source, which got this wrong twice.
Result: **14 groups, every one with live files** (a group with nothing staged would make
`git commit` fail and `set -e` would abort the run mid-way), and exactly two paths left uncovered —
`docker-compose.omniroute-trial.yml` and the plan script itself, both named in the header as
deliberate.

Run it from the main tree on `harvis1.2`:

```bash
./scripts/commit-groups-2026-08-01.sh
```
