# Handoff — 2026-07-26: three cleanup commits landed, and the Odysseus gap turned out to be one package

## One-line state

Three commits sit **local and unpushed** on `deploy-optimize-test`. One **security decision blocks
the push**. No code work is in flight. The interesting thread is the last section — the
Harvis-vs-Odysseus size gap decomposed to a single cause, with four named blockers and an
already-installed escape hatch nobody is using.

| Commit | What | Where |
|---|---|---|
| `f4e5041a` | untrack the committed 51 MB DB dump | local only |
| `fbb636b6` | stop calling a correct default install "degraded" | local only |
| `189171c8` | untrack `node_modules` + runtime scratch | local only |

`origin/deploy-optimize-test` is still at `2530e090`. `origin/harvis1.1` (`bcd6005e`) and
`origin/harvis1.1-deploy-test` (`498c25db`) are untouched, as intended.

---

## The blocking decision — read this first

`f4e5041a` removed `embedding/database_backup.dump` from the working tree. **The 51 MB blob is
still in git history on all three pushed branches of a PUBLIC repo with one fork.** It contains
real data:

| table | rows |
|---|---:|
| `langchain_pg_embedding` | 23,952 |
| `chat_messages` | 770 |
| `chat_sessions` | 315 |
| `n8n_automation_history` | 124 |
| `vibecoding_sessions` | 9 |
| `users` | 1 — **username, email, bcrypt password hash** |
| `user_api_keys` | 0 (schema only) |

`.gitignore:142` already had `*.dump`. It never untracked the file because the file predates the
rule — **`.gitignore` never untracks what is already committed, and `git status` stays silent about
it.** Third instance of this defect class in this repo.

**The choice:** purge from history across all three branches and force-push — which breaks existing
clones and **does not reach the fork** — versus leave history as-is and just push the three commits.
Separately: that account's password should be treated as compromised either way.

Nothing else should be pushed until this is settled.

---

## What the three commits actually did

**`fbb636b6` — health honesty.** Compose profiles are opt-in, so a default `docker compose up`
starts neither `openclaw` (profile `engines`) nor `tts-service` (profile `voice`). Both
`/api/health/services` and the `/api/setup/verify` aggregate probed them unconditionally, so a
correct fresh clone reported itself **degraded** with red setup ticks — which teaches people to
ignore the health page.

A container cannot see `docker compose --profile`, so compose now passes the enabled set in as
`HARVIS_ENABLED_PROFILES`.

**The design detail worth keeping:** the probe **always runs first**, and the profile is used only
to *classify a failure*. My first version returned `not_installed` before probing, which meant a
stale or absent profile list would report a **running** service as missing. Verified across three
cases in a throwaway container — default install skips both; `engines` on turns an openclaw failure
back into a real failure while tts stays skipped; and **services reachable with no profiles listed
still report ready**, which is the case the ordering exists for.

> **Trap that cost time:** single-file Docker bind mounts pin to an **inode**, and the Edit tool
> writes via atomic rename. Live edits to `python_back_end/main.py` and `setup_flow.py` **do not
> reach the running `harvis-backend`** — the container had 282 lines while the host had 322.
> Verify by mounting the edited file fresh into a throwaway container from the same image, or
> recreate the container. Do not trust a curl against the live backend after editing those files.

> **Live-box caveat:** this dev box runs every profile, so `/api/health/services` returns everything
> "up" here. The regression only manifests on a default clone.

**`189171c8` — hygiene.** `python_back_end/node_modules` was tracked (2,250 files, 16.5 MB) despite
`.gitignore:229` — same predates-the-rule defect as the dump. Nothing uses it: the backend
Dockerfile has no npm step, no compose service mounts it, and no Python imports the
`ai`/`@ai-sdk/openai` packages. Also added `node_modules/` to `python_back_end/.dockerignore`,
because `COPY . .` was baking all 2,250 files into the image.

> **Correction worth carrying forward:** an earlier sweep listed `python_back_end/harvis_voice.mp3`
> as a stray. **It is not.** It is the voice-cloning reference audio that `qwen3_tts.py`, `main.py`
> and `vibecoding/commands.py` read at runtime. Untracking it would have broken TTS on a fresh
> clone. Always check references before untracking a binary — the earlier list was wrong on 1 of 4.

---

## The finding: why Odysseus is 3 GB and we are 27

Full write-up lives in **`docs/deploy/STORAGE-BUDGET.md`**, section *"Why Odysseus is 3 GB and we
are 27."* Summary:

Measured against the Odysseus stack running on this same box, UNIQUE SIZE method, zero models:
Harvis default **27.4 GB** / Harvis BYO **17.7 GB** / Odysseus **3.03 GB**.

**Two reframings before anyone panics about 9×.** Odysseus ships no model server — its compose
points at `host.docker.internal:11434`, the same posture `--ollama-url` gives us. Count the Ollama a
local-inference user needs either way and it is **2.15×**. And decomposing the like-for-like delta:
the app image accounts for 13.69 GB of it and *everything else* for 0.97 GB. **The supporting cast
is already within a gigabyte.** 12.10 GB of our backend is the pytorch CUDA base — **83% of the
entire gap is that one base image.**

