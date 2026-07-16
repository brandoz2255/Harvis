"""Native sub-agent runner — the in-process agent tool-loop for P5.

One step = ModelRouter completion (with tool schema) → parse tool_calls →
dispatch via tools.py inside the isolated workspace → feed results back → repeat
until the agent calls finish() / stops emitting tool calls / hits a limit.
Emits OpenClawEvents tagged run_id/parent_run_id/agent_label/model, so the
existing persistence + RunView / Neural Map render it with no changes.

Tool results are fed back as a plain user turn (not the strict OpenAI tool-role
protocol) — more robust across heterogeneous local models, which is the recurring
Harvis tool-call-discipline concern.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import AsyncGenerator

from owui_compat.workspace_method import DEFAULT_SAFE_LANE

from ..openclaw_client import OpenClawEvent
from .authz import authorize_action
from .model_router import ModelRouter
from .risk import await_action_decision, mark_pending_resolved, persist_pending, register_pending
from .tools import WIRE_TOOL_SCHEMA, dispatch_tool, filter_wire_schema, lane_for_tool, parse_tool_calls

logger = logging.getLogger(__name__)

# No-progress guard: how many consecutive steps with ZERO file change before we
# stop a churning sub-agent (the finish-reluctance loop — re-reading/re-writing
# the same file without ever calling finish). Tunable via env.
_MAX_IDLE_STEPS = max(1, int(os.getenv("HARVIS_ORCH_MAX_IDLE_STEPS", "3")))
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".next", "target", "vendor", ".cache", "coverage", ".mypy_cache", ".pytest_cache",
}
_BASELINE_FILE = ".harvis-baseline.json"


def _ws_fingerprint(path: str) -> str:
    """SHA-256 over the workspace's files — lets the runner detect when an agent has
    stopped producing real changes. Large files (>1 MB) fingerprint by (size, mtime)
    instead of by content so a big repo / binary can't make the scan slow. This is
    synchronous heavyweight IO: callers MUST run it off the event loop (asyncio.to_thread)."""
    h = hashlib.sha256()
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fn in sorted(files):
                if fn == _BASELINE_FILE:
                    continue
                fp = os.path.join(root, fn)
                try:
                    h.update(os.path.relpath(fp, path).encode("utf-8", "replace"))
                    st = os.stat(fp)
                    if st.st_size > 1024 * 1024:
                        # Large file: fingerprint by metadata, don't read the content.
                        h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
                        continue
                    with open(fp, "rb") as f:
                        h.update(f.read(256 * 1024))
                except Exception:
                    continue
    except Exception:
        return ""
    return h.hexdigest()


_SYSTEM = (
    "You are {label}, an autonomous coding sub-agent working in an ISOLATED, "
    "initially-empty workspace directory. You can ONLY use the provided tools, and "
    "ONLY touch files inside your workspace using RELATIVE paths. Create new files "
    "with edit_file. To CHANGE a file you already created, use str_replace (it "
    "edits a snippet and keeps the rest intact) rather than rewriting the whole "
    "file. Optionally run exec / run_tests to check your work. Do NOT ask "
    "questions. When the task is fully done, call finish with a one-line summary."
)


class SubAgentRunner:
    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    async def _propose_skill(self, pool, user_id, args: dict) -> str:
        """Persist an agent-proposed DRAFT skill (enabled=FALSE, empty audit). The
        draft is uninjectable/unpublishable until a HUMAN marks it 'supported'
        (skills.gated_skill_blocks enforces the verdict gate) — the agent cannot
        self-approve. Never raises; returns a human-readable result line."""
        import json as _json
        import re as _re
        import uuid as _uuid

        if pool is None or user_id is None:
            return "ERROR: cannot save skills in this run context."
        name = str((args or {}).get("name") or "").strip().lower()
        desc = str((args or {}).get("description") or "").strip()
        content = str((args or {}).get("content") or "").strip()
        if not name or not content:
            return "ERROR: propose_skill needs a kebab-case name and markdown content."
        if len(name) > 40 or not _re.match(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", name):
            return "ERROR: skill name must be kebab-case (e.g. 'reset-schema'), max 40 chars."
        content = content[:20000]
        try:
            async with pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT 1 FROM owui_skills WHERE user_id=$1 AND name=$2", int(user_id), name
                )
                if exists:
                    return (
                        f"A skill named '{name}' already exists — not creating a duplicate. "
                        "Ask the human to review it in Customize → Skills."
                    )
                await conn.execute(
                    "INSERT INTO owui_skills (id, user_id, name, description, content, meta, enabled) "
                    "VALUES ($1,$2,$3,$4,$5,$6::jsonb,FALSE)",
                    str(_uuid.uuid4()), int(user_id), name, desc, content,
                    _json.dumps({"audit": {}, "source": "agent_proposed"}),
                )
        except Exception as exc:
            logger.warning("propose_skill insert failed: %s", exc)
            return "ERROR: could not save the draft skill."
        return (
            f"Drafted skill '{name}' for human review — it is NOT active and applies to nothing "
            "until a human marks it 'supported' in Customize → Skills."
        )

    async def _generate_image(self, pool, run_id: str, args: dict, seq: int) -> tuple[str, dict | None]:
        """Agent-initiated image generation — the in-run twin of
        POST /api/harvis/image/generate: SAME enable flag, SAME provider
        resolution, SAME _db_save_artifact path, but the PNG lands under the
        agent's CURRENT run (no new run row). Handled in-runner (not
        dispatch_tool) because it needs the pool. Never raises; returns
        (result line, 'artifact' event payload | None)."""
        try:
            from image.harvis_image import _image_gen_enabled
            from image.provider import GenSpec, resolve_provider
            from workspace.workspace_router import _db_save_artifact
        except Exception as exc:  # fail-closed if the image module is absent
            logger.warning("generate_image: image module unavailable: %s", exc)
            return ("ERROR: image generation is unavailable on this deployment.", None)
        if pool is None:
            return ("ERROR: image generation is unavailable in this run context.", None)
        if not _image_gen_enabled():
            return ("ERROR: image generation is disabled (enable_image_generation flag off).", None)
        try:
            spec = GenSpec(
                prompt=str((args or {}).get("prompt") or ""),
                negative_prompt=str((args or {}).get("negative_prompt") or ""),
                width=(args or {}).get("width", 512),
                height=(args or {}).get("height", 512),
            )
        except ValueError as exc:
            return (f"ERROR: {exc}", None)
        try:
            provider = await resolve_provider()
            if provider.id == "none":
                report = await provider.readiness()
                return (f"image generation isn't ready: {report.get('reason')}", None)
            png = await provider.txt2img(spec)
            if not png:
                return (f"ERROR: {provider.id} returned empty image data.", None)
            path = f"generated/{run_id}-{seq}.png"
            artifact_id = await _db_save_artifact(pool, run_id, "file", path=path, content_bytes=png)
            if not artifact_id:
                return ("ERROR: could not persist the generated image artifact.", None)
        except Exception as exc:
            logger.warning("generate_image failed: %s", exc, exc_info=True)
            return (f"ERROR: image generation failed: {exc}", None)
        payload = {
            "run_id": run_id,
            "artifact_id": artifact_id,
            "path": path,
            "mime_type": "image/png",
            "size_bytes": len(png),
            "label": f"{run_id}-{seq}.png",
        }
        return (
            f"Generated a {spec.width}x{spec.height} image via {provider.id} "
            f"({spec.steps} steps) — saved as artifact {artifact_id}. Inline preview: "
            f"![](/api/workspace/artifact/{artifact_id}/raw)",
            payload,
        )

    async def run(
        self,
        *,
        run_id: str,
        parent_run_id: str,
        label: str,
        task: str,
        model_name: str,
        workspace_path: str,
        max_steps: int = 12,
        max_runtime_seconds: int = 600,
        system_prompt: str | None = None,
        permission_mode: str | None = None,
        launch_mode: str = "user",
        disabled_tools: set[str] | None = None,
        skill_blocks: list[str] | None = None,
        pool=None,
        user_id: int | None = None,
        session_id: str | None = None,  # VibeCode session — enables approve-for-session
    ) -> AsyncGenerator[OpenClawEvent, None]:
        def ev(etype: str, data: dict) -> OpenClawEvent:
            e = OpenClawEvent(
                etype,
                {**data, "agent_label": label, "parent_run_id": parent_run_id, "model": model_name},
            )
            e.run_id = run_id
            e.agent_label = label
            return e

        started = time.monotonic()
        yield ev("agent_start", {"label": label})

        # The default template carries a {label} placeholder; a CUSTOM sub-agent
        # system prompt is used VERBATIM (it may contain literal braces — never
        # .format it, or a code-heavy prompt would raise KeyError/ValueError).
        sys_content = system_prompt if system_prompt else _SYSTEM.format(label=label)
        if skill_blocks:
            # Sub-agent skills — already run through the SAME fail-closed gate as chat
            # (skills.gated_skill_blocks): a non-'supported' skill contributes an honest
            # 'unavailable' note here, never its body.
            sys_content = (
                sys_content
                + "\n\n## Attached skills — apply these when relevant:\n\n"
                + "\n\n".join(skill_blocks)
            )
        messages = [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": task},
        ]
        summary = ""
        # Final success = did the agent ACTUALLY COMPLETE its task — it called finish(),
        # or it produced real edits. A tool that fails mid-run (e.g. str_replace "old_str
        # not found") then gets retried successfully must NOT mark the agent failed. So we
        # track completion, NOT "every tool call succeeded".
        completed = False
        steps = 0
        last_fp = await asyncio.to_thread(_ws_fingerprint, workspace_path)  # baseline (off the event loop)
        made_edit = False
        idle = 0
        action_seq = 0  # per-action ids for the in-place permission gate
        image_seq = 0  # per-run counter for generate_image artifact paths
        # Token accounting (real OpenAI usage surfaced by ModelRouter). The LAST step's
        # prompt_tokens ≈ current context occupancy; completion/total accumulate over steps.
        last_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens_sum = 0
        ctx_window = int(os.getenv("HARVIS_OLLAMA_NUM_CTX", "24576") or 24576)
        # Offer-time tool policy: auto-detected launches never even SEE the heavy
        # tools in the offered schema. authorize_action stays the runtime backstop.
        # launch_mode == "user" (the default) → empty set → schema identical to today.
        disabled: set[str] = (
            {"exec", "edit_file", "str_replace"} if launch_mode == "auto" else set()
        )
        # A custom sub-agent's allowed-tools ALLOWLIST arrives already inverted to a
        # withhold set by the orchestrator; union it in. 'finish' is never withheld
        # (the loop needs it to terminate). authorize_action at dispatch stays the
        # backstop for anything the model emits despite the offer-time withhold.
        if disabled_tools:
            disabled |= {t for t in disabled_tools if t != "finish"}
        # Phase 4: the tracked session tools exist ONLY inside a VibeCode session —
        # non-session runs never even see them in the offered schema (dispatch_tool
        # also refuses them without a session_id; belt-and-braces). Session runs are
        # unaffected: the tools appear alongside edit_file/str_replace as today.
        if not session_id:
            disabled |= {"apply_patch", "git_commit"}
        # propose_skill (agent self-authorship) is offered ONLY on user-initiated runs
        # with DB context — never auto-escalations (a user-intent signal, like heavy
        # tools) and never when there's no pool/user to persist a DRAFT under. The draft
        # is uninjectable until a HUMAN 'supported' verdict (gated_skill_blocks), so the
        # agent can never self-approve.
        if launch_mode != "user" or pool is None or user_id is None:
            disabled.add("propose_skill")
        # generate_image rides the SAME flag as /api/harvis/image/generate (never a
        # bypass) and needs a pool to persist the PNG artifact. Unlike propose_skill
        # it is NOT restricted to launch_mode == "user" — it's a benign creative tool
        # (no code exec). Fail-closed if the image module can't even import.
        try:
            from image.harvis_image import _image_gen_enabled
            _img_ready = _image_gen_enabled()
        except Exception:
            _img_ready = False
        if not _img_ready or pool is None:
            disabled.add("generate_image")

        try:
            while steps < max_steps and (time.monotonic() - started) < max_runtime_seconds:
                steps += 1
                msg = await self.router.complete(
                    model_name=model_name, messages=messages, tools=filter_wire_schema(disabled), temperature=0.2
                )
                _usage = msg.get("_usage") or {}
                if _usage:
                    last_prompt_tokens = int(_usage.get("prompt_tokens") or last_prompt_tokens)
                    total_completion_tokens += int(_usage.get("completion_tokens") or 0)
                    total_tokens_sum += int(_usage.get("total_tokens") or 0)
                content = (msg.get("content") or "").strip()
                tcs = parse_tool_calls(msg)

                if not tcs:
                    # No tool call → the model is done (its content is the summary).
                    if content:
                        yield ev("token", {"content": content[:600]})
                    summary = content or summary or "Task complete."
                    break

                if content:
                    yield ev("token", {"content": content[:600]})

                results_text: list[str] = []
                finished = False
                for tc in tcs:
                    name, args = tc["name"], tc["args"]
                    if name == "finish":
                        summary = str(args.get("summary") or "Task complete.")
                        finished = True
                        completed = True
                        break
                    yield ev("tool_call", {"tool": name, "args": args})
                    lane = lane_for_tool(name)
                    # Phase D dispatch-time enforcement (the runtime backstop for the
                    # offer-time policy): a tool WITHHELD from the schema on an auto launch
                    # must ALSO be denied at dispatch — the model can still emit it via
                    # prompt injection, hallucination, or the content-JSON fallback in
                    # parse_tool_calls, and a lane<=3 tool would otherwise skip
                    # authorize_action below and execute. `disabled` is empty for "user".
                    if name in disabled:
                        yield ev("decision", {
                            "tool": name, "lane": lane, "policy": "deny",
                            "reason": "withheld in auto-launched run", "source": "launch_mode",
                        })
                        yield ev("tool_result", {
                            "output": f"DENIED: '{name}' is not available in auto-launched runs.",
                            "success": False,
                        })
                        results_text.append(f"{name} DENIED (auto launch)")
                        continue
                    if name == "propose_skill":
                        # Agent self-authorship: write a DRAFT skill (enabled=FALSE, empty
                        # audit) the human must approve. Handled in-runner (not dispatch_tool)
                        # because it needs the pool/user context; never grants a tool or lane.
                        out = await self._propose_skill(pool, user_id, args)
                        yield ev("tool_result", {"output": out, "success": not out.startswith("ERROR")})
                        results_text.append(out)
                        continue
                    if name == "generate_image":
                        # Agent-initiated image generation: same flag + provider gate as
                        # the /api/harvis/image/generate endpoint, PNG saved under THIS
                        # run. In-runner (not dispatch_tool) because it needs the pool.
                        image_seq += 1
                        out, art = await self._generate_image(pool, run_id, args, image_seq)
                        if art:
                            # 'artifact' trace event → the Artifacts rail previews the PNG.
                            yield ev("artifact", art)
                        yield ev("tool_result", {"output": out, "success": art is not None})
                        results_text.append(out)
                        continue
                    # Lane-unification choke point (Phase 2): authorize_action composes
                    # the structural 6-lane gate with the per-action risk gate. Entered
                    # under the OLD gate's condition (permission_mode set — in-place
                    # sessions) OR for a lane>3 tool, so lane<=3 with no permission_mode
                    # keeps today's exact control flow: no gating, byte-for-byte
                    # unchanged (clone-mode + the orchestrator pass None).
                    if permission_mode or lane > DEFAULT_SAFE_LANE:
                        decision_payloads: list[dict] = []
                        res = await authorize_action(
                            tool_name=name,
                            args=args,
                            lane=lane,
                            permission_mode=permission_mode,
                            run_id=run_id,
                            emit=decision_payloads.append,
                            session_id=session_id,
                            pool=pool,
                        )
                        # 'decision' trace events ride the normal event pipeline
                        # (workspace_events + SSE), same as tool_call/tool_result.
                        for payload in decision_payloads:
                            yield ev("decision", payload)
                        if not res.allowed and res.tier is None:
                            # Structural lane deny (lane>3 without its enabling flag) —
                            # new in Phase 2; lane<=3 tools can never take this branch.
                            yield ev("tool_result", {"output": f"DENIED: {res.reason}", "success": False})
                            results_text.append(f"{name} DENIED ({res.reason})")
                            continue
                        if not res.allowed:
                            msg_b = (
                                f"BLOCKED: '{name}' was NOT executed. This turn is PLAN MODE "
                                "(read-only) — every edit and command will fail, so do NOT "
                                "retry it or try another edit. Call finish NOW with `summary` "
                                "= a NUMBERED plan written in PLAIN ENGLISH: one FULL SENTENCE "
                                "per step saying what you would change and why, naming files in "
                                "words (e.g. \"1. Add a SUMMARY.md at the repo root describing "
                                "what hello.txt contains.\"). Do NOT put tool calls, function "
                                "names, JSON, or code in the plan — describe each step in words."
                            )
                            yield ev("tool_result", {"output": msg_b, "success": False})
                            results_text.append(f"{name} BLOCKED (plan mode) — finish with a plan instead")
                            continue
                        if res.needs_approval:
                            action_seq += 1
                            action_id = f"{run_id}-{steps}-{action_seq}"
                            register_pending(action_id, {
                                "tool": name, "args": args, "risk": res.tier,
                                "reason": res.reason, "session_id": session_id,
                            })
                            # Durability mirror: a restart must not silently lose the
                            # pending approval (fail-open — DB errors just log).
                            await persist_pending(
                                pool, action_id, run_id, session_id, name, args, res.tier, res.reason,
                            )
                            yield ev("approval_request", {
                                "action_id": action_id, "tool": name, "args": args,
                                "risk": res.tier, "reason": res.reason,
                            })
                            approved = await await_action_decision(action_id)
                            # Covers the timeout-deny path too (the resolve endpoint only
                            # marks rows it actually resolved).
                            await mark_pending_resolved(
                                pool, action_id, "approved" if approved else "denied",
                            )
                            yield ev("approval_resolved", {"action_id": action_id, "approved": approved})
                            if not approved:
                                yield ev("tool_result", {"output": "Denied by the user.", "success": False})
                                results_text.append(f"{name} DENIED by user")
                                continue
                    # session_id (vibecode turns only) routes exec/run_tests into
                    # the hardened per-session runner container (Phase 3 security);
                    # orchestrated/generic runs pass None → unchanged in-process path.
                    result, ok = await dispatch_tool(
                        workspace_path, name, args, session_id=session_id,
                        pool=pool, run_id=run_id,
                    )
                    # NOTE: a single failed tool no longer marks the whole agent failed —
                    # the agent can (and often does) recover and finish. Success is decided
                    # by completion (finish() / real edits), not by per-tool `ok`.
                    # Count as a real edit only AFTER a successful dispatch — a blocked
                    # (Plan) or denied (Ask) edit never reached the filesystem, so it must
                    # not trip the no-progress guard.
                    if ok and name in ("edit_file", "str_replace", "write", "apply_patch"):
                        made_edit = True
                    # `tool` rides along so the UI can special-case results
                    # (e.g. a run_tests pass/fail summary line) without
                    # re-pairing events. Additive — older consumers ignore it.
                    yield ev("tool_result", {"tool": name, "output": result, "success": ok})
                    results_text.append(
                        f"{name}({json.dumps(args)[:140]}) -> {result[:500]}"
                    )
                if finished:
                    break

                # ── No-progress guard: stop the finish-reluctance churn (the model
                # re-reading / re-writing the same file without ever calling finish).
                # Only after a real edit, and only when the workspace has been
                # unchanged for _MAX_IDLE_STEPS in a row — so edit→test→edit loops
                # (which DO change files) keep going. ──────────────────────────────
                fp = await asyncio.to_thread(_ws_fingerprint, workspace_path)
                idle = idle + 1 if fp == last_fp else 0
                last_fp = fp
                if made_edit and idle >= _MAX_IDLE_STEPS:
                    summary = summary or (
                        f"Stopped — no further changes after {idle} idle steps."
                    )
                    logger.info(
                        "subagent %s: no-progress guard tripped at step %d", label, steps
                    )
                    break

                # Feed tool results back as a user turn (robust for local models).
                messages.append({"role": "assistant", "content": content or "(used tools)"})
                messages.append(
                    {
                        "role": "user",
                        "content": "Tool results:\n"
                        + "\n".join(results_text)
                        + "\n\nContinue the task. Call finish(summary) once it is fully done.",
                    }
                )

            if not summary:
                summary = f"Reached step limit ({steps})."
        except Exception as exc:
            logger.warning("subagent runner error (%s): %s", label, exc, exc_info=True)
            yield ev(
                "agent_end",
                {
                    "label": label,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "summary": f"error: {exc}",
                    "success": False,
                },
            )
            return

        yield ev(
            "agent_end",
            {
                "label": label,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "summary": summary,
                # Green/done when the agent actually completed the task (called finish, or
                # produced real edits); red/error only if it did neither. Transient tool
                # failures it recovered from no longer count against it.
                "success": completed or made_edit,
                "prompt_tokens": last_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens_sum or (last_prompt_tokens + total_completion_tokens),
                "context_window": ctx_window,
            },
        )
