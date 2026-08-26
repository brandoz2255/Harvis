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
# How many identical tool calls to absorb before forcing the agent to answer. One
# repeat is a stumble worth a nudge; two is a loop that will burn the whole step
# budget and then time out. See seen_calls in SubAgentRunner.run.
_MAX_DUP_CALLS = max(1, int(os.getenv("HARVIS_ORCH_MAX_DUP_CALLS", "2")))
# How many times one file may be written in a single run before the run stops paying for
# it. The identical-call guard above keys on the exact (tool, args) pair, so rewriting the
# same file with one comment changed produces a different key and sails straight through:
# one observed run spent 40 steps and 28,843 completion tokens rewriting one 1.2 KB script.
# This guard watches the TARGET PATH instead, which no amount of argument-jitter can hide.
# Behavioural, not model-specific — it never looks at which model or provider is running.
_MAX_WRITES_PER_PATH = max(1, int(os.getenv("HARVIS_ORCH_MAX_WRITES_PER_PATH", "6")))
# Argument keys the file-writing tools use for their target, across every engine we speak
# to. Order matters: the first one present wins.
_PATH_ARG_KEYS = ("path", "file_path", "filename", "file", "filepath", "target_file", "target")
# Argument keys carrying the bytes to be written.
_CONTENT_ARG_KEYS = ("content", "text", "contents", "new_str", "body", "data", "patch", "diff")


def _write_target(args: dict) -> str:
    """The file a write-ish tool call is aimed at, normalised, or "" if it names none."""
    if not isinstance(args, dict):
        return ""
    for k in _PATH_ARG_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().lstrip("./")
    return ""


def _write_fingerprint(args: dict) -> str:
    """Hash of the bytes a write would land, so a byte-identical rewrite is recognisable
    even when some unrelated argument changed."""
    if not isinstance(args, dict):
        return ""
    for k in _CONTENT_ARG_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v:
            return hashlib.sha256(v.encode("utf-8", "replace")).hexdigest()[:16]
    return ""
_MAX_VERIFY_PREVIEWS = max(1, int(os.getenv("HARVIS_VISION_MAX_PREVIEWS", "2")))
# How much of a tool's output is allowed into the conversation. results_text is the
# ONLY channel by which a tool result reaches the model, and everything went through
# one 500-char clip — fine for "wrote 3 files", destructive for a fetched page. A
# 24,000-char README arrived as its first 500 characters, so the agent kept re-reading
# it looking for a hardware section it had never been shown. Content tools get a real
# slice, with a run-wide ceiling so three long pages can't crowd out the context.
_TOOL_RESULT_CHARS = max(200, int(os.getenv("HARVIS_ORCH_TOOL_RESULT_CHARS", "500")))
_READ_RESULT_CHARS = max(1000, int(os.getenv("HARVIS_ORCH_READ_RESULT_CHARS", "12000")))
_READ_TOTAL_CHARS = max(4000, int(os.getenv("HARVIS_ORCH_READ_TOTAL_CHARS", "36000")))
# Tools whose output IS the information the agent was asked for. Every agent_reach.*
# tool qualifies (matched by prefix below), plus reading a file off the workspace.
_CONTENT_TOOLS = ("read_file",)
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


