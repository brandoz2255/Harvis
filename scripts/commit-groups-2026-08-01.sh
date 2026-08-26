#!/usr/bin/env bash
# Step 8 commit plan for the 2026-08-01 integration pass (agent-reach,
# screenshot-to-code, sentrysearch, skillopt + the in-flight free-provider,
# usage-meter, integrations-redesign and storefront work).
#
# Local commits only. Nothing is pushed. Both new feature flags stay false.
# Run from the repo root on branch harvis1.2.
#
# Amended 2026-08-02: the original plan was written at 16:51 on 08-01, BEFORE the
# attachments arc (22:36) and the SkillOpt/Agent-Reach arc (23:54), so it silently
# left 155 insertions behind while still printing "Done." Groups 9 and 11 are new,
# and the gate tests + E2E harness were added to their existing groups.
#
# Amended again 2026-08-02 evening: the plain-chat Agent Reach arc and the runner
# honesty / event-redaction arc both landed after the last amendment, leaving 9 more
# files uncovered. Groups 15 and 16 are new.
#
# A file may appear in exactly ONE group. git commits whole files here, so a second
# group naming an already-committed file stages nothing, `git commit` exits 1 on an
# empty commit, and `set -e` kills the run halfway through. That is why runner.py and
# workspace_router.py moved OUT of group 10 and into group 16 — they carry edits from
# both arcs and can only be committed once.
#
# NOT committed on purpose:
#   docker-compose.omniroute-trial.yml  — OmniRoute was dropped; trial leftover.
#   scripts/commit-groups-2026-08-01.sh — this file; a single-use commit plan.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

commit () {   # commit <subject+body via stdin> -- paths...
  local msg; msg="$1"; shift
  git add -- "$@"
  git commit -q -m "$msg"
  git --no-pager log --oneline -1
}

# 1 — MCP client runtime
commit "$(cat <<'EOF'
feat(mcp): MCP client runtime, catalog and connection wizard

Runs MCP servers as sibling sandbox containers rather than in-process: the
backend image ships neither node nor uv, so a stdio server can only start
next to it. Off by default behind HARVIS_MCP_RUNTIME_ENABLED.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/plugins/mcp/protocol.py \
   python_back_end/plugins/mcp/runtime.py \
   python_back_end/plugins/mcp/tool_bridge.py \
   python_back_end/owui_compat/mcp_catalog.py \
   python_back_end/owui_compat/mcp_wizard.py

# 2 — sentrysearch MCP server
commit "$(cat <<'EOF'
feat(mcp): sentrysearch server for semantic video search

Packaged as a standalone MCP server image rather than a backend module, so it
carries its own embedding dependencies instead of growing the core image.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" mcp-servers/

# 3 — lane-5 authorization
commit "$(cat <<'EOF'
refactor(authz): pick the lane-5 flag per capability, not per lane

Lane 5 now holds SSH, MCP connectors and the screenshot verify loop. One
shared flag would have meant enabling remote shell access in order to use a
filesystem connector, so each capability answers to its own env flag.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/workspace/orchestration/authz.py

# 4 — free-tier providers, backend
commit "$(cat <<'EOF'
feat(providers): free-tier LLM providers (Groq, Cerebras, Gemini, NVIDIA, Mistral)

BYO-key only — no shared or rotating pool, and no key ships in the repo or an
image. Per-provider fields cover the vendor quirks: Gemini reports a bad key as
400, NVIDIA serves its model list without auth.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/owui_compat/free_providers.py \
   python_back_end/owui_compat/cloud_chat.py \
   python_back_end/owui_compat/engine_auth.py \
   python_back_end/owui_compat/integrations_status.py

# 5 — chat token/cost meter
commit "$(cat <<'EOF'
feat(chat): token and cost meter in the composer

capabilities.usage is the gate that makes the chat ask for token counts; a
model that declares nothing reads zero forever. Streaming responses carry no
usage object unless the request sets stream_options, and upstreams that have
never heard of that field reject the whole request, so model_proxy retries once
without it rather than breaking chat for a token count.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" front_end/owui/src/lib/components/chat/ChatUsageMeter.svelte \
   front_end/owui/src/lib/components/chat/MessageInput.svelte \
   front_end/owui/src/lib/agent-studio/UsageMeter.svelte \
   python_back_end/workspace/model_proxy.py \
   python_back_end/owui_compat/translate.py

# 6 — integrations redesign + free-key guide
commit "$(cat <<'EOF'
feat(integrations): redesigned panel, brand marks and free-key guide

Providers becomes Engines & Connectors and moves up the sidebar — it is the
first thing a fresh install needs. FreeKeysGuide links each free tier's own
signup page; cheahjs/free-llm-api-resources is linked, never vendored (it has
no licence).

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" front_end/owui/src/lib/integrations/ \
   front_end/owui/src/lib/agent-studio/customize/brandMarks.ts \
   front_end/owui/src/lib/agent-studio/customize/ConnectorLogo.svelte \
   front_end/owui/src/lib/components/chat/Placeholder.svelte \
   front_end/owui/src/lib/components/layout/Sidebar.svelte \
   "front_end/owui/src/routes/(app)/harvis/integrations/+page.svelte" \
   "front_end/owui/src/routes/(app)/harvis/console/+page.svelte" \
   front_end/owui/src/lib/i18n/locales/en-US/translation.json

