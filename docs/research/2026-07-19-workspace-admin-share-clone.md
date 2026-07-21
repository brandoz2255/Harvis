# What /workspace and /admin are — and what Share/Clone would cost

**Date:** 2026-07-19
**Method:** 3 parallel code investigations (workspace surfaces · admin surfaces · Share+Clone scope)
against the real backend routes, then synthesis. Every claim traced to a file, not recalled.

# Briefing: /workspace, /admin, and the Share/Clone buttons

## 1. What /workspace is

**Short answer: it's Open WebUI's "Library" — five admin pages for reusable building blocks — and four of the five are either dead or worse versions of things Harvis already has. The whole section can be retired.**

The sidebar calls it "Library." Here's each tab, whether it works, and what already covers it:

- **Models** — for building custom assistant presets (name + avatar + system prompt + attached knowledge). **Dead, and visibly broken**: it shows a "Could not load models" error banner on load because it calls an endpoint that doesn't exist anywhere in the backend. Every create/edit/delete action 404s. This is also the page admins land on first when they open the Library, so the broken one is the front door. The job it was for is already covered by your custom Sub-Agents in Customize plus the model-profiles feature.
- **Knowledge** — document collections for RAG. **Read-only**: you can list and delete collections but cannot create, rename, or add files — all of that 404s. The backend routes that do exist were written so the chat composer's "Attach Knowledge" picker works, not for this page. Your own `/harvis/knowledge` page does everything this page does **plus creation**, against the same data. Straight duplicate, and the lesser one.
- **Prompts** — saved slash-command text snippets. **Dead**: zero backend routes, not even stubs. The list stays empty forever and creating one fails. No direct Harvis twin, but the job overlaps heavily with skills, and your queued "/" skill-picker plan already points that way.
- **Tools** — write Python plugin functions the server would run mid-chat. **Dead by design**: the list endpoint is a deliberate empty stub so chat boot doesn't break; everything else 404s. Harvis's real tool story is MCP + connectors + OpenClaw. Building this would mean running user-written Python on the server — a second, riskier path to a job you've already solved.
- **Skills** — SKILL.md packs. **This one actually works** — real backend, real database table. But it's an exact duplicate of the Skills manager you built in Settings → Customize, which hits the same routes and same table and is the better UI (it has GitHub browse/import and the audit/governance views; the workspace page doesn't). Two UIs, one dataset; this is the lesser twin.

Who can see any of this: admins only, and "admin" means user id 1 (or ids listed in an env var). There is no UI to change that — the permissions screens it would need don't exist in the backend.

The investigator's overall call, which I agree with: the only unique thing `/workspace` hosts is a redundant skills list, so the cheapest coherent move is to retire the shell entirely and point the "Library" sidebar entry at `/harvis/knowledge` (or remove it). There's also an orphaned `workspace/functions/create` page with no nav link — same cleanup batch.

## 2. What /admin is

**Short answer: it's Open WebUI's multi-tenant server administration — built for someone running a team server with many users. Almost none of it talks to your backend. Of five surfaces and thirteen settings tabs, exactly two slivers work: the Models list (read-only) and the Audio config (read-only; its Save button pretends to work but discards everything). The rest 404s.**

- **Users & Groups** — list accounts, change roles, organize people into permission groups. **Dead.** The page shows an error toast and an empty table. This is the one surface with a genuinely Harvis-relevant kernel: if you ever share your instance, you currently have *no way at all* to see who has accounts or turn off signup (signup is open by default). But that argues for a small "who's on my server + disable signup" panel someday, not upstream's full roles/groups machinery.
- **Analytics** — usage dashboards. **Dead**, and visible in the nav only because a config flag was never set (the frontend defaults a missing flag to "show it"). One line in the backend config hides it. If you ever want usage stats, your Dev Console at `/harvis/console` is the working, Harvis-native place to grow them.
- **Evaluations** — a model leaderboard built from thumbs-up/down ratings. **Dead twice over**: no backend routes, and message rating is deliberately turned off so the data it would display is never collected.
- **Functions** — upstream's server-side Python plugin system. **Dead**, and it manages plugins for a backend you replaced. Skills, MCP, and sub-agents are your equivalents. (The empty-list stub must stay — chat boot depends on it.)
- **Settings (13 tabs)** — the *needs* are real (models, connections, TTS, RAG config) but roughly 11 of 13 tabs are dead, and everything they cover already lives somewhere Harvis-native: Connections/Integrations → `/harvis/integrations`; Documents/Web Search → `/harvis/knowledge`; Models → your live catalog and per-user model settings; Audio → fixed by env vars anyway; Database → your `database-backup/` scripts. The Audio tab's Save button is the worst offender: it says "saved" and silently throws the input away.

**The security finding you should know about** (detail in section 5): the admin gate is client-side only, and there is no server-side admin check anywhere in the backend. Today that's mostly harmless because the admin routes don't exist — a 404 is decent access control. But it's a loaded trap for future work.

## 3. Recommendations

