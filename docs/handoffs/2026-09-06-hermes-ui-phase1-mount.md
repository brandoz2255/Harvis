# Handoff — Mount the vendored Hermes UI at `/hermes` (Phase 1)

**Date:** 2026-09-06
**Branch:** `fixes`
**Status:** vendored, untracked, nothing wired yet
**Vault note:** `~/Nexusys/projects/hermes-ui-takeover.md` (background, license, full option set)

---

## Read this first: what you are and are not doing

You are **adding a second frontend**, mounted at `/hermes` on the existing
nginx at `:9000`. You are **not** touching owui, `location /`, or any existing
route. If your change makes `http://localhost:9000/` behave differently, you
have gone off-plan.

The goal of Phase 1 is to get the Hermes UI **rendering and talking to the
Harvis backend** so the owner can use it for a couple of weeks and decide
whether to pay for Phase 2 (the ~33k-line surface port). Phase 1 succeeding
does not commit anyone to Phase 2.

## What's already on disk

`front_end/hermes-desktop-ui/` — the Hermes desktop app, rsync'd from
`~/.hermes/hermes-agent/apps/desktop/` at upstream `29112bef0992`.
2,212 files, 33 MB, 1,068 non-test `.ts`/`.tsx`, 268,893 lines.
MIT © 2025 Nous Research; `LICENSE.upstream` is in the folder and **must
survive any distribution**. Untracked — `git add` it as your first commit.

## The precedent you are copying

This repo has already done exactly this once. The vendored open-notebook UI is
mounted at `/onb` with a compat facade at `/onb-api`:

- `nginx-harvis.conf:379-398` — `location = /onb` and `location /onb/`
- `nginx-harvis.conf:403` — `location /onb-api/` proxying `$backend_upstream`

Follow that shape. Difference: open-notebook is a Next server behind a proxy;
the Hermes UI is a **static SPA**, so yours is a `root` + `try_files` block like
`nginx-harvis.conf:437-439`, not a `proxy_pass`.

---

## Why the shim is smaller than it looks

Every OS-level call in the renderer goes through one contextBridge object,
`window.hermesDesktop` (`src/global.d.ts:17`). Measured:

- **911 references across 224 files** — but **207 of ~300 call sites are
  optional-chained** (`hermesDesktop?.x`), and **100 of the type's members are
  declared optional**. Leave those `undefined` and the app degrades on its own.
- **67 members are non-optional.** Of the hard call sites, `api` (36) and
  `openExternal` (26) are 62 of 93.
- **`api` is the entire backend surface and it is a fetch wrapper.**
  `src/global.d.ts:217` — `api: <T>(request: HermesApiRequest) => Promise<T>`,
  where `HermesApiRequest` (`:1185`) is `{ path, method?, body?, upload? }`.

Verified browser-safe: **zero renderer files import `electron`, `fs`, `path`,
`child_process` or `os`.** `vite.config.ts:105` sets `base: './'`;
`dev:renderer` runs Vite alone on :5174.

So the shim is one real fetch wrapper, one WS URL resolver, ~10 web-equivalents,
and a pile of stubs.

---

## Tasks

### 1. Commit the vendor drop
`git add front_end/hermes-desktop-ui/` as its own commit, message noting
upstream ref `29112bef0992` and MIT © 2025 Nous Research. Do not mix code
changes into this commit — a clean vendor commit is what makes the next
upstream re-sync a readable diff.

### 2. Write `src/lib/desktop-shim/` (the only real work)
Install a browser `window.hermesDesktop` before the app boots. Import it at the
top of `src/main.tsx` (entry per `index.html:37`).

**Implement for real:**
| Member | Browser implementation |
|---|---|
| `api` | `fetch('/api' + req.path, { method, body: JSON.stringify(req.body), credentials: 'include' })` → `.json()`. Multipart when `req.upload` is set. |
| `getGatewayWsUrl` | return `wss?://${location.host}/ws/...` matching the `GatewayWsUrlResult` shape at `src/global.d.ts:49` |
| `openExternal` | `window.open(url, '_blank', 'noopener')` |
| `readClipboard` / `writeClipboard` | `navigator.clipboard` |
| `notify` | Notification API, `Promise<boolean>` on permission |
| `getVersion` | a build-time constant |
| `settings`, `themes` | `localStorage` |

**Stub as "not available in browser"** (resolve to a benign value, never throw):
all bootstrap members (`getBootstrapState`, `getBootProgress`,
`continueBootstrapLocal`, `repairBootstrap`, `resetBootstrap`, `cancelBootstrap`,
`onBootProgress`, `onBootstrapEvent`), `terminal`, `openSessionInTerminal`,
`sshConfigHosts`, `sshResolveHost`, `selectPaths`, `readDir`, `readFileText`,
`revealLogs`, `uninstall`, `updates`, `findInPage`/`stopFindInPage`,
`watchPreviewFile`/`stopPreviewFileWatch`, `petOverlay`, `quickEntry`.
Every `on*` listener returns a no-op disposer.

**Do not** touch any file under `src/app/` in Phase 1. If a surface breaks
because a stub returned nothing, stub it better — do not patch the UI. Keeping
their tree unmodified is what makes upstream re-syncs cheap.

### 3. Point it at the Harvis backend
Decide where `api` requests land. Two choices — pick one and write down why:
- **`/api/` directly**, if Hermes' paths happen to line up with Harvis'; or
- **`/hermes-api/`**, a compat facade mirroring `/onb-api/`
  (`nginx-harvis.conf:403`) that maps Hermes paths onto Harvis handlers.

The endpoint mapping first pass is in the vault note under
*Endpoint mapping* — **verify every row against the live backend**, it was
written from type signatures, not from traffic.

### 4. Build and mount
- Set `base: '/hermes/'` in `vite.config.ts` (currently `'./'`).
- Add a `hermes-ui-builder` one-shot service mirroring `owui-builder`
  (`docker-compose.yaml:794`), `target: artifact`, output into a volume.
- Mount it read-only on nginx alongside owui, next to
  `docker-compose.yaml:855`'s `./front_end/owui/build:/usr/share/nginx/owui:ro`.
- Add to `nginx-harvis.conf`, **above** `location /`:
  ```
  location /hermes/ {
      alias /usr/share/nginx/hermes/;
      try_files $uri $uri/ /hermes/index.html;
  }
  ```
  Give its hashed assets the same 1y-immutable treatment as
  `location /_app/immutable/` (`nginx-harvis.conf:430`), and make sure the SPA
  shell itself is revalidated every load — the comment at `nginx-harvis.conf:441`
  explains what happens when it isn't, and it has already cost one debugging round.
- Put the whole thing behind a compose profile so a stock `up` doesn't build it.

## Done when

`http://localhost:9000/hermes/` loads the Hermes UI, a chat turn completes
against the Harvis backend, and `http://localhost:9000/` is byte-identical to
before. Report the endpoint mapping you actually verified, and the list of
members you stubbed that a real user visibly noticed missing — that list is the
input to the Phase 2 decision.

## Do not do in Phase 1

Porting any Harvis surface to React. Removing owui. Changing `location /`.
Changing the default compose profile. Rebranding. Touching `~/.hermes/` — that
is the owner's live Hermes install, running on `kimi-coding`/`k3`, and it must
keep working.

## Phase 2 (not yours yet — for context only)

~33,330 lines with no Hermes counterpart: agent-studio (18,597), CAD (7,905),
vibecode (3,300), notebooks/knowledge/integrations/projects/build/console
(~3,400), plus ~144 owui `admin`/`workspace` component files. Full table in the
vault note.