# 7 — plugins/skills storefront
commit "$(cat <<'EOF'
feat(skills): Plugins | Skills storefront and bundled skill seeding

Bundled filesystem skills seed into owui_skills with a server-side 'supported'
verdict that CRUD cannot forge. Connectors is renamed Plugins and paired with a
Skills surface behind one switch.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/owui_compat/skills.py \
   front_end/owui/src/lib/agent-studio/customize/SkillsPanel.svelte \
   front_end/owui/src/lib/agent-studio/customize/ConnectorsPanel.svelte \
   front_end/owui/src/lib/agent-studio/surfaces.ts \
   front_end/owui/src/lib/components/chat/Settings/Skills/SkillsBrowse.svelte \
   front_end/owui/src/lib/components/chat/Settings/Skills/SkillsManager.svelte \
   front_end/owui/src/lib/components/chat/SettingsModal.svelte \
   skills/Harvis/harvis-build/ \
   skills/Harvis/harvis-agent/SKILL.md

# 8 — Agent Reach
commit "$(cat <<'EOF'
feat(agent-reach): lane-5 web reach with SSRF guards and honest failures

Every redirect is re-validated and resolved addresses are re-checked to close
DNS rebinding. A feed that will not parse returns ok:false with the reason
instead of an empty success. Off by default; never installed inside OpenClaw.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/agent_reach/ \
   skills/Harvis/harvis-agent-reach/ \
   scripts/agent-reach-e2e.py \
   docs/design/2026-08-01-agent-reach-lane5.md

# 9 — Build run view: real preview pane, and a finished run that says so
commit "$(cat <<'EOF'
fix(build): the run view showed a preview it never had and a task that never ended

The Preview tab was hardcoded off behind a false const, so the run's primary
artifact had nowhere to go but an inline card in the thought stream. It is now a
slot the parent fills, and the tab appears only when a preview actually exists —
still no permanent empty promise, but a real pane when there is something to show.

The pulsing "Working…" over a finished task was a stream artifact: a view mounted
on an already-complete run starts at phase 'connecting', and a replay that closes
without a terminal event leaves it there forever. The run record's status is the
authority now; the stream is only a live hint.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" front_end/owui/src/lib/agent-studio/RunView.svelte \
   front_end/owui/src/lib/agent-studio/build/WorkspaceMainPanel.svelte

# 10 — screenshot-to-code + sandboxed preview
commit "$(cat <<'EOF'
feat(vision): screenshot-to-code sends real image bytes and requires vision

The attached screenshot now travels as a multimodal image_url part all the way
to the provider, instead of the model inferring a UI from the file name. A turn
that carries images checks the model first and refuses with an actionable
message; the check blocks only on positive evidence of no vision, so unknown
and unreachable models still pass.

Suggestions require vision AND tools: the Build runner always offers a tool
schema and Ollama answers 400 for a vision-only tag. Attachment resolution is
confined to data: URIs, IMAGES_DIR, file_id sidecars and the Discord CDN, with
a 20 MB cap and no redirects. Preview rendering is data:-URL only in
browser-runner — no arbitrary JS, no internal network, no CDN.

Verified: unit probes, capability verdicts against all 14 installed tags, and a
wire capture proving the provider receives decodable image bytes. Not verified
on this box: a vision model actually reading the pixels — Ollama cannot load
any model while ~5.5 GB of the 8 GB GPU is held by another project.

Flag stays false: HARVIS_VISION_SELF_CHECK_ENABLED.

The matching runner.py and workspace_router.py edits ride in the runner-honesty
commit below — those two files also carry the tool-result budget and the event
redaction, and git can only commit each of them once.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/vision_to_code/ \
   python_back_end/workspace/orchestration/session_turn.py \
   python_back_end/workspace/orchestration/tools.py \
   python_back_end/integrations/discord_workspace_bot.py \
   browser_runner/app.py \
   browser_runner/Dockerfile \
   front_end/owui/src/lib/apis/streaming/runStream.ts \
   front_end/owui/src/lib/agent-studio/build/BrowserPanel.svelte \
   "front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte" \
   docs/design/2026-07-31-screenshot-to-code-build-spec.md

# 11 — attachments on every Build lane
commit "$(cat <<'EOF'
feat(build): attachments reach every engine, not just the multimodal lanes

The API lanes (Kimi, cloud and local Ollama) now send a real image_url part
instead of a line of text naming a file the model cannot open, and every
sub-agent gets the same attachments — one that cannot see the screenshot writes
about a screenshot it imagined.

The CLI engines get the bytes on disk instead. Their sidecar mounts
/data/artifacts and nothing else: no route to the Harvis API, often no curl. Given
only a URL, the CLI spends the whole run hunting for a file it can never reach and
then reports itself blocked, so the attachment is staged next to its working tree
and the brief carries the real path.

