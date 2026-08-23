# Handoff — free-tier LLM providers + the main-chat usage meter (2026-08-01)

**Branch:** `harvis1.2` (main tree at `/home/user/Harvis`), HEAD `095678a5`.
**Rig:** local dev box, stack up via `docker compose`, UI at `http://localhost:9000`.
**Verified:** backend live, frontend built and served. **Nothing is committed and nothing is pushed.**
Per-change detail is in `changes.md`; this is the orientation document.

---

## What this arc was

The user asked to drop OmniRoute and build free-tier LLM access directly instead:

> "ok lets move without omni route and lets move iwth the free llm api stuff"

and then, once the backend lane existed:

> "we are gioing to need the UI part we have to get the user to see and use it while also
> tracking how many tokens and costs are used just like how it is in the build area just in
> the main chat"

and:

> "fix those bugs and then realize that integrtions is engines tab now / but feel free to make
> whatever is needed to help a new user get the api keys for free"

So: five BYO-key providers, cards for them on the Engines tab, an onboarding path to go get the
keys, and a token/cost meter in the main chat composer.

## What OmniRoute turned into

Nothing. It was trialled locally (2.63 GB image), and the conclusion was that Harvis needs the
*providers*, not the *gateway*. `docs/research/2026-07-30-omniroute.md` and
`docs/design/2026-07-31-omniroute-scope.md` hold the measurement and the scope that was abandoned.
The planned 205-entry `provider_catalog.py` was never written — `free_providers.py` is a five-row
table instead, which is what the product actually needed.

`github.com/cheahjs/free-llm-api-resources` has **`license: null`**. It was read as a reference and
never vendored, forked, or copied. Don't change that without a license appearing upstream.

**Cleanup still on disk:** `docker-compose.omniroute-trial.yml`, `.env.omniroute-trial` (holds
secrets — gitignored at `.gitignore:151`), and that `.gitignore` line. Delete when convenient.

---

## The backend lane

`python_back_end/owui_compat/free_providers.py` (new) — a table of five providers:

| id | vendor | `stream_usage` |
|---|---|---|
| `groq` | Groq | `True` |
| `cerebras` | Cerebras | `True` |
| `gemini` | Google AI Studio | `False` |
| `nvidia` | NVIDIA NIM | `True` |
| `mistral` | Mistral | `True` |

Each row carries base URL, key env/credential name, and a model-discovery endpoint. Credentials are
the user's own, entered in the UI, stored through the existing engine-auth path. **No shared key
pool, no key shipped in the repo or an image** — that constraint predates this work and still holds.

`cloud_chat.py` builds the model entries. Free-provider entries declare
`"capabilities": {"usage": True}` and `price_in: 0` / `price_out: 0` — stating zero explicitly
rather than leaving it unset, because the meter's "is this free" test is *both prices are zero*.

`stream_usage` exists because vendors disagree about `stream_options`. Gemini is `False` from the
start; the others start `True` and get demoted at runtime by `note_stream_usage_rejected()` into
`_stream_usage_denied` when an upstream 400s on the field.

## The two bugs fixed on the way to the meter

**1 · Local models never reported tokens.** `Chat.svelte:2829` only appends
`stream_options: {include_usage: true}` when the model declares
`info.meta.capabilities.usage`. `translate.py`'s `harvis_models_to_owui` emitted no `info` at all,
so every native/Ollama model silently opted out of usage reporting and the meter would have read
zero forever. Fixed at `translate.py:151` — native entries now declare
`{"meta": {"capabilities": {"usage": True}}, "params": {}}`.

**2 · That declaration would break unknown upstreams.** A server that has never heard of
`stream_options` rejects the *whole request* with a 4xx, so declaring the capability universally
would trade a working chat for a token count on somebody's llama.cpp build. Fixed in
`workspace/model_proxy.py`: `_stream_from_upstream` is now a thin retry wrapper around
`_stream_from_upstream_once`. On a 4xx **where `stream_options` was actually in the body**, the
wrapper drops the field and retries exactly once. Safe because a non-200 means nothing has been
yielded yet.

