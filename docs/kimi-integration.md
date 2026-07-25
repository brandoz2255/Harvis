# Kimi integration — how the requests actually work

Written 2026-07-25, after getting both Kimi paths working end to end. This is the reference for
anyone touching Kimi in Harvis. The short version: **Kimi is two different products behind one
brand name**, and almost every bug in this integration came from treating them as one.

---

## 1. The two products (read this before anything else)

| | **Moonshot platform** | **Kimi Code** |
|---|---|---|
| Console | `platform.moonshot.ai` / `platform.moonshot.cn` | `kimi.com/coding` |
| API base | `https://api.moonshot.{ai,cn}/v1` | `https://api.kimi.com/coding` |
| Wire format | OpenAI-compatible (`/chat/completions`) | **Anthropic**-compatible (`/v1/messages`) |
| Billing | pay-as-you-go balance | membership / subscription allowance |
| Harvis engine id | `kimi` | `kimi-code` |
| Credential store | `user_api_keys`, provider `moonshot` | `user_engine_auth`, engine `kimi-code` |
| Verified at save? | yes — `verify_moonshot_key` | yes — probes `api.kimi.com/coding` |
| Model ids | `moonshot/kimi-k3`, `…k2.6`, `…k2.5` | `kimi-code/kimi-for-coding`, `…/k3`, `…/k3-256k`, `…/kimi-for-coding-highspeed` |
| Integrations tile | `kimi-api` | `kimi-code` |
| What runs | a chat/stream proxy | the **real Claude Code CLI**, repointed |