An image that could not be delivered emits a plain-English skipped line — an image
the model never received must not read as one it chose to ignore. And when a
request carried an image, a 4xx now blames a text-only model before it blames the
API key.

Riding along inside engine_adapter.py, because git can commit a file once:
_cad_mcp_args(), which registers the Harvis CAD tool server with the Claude Code
and Kimi Code sidecars and injects the conversation id, the user's verbatim text
and the real provider/model as an authenticated header the model cannot forge. It
belongs to the CAD authoring gates and is described in full there — see the 7C-3b
section of scripts/commit-gate7bc-authoring.sh, which deliberately leaves this
file to this commit rather than fight it for the path.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/workspace/kimi_workspace.py \
   python_back_end/workspace/orchestration/engine_adapter.py

# 12 — skillopt
commit "$(cat <<'EOF'
feat(skills-training): offline skill optimisation job

Deliberately off the chat hot path — it runs as a batch job, so a training pass
can never add latency to a user turn.

The 10 structural-gate tests cover both directions: the dangerous shapes rejected
AND the legitimate ones accepted. An over-eager gate turns every proposal into a
rejection while still looking like it works — two of the eight gates did exactly
that on first contact, one of them firing on the base skill's own safety language.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/skills_training/ \
   python_back_end/tests/test_skillopt_gate.py \
   scripts/skillopt-offline.sh \
   docs/design/2026-08-01-skillopt-offline.md

# 13 — container wiring
commit "$(cat <<'EOF'
chore(compose): mount the new packages and pass the feature flags

agent_reach, vision_to_code, skills_training and skills/Harvis were invisible
to the backend container, so all four features were inert however they were
configured. Both new feature flags default to false.

Also drops python_back_end/api/ — tts_routes had no remaining importer.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" docker-compose.yaml .gitignore python_back_end/api/

# 14 — docs
commit "$(cat <<'EOF'
docs: research, handoffs and change log for the integration pass

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" docs/ changes.md front_end/newjfrontend/changes.md

# 15 — Agent Reach in plain chat
commit "$(cat <<'EOF'
feat(chat): ground plain chat in real sources, without implementing tool calling

Cloud Claude, GPT and Hermes never called a tool when asked to read a page: one
model round cost 10.3s and came back with zero tool calls. chat_reach runs a
deterministic search-then-read FIRST and injects the result as TEXT, so a
provider that has no tool-calling wiring is still grounded in what was fetched.

Auto mode now treats "needs live information" as a launch reason on its own, and
a pure question routes to chat_reach even at high detector confidence — asking
what a README says should not spin up a build workspace.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/owui_compat/chat_reach.py \
   python_back_end/owui_compat/chat_completion.py \
   python_back_end/owui_compat/workspace_bridge.py \
   python_back_end/workspace/orchestration/provider_route.py \
   python_back_end/workspace/orchestration/model_router.py \
   front_end/owui/src/lib/components/chat/Chat.svelte

# 16 — runner honesty, the tool-result budget, and event redaction
commit "$(cat <<'EOF'
fix(build): the agent was starved, not looping — and a failed run said "complete"

results_text is the only channel by which a tool result reaches the model, and
both append sites clipped it to 500 characters. Fine for "wrote 3 files";
destructive for a fetched page. A 24,000-character README arrived as its first
500 characters, so the agent re-fetched it looking for a section it had never
been shown. Content tools now get a real slice under a run-wide ceiling, and a
truncated result says so, so "I don't have the rest" is a claim the model can
make honestly. Measured on the same prompt: gemma4:12b went from a 240s timeout
to a correct answer in 17.6s; gpt-oss:20b from 7 re-reads to 1 fetch.

The duplicate-call guard added alongside it fired twice before the budget change
and zero times after — it is a backstop now, not the cure. A model that answers
in prose never calls finish(), so a correct research answer was being flagged
failed; that is fixed without excusing a run that tried to change something and
merely stopped talking.

The narrator was innocent: orchestrator.py emitted an unconditional 'done', so
every child could die and the run row still read done. It now reports whether
its children succeeded, the router downgrades the verdict, and a failed run
keeps whatever work it produced instead of showing a bare error.

Credentials no longer reach the event log. A run that executed `env` persisted a
live API key into workspace_events in plaintext. Three redaction implementations
already existed in this repo and every one would have caught the string — none
ran on the path that stored it. Redaction now runs in _db_save_event, the single
funnel into that table, at persist time rather than output time: the operator
still sees their own shell output live, only the durable copy is scrubbed.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)" python_back_end/workspace/secret_redaction.py \
   python_back_end/workspace/workspace_router.py \
   python_back_end/workspace/orchestration/runner.py \
   python_back_end/workspace/orchestration/orchestrator.py \
   python_back_end/workspace/build_narrator.py

echo
echo "Done. 16 local commits. Nothing pushed."
git --no-pager log --oneline -16
echo
echo "Still uncommitted on purpose:"
git status --porcelain