| Surface | Call | Why |
|---|---|---|
| /workspace → Models | **HIDE** (delete with the shell) | Error banner on load, no backend, and it's the Library's landing page — worst first impression in the app. Job covered by Sub-Agents + model profiles. |
| /workspace → Knowledge | **DELETE (duplicate)** | `/harvis/knowledge` does everything it does plus creation. Keep the backend read routes — the chat composer's Attach Knowledge picker needs them. |
| /workspace → Prompts | **HIDE** | Zero backend. If you ever want snippets, fold them into the planned "/" skill picker instead of implementing upstream's prompt routes. |
| /workspace → Tools | **HIDE** | Deliberately stubbed; implementing it means running user Python on your server for a job MCP + OpenClaw already do. |
| /workspace → Skills | **DELETE (duplicate)** | Backend is real, but Settings → Customize is the better UI on the same data. One skills UI is enough; this isn't the one. |
| /admin → Users | **IMPLEMENT (minimal), later** | The one admin job you genuinely have: list accounts, delete one, toggle signup. Must land together with a server-side admin check. Skip groups/permissions entirely. |
| /admin → Groups | **HIDE** | Permission machinery for a product model you don't have. |
| /admin → Analytics | **HIDE** | One line in the backend config removes it from the nav. Grow the Dev Console instead if stats ever matter. |
| /admin → Evaluations | **HIDE** | Its data source is deliberately off; it can never work without re-adopting upstream's rating system. |
| /admin → Functions | **HIDE** | Plugin manager for a backend you replaced. Keep the empty-list stub. |
| /admin → Settings | **HIDE** (all of it, or all but a read-only Models view) | Eleven dead tabs plus a Save button that lies. Real configuration lives in `/harvis/integrations`, `/harvis/knowledge`, chat Settings, and env vars. |
| Chat → Clone button | **IMPLEMENT** | Small, useful, no security surface. Detail below. |
| Chat → Share button | **HIDE for now** | Silently fails today; the feature is medium-sized and near-useless on a single-operator install. Detail below. |

## 4. Share + Clone: what building them actually costs

**Clone: build it. Small — roughly half a day including verification.** The button already exists in the chat right-click menu; it 404s today. Because each chat is stored as one self-contained blob in a single table, cloning is essentially "insert a new row with the same content and a new title" — one backend route, about 20 lines reusing functions that already exist, no schema change. The investigator checked the traps: attachments are shared by reference between original and clone (fine, since both belong to the same owner — worst case is deleting a file from one chat breaks its preview in the other), and background-job artifacts don't follow the clone (which is the correct behavior — a clone starts clean). For one person, "branch this conversation and retry with a different model" is a real daily-use feature.

**Share: skip it, and hide the button. Medium — 2 to 3 days done honestly — and it doesn't earn that on your deployment.** Two things you should know:

- **The "public URL" fear doesn't actually apply in this fork — but that also kills the feature's point.** The investigator confirmed that the shared-chat viewer page sits behind your login wall: any visitor without a valid session gets bounced to the login page, with no exception for share links. So a share link is only viewable by *people with accounts on your Harvis instance*. On a single-operator box, that means sharing chats with yourself. (This is a place where I side with the shareclone investigator against any earlier framing of Share as a quick win: it's the more expensive of the two features *and* the less useful one here.) If you ever want links that work without an account, that's a deliberate, separate decision — it requires punching a hole in the auth wall and accepting that anyone with the URL sees the content until revoked. Don't stumble into it.
- **If you ever do build it, the trap is the snapshot promise.** The share dialog tells users "messages you send after creating your link won't be shared." Honoring that requires freezing a copy of the chat at share time. The lazy implementation — a link that looks up the live chat — makes that promise a lie and leaks future messages to anyone holding the link. There's also an access-restrictions panel in the dialog that would either need full implementation or removal; leaving it half-built would show restrictions that aren't enforced.

Meanwhile the actual job — "show someone this conversation" — already works today with no backend at all: the same chat menu exports to JSON, plain text, and PDF. Sending a PDF beats standing up a share-links subsystem.

Today the Share button fails *silently* (per the code, no error toast — runtime behavior unverified but that's what the code says), which is the worst failure mode. Hiding the two Share menu entries is about a 10-minute change and makes the UI honest. Revisit Share for real if Harvis goes multi-user.

## 5. What else is needed — things you haven't been told yet

1. **The admin security trap (most important item in this briefing).** The "admins only" gate on `/admin` and `/workspace` is enforced only in the browser. The backend has no server-side admin check anywhere — no helper function for it even exists. Today this is mostly harmless because the admin routes 404 for everyone. But the first time anyone implements a users route or a config route in the backend without adding a real admin check, that route ships to **every signed-in user**. There's already a live example of the pattern: the audio config-update endpoint is reachable by any logged-in user (harmless only because it's a no-op). **Recommendation: add a `require_admin` server-side dependency to the backend *before* any admin feature gets built, so future work has the right thing to copy.** This is a small, standalone change.

2. **On a fresh internet-reachable install, whoever registers first becomes admin.** Signup is open by default and admin is "user id 1." Fine on a laptop; worth documenting — and worth a "disable signup" switch — for anyone deploying this as an open-source product for others, which is exactly the direction you're taking it.

3. **The Audio settings Save button lies.** It reports success and persists nothing. If the Settings tabs get hidden per the table above, this goes away with them; otherwise it deserves its own fix, because a control that pretends to work is worse than one that errors.

4. **Analytics appears in the admin nav purely by accident** — a missing config flag that the frontend defaults to "on." One line in the backend config hides a fully dead dashboard.

5. **Small cleanup items for the same batch:** an orphaned `workspace/functions/create` page with no navigation link to it; the workspace Skills tab lacking the sharing route the other skills UIs also lack (moot if the tab is deleted); and the chat composer's "/" command menu quietly calling the nonexistent prompts endpoint (it swallows the failure, so it's cosmetic — but it stops mattering entirely if prompts stay hidden).

6. **One point of investigator disagreement, surfaced rather than averaged:** the workspace investigator suggested Prompts could someday be worth folding into skills; the share/clone investigator's broader principle — don't implement upstream routes for jobs Harvis already answers differently — points the same direction. Nobody recommends implementing upstream's prompts API. The only genuine build recommendations to come out of all three reports are: **Clone (small, now), a server-side admin check (small, before anything else admin-shaped), and a minimal Users panel (later, only if you start sharing your instance).** Everything else is hide or delete.