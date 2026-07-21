# Reference scan — OmniRoute · Tinker · Inkling

**Date:** 2026-07-18
**Purpose:** three external projects to evaluate against Harvis's direction. Each is assessed for
what it does, what it would mean for Harvis, and the honest constraints.

---

## 1. OmniRoute — `github.com/diegosouzapw/OmniRoute`

**The headline: this is the OmniRouter idea, already built, at scale, MIT-licensed.**

The vault has carried an `OmniRouter` spark since 2026-07-15 — a router giving Harvis users free,
auto-refreshing API keys via a rotating pool of free-tier providers, sitting behind `model_proxy`.
OmniRoute is that concept shipped and mature.

### What it is

An AI gateway aggregating 251+ LLM providers behind one OpenAI-compatible endpoint. Its own
description: *"Never stop coding. Connect every AI tool to 265 providers — 90+ free — through one
endpoint."*

| | |
|---|---|
| **License** | MIT |
| **Maturity** | 19.1K stars · 2.7K forks · 5,289 commits · release v3.8.49 · 21,000+ tests |
| **Stack** | TypeScript/Node · Next.js dashboard · Express local proxy · `better-sqlite3` |
| **Deploy** | Docker (multi-arch) · npm · Electron · Termux (Android) |
| **Protocols** | OpenAI `/v1` · MCP · A2A · SSE |

### Features that matter to us

- **Local-first proxy that never phones home** — matches Harvis's self-hosted posture exactly.
- **18 composable routing strategies** — priority (drain subscriptions → cheap APIs → free tiers),
  cost-optimized, weighted/round-robin, and a 12-factor auto-combo score (health, quota, cost,
  latency, success rate).
- **Auto-fallback across 4 provider tiers on quota exhaustion.** This is the rotation/blacklist/
  fallback-ladder design the OmniRouter note sketched, already implemented.
- **Free-tier aggregation** — ~1.6B free tokens/month across 90+ providers, 11 "free forever"
  (Cerebras, Cloudflare, NVIDIA NIM, Pollinations, others).
- **Context compression** — 10 stacked engines (session dedup, context-caching retrieval,
  tool-result filtering, JSON compaction, LLMLingua-2 pruning) claiming 78–95% savings on
  tool-heavy prompts while preserving code/URLs byte-perfect.
- **MCP server exposing 94 tools across 30 scopes.**
- **Guardrails** — PII detection, prompt-injection guards.
- **Cost telemetry** via `X-OmniRoute-*` response headers.
- **`context-relay`** — *"hand off conversation history across models for long sessions."*

### Why this changes the OmniRouter plan

The build-vs-adopt question is now lopsided. The OmniRouter note estimated key pool + rotation +
health-check/blacklist + per-user quota + fallback ladder as net-new work gated behind the
remote-dev path. OmniRoute has all of it, MIT, with 21k tests.

**Recommended stance: evaluate OmniRoute as the provider layer behind `model_proxy`, rather than
building OmniRouter from scratch.** Harvis keeps `model_proxy` as the security boundary (the client
never sees a key — that constraint does not move); OmniRoute becomes what `model_proxy` talks to.

### What must be checked before adopting

- **The proxy-only invariant must survive.** Harvis's rule is that raw keys stay server-side. Needs
  confirmation that OmniRoute can run fully internal with no client-facing key exposure.
- **Free-tier ToS.** The OmniRouter note already flagged this and it does not go away by adopting
  someone else's rotation logic — rotation must respect per-provider limits, not launder abuse.
  This is the single biggest reason to read their implementation before trusting it.
- **Dependency weight.** It embeds Redis, Bifrost (a Go AI-gateway), and Mux. Harvis's compose is
  already heavy; a nested gateway stack is a real operational cost.
- **Trust surface.** A component that holds every provider credential and sees every prompt is the
  highest-value target in the system. MIT and popular is not the same as audited.

### Direct overlap with Continuity Bridge

Their tagline is *"Never stop coding"* — the same problem statement as the
[Continuity Bridge](../design/2026-07-18-continuity-bridge.md). But they solve it at the
**inference layer** (when a provider is exhausted, route the next token elsewhere), while
Continuity Bridge solves it at the **work-state layer** (when a provider dies, the session's
context and repo state survive so another agent can resume).

These are complementary, not competing. `context-relay` is worth reading closely as prior art for
the handoff format.

---

## 2. Tinker — Thinking Machines Lab

A flexible API for fine-tuning open-weight models with LoRA. You write the training loop in Python
locally; they run it on distributed GPUs. The primitives are deliberately low-level —
`forward_backward` and `sample` — which compose into arbitrary post-training methods, including
online RL (sample a completion, score it, update on whether it was good).

It abstracts away cluster management so fine-tuning is simple Python calls, and supports large MoE
models including Qwen-235B-A22B. Announced 2025-10-01; private beta, early access free with
usage-based pricing expected later.

### Relevance to Harvis

