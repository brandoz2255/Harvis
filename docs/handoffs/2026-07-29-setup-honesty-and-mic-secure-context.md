# Handoff — 2026-07-29 (late): setup wizard honesty pass + the mic "permission denied" that wasn't

**Branch:** `deploy-optimize-test` · **rig:** VM 102 `harvis-fresh` 192.168.20.98 (the pristine
fresh-install box) · **everything below is deployed there and verified live.**

Read `changes.md` (top entry, same date) for the per-fix detail. This document is the state of
play and what's next.

---

## What this session closed

Five wizard items the user reported, plus two defects found while verifying them.

1. **Wizard wouldn't advance after connecting a Kimi Code key.** `verify` stored
   `verified_at=NOW()`, then `save` reset it — so a key the vendor had just accepted was recorded as
   unverified and every downstream gate said no. Fixed on both sides: an unchanged-secret re-save
   keeps its verification (`engine_auth.py`), and `connectKey` saves before verifying
   (`setup/+page.svelte`).
2. **OpenClaw checkbox → engine readiness rows.** `_probe_engines` reports per-engine state with an
   actionable reason. Verified-but-no-sidecar is deliberately **neutral**, and the tick prints the
   exact `docker compose --profile engines up -d claude-code`.
3. **Ollama declared optional** when a cloud provider is connected — a neutral skipped tick, not a
   red ✗.
4. **Test key button** — `POST …/verify` with no body re-verifies the *stored* credential against the
   vendor. Verified live on the real `kimi-code` row.
5. **TTS explained** in the wizard copy.
6. **FOUND: `test-model` sent cloud models to Ollama.** The final wizard step called a working
   cloud-only install broken. Now routed through `proxy_cloud_chat`; the local branch names the
   address it could not reach.
7. **FOUND + FIXED: the mic message was false.** See below — this one has a residual.

---

## The residual that needs a product decision: no HTTPS

`nginx.conf` has one `listen 80;` and zero `ssl_certificate` lines. Browsers expose
`navigator.mediaDevices` **only** over HTTPS or from `localhost`/`127.0.0.1`. So:

- On `http://localhost:9000` (the machine running Docker) voice works.
- On any LAN origin — `http://192.168.20.98:9000`, which is how anyone else opens Harvis — the API
  is `undefined` and voice **cannot** work.

The code fix made the message honest (it now names the origin and says nothing was denied). It did
not, and cannot, make voice work remotely. Three ways forward, in ascending effort:

1. Tell people to browse from the host. Zero work, poor answer for a self-hosted product.
2. Self-signed cert + an `ssl` server block, with a documented one-time browser trust step.
3. Real certs — mkcert for LAN, or Let's Encrypt where there's a domain. This is also what a
   K8s ingress would give for free.

Voice is a headline feature ("Voice-First Default"), and today it silently only works on one
machine. Worth a decision before the next fresh-clone test.

---

## Measured footprint (VM 102, after install + this deploy)

| | |
|---|---|
| Images (9, deduped) | **5.218 GB** |
| Volumes (7) | 0.590 GB |
| Repo checkout (`.git` 119 MB, owui `build/` 264 MB) | 0.472 GB |
| **On-disk total** | **≈6.28 GB** ✓ under the 7 GB finish line |
| Build cache | **9.79 GB** (7.61 GB reclaimable) — uncounted by every measurement so far |

The plan's finish line is *"fresh clone → working Harvis in one command, no questions asked, under
7 GB."* The install itself clears it with ~0.7 GB of margin. The build cache does not, and it is a
real 9.8 GB on a real disk. `docker builder prune -f` after a successful install would reclaim
7.6 GB at the cost of slower rebuilds — **open call, the user's.**

Two build-side facts worth keeping:

- **The owui build needs swap on an 8 GB box.** `npm run build` sets
  `--max-old-space-size=8192`; on VM 102 (7941 MB, no swap) with the stack already up, the kernel
  SIGKILLs it during "rendering chunks" after `✓ 6285 modules transformed`. 6 GB of temporary swap
  fixes it; a *fresh* `install.sh` survives only because nothing else is running yet. Anyone
  rebuilding the frontend on a running 8 GB deploy will hit this.
- **Clearing the bind-mounted build dir needs `sudo` and must happen in place.** `owui-builder`
  populates it with `cp -a`, preserving container ownership, and its command is
  skip-if-`/out/index.html`-exists. `sudo find front_end/owui/build -mindepth 1 -delete` — replacing
  the directory inode would break the bind mount.

---

## Verification actually performed

Not stubs. Every credential verifier was called against the live vendor with a junk key, inside the
running backend container:

```
codex        ok=False  'OpenAI rejected the key (HTTP 401).'
claude-code  ok=False  'Anthropic rejected the key (HTTP 401).'
kimi-code    ok=False  'Kimi Code rejected this key. Use the key from the Kimi Code Console…'
moonshot     ok=False  'Moonshot rejected this key on both of its platforms…'
```

`test-model` across all three model shapes (cloud-ready / cloud-unconnected / local-with-no-server),
the exposure step in both states with `instance_settings` restored, and the stored-credential probe
on the real `kimi-code` row (`ok: True`, `verified_at` refreshed).

**Not exercised:** the model step's `pull` state (needs a reachable Ollama; VM 102 has none by
design) and admin-claim (single-use, already spent on that rig).

---

## Next, in the order I'd take it

1. **Decide the HTTPS question above.** It gates voice for every user who isn't sitting at the
   Docker host.
2. **Decide whether install should prune the build cache.** 7.6 GB reclaimable, versus rebuild speed.
3. **Rebuild the backend image.** Several root-level `python_back_end/*.py` files are *not*
   bind-mounted (`n8n/automation_service.py`, `n8n/workflow_builder.py`, `n8n_automation_system.py`,
   `ollama_cli/main.py`, `ollama_n8n_optimizer.py`), so edits there don't apply until the image is
   rebuilt. Nothing from this session is affected — `setup_flow.py` and `owui_compat/` are mounted —
   but it's a standing trap.
4. **Pre-flight the engine picker** so an engine whose sidecar is absent isn't offered as if it
   were installed. Today the Verify step explains it after the fact; better to not offer it.
5. **Task #96** — the native lane's two tool-contract gaps: `run_tests` is dispatched at
   `tools.py:551` and named at `runner.py:80` but missing from `TOOL_SCHEMA`; `dir_list` is named at
   `session_turn.py:248` and does not exist. Consider raising `max_steps` from 12.

Smaller flags still open: the docker-missing preflight row has no command to copy; the trace ticks
`✓ Model responded` / `✓ Agent finished` on dispatch rather than on evidence;
`projects/Harvis.md`'s `next:` frontmatter is stale; `_SERVICE_PROFILE["tts"]` and
`_not_installed_reason("tts")` are now unreferenced.