The keys are **not interchangeable**. A Moonshot key sent to `api.kimi.com/coding` 401s, and a
Kimi Code key sent to `api.moonshot.ai` 401s. Neither error says why. That is exactly why the two
credentials live in two separate stores with two separate verify paths — see the comment block at
[engine_auth.py:37](../python_back_end/owui_compat/engine_auth.py#L37).

---

## 2. The `kimi` lane (Moonshot platform)

### Credential

Resolved as `(api_key, base_url)` — the base URL travels with the key. Two implementations that
must stay in agreement:

- chat: `_moonshot_key` — [cloud_chat.py:264](../python_back_end/owui_compat/cloud_chat.py#L264)
- workspace: `_get_kimi_credentials` — [workspace_router.py:306](../python_back_end/workspace/workspace_router.py#L306)

Both check the per-user `user_api_keys` row first, then fall back to the `MOONSHOT_API_KEY` env.

### The `.ai` / `.cn` split — the single most common failure

Moonshot runs **two platforms with separate key namespaces**. A key issued on one returns 401 on
the other, with a body that says nothing about regions. The fix, in
[moonshot_api.py](../python_back_end/moonshot_api.py):

1. `verify_moonshot_key` probes **both** platforms at save time with `GET /models` (real auth,
   zero tokens) and returns whichever one accepted the key.
2. That base URL is **persisted with the key**, so every later request goes to the console that
   issued it. The env default (`MOONSHOT_BASE_URL`, defaulting to `.ai`) is only correct for an
   env-provided key.
3. `_explain_error` turns a 401 into an actionable sentence naming the other platform, instead of
   echoing Moonshot's raw body.

Keys are fingerprinted for logs with `_key_fingerprint` (length + an 8-char SHA-256 prefix) so two
keys can be told apart in a log without the key ever appearing.

### Request shaping

`_proxy_moonshot_api` ([cloud_chat.py:794](../python_back_end/owui_compat/cloud_chat.py#L794)) is a
near-passthrough — Moonshot already emits `chat.completion.chunk` SSE, so the stream is forwarded
verbatim. Two things it must do:

- Strip the catalog prefix: `moonshot/kimi-k2.5` → `kimi-k2.5` before sending.
- Pin `temperature: 1.0`. **Kimi only accepts 1.0**; anything else is rejected. This is also why
  no Moonshot model advertises `supports_effort`.

### Where it runs in Build

`agent_id="kimi"` → `stream_kimi_workspace`
([kimi_workspace.py](../python_back_end/workspace/kimi_workspace.py)), dispatched from
[workspace_router.py:1188](../python_back_end/workspace/workspace_router.py#L1188). This is the
original Harvis workspace engine — a cloud reasoning engine, not a sidecar. With no key it falls
back to local Ollama and **says so in the stream** (the run card corrects its engine chip when that
happens — `WorkspaceRunCard.svelte:198`).

---

## 3. The `kimi-code` lane (membership)

### What actually runs

The **real Claude Code CLI**, inside the existing `harvis-claude-code` sidecar, with
`ANTHROPIC_BASE_URL` repointed at Kimi Code. Same container, same CLI, same tool loop as the
`claude-code` engine — only the base URL and the credential differ
([engine_adapter.py:560](../python_back_end/workspace/orchestration/engine_adapter.py#L560)).

Running the genuine CLI rather than a proxy that imitates it is **deliberate and load-bearing**:
Kimi Code's terms require third-party coding tools to keep their true client identity. Harvis
injects the documented env vars and lets the CLI speak for itself. Do not replace this with a
hand-rolled client.

### Pin every model slot — not just `ANTHROPIC_MODEL`

This is the gotcha that cost the most time. Claude Code resolves its **own** model aliases
internally: a Sonnet-tier model for the main loop, a Haiku-tier one for cheap side calls, and a
separate subagent model for `Task`. Each of those would otherwise request an *Anthropic* model id
that Kimi Code does not serve — so the run fails **partway through**, with a model-not-found, long
after the first token made it look like it was working.

All six env vars, from [engine_adapter.py:635](../python_back_end/workspace/orchestration/engine_adapter.py#L635):

```
ANTHROPIC_BASE_URL=https://api.kimi.com/coding
ANTHROPIC_API_KEY=<the membership key>
ANTHROPIC_MODEL=<chosen kimi model>
ANTHROPIC_DEFAULT_OPUS_MODEL=<same>
ANTHROPIC_DEFAULT_SONNET_MODEL=<same>
ANTHROPIC_DEFAULT_HAIKU_MODEL=<same>
CLAUDE_CODE_SUBAGENT_MODEL=<same>
CLAUDE_CODE_SIMPLE=1
```

Plus, for the large-window models, `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` from `KIMI_CODE_CONTEXT_TOKENS` (262,144 for `kimi-for-coding`
and `k3-256k`) — without them the CLI sizes its context and auto-compact threshold for Anthropic's
windows.

`CLAUDE_CODE_SIMPLE=1` matters too: the sidecar image bakes simple/bare mode, which reads auth
**strictly** from `ANTHROPIC_API_KEY` and ignores `CLAUDE_CODE_OAUTH_TOKEN`. Kimi Code is API-key
only, so leaving it on is correct here — but the `claude-code` engine's OAuth mode has to clear it
(`CLAUDE_CODE_SIMPLE=`), which is why the two lanes set it differently.

### Model default

`KIMI_CODE_DEFAULT_MODEL = "kimi-for-coding"` — the one model **every** membership tier can use.
`k3` / `k3-256k` need Moderato+, `kimi-for-coding-highspeed` needs Allegretto+. Entitlement is
per tier and the API is the only authority, so all four are offered and a tier rejection surfaces
as a model-access error rather than being guessed at locally. An unrecognized model id falls back
to the default ([engine_adapter.py:628](../python_back_end/workspace/orchestration/engine_adapter.py#L628)).

### The SSE bug that made Kimi "say nothing"

`_stream_anthropic` parsed SSE by matching the literal prefix `"data: "` — with the space.
**The space after `data:` is optional in the SSE spec.** Anthropic sends `data: {…}`; Kimi Code
sends `data:{…}`. Requiring the space silently dropped *every* event from Kimi: the stream
completed **200 with an empty answer**, which reads as "the model said nothing" rather than "we
failed to parse it."

Fixed at [cloud_chat.py:659](../python_back_end/owui_compat/cloud_chat.py#L659) — match on
`data:` and `lstrip()` what follows, so both wire styles parse. `event:` lines are ignored on
purpose; the payload's own `type` field is the authority.

This is the canonical silent-success shape for this codebase: a 200 with no content is a parse
failure until proven otherwise.

### The unrequested chain-of-thought

Kimi's k3 emits a **thinking block on every turn** — including on "hello" — even though the Kimi
Code lane never requests extended thinking (the `thinking` parameter would be rejected there, so
`_kimi_code_payload` doesn't send it). The result was raw reasoning pasted in front of every
answer.

The gate at [cloud_chat.py:620-630](../python_back_end/owui_compat/cloud_chat.py#L620): surface
reasoning only when `"thinking" in payload` — i.e. when *this request* asked for it. Otherwise
buffer it, and emit it only if the model produced no text at all, so a thinking-only response
doesn't render as silence. Anthropic's behaviour is unchanged; it only emits thinking when asked.

---

## 4. Match `kimi-code` **before** `kimi`. Everywhere.

`"kimi-code"` starts with `"kimi"`. Any `startsWith('kimi')` test that runs first will claim the
membership engine and route it onto the pay-as-you-go platform — wrong API, wrong bill, and a 401
that names neither.

The two places this is already handled, both first-match-wins:

- engine resolution — [vibecode/+page.svelte:646](../front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte#L646):
  `if (o === 'kimi-code') return 'kimi-code';` **then** `if (o.startsWith('moonshot') || o.startsWith('kimi')) return 'kimi';`
- model grouping — [vibecode/+page.svelte:755](../front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte#L755):
  the `Kimi Code (membership)` group is declared **before** the generic `Kimi` group.

Backend equivalent: `_provider_for` tests `mid.startswith("kimi-code/")` explicitly rather than
falling through a generic Kimi test ([cloud_chat.py:248](../python_back_end/owui_compat/cloud_chat.py#L248)).

**Any new Kimi-aware code must preserve this ordering.**

---

## 5. Readiness gates

The two engines report ready by different rules, and that difference is intentional
([capabilities.py:241](../python_back_end/owui_compat/capabilities.py#L241)):

- **`kimi`** — ready iff a Moonshot key *exists* (per-user row or env). Same gate as the chat lane.
- **`kimi-code`** — ready iff a `kimi-code` engine-auth row is **verified**, meaning the key was
  actually proven against `api.kimi.com/coding` at save time.

Requiring verification on `kimi-code` is what stops a Moonshot pay-as-you-go key pasted into the
wrong box from presenting as a working membership engine.

One trap worth naming: `_moonshot_key` returns a **tuple**, and `("", "")` is truthy. Every gate
must test `(...)[0]`, not the tuple. Testing the tuple offers Kimi to every user regardless of
whether a key exists — the mistake is called out at three separate call sites for that reason.

---

## 6. Checklist when Kimi breaks

1. **Which product?** `kimi` vs `kimi-code`. Get this wrong and nothing else matters.
2. **401 on the `kimi` lane** → almost certainly the `.ai` / `.cn` split. Check the stored
   `base_url` on the key row, not just the key.
3. **401 on `kimi-code`** → a Moonshot key in the Kimi Code slot, or an unverified row.
4. **200 with an empty answer** → SSE parsing. Check the `data:` prefix handling before
   suspecting the model.
5. **Fails partway through a Build run with model-not-found** → a model slot that isn't pinned.
6. **Reasoning showing up unasked** → the `show_thinking` gate.
7. **Membership run billed to pay-as-you-go** → an ordering bug: something matched `kimi` before
   `kimi-code`.

## Related

- [`handoffs/2026-07-22-kimi-k3-k2.6-build-engine.md`](handoffs/2026-07-22-kimi-k3-k2.6-build-engine.md)
- [`handoffs/2026-07-24-kimi-code-membership-engine.md`](handoffs/2026-07-24-kimi-code-membership-engine.md)
- [`handoffs/2026-07-24-research-pipeline-never-ran.md`](handoffs/2026-07-24-research-pipeline-never-ran.md) — the same silent-success bug class