Harvis's north star includes **customization** alongside optimization and mid-range accessibility.
Tinker is a credible path to the customization axis without owning a GPU cluster: fine-tune a small
open model on Harvis-specific behavior (tool-call formatting, the trace/event schema, CTF task
shapes) rather than fighting it with ever-longer prompts.

The concrete itch is already documented across the vault — models that misbehave *structurally*
rather than for lack of intelligence: `hermes4` ignoring stop tokens, `gemma4:e4b` silently
stopping after a tool result, and the Ollama `tool_choice` ceiling where pin-to-function and
`required` are ignored above trivial complexity. Those are exactly the failures fine-tuning fixes
and prompting does not.

### Honest constraints

- **Private beta** — access is not guaranteed.
- **It is a training service, not a serving one.** A tuned model still has to be served. The dev
  box has an **8GB GPU**, so anything trained must be small enough to run locally or be served
  elsewhere — which reintroduces the provider dependency Harvis is trying to reduce.
- Weigh against the cheaper fix first: better prompts, better tool schemas, and model-task pairing
  (already documented — qwen3 for hash/CodeAct, gemma4 for MCQ/crypto).

---

## 3. Inkling — Thinking Machines Lab's open-weights model

Released **2026-07-15** — three days before this scan.

| | |
|---|---|
| **Architecture** | Mixture-of-Experts transformer |
| **Parameters** | 975B total / 41B active |
| **Context** | up to 1M tokens |
| **Pretraining** | 45T tokens of text, images, audio, video |
| **Modalities** | reasons natively over text, images, and audio |
| **Weights** | open — downloadable and modifiable |
| **Availability** | HuggingFace · Databricks |

Two design choices stand out for our purposes. It gives **calibrated answers — flagging uncertainty
rather than guessing.** And it exposes **controllable thinking effort**, trading depth for speed on
demand.

It is positioned as a starting point rather than a finished product: something organizations
fine-tune themselves **through Tinker**. Tinker and Inkling are one strategy, not two products —
the bet being that models organizations can adapt will beat one-size-fits-all.

### Relevance to Harvis

Philosophically this is the closest thing yet to Harvis's own thesis. "Open weights + customize it
yourself + dial the effort" is the platform argument Harvis makes about agent infrastructure, made
about the model layer instead.

The calibration property is worth noting given this week's work: the entire Recon #2 fix batch was
about the *UI* not asserting things it cannot support. A model that flags uncertainty instead of
guessing is the same principle one layer down.

### Honest constraints — this is the important part

**975B total / 41B active does not run on an 8GB GPU.** Not with quantization, not with offload.
Local inference is off the table on current hardware, and almost certainly on any single consumer
GPU.

Realistic paths, in order of cost:

1. **Hosted via Databricks or another provider** — works today, but reintroduces exactly the
   provider dependency that motivates Continuity Bridge. Fine for evaluation; contradicts the
   local-first thesis as a default.
2. **Fine-tune a small open model via Tinker instead**, treating Inkling as the aspirational target
   rather than the deployment target.
3. **Wait for smaller Inkling variants**, if the lab ships a family rather than a single model.

Recommendation: **evaluate Inkling hosted, adopt nothing yet.** Its value to Harvis right now is
directional — validation of the open-weights + customization thesis — not an integration. The one
concrete near-term action is to test whether its calibration and effort control behave well inside
Harvis's agent loop, since those are the two properties local models keep failing at.

---

## Summary

| Project | Verdict | Next action |
|---|---|---|
| **OmniRoute** | **Adopt-candidate.** Likely supersedes building OmniRouter by hand. | Read the proxy + key-handling code; confirm the no-client-key invariant holds; assess ToS posture and dependency weight. |
| **Tinker** | **Watch / apply for access.** The customization path. | Check beta availability; pick one concrete fine-tune target (tool-call formatting is the best candidate). |
| **Inkling** | **Directional validation.** Cannot run locally. | Evaluate hosted; test calibration + effort control in the agent loop. Do not plan a local deployment. |

## Sources

- [OmniRoute — GitHub](https://github.com/diegosouzapw/OmniRoute)
- [Announcing Tinker — Thinking Machines Lab](https://thinkingmachines.ai/news/announcing-tinker/)
- [Tinker — Thinking Machines Lab](https://thinkingmachines.ai/tinker/)
- [Thinking Machines Releases Tinker API for Flexible Model Fine-Tuning — InfoQ](https://www.infoq.com/news/2025/10/thinking-machines-tinker/)
- [Inkling: Our open-weights model — Thinking Machines Lab](https://thinkingmachines.ai/news/introducing-inkling/)
- [Inkling Model Card — Thinking Machines Lab](https://thinkingmachines.ai/model-card/inkling/)
- [Thinking Machines amps up its bet against one-size-fits-all AI with its first open model, Inkling — TechCrunch](https://techcrunch.com/2026/07/15/thinking-machines-amps-up-its-bet-against-one-size-fits-all-ai-with-its-first-open-model-inkling/)
- [Inkling model from Thinking Machines Lab now on Databricks — Databricks](https://www.databricks.com/blog/inkling-thinking-machines-lab-now-databricks)