Guards that matter if you touch this: the retry only fires when `state is not None` (the second
attempt passes `None`, so it can't recurse), and only when `"stream_options" in body` — a 4xx on a
request that never carried the field is a real failure and still reaches the user.

Proven with a fake httpx client, three cases: upstream 400s with the field then 200s without →
two attempts, zero error events, usage forwarded. 400 without the field → one attempt, error
surfaced. Retry also fails → exactly two attempts, error surfaced.

Before flipping the capability I probed the real Ollama at `host.docker.internal:11434` (8 models
installed): a live streamed request returned
`{'prompt_tokens': 67, 'completion_tokens': 8, 'total_tokens': 75}`. It honours the field.

---

## The frontend

**Engines tab** — `/harvis/integrations` is the same route; it's titled *Engines* in the UI. Five
cards added to `integrations/catalog.ts` (`groq-api`, `cerebras-api`, `gemini-api`, `nvidia-api`,
`mistral-api`) with `authEngine`, `keyConsoleUrl`, `keyHelp`, `freeTier`, and
`detect.serviceKey` — that last one is what lets `mergeLiveStatus` map the backend probe onto the
card. Without it a connected provider still reads as disconnected.

**"Get free API keys"** — `integrations/FreeKeysGuide.svelte` (new), a modal reached from the
Engines header and from a callout that appears when no model provider is configured. Its list is
derived, not hand-written: `CATALOG.filter(d => d.freeTier && d.keyConsoleUrl)`. Add a card with
those two fields and it shows up here automatically.

**The meter** — `components/chat/ChatUsageMeter.svelte` (new), mounted as the first child of the
composer's right cluster in `MessageInput.svelte`, hidden below `sm:`. Pure derivation, no fetch
and no store of its own:

- It walks `parentId` from `history.currentId` rather than summing `history.messages`. The map
  holds every sibling of every regenerate and edit, so summing it bills the user for branches they
  walked away from. Tested against a fixture with an abandoned 999,999-token branch — excluded.
- It reads **both** usage shapes: OpenAI-compatible (`prompt_tokens`/`completion_tokens`) and
  Ollama native (`prompt_eval_count`/`eval_count`). One thread can switch models mid-way, so
  picking one shape would zero out half a conversation.
- It renders nothing until a reply actually carries usage. An empty gauge on a fresh chat says "0"
  without meaning it.

`agent-studio/UsageMeter.svelte` gained two **additive** props so `RunView` and the VibeCode
composer are untouched: `placement: 'top' | 'bottom'` (default `bottom`; the chat composer sits at
the bottom of the viewport, where a downward panel opens off-screen) and `freeLabel` (default
`"Free · local"`; a connected free-tier vendor key is free but *not* local, so the chat passes
plain `"Free"` rather than letting the meter claim something untrue about where it ran).

---

## Verification actually performed

- `npm run build` in `front_end/owui` → `✓ built in 1m 12s`.
- `docker compose restart backend nginx`; backend `/health` → 200. (`/api/health` is a 404 — the
  path is `/health`. `/api/models` correctly 401s without auth.)
- Live in-container check: native model entry meta reads `{'capabilities': {'usage': True}}`;
  retry wrapper present.
- Bundle chunks confirmed on disk under `/usr/share/nginx/owui` and HTTP 200: `chunks/BZDq0q2J.js`
  (the meter — contains `bottom-full mb-2`) and `chunks/CY-neG0p.js` (the composer mount).
- Derivation and retry logic each proven against fixtures, described above.

**Not verified:** an end-to-end run with a real vendor key. Only the user can supply one — that's
task **#106** and it's the honest gap in this arc.

## Known gaps

- **#110** — paid cloud entries (`cloud_chat.py:328`) still declare `"capabilities": {}`, so the
  meter stays hidden on Claude, OpenAI, and Kimi. That's exactly where cost matters most. The fix
  is plumbing `usage_provider` through the paid dispatch path the way the free path already has it;
  it wasn't shipped blind because verifying it needs real vendor keys.
- **#106** — live E2E with a free key.
- **#102** — provider fallback chain in `model_proxy` (independent of everything above).

## Deploy mechanics (so the next session doesn't rebuild needlessly)

`owui_compat/`, `workspace/`, and `main.py` are bind-mounted from the main repo into
`harvis-backend`. Python edits go live on `docker compose restart backend` — no image rebuild.
Frontend needs `npm run build` in `front_end/owui`, then `docker compose restart nginx` (nginx
bind-mounts `front_end/owui/build` → `/usr/share/nginx/owui`).

## Next

Sequenced by the user: free-LLM providers first (this), **screenshot-to-code second**. The spec is
already written at `docs/design/2026-07-31-screenshot-to-code-build-spec.md` and nothing is built.