**The mechanism.** Odysseus's whole `site-packages` is 371 MB and its largest entry is
**`onnxruntime` at 55 MB**. Checked by name in the image: no `torch`, `transformers`,
`sentence_transformers`, `whisper`, `librosa`, `nvidia/*`, `triton`. Ours is **8,486 MB**, of which
`nvidia` 4,184 + `torch` 1,692 + `triton` 542 = **76%**. ONNX Runtime executes a pre-compiled graph;
PyTorch ships a tensor library, autograd, a compiler and the CUDA toolchain because it exists to
*train*. Harvis never trains anything.

**The annoying part.** `onnxruntime` (57 MB) and `piper` (25 MB) are **already installed here**.
`piper` is a real, used ONNX TTS engine (6 importers). `onnxruntime` has **zero direct importers** —
it came in transitively. The ONNX path is not foreign to Harvis; it is sitting next to torch.

---

## Tomorrow: what to dig into

The four consumers keeping torch alive, with the migration each would need:

| Consumer | Call sites | Torch-free path | Difficulty |
|---|---|---|---|
| `sentence_transformers` | `enhanced_vector_optimizer.py:8`, `research/rank/rerank.py:139` | fastembed / ONNX MiniLM | **easiest — 2 sites, Odysseus's exact choice** |
| `openai-whisper` | `main.py:120`, `cody.py:19`, +2 | `faster-whisper` (CTranslate2) | medium — needs a quality/latency A-B |
| `chatterbox` / `qwen3_tts` | `tts_engine_manager.py:45`, `qwen3_tts.py:14`, +10 | `piper` (already present) | medium — voice-clone quality regression |
| `transformers` (vision) | `model_manager.py:463`, `chatbot.py:9`, `vison_models/qwen.py:1` | ONNX export or a sidecar | **hard — the real blocker** |

### Suggested first move

**Measure before migrating.** The single highest-value unknown is the CUDA split, and it is
currently an **estimate, not a measurement**:

> GPU speech still needs cuDNN (1,005 MB) + cuBLAS (830 MB) because CTranslate2 links them too. The
> *torch-only* libs are roughly cusolver + cusparselt + nccl + nvrtc + cufft + cusparse + curand ≈
> **2.2 GB**. The one-package-at-a-time removal tests in STORAGE-BUDGET.md were run against
> **torch**. CTranslate2's requirement set has never been tested.

So: build a throwaway image with `faster-whisper` and no torch, then remove nvidia packages **one at
a time in fresh containers**, exercising real transcription — not a smoke test.

> **The lesson from the existing tests, which applies double here:** a shallow CUDA check greenlights
> removals that break the workload. `nvidia-cuda-nvrtc` survives `import torch` + matmul + conv2d but
> **breaks `fft` and `stft`** — and `stft` is how Whisper builds its log-mel spectrogram. Exercise
> `fft`/`stft`/`linalg`/`sdpa`, never just `a @ b`.

### Two things to hold onto

**It is all-or-nothing.** One surviving torch consumer keeps the entire 6.4 GB stack. Migrating
three of four buys **zero** image size. Sequence the work so the hard one (vision) is scoped *before*
the easy ones are done, or the effort strands.

**The ceiling is ~10 GB, not 3 GB.** On the estimate above: torch 1.7 + triton 0.5 + transformers
0.12 + torch-only CUDA 2.2 ≈ 4.6 GB off → backend 15.4 → **~10.8 GB**, or ~10.2 with item 7's slim
base. Still 6× Odysseus, because Odysseus does no GPU speech at all.

**Why the last 6× cannot be engineered away.** Odysseus is a router; Harvis is a runtime. Exactly one
change bridges them — move torch into a GPU worker behind a profile, leaving the core as a router —
and that is the `harvis-core` / `harvis-gpu-worker` split which was **deliberately closed** because
speech stays first-class in core. That decision sets the floor, and it is a legitimate one.

---

## Also still open (unchanged from before)

- **Item 7**, slim base + drop triton: built and 14/14-CUDA-verified at 13.8 GB, **not adopted**.
  Worth 1.6 GB, costs a knowingly inconsistent `pip check` about triton.
- Whether `browser-runner` (677 MB unique, 390 MB firefox-esr) leaves the default profile.
- Split the HF model cache — `HF_HOME` and `TRANSFORMERS_CACHE` are both set, so models download
  twice (~13 GB). Fix is destructive.
- The **hosting mode** is explicitly deferred by the user: *"this is something for the future not now."*

## Environment notes

- Canonical tree is `/home/user/Harvis` on `deploy-optimize-test`. The shell
  cwd resets to a stale worktree after every command — always use absolute main-tree paths.
- **Never run `grep`/`ugrep` on this box** — it wedges in an unkillable kernel state. Use Python
  (`pathlib` + `re`). `docker exec <container> grep` is fine.
- `pg_restore` is **not installed on the host**; run it via `docker run --rm postgres:15`. A Python
  wrapper silently swallowed "command not found" and returned a false "0 tables."
- Read **UNIQUE SIZE** from `docker system df -v`, never the `docker images` SIZE column — the
  backend/harvis-mcp family shares one multi-GB layer stack that exists on disk exactly once.
- `harvis-backend:latest` on this box is **9 days old** and predates the trim commits. Do not quote
  its 16.9 GB as current; the committed Dockerfile builds `slim-cli` at 15.4 GB.
