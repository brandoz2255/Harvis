# Handoff — how we prep the push to `main`

**Date:** 2026-08-26
**Written from:** `test/fresh-clone-2026-08-23` @ `eb7a3f67`
**Status:** planning only. Nothing merged, nothing pushed, no refs touched. The measurements below
came from `git merge-tree --write-tree` (read-only) and `git diff`.

---

## 1. The one number that decides everything

```
merge base:  483e3cf5   2026-03-18
origin/main is  206 commits  ahead of that base   (last one 2026-05-06)
our branch  is  416 commits  ahead of that base   (last one 2026-08-26)
```

`main` and the working branch **split on 18 March and never rejoined**. `main` has not moved since
6 May. This is not a fast-forward and it is not a small merge — it is a five-month fork where both
sides kept building.

## 2. What is actually on `main` that we don't have

206 commits, 170 files, 204 of them authored by `brandoz2255`, all between 2026-03-18 and
2026-05-06. By area:

| Area | Files | What it is |
|---|---|---|
| `k8s-manifests/overlays/` + `services/` | 23 | The prod K8s/ArgoCD deployment — Hermes pinned through v0.11.5, OpenClaw image bumps, rolling-update strategy, readiness probes, OpenCode env wiring |
| `front_end/newjfrontend/` | 23 | The **old Next.js frontend**. Superseded by `front_end/owui/` on our side |
| `python_back_end/mcp_server/` | 11 | MCP server work |
| `skills/Harvis/` | 8 | Skill definitions |
| `.planning/`, `.opencode/plans/`, `scripts/`, docs | rest | Planning notes, helper scripts, a large root-`*.md` → `docs/` reorganisation |

**The judgement call this doc exists to surface:** of those five areas, only the K8s/ArgoCD
manifests are plausibly still wanted. `newjfrontend` is dead on our branch. The rest is either
superseded or notes. **That call is the user's, not mine** — see §5.

## 3. What the merge actually costs, measured

Dry-run merge of `origin/main` into `test/fresh-clone-2026-08-23`: **36 conflicting paths.**

| Kind | Count | Nature |
|---|---|---|
| `rename/delete` | 22 | `main` moved root `*.md` into `docs/`; our branch deleted those files outright. Mechanical — resolve by keeping the deletion |
| `modify/delete` | 1 | `README.md` — deleted on `main`, rewritten on ours. Keep ours |
| `content` | 13 | Real. Four of these are also docs; **nine are code** |

The nine real code conflicts, with how much each side changed since the split:

| File | `main` side | our side |
|---|---|---|
| `python_back_end/main.py` | +771 / −155 | **+2076 / −191** |
| `python_back_end/workspace/model_proxy.py` | +42 / −24 | **+1353 / −18** |
| `k8s-manifests/overlays/prod/openclaw.yaml` | +136 / −293 | +180 / −17 |
| `ci_openclaw_pipeline.sh` | +219 / −89 | +71 / −9 |
| `k8s-manifests/overlays/prod/kustomization.yaml` | +123 / −17 | +3 / −3 |
| `python_back_end/research/llm/ollama_client.py` | +107 / −106 | +36 / −12 |
| `nginx.conf` | +26 / −0 | +42 / −212 |
| `python_back_end/agent_research.py` | +29 / −9 | +220 / −67 |
| `.gitignore` | +6 / −0 | +114 / −5 |

`main.py` and `model_proxy.py` are the dangerous ones. Ours rewrote them; `main`'s versions are five
months stale. A careless three-way resolve there reintroduces dead code into the file every request
flows through.

## 4. Blockers to clear before any push, regardless of strategy

These are ours, not merge-related, and each is independently checkable.

1. **Uncommitted work is two unrelated piles that must not be committed together.**
   - This session's Engines-tab pass: **14 files** under `front_end/owui/src/lib/integrations/` and
     `routes/(app)/harvis/integrations/` (documented in
     `2026-08-26-engines-light-mode-and-contrast.md`).
   - The user's live CAD work: **24 tracked** files (`cad-engine/`, `owui_compat/cad_*.py`,
     `lib/cad/*`, CAD tests) plus **67 untracked** files, nearly all CAD.
   The first pile is ready. The second is the user's and is not mine to commit.

2. **Dev-machine paths in tracked files** — the standing rule is that Harvis ships to strangers and
   no tracked file carries a dev path or a home IP. Still present:
   - `embedding/config.py:18-20`, `embedding/docker-compose.yml:13`, `embedding/run-embedding.sh:69,87`
     → hardcoded `/home/guruai/compose/rag-info`.
   - `harvis-helm-chart/values.yaml:177`, `metallb-config.yaml`, `k8s-manifests/**` → `192.168.4.24x`
     LoadBalancer IPs. Defensible for an infra overlay, but they should be values, not literals.
   - `python_back_end/tests/test_ollama_hosts.py:34` → `http://192.168.5.58:11434`, a real rig.
   (Placeholder IPs inside `placeholder="…"` attributes are fine — those are UI hints.)

3. **`python_back_end/__pycache__/browser.cpython-311.pyc` is tracked.** One committed bytecode
   file. It should be removed and the directory ignored.

4. **The test VM is behind.** 192.168.4.201 is still on `eb7a3f67`; the Engines-tab work has not
   been deployed there. E2E verification on a clean box is the last gate before any of this is
   called releasable.

## 5. The decision that has to come first

Three strategies. They differ in what happens to `main`'s 206 commits, and that is the whole
question.

**A — True merge.** `git merge origin/main` on the branch, resolve all 36, then push the branch to
`main`. Keeps every commit on both sides. Costs a careful resolve of nine code conflicts, two of
which are heavily-rewritten hot files, with a real chance of resurrecting five-month-old code.

**B — `main` becomes the branch.** `git merge -s ours origin/main` records the merge (so `main`'s
history is preserved and future merges behave) while taking **none** of its content, then push. Zero
conflicts. The cost is explicit and total: the K8s/ArgoCD manifests as they exist on `main` are
gone from the tree.

**C — Salvage, then B.** Cherry-pick only the K8s/ArgoCD manifest commits worth keeping
(`k8s-manifests/overlays/`, `k8s-manifests/services/` — roughly the 23-file group in §2), verify
them, then `-s ours` the remaining 183 and push.

**Recommendation: C.** It is the only one that both keeps the deployment manifests and refuses to
drag `newjfrontend` and the March planning notes back into the tree. B is the honest fallback if
the manifests turn out to be dead too — the whole cluster story has moved since May.

**What is needed from the user before any of this runs:**
- Are the 206 commits still wanted at all, or is `main` simply stale?
- If strategy C: is `k8s-manifests/` the only area worth salvaging, or does `python_back_end/mcp_server/`
  or `skills/Harvis/` carry something live?
- Explicit go-ahead to push to `main` — this branch has been pushed only to
  `test/fresh-clone-2026-08-23` all along, and that stays true until told otherwise.

## 6. Sequence, once the decision is made

1. Commit the 14 Engines-tab files on their own. Leave the CAD piles alone.
2. Clear §4 items 2 and 3 as their own commits — path/IP cleanup, drop the tracked `.pyc`.
3. Build owui, verify by string presence in the bundle (never by exit code — it lies two ways on
   this repo), restart nginx, spot-check both themes.
4. Deploy to VM 192.168.4.201, run the fresh-clone install path, confirm 10/10 services.
5. Only then execute the chosen merge strategy on a scratch branch first, build and run from that
   result, and confirm the stack still comes up.
6. Push to `main` with an explicit refspec, after the user says so.

Steps 1–4 are worth doing regardless of which strategy wins, and none of them touch `main`.
