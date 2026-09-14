# Mac install fix, security pass, and the automation finding — 2026-08-26

Three threads ran together this session: getting `install.sh` working on a fresh Mac,
a security review of the frontend and backend, and scoping the "automation like n8n"
work. Only the first one shipped.

---

## 1. SHIPPED — `install.sh` could not see Docker Desktop

**Commit `d2480fc7` on `main`, pushed** (`0628d388..d2480fc7`). 66 insertions, 1 deletion.

One reported symptom, two independent defects.

### Defect A — the CLI is not on PATH

Docker Desktop 4.18+ installs the `docker` binary into `~/.docker/bin` and puts that
directory on PATH **only by editing the shell profile**. A terminal opened before
Docker was installed, or any non-login shell, therefore resolves no `docker` at all.
`check_prereqs()` did a bare `command -v docker`, so it printed

```
FAIL  docker           not found — install Docker first
```

while Docker Desktop was running in the menu bar. The advice was actively wrong: the
user already had Docker.

`find_docker_cli()` now probes, in order, `~/.docker/bin`, `/usr/local/bin`,
`/opt/homebrew/bin`, and `/Applications/Docker.app/Contents/Resources/bin`. On a hit it
prepends that directory to PATH for the run and buffers a hint telling the user to open
a new terminal, with the exact `export PATH=…` line as a fallback.

### Defect B — a stopped engine passed preflight

`docker` and `docker compose` are **client** binaries. Both answer normally with the
engine stopped, so the entire preflight table went green and the *first* real command
died on `Cannot connect to the Docker daemon`. On macOS the engine is a GUI app that has
to be launched, and nothing in the script ever said so — the failure read like a Harvis
bug rather than "Docker Desktop isn't running."

There is now a `docker daemon` row driven by `docker version --format
'{{.Server.Version}}'`, with an OS-aware remedy: `open -a Docker` on Darwin,
`systemctl start docker` plus the docker-group hint elsewhere.

### Verification — both failure paths, not just the happy one

Passing (this dev box):

```
PASS  docker           Docker version 29.5.2, build 79eb04c
PASS  docker compose   5.1.4
PASS  docker daemon    engine 29.5.2
```

Engine unreachable, via `DOCKER_HOST=unix:///nonexistent/docker.sock`:

```
FAIL  docker daemon    CLI is installed but the engine is not reachable
```
…and it aborts before touching anything.

CLI recovery, with PATH stripped to an empty directory and the binary present only at
`$HOME/.docker/bin/docker`:

```
RECOVERED -> /tmp/…/home/.docker/bin/docker
```

`bash -n install.sh` clean. All new code is bash-3.2 safe (macOS ships bash 3.2): no
`declare -A`, no `mapfile`/`readarray`, no `${x^^}`. `${HOME:-/nonexistent}` guards
against `set -u`.

---

## 2. macOS install audit — what else was checked

Cleared:

- Every digest-pinned image in the default profile is multi-arch with an arm64 variant;
  no `platform:` pins anywhere.
- No CUDA or nvidia dependency in the default backend — `python_back_end/Dockerfile.core`
  is `python:3.12-slim` for both stages. The CUDA base is only in
  `python_back_end/Dockerfile`, used by `model-downloader` under the `advanced-voice`
  profile. The `tts-service` GPU reservation is likewise profile-gated.
- `install.sh` needs no `sudo`.
- `port_listening()` uses the bash `/dev/tcp` builtin, not `nc`.
- The BSD `stat -f` fallback for the docker socket GID is already present (line ~158).
- The only Linux-only invocation is `ip route show default` in `llm_probe_hosts()`, and
  it is `2>/dev/null`-guarded — on macOS it simply contributes no gateway candidate.
- No case-collisions in tracked paths.

### Still open — the one that will bite, and it fails SILENTLY

`front_end/owui/Dockerfile:31` has `ENV NODE_OPTIONS="--max-old-space-size=4096"`
**commented out**, and `owui-builder` carries no memory limit in `docker-compose.yaml`.

Under Docker Desktop's default VM allocation the frontend build OOMs and **exits 0**.
The stack then comes up serving a stale or missing UI with no error anywhere. This is the
same class of failure recorded before: *the owui build exits 0 two ways* — heap OOM, and
the builder's "already present … skipping" path. **Never verify that build by exit code;
verify by grepping the built bundle for a string you just added.**

Recommended before the Mac run: uncomment that line, and give Docker Desktop enough
memory in its own settings.

---

## 3. Security pass

### XSS — clean

All **30 `{@html}` sinks** across **21 owui files** were traced to their source. Every
one is safe, by one of four mechanisms:

| Mechanism | Examples |
|---|---|
| DOMPurify at the sink | `ChangelogModal`, `Banner`, `MessageInput`, `AccountPending`, `auth/+page`, `MarkdownInlineTokens`, `SVGPanZoom`, `ConfirmDialog` |
| DOMPurify at the source, before the prop is passed | `FilePreview.fileOfficeHtml` (sanitized in `FileNav.svelte:448,459,1287`), `FileItemModal.excelHtml/docxHtml` (`:164,180`), `NotebookView` `text/html` outputs via `getOutputHtml` (`:95`), `knowledge/+page.resultHtml` (`:156`), `ModelComparison.renderMd` (`:363`) |
| An escaping renderer, not raw HTML | shiki `codeToHtml` (`NotebookView.highlightedCells`), `hljs.highlightAuto` (`CodeBlock`), KaTeX `renderToString` with `throwOnError:false`, Vega-Lite via `renderChart()` — which builds a spec object, never passes model HTML |
| Static local constants | `Placeholder` brand/capability SVGs, `build/+page` chevron, `agent-studio/+page` card icons |

Notebook `text/html` output is the one that deserved the closest look — an `.ipynb` is
an attacker-supplyable file and its outputs can carry arbitrary HTML — and it is
sanitized.

### SQL injection — clean

25 f-string query sites exist in the backend (`job_queue.py`, `rag_corpus/init_tables.py`,
`rag_corpus/vectordb_adapter.py`). All interpolate **identifiers**, never values, and
every identifier traces to a server-side constant:

- `VectorDBAdapter.table_name` ← `collection_name` ← `EMBEDDING_TIER_CONFIG[tier]["collection"]`
- `get_collection_for_source()` (`rag_corpus/routes.py:106`) returns either a
  `_config_manager` entry or `EMBEDDING_COLLECTIONS.get(model, "local_rag_corpus_docs")`
  — a closed map with a fixed default.
- `JobQueue.schema` defaults to `"boss"` and has no external caller.

No request-supplied value reaches a table or schema name.

### SSRF — strong on the audited path

`agent_reach/tools.py` is better than most production code: the URL scheme and host are
checked, DNS is resolved server-side, **every** answer record must be public (a name
answering with both a public and a private address is rejected as a rebinding attempt
rather than filtered), the TCP connection is **pinned** to a validated address, redirects
are followed manually so each hop gets the same treatment, and IPv4-mapped / 6to4 IPv6
forms are recursed into so a private v4 cannot be smuggled through a v6 literal.

### NOT done — carry forward

1. **`tools/openclaw_proxy.py` (1305 lines).** This is the `X-Live-Web: true` path, which
   *by design* skips the domain allow/deny lists (`_validate_url(..., live_web=True)`,
   `:146-192`) and the browser allowlist (`_validate_browser_url`, `:257-276`). Its guard
   is `_ensure_resolved_addresses_public()` (`:68`). **Unverified: whether it pins the
   connection to the address it validated, or check-then-fetches.** If the latter, the one
   path intended to be unrestricted has a DNS-rebinding window that `agent_reach` closed.
   This is the highest-value remaining check.
2. **Performance pass — not started.** One item already surfaced separately:
   `integrations_status.py` probes services sequentially, so the panel's latency is the
   sum of every timeout rather than the max.
3. Auth coverage (unauthenticated endpoint enumeration) not swept.

---

## 4. Automation ("something like n8n") — ~80% already exists

The spec was going to be written from scratch. It should not be. `python_back_end/plugins/cron/`
is a complete, wired scheduler (~35 KB, adapted from NousResearch/hermes-agent, MIT).

**What is already there:**

- `types.py` — `ScheduleType` of `CRON` (POSIX expression, via `croniter`, already in
  `requirements-core.txt`), `INTERVAL` (`"30m"`, `"2h"`, `"7d"`), `ONCE` (ISO datetime).
  `JobStatus` of scheduled / running / paused / completed / error. A frozen `CronJob`
  dataclass carrying `next_run_at`, `last_run_at`, `run_count`, `error_message`, `metadata`.
- `scheduler.py` — `CronScheduler.tick()` with **race-safe claiming** (`mark_running`
  gated on `WHERE status='scheduled'`), a pluggable `JobDispatchFn` returning
  `(success, error_message)`, and `compute_next_run()` on success.
- `runtime.py` — **two** delivery lanes, split on `metadata.context`: `coding` launches a
  workspace run through the existing `workspace_router`; `chat` runs one completion and
  persists the exchange into an `owui_chats` row (the Schedules lens).
- `routes.py` — 6 HTTP routes: list, create, stats, get, set status, delete.
- **It is live.** `main.py:1199-1200` starts the tick loop in the lifespan,
  `:1227` stops it, `:1775-1778` registers the router — all wrapped so a broken cron
  runtime cannot block backend startup.
- **A UI exists**: `lib/agent-studio/Automations.svelte` (742 lines), its API client
  `lib/apis/cron/index.ts` (146 lines), the route `/automations`, a sidebar entry, a
  group permission, and `Schedules.svelte` as a main-chat lens over the same store.

**Stale comment to fix:** `scheduler.py`'s module docstring claims the tick loop is
"intentionally not wired here." `main.py` demonstrably starts it. Anyone reading that
docstring will conclude the feature is dormant when it is running in production.

**What an n8n replacement genuinely still needs**, and what the spec should cover:

1. **Non-time triggers.** Everything today is time-based. No inbound webhook, no
   "when a file lands / a run finishes / a label is applied" event trigger.
2. **A step/chain model.** A job is a single `prompt` string. There is no DAG, no
   step sequencing, no branching, no passing output from one step into the next.
3. **Actions beyond the two delivery lanes.** Though note the big structural advantage
   over n8n: the 128 MCP connector tools already exist, so "integrations" is largely a
   solved problem — the missing piece is *composition*, not connectors.

Write the spec against this, extending `plugins/cron/`, not replacing it.

---

## Open items

- [ ] Uncomment `NODE_OPTIONS` in `front_end/owui/Dockerfile:31` before the Mac install.
- [ ] Verify connection pinning in `openclaw_proxy._ensure_resolved_addresses_public`.
- [ ] Performance pass; start with sequential probes in `integrations_status.py`.
- [ ] Fix the stale "not wired here" docstring in `plugins/cron/scheduler.py`.
- [ ] Write the automation spec: triggers + step chaining on top of `plugins/cron/`.