def _default_system(label: str, disabled: set[str]) -> str:
    """The sub-agent system prompt, describing the tools this run ACTUALLY offers.

    The fixed version of this prompt named edit_file, str_replace and exec — all three
    of which an auto-detected launch withholds, which is the mode plain chat uses. So
    the model was being instructed to call tools it had not been given, and small models
    dutifully narrated them into prose. Deriving the wording from ``disabled`` is the
    only way the instructions and the schema cannot drift apart.
    """
    create = "apply_patch" if "apply_patch" not in disabled else "edit_file"
    if "apply_patch" not in disabled:
        edit = (
            "Create or rewrite a file with apply_patch(path, content). To change part of "
            "a file you already created, call apply_patch(path, old_str, new_str) instead "
            "of rewriting the whole thing."
        )
    else:
        edit = (
            "Create new files with edit_file. To CHANGE a file you already created, use "
            "str_replace (it edits a snippet and keeps the rest intact) rather than "
            "rewriting the whole file."
        )
    check = (
        " Optionally run exec / run_tests to check your work."
        if "exec" not in disabled
        else " You cannot run commands in this session, so make the code correct by reading it."
    )
    return (
        f"You are {label}, an autonomous coding sub-agent working in an ISOLATED, "
        "initially-empty workspace directory. You can ONLY use the provided tools, and "
        f"ONLY touch files inside your workspace using RELATIVE paths. {edit}{check} "
        "Do NOT ask questions. When the task is fully done, call finish with a one-line "
        "summary.\n\n"
        "The workspace starts EMPTY. There is no spec, task file, or README to find — do "
        "not go looking for one, and do not search the web to work out what your task "
        f"means. If the request is short or vague, choose a sensible interpretation, say "
        f"which one you chose, and build it with {create} straight away.\n\n"
        "An empty workspace is not an empty memory. When earlier turns of this chat are "
        "quoted above your task, they are yours — you said those things. Answer from them "
        "instead of inspecting the filesystem for traces of earlier work, and never tell "
        "the user you have no context when the conversation is sitting in front of you.\n\n"
        "## How to finish\n"
        "Write each file ONCE. A file you have already written and believe is correct is "
        "done — re-writing it to tidy a comment or rename a variable burns the whole "
        "budget and produces the same file. Stop when the task is met, not when you run "
        "out of ideas for improvements.\n"
        "Then call finish with a SHORT plain-English summary: what you built, one line "
        "per file, and anything the human has to know to run it. Do NOT paste the file "
        "contents into the summary — Harvis shows every file you wrote as its own opener "
        "beside your answer, so repeating the code there just prints it twice.\n\n"
        "## When the request is a QUESTION, not a build\n"
        "Plain chat routes questions through this same runner, and then the finish "
        "summary is the entire reply the user sees — there are no files beside it. So "
        "the summary must BE the answer: the table, the numbers, the comparison, the "
        "sources you read. A run that answers \"I compiled a comparison of X and Y\" "
        "has told the user nothing. Write what you found, not what you did."
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

    async def _screenshot_preview(
        self, workspace_path: str, args: dict, seq: int
    ) -> tuple[str, list[dict], dict]:
        """Render workspace HTML at desktop+mobile via browser-runner.

        Returns (text result, multimodal image_url parts, preview meta).
        PNGs are not persisted as artifacts ("for seeing, not keeping").
        """
        from .isolation import validate_agent_path
        from .tools import lane_for_tool

        empty_meta = {
            "ok": False, "desktop_b64": "", "mobile_b64": "",
            "desktop_viewport": None, "mobile_viewport": None,
        }
        if seq > _MAX_VERIFY_PREVIEWS:
            return (
                f"ERROR: screenshot_preview capped at {_MAX_VERIFY_PREVIEWS} "
                "calls this turn — finish or fix with str_replace from prior renders.",
                [],
                empty_meta,
            )
        try:
            from vision_to_code.method_pack import vision_self_check_enabled
            from vision_to_code.preview import render_html_dual_viewport
        except Exception as exc:
            logger.warning("screenshot_preview: vision_to_code unavailable: %s", exc)
            return ("ERROR: screenshot_preview is unavailable on this deployment.", [], empty_meta)
        if not vision_self_check_enabled():
            return (
                "DENIED: screenshot_preview is disabled "
                "(set HARVIS_VISION_SELF_CHECK_ENABLED=1 to enable).",
                [],
                empty_meta,
            )
        rel = str((args or {}).get("path") or "").strip()
        if not rel:
            return ("ERROR: screenshot_preview needs `path` (e.g. index.html).", [], empty_meta)
        if not validate_agent_path(workspace_path, rel):
            return (f"DENIED: path '{rel}' is outside your workspace.", [], empty_meta)
        fp = os.path.join(workspace_path, rel)
        if not os.path.isfile(fp):
            return (f"ERROR: no such file: {rel}", [], empty_meta)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                html = f.read(2_000_000)
        except OSError as exc:
            return (f"ERROR: could not read {rel}: {exc}", [], empty_meta)
        if not html.strip():
            return (f"ERROR: {rel} is empty.", [], empty_meta)

        # Lane-5 structural gate (same choke point as other external tools).
        decision_payloads: list[dict] = []
        res = await authorize_action(
            tool_name="screenshot_preview",
            args=args or {},
            lane=lane_for_tool("screenshot_preview"),
            permission_mode=None,
            run_id="screenshot_preview",
            emit=decision_payloads.append,
        )
        if not res.allowed:
            return (f"DENIED: {res.reason}", [], empty_meta)

        result = await render_html_dual_viewport(html)
        if not result.get("ok"):
            return (
                f"ERROR: render failed: {result.get('error') or 'unknown'}",
                [],
                {**empty_meta, **result},
            )
        parts: list[dict] = []
        labels = []
        if result.get("desktop_b64"):
            parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{result['desktop_b64']}",
                },
            })
            labels.append("desktop")
        if result.get("mobile_b64"):
            parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{result['mobile_b64']}",
                },
            })
            labels.append("mobile")
        text = (
            f"screenshot_preview of {rel}: rendered {', '.join(labels) or 'nothing'} "
            f"(iteration {seq}/{_MAX_VERIFY_PREVIEWS}). Compare these PNGs to the user's "
            "screenshot; fix visual defects with str_replace — do not regenerate the whole file."
        )
        return (text, parts, result)

    async def run(
        self,
        *,
        run_id: str,
        parent_run_id: str,
        label: str,
        task: str,
        model_name: str,
        workspace_path: str,
        # Multimodal image parts for the FIRST user turn (screenshot-to-code).
        # `task` stays a plain string everywhere else — the run row, the DB
        # write, and the detectors all read it as text.
        task_images: list[dict] | None = None,
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
        # Placeholder: the default wording depends on `disabled`, which is not known
        # until below. Rewritten in place once it is. A CUSTOM prompt is never touched.
        sys_content = system_prompt if system_prompt else ""
        if skill_blocks:
            # Sub-agent skills — already run through the SAME fail-closed gate as chat
            # (skills.gated_skill_blocks): a non-'supported' skill contributes an honest
            # 'unavailable' note here, never its body.
            sys_content = (
                sys_content
                + "\n\n## Attached skills — apply these when relevant:\n\n"
                + "\n\n".join(skill_blocks)
            )
        # With images attached the first user turn becomes a parts list, the same
        # shape the verify-loop follow-up already uses below. Without them it stays
        # a bare string so nothing downstream has to special-case the common path.
        messages = [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": (
                [{"type": "text", "text": task}, *task_images] if task_images else task
            )},
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
        verify_seq = 0  # screenshot_preview calls this turn (capped)
        # Identical-call ledger. Measured on two different models (gemma4:12b and
        # gpt-oss:20b, same prompt): each fetched the SAME README six or seven times,
        # and every repeat appended another full copy of the page to the context until
        # the next model round blew the router's 240s read timeout. Nothing stopped it —
        # the no-progress guard below only watches the filesystem, and a read-only
        # research run never touches it. Key is the exact (tool, args) pair, so a
        # genuinely different call is never blocked; a model that varies its arguments
        # slips through, which is the safe direction to fail.
        seen_calls: dict[str, int] = {}
        # path -> [step numbers it was written at]; path -> {content hashes already landed}
        writes_per_path: dict[str, list[int]] = {}
        written_bytes: dict[str, set[str]] = {}
        dup_blocks = 0
        # Did it ever try to change something? Distinguishes "ran out of steps while
        # building" (a real failure) from "answered a question" (a real success) at the
        # bottom of this method. Counted on the ATTEMPT, so a denied edit still counts.
        edit_attempted = False
        answered = False
        pending_results: list[str] = []
        _EDIT_TOOLS = ("edit_file", "str_replace", "write", "apply_patch")
        # Stand-in for an assistant turn that carried only tool calls. Several APIs
        # reject an empty assistant content, so SOMETHING has to go here — but it is
        # put in the model's own mouth, and a mimicking model will copy it back as
        # its answer. Gemini 3.5 Flash did exactly that: three of these in a row and
        # its final reply was the placeholder, which is what the user saw. Name it,
        # and refuse it wherever an answer is read back out.
        _NO_PROSE = "[tool calls]"
        # The guard has to strip the SAME punctuation the stand-in carries. It used
        # to strip only quotes and periods, so "(used tools)" — parentheses and all —
        # never matched "used tools" and the guard never fired once. ox-alpha read
        # four benchmark pages, parroted the placeholder back, and that is the whole
        # answer the user got. Both spellings stay listed: old transcripts replayed
        # from the event log still carry the parenthesised one.
        _PLACEHOLDERS = {"used tools", "tool calls", "tool call"}

        def _is_placeholder(s: str) -> bool:
            return s.strip().strip('"\'`.()[]<>*').strip().lower() in _PLACEHOLDERS
        # Withheld names that apply_patch covers argument-for-argument.
        _WRITE_ALIASES = ("edit_file", "str_replace")
        read_chars_used = 0

        def fit(name: str, result: str) -> str:
            """Trim a tool result to what may enter the conversation.

            A page or a source file is the payload, not a status line, so those get a
            real slice instead of the flat 500-char clip every tool used to share.
            The run-wide ceiling keeps a handful of long reads from filling the
            context window and timing out the next model round.
            """
            nonlocal read_chars_used
            if not (name.startswith("agent_reach.") or name in _CONTENT_TOOLS):
                return result[:_TOOL_RESULT_CHARS]
            room = min(_READ_RESULT_CHARS, _READ_TOTAL_CHARS - read_chars_used)
            if room <= _TOOL_RESULT_CHARS:
                return result[:_TOOL_RESULT_CHARS]
            read_chars_used += min(len(result), room)
            if len(result) <= room:
                return result
            # Say it was cut, so "I don't have the rest" is a claim the model can
            # make honestly instead of assuming the page simply ended.
            return (
                result[:room]
                + f"\n[...truncated — {len(result) - room} more characters of this "
                "result were not shown]"
            )
        # Token accounting (real OpenAI usage surfaced by ModelRouter). The LAST step's
        # prompt_tokens ≈ current context occupancy; completion/total accumulate over steps.
        last_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens_sum = 0
        ctx_window = int(os.getenv("HARVIS_OLLAMA_NUM_CTX", "24576") or 24576)
        # Offer-time tool policy: auto-detected launches never even SEE the heavy
        # tools in the offered schema. authorize_action stays the runtime backstop.
        # launch_mode == "user" (the default) → empty set → schema identical to today.
        #
        # Only `exec` is heavy. This set used to carry edit_file and str_replace too,
        # which — combined with the no-session withhold of apply_patch below — left an
        # auto-detected launch with NO way to write a file at all. Plain chat is always
        # launch_mode "auto", so "write me a script" reached the model with a schema
        # that could only read. Every model then either narrated an edit_file it had
        # not been given or, having been DENIED one, went looking for its task on the
        # web. Writing into an isolated, initially-empty scratch directory behind
        # validate_agent_path is not the risk this withhold was defending against;
        # running code is, and that stays withheld.
        disabled: set[str] = ({"exec"} if launch_mode == "auto" else set())
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
        # screenshot_preview — Build verify loop. Offer only when the per-capability
        # flag is on (lane-5 gate also enforces at dispatch).
        try:
            from vision_to_code.method_pack import vision_self_check_enabled

            if not vision_self_check_enabled():
                disabled.add("screenshot_preview")
        except Exception:
            disabled.add("screenshot_preview")
        # Agent Reach — lane-5 research; withhold when flag off (never OpenClaw).
        # Derived from the schema rather than listed here: a hand-kept list silently
        # keeps offering whichever reach tool was added last.
        _reach_tools = {
            n
            for n in ((e.get("function") or {}).get("name", "") for e in WIRE_TOOL_SCHEMA)
            if n.startswith("agent_reach.")
        }
        try:
            from agent_reach import agent_reach_enabled

            if not agent_reach_enabled():
                disabled |= _reach_tools
        except Exception:
            disabled |= _reach_tools

        # `disabled` is final — now the default prompt can name the real tool set.
        if not system_prompt:
            _base = _default_system(label, disabled)
            if skill_blocks:
                _base += (
                    "\n\n## Attached skills — apply these when relevant:\n\n"
                    + "\n\n".join(skill_blocks)
                )
            messages[0]["content"] = _base

        # MCP connector tools. Resolved ONCE per run, not per step: connecting
        # spawns a container, and a server that is down must cost one failed
        # attempt rather than one per loop iteration. An empty list (runtime
        # off, no servers, or every server unreachable) leaves the offered
        # schema byte-identical to today's.
        mcp_specs: list[dict] = []
        mcp_registry_obj = None
        if pool is not None and user_id is not None:
            try:
                from plugins.mcp.server_registry import McpServerRegistry
                from plugins.mcp.tool_bridge import mcp_tool_specs

                mcp_registry_obj = McpServerRegistry(pool)
                mcp_specs = await mcp_tool_specs(mcp_registry_obj, int(user_id))
            except Exception:
                logger.exception("mcp: tool discovery failed; continuing without it")
                mcp_specs = []
        if mcp_specs:
            yield ev("token", {
                "content": f"[{len(mcp_specs)} connector tool(s) available]\n"
            })

        try:
            while steps < max_steps and (time.monotonic() - started) < max_runtime_seconds:
                steps += 1
                msg = await self.router.complete(
                    model_name=model_name, messages=messages,
                    tools=filter_wire_schema(disabled) + mcp_specs, temperature=0.2,
                    # Per-user cloud credentials (the five free tiers, OpenAI, Moonshot)
                    # live per-user in the database, so the router can only reach them
                    # with this run's pool + user. Without them a cloud model falls back
                    # to the local route and answers as whatever Ollama has.
                    pool=pool, user_id=user_id,
                )
                _usage = msg.get("_usage") or {}
                if _usage:
                    last_prompt_tokens = int(_usage.get("prompt_tokens") or last_prompt_tokens)
                    total_completion_tokens += int(_usage.get("completion_tokens") or 0)
                    total_tokens_sum += int(_usage.get("total_tokens") or 0)
                    # Report the running totals now, not only in agent_end. These numbers
                    # exist after every model call, and a run that takes a minute should
                    # not spend that minute telling the user it has used no tokens.
                    yield ev("usage", {
                        "prompt_tokens": last_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_tokens_sum
                        or (last_prompt_tokens + total_completion_tokens),
                        "context_window": ctx_window,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "steps": steps,
                    })
                content = (msg.get("content") or "").strip()
                # Every tool name Harvis HAS, not just the ones offered this step.
                # The content fallback needs a universe to tell a narrated tool call
                # from a JSON object that merely happens to carry a "name" key — but
                # scoping that universe to the OFFERED set silently ate exactly the
                # calls this fallback exists to recover: an auto launch withholds
                # edit_file, a small model narrates edit_file anyway, and the run ends
                # with the raw JSON printed at the user. Recover it here; the
                # withheld-tool policy is enforced at dispatch below, where it can
                # tell the model what happened.
                _wire = filter_wire_schema(set()) + mcp_specs
                tcs = parse_tool_calls(msg, known={
                    (s.get("function") or {}).get("name")
                    for s in _wire if isinstance(s, dict)
                })

                if not tcs:
                    # No tool call → the model is done (its content is the summary).
                    if _is_placeholder(content):
                        content = ""
                    if content:
                        yield ev("token", {"content": content[:600]})
                    # Answering in prose is how a question ends — the model has no
                    # reason to call finish() once it has said the answer. Without
                    # this, a correct research answer came back flagged failed. A run
                    # that tried to CHANGE something and merely stopped talking is a
                    # different case and stays a failure.
                    if content or summary:
                        summary = content or summary
                        answered = bool(content) and not edit_attempted
                    # No usable prose and nothing said earlier: leave `summary` empty
                    # so the tools-removed answer round below runs. Calling this
                    # "Task complete." shipped a run that had read four pages and
                    # told the user only that it had used tools.
                    break

                if content:
                    yield ev("token", {"content": content[:600]})

                results_text: list[str] = []
                vision_parts: list[dict] = []  # multimodal parts from screenshot_preview
                finished = False
                forced_answer = False
                for tc in tcs:
                    name, args = tc["name"], tc["args"]
                    if name == "finish":
                        _fin = str(args.get("summary") or "Task complete.")
                        # A model that answers in prose and THEN calls finish() to
                        # label the answer is behaving correctly — but taking only
                        # the label threw the answer away. "make it again" came back
                        # as "Made two new ASCII trees in text blocks … shown
                        # directly in the chat above" with no trees anywhere,
                        # because the trees were in `content` on this very turn and
                        # this line overwrote them. The run's answer is what reaches
                        # the chat (workspace_router emits `summary` as
                        # final_message), so for a run that changed no files the
                        # prose IS the deliverable and the label stays a label.
                        # A run that edited files keeps the finish summary — there
                        # the label reports work the prose only narrates.
                        _prose = "" if _is_placeholder(content) else (content or "").strip()
                        summary = (
                            _prose
                            if (_prose and not edit_attempted and len(_prose) > len(_fin))
                            else _fin
                        )
                        finished = True
                        completed = True
                        break
                    yield ev("tool_call", {"tool": name, "args": args})
                    if name in _EDIT_TOOLS:
                        edit_attempted = True
                    try:
                        call_key = f"{name}|{json.dumps(args, sort_keys=True, default=str)}"
                    except Exception:
                        call_key = ""
                    if call_key and call_key in seen_calls:
                        # Re-running it would return the same bytes and double their cost
                        # in context. Point at the copy the model already has instead.
                        dup_blocks += 1
                        prior = seen_calls[call_key]
                        repeat_msg = (
                            f"ALREADY DONE: you called {name} with these exact arguments at "
                            f"step {prior} and it succeeded. Its full result is in this "
                            "conversation above — it has not changed and it was not run "
                            "again. Use what you already have. If you need something else, "
                            "call a DIFFERENT tool or different arguments; otherwise call "
                            "finish(summary) now."
                        )
                        yield ev("tool_result", {
                            "tool": name, "output": repeat_msg, "success": True,
                        })
                        results_text.append(f"{name}: ALREADY DONE at step {prior} — do not repeat")
                        if dup_blocks >= _MAX_DUP_CALLS:
                            logger.info(
                                "subagent %s: identical-call guard tripped at step %d (%s)",
                                label, steps, name,
                            )
                            forced_answer = True
                            break
                        continue

                    # Write-churn guard. Two distinct no-ops the identical-call guard
                    # cannot see, because both produce a fresh (tool, args) key:
                    #   1. re-landing bytes already written to that path
                    #   2. rewriting one file over and over with small cosmetic edits
                    # Both burn the budget and end with the file the run already had.
                    if name in _EDIT_TOOLS:
                        _tgt = _write_target(args)
                        if _tgt:
                            _prior = writes_per_path.get(_tgt, [])
                            _fp = _write_fingerprint(args)
                            _identical = bool(_fp) and _fp in written_bytes.get(_tgt, set())
                            _churned = len(_prior) >= _MAX_WRITES_PER_PATH
                            if _identical or _churned:
                                dup_blocks += 1
                                if _identical:
                                    _why = (
                                        f"NO-OP: the content you just passed to {name} for "
                                        f"{_tgt} is byte-for-byte what is already in that "
                                        "file (written at step "
                                        f"{_prior[-1] if _prior else '?'}). Nothing was "
                                        "written."
                                    )
                                else:
                                    _why = (
                                        f"STOP REWRITING {_tgt}: you have written this file "
                                        f"{len(_prior)} times in this run (steps "
                                        f"{', '.join(str(s) for s in _prior)}). Nothing was "
                                        "written."
                                    )
                                _msg = (
                                    _why + " A file you have already written and believe is "
                                    "correct is done. If the task is met, call "
                                    "finish(summary) now. If something is genuinely wrong "
                                    "with it, read it first and fix that one thing — do not "
                                    "re-emit the whole file."
                                )
                                logger.info(
                                    "subagent %s: write-churn guard blocked %s on %s at step "
                                    "%d (%s, %d prior writes)",
                                    label, name, _tgt, steps,
                                    "identical bytes" if _identical else "churn", len(_prior),
                                )
                                yield ev("tool_result", {
                                    "tool": name, "output": _msg, "success": False,
                                })
                                results_text.append(f"{name}: BLOCKED — {_tgt} already written")
                                if dup_blocks >= _MAX_DUP_CALLS:
                                    forced_answer = True
                                    break
                                continue
                            writes_per_path.setdefault(_tgt, []).append(steps)
                            if _fp:
                                written_bytes.setdefault(_tgt, set()).add(_fp)

                    lane = lane_for_tool(name)
                    # Phase D dispatch-time enforcement (the runtime backstop for the
                    # offer-time policy): a tool WITHHELD from the schema on an auto launch
                    # must ALSO be denied at dispatch — the model can still emit it via
                    # prompt injection, hallucination, or the content-JSON fallback in
                    # parse_tool_calls, and a lane<=3 tool would otherwise skip
                    # authorize_action below and execute. `disabled` is empty for "user".
                    if name in _WRITE_ALIASES and name in disabled and "apply_patch" not in disabled:
                        # apply_patch takes the same arguments and does strictly more:
                        # it writes the file AND records the change in the session's
                        # audit trail. Since it stays offered on auto launches, denying
                        # edit_file/str_replace there removes no capability at all — it
                        # only breaks the two names small models were trained on. Route
                        # the call to the audited tool instead of burning the step.
                        logger.info(
                            "subagent %s: aliased withheld %s → apply_patch (auto launch)",
                            label, name,
                        )
                        name = "apply_patch"
                        tc["name"] = name
                        lane = lane_for_tool(name)
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
                    if name == "screenshot_preview":
                        verify_seq += 1
                        out, parts, preview_meta = await self._screenshot_preview(
                            workspace_path, args, verify_seq
                        )
                        ok_preview = bool(preview_meta.get("ok"))
                        if ok_preview:
                            # Live-only UI event (PNGs not persisted — "for seeing, not keeping").
                            yield ev("verify_preview", {
                                "path": str((args or {}).get("path") or ""),
                                "desktop_b64": preview_meta.get("desktop_b64") or "",
                                "mobile_b64": preview_meta.get("mobile_b64") or "",
                                "desktop_viewport": preview_meta.get("desktop_viewport"),
                                "mobile_viewport": preview_meta.get("mobile_viewport"),
                                "iteration": verify_seq,
                            })
                            vision_parts.extend(parts)
                        yield ev("tool_result", {
                            "tool": name, "output": out, "success": ok_preview,
                        })
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
                    if name.startswith("mcp__"):
                        # Connector tools go to the MCP runtime, not dispatch_tool
                        # — same reason as propose_skill/generate_image: they need
                        # the per-user server registry, which dispatch_tool has no
                        # access to. They reached here only after the lane-5 gate
                        # above, so the flag and any approval already passed.
                        from plugins.mcp.tool_bridge import dispatch_mcp_tool

                        result, ok = await dispatch_mcp_tool(
                            mcp_registry_obj, int(user_id), name, args,
                            # Lets an image a connector produced land in the
                            # artifacts instead of behind a Docker-only URL.
                            # Against the PARENT run: the Artifacts rail is per
                            # launched run, so an image filed under a sub-agent's
                            # own id would exist but never appear beside the
                            # answer that produced it.
                            pool=pool, workspace_id=(parent_run_id or run_id or ""),
                        )
                        if ok and call_key:
                            seen_calls[call_key] = steps
                        yield ev("tool_result", {"tool": name, "output": result, "success": ok})
                        results_text.append(f"{name}: {fit(name, result)}")
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
                    if ok and name in _EDIT_TOOLS:
                        made_edit = True
                    # Ledger only records what actually succeeded: a failed call is worth
                    # retrying (a transient 403, a typo'd path), an identical successful
                    # one never is.
                    if ok and call_key:
                        seen_calls[call_key] = steps
                    # `tool` rides along so the UI can special-case results
                    # (e.g. a run_tests pass/fail summary line) without
                    # re-pairing events. Additive — older consumers ignore it.
                    yield ev("tool_result", {"tool": name, "output": result, "success": ok})
                    results_text.append(
                        f"{name}({json.dumps(args)[:140]}) -> {fit(name, result)}"
                    )
                if finished:
                    break
                if forced_answer:
                    # Out of the tool loop, into the answer round below. Everything from
                    # earlier steps is already in `messages`; this step's results are not
                    # (the append at the bottom of the loop never runs), so carry them.
                    pending_results = list(results_text)
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
                # When screenshot_preview returned PNGs, attach them as multimodal
                # image_url parts so vision models can compare against the input.
                messages.append({"role": "assistant", "content": content or _NO_PROSE})
                follow_text = (
                    "Tool results:\n"
                    + "\n".join(results_text)
                    + "\n\nContinue the task. Call finish(summary) once it is fully done."
                )
                if vision_parts:
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": follow_text},
                            *vision_parts,
                        ],
                    })
                else:
                    messages.append({"role": "user", "content": follow_text})

            if not summary:
                # The loop stopped without an answer — step limit, runtime limit, or the
                # identical-call guard. Ending here on "Reached step limit" throws away
                # every page the agent actually fetched and shows the user nothing; a
                # measured run read the right README seven times and still said nothing.
                # One more round, tools removed, so it has to answer from what it has.
                messages.append({"role": "assistant", "content": _NO_PROSE})
                tail = ("Tool results:\n" + "\n".join(pending_results) + "\n\n") if pending_results else ""
                messages.append({"role": "user", "content": (
                    f"{tail}Stop calling tools — none are available for this reply. Using "
                    "ONLY the tool results already in this conversation, answer the "
                    "original request now, in full. If something you needed is genuinely "
                    "missing, say plainly what is missing and answer with the rest."
                )})
                try:
                    final = await self.router.complete(
                        model_name=model_name, messages=messages, tools=[],
                        temperature=0.2, pool=pool, user_id=user_id,
                    )
                    text = (final.get("content") or "").strip()
                    if _is_placeholder(text):
                        # It echoed the stand-in instead of answering. Showing that to the
                        # user is worse than saying nothing, so treat it as no answer.
                        logger.info(
                            "subagent %s: final round echoed the tool placeholder", label
                        )
                        text = ""
                    if text:
                        yield ev("token", {"content": text[:600]})
                        summary = text
                        # An answer is a real result — but only for a run that never set
                        # out to change anything. A build that ran out of steps without
                        # writing a file did NOT succeed, however well it describes itself.
                        answered = not edit_attempted
                except Exception:
                    logger.warning(
                        "subagent %s: final answer round failed", label, exc_info=True
                    )
            if not summary:
                summary = f"Reached step limit ({steps})."
        except Exception as exc:
            logger.warning("subagent runner error (%s): %s", label, exc, exc_info=True)
            # httpx timeout exceptions stringify to "" — the user's run card read
            # literally "error:" with nothing after it. Never surface a blank cause.
            detail = str(exc).strip()
            kind = exc.__class__.__name__
            if "Timeout" in kind:
                detail = (
                    f"the model stopped responding ({kind}). The conversation may have "
                    "grown too large for it to answer in time."
                )
            elif not detail:
                detail = kind
            # A model that dies mid-loop does not undo the work already done. The
            # workspace starts empty, so whatever is in it now was written by this
            # run — and reporting "error:" with nothing after it told a user whose
            # script had been written perfectly on step one that nothing happened.
            # Name the files so the run card can still hand them over.
            made: list[str] = []
            try:
                for root, _dirs, files in os.walk(workspace_path):
                    for fn in files:
                        rel = os.path.relpath(os.path.join(root, fn), workspace_path)
                        if not rel.startswith("."):
                            made.append(rel)
            except Exception:
                pass
            made.sort()
            if made:
                shown = ", ".join(made[:6]) + (f" (+{len(made) - 6} more)" if len(made) > 6 else "")
                detail = f"{detail}\n\nThe run had already written: {shown}"
            yield ev(
                "agent_end",
                {
                    "label": label,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "summary": f"error: {detail}",
                    "success": False,
                    "files": made,
                },
            )
            return

        yield ev(
            "agent_end",
            {
                "label": label,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "summary": summary,
                # Green/done when the agent actually completed the task (called finish,
                # produced real edits, or answered a question it was never asked to change
                # anything for); red/error only if it did none of those. Transient tool
                # failures it recovered from no longer count against it.
                "success": completed or made_edit or answered,
                "prompt_tokens": last_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens_sum or (last_prompt_tokens + total_completion_tokens),
                "context_window": ctx_window,
            },
        )
