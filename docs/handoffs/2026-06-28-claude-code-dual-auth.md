# Claude Code dual-auth — API key OR Claude subscription token (COMPLETE + real-token verified)

**Date:** 2026-06-28 · **Branch:** `harvis1.1` · **Status:** built, deployed, **E2E-verified with a real
Claude subscription token**, committed in the external-engines arc.

## Goal

Claude Code (the cloud Build engine, Phase E2) was **API-key-only**. The product truth is now:

> **Claude Code = a cloud Claude Build engine with per-user auth — an Anthropic API key, *or* a Claude
> subscription token. Subscription users (Pro/Max/Team/Enterprise) do NOT need API credits.**

The user picks the mode in the Integrations Connect panel; Harvis stores the chosen credential encrypted
and injects the matching env var at run time.

## How it works

| | API key mode | Claude subscription mode |
|---|---|---|
| User provides | an Anthropic API key | the token from `claude setup-token` (needs Pro/Max/Team/Enterprise) |
| Stored | encrypted, `user_engine_auth.auth_mode='api_key'` | encrypted, `auth_mode='oauth_token'` |
| Runtime env injected | `ANTHROPIC_API_KEY` | `CLAUDE_CODE_OAUTH_TOKEN` |
| Verify | cheap `max_tokens:1` Messages call | **a real `claude -p "Reply OK"` CLI smoke in the sidecar** |
| Readiness | `engine_readiness.claude-code.ready` once the sidecar is up + this credential verifies | same |

**Exactly one** credential env var is injected per run — **never both** (`ANTHROPIC_API_KEY` officially takes
precedence, so a stray one would silently shadow the OAuth token). Harvis never uses `--bare` (bare mode
ignores the OAuth token). Secrets are write-only at the UI, encrypted (Fernet), decrypted only at run time,
**never logged**. Per-user isolated.

### The root-cause gotcha (cost a debug cycle)

The E2 `claude-code/Dockerfile` bakes `ENV CLAUDE_CODE_SIMPLE=1` — "simple/bare mode reads auth **strictly**
from `ANTHROPIC_API_KEY`, no OAuth/keychain". With it on, a **valid** OAuth token makes `claude -p` print
**"Not logged in · Please run /login"** (to stdout) and exit 1 — the token is silently dropped. This is the
env-var twin of the documented `--bare` gotcha.

**Fix (no image rebuild):** control `CLAUDE_CODE_SIMPLE` **per-exec** by mode —
- `_build_claude_command`: `-e CLAUDE_CODE_SIMPLE=` (off) for `oauth_token`, `-e CLAUDE_CODE_SIMPLE=1` for
  `api_key`.
- `_verify_oauth_token_via_cli`: adds `-e CLAUDE_CODE_SIMPLE=` + `--dangerously-skip-permissions`, and
  captures **stdout** in the error (the CLI prints auth errors to stdout, so the old stderr-only capture
  surfaced a useless "exit 1").

Proof: bogus token with SIMPLE off → `401 Invalid bearer token` (token reached Anthropic); with SIMPLE on →
"Not logged in" (ignored). Sidecar egress to api.anthropic.com confirmed (no `curl` in image — use node).

## How the user uses it

1. **Operator:** `HARVIS_OWUI_EXTERNAL_ENGINES=1 docker compose up -d --build claude-code backend` (the
   engine flag makes Claude Code selectable in Build; the Connect panel works regardless).
2. **End user:** Integrations → **Claude Code** → Connection → pick **Claude subscription** → follow the
   3-step inline guide: run `claude setup-token` in a terminal, sign in, paste the token → **Connect &
   verify**. (Or pick **API key** and paste an Anthropic key.)
3. On verify success, Claude Code shows **ready**. In **Build / VibeCode** → new clone session → **Engine:
   Claude Code** → every turn runs on the chosen credential.

## Verification (this session)

| Check | Result |
|---|---|
| Schema `auth_mode` ALTER (idempotent on startup) | ✅ |
| Env injection: one var per mode, never both, no `--bare`, correct `CLAUDE_CODE_SIMPLE` | ✅ (unit test) |
| Status `supports_oauth` true for claude-code / false for codex; codex+oauth → 400 | ✅ |
| API-key verify routes to Anthropic HTTP | ✅ (bogus → 401) |
| OAuth verify routes to the CLI smoke (not the Messages API) | ✅ (bogus → CLI "401 Invalid bearer token") |
| **Real subscription token** → verify `ok=true`, readiness `ready:true` | ✅ |
| **Real Build run** via Claude Code on the OAuth token | ✅ created `hello.py` + diff in **6.3s, no API credits**, token not logged |
| No baked `ANTHROPIC_API_KEY` in the sidecar (no shadowing) | ✅ |
| Frontend build + deploy; friendly OAuth UI + corrected card copy | ✅ live on :9000 |
| `tests/test_engine_auth_modes.py` | ✅ 7 passing |

## Files

**Backend:** `workspace/orchestration/__init__.py` (`auth_mode` column + ALTER) · `owui_compat/engine_auth.py`
(dual save/verify/status, `get_verified_engine_auth`, `_verify_oauth_token_via_cli`) ·
`workspace/orchestration/engine_adapter.py` (`_build_claude_command` per-mode env + `CLAUDE_CODE_SIMPLE`) ·
`workspace/workspace_router.py` (threads `engine_auth_mode`).
**Frontend:** `lib/apis/integrations/index.ts` (`credential`+`auth_mode`) · `lib/integrations/ConnectionPanel.svelte`
(mode toggle + OAuth steps) · `lib/integrations/catalog.ts` (corrected Claude Code copy).
**Tests/docs:** `tests/test_engine_auth_modes.py` · `docs/guides/vibecode-external-engines.md` (dual-auth
section) · this doc.

## Follow-ups / notes

- **API-key mode** is plumbing-verified but not yet run with a *real* Anthropic key (needs a key paste); the
  OAuth path is fully real-token-verified.
- The `claude-code` Dockerfile still bakes `CLAUDE_CODE_SIMPLE=1` as the default; Harvis overrides it
  per-exec. A future cleanup could drop the bake entirely and set it only for API-key mode.
- Codex stays API-key-only (no subscription toggle) — `OAUTH_ENGINES = {"claude-code"}`.
