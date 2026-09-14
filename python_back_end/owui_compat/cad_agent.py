"""Gate 7C-3: the native tool-calling CAD lane for cloud Claude and Kimi.

The local generator (:mod:`cad_generate`) asks one small model for one JSON blob and
does everything else itself — validate, build, measure, repair. That shape exists
because a 4B model cannot be trusted to drive; it is handed a schema and its output
is treated as data. It stays, unchanged, for the offline lane.

A frontier model does not need to be driven. It needs *tools*, and the nine it gets
here are the same nine the MCP sidecars get, from the same registry, through the same
:func:`cad_tools.dispatch`. So this module is deliberately thin: it resolves which
provider actually serves the selected model, runs a bounded tool loop, and reports
what happened. Every rule about ownership, quota, proposal state and the answer key
lives in the dispatcher and is not restated — a second copy would be a second place
for it to drift.

**No silent fallback, in either direction.** :func:`resolve_lane` answers only when
the selected model genuinely resolves to a cloud provider with a credential that
exists. When it answers ``None`` the caller uses the local lane, which is not a
fallback — it is the selected model's own lane. When it answers a lane and that lane
then fails, the failure is reported as itself. A cloud request quietly finished by
``qwen3:4b`` would be the exact dishonesty Gate 7C was opened to remove: the user
would be told a frontier model authored their part.

**Why the loop waits on a build the model started.** ``cad_start_build`` returns a
build id immediately, and the tool description tells the model to poll. Polling from
the model costs a full round trip per lap for a build that finishes in seconds, so
this loop waits for the terminal state itself and hands the model the start result
*and* the finished build together, each labelled. That is a courtesy of this lane
only — :func:`cad_tools.dispatch` is untouched, so the MCP surface and this one still
mean the identical thing by ``cad_start_build``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from . import cad_generate, cad_tools

logger = logging.getLogger(__name__)

# An optional observer for a turn in progress. It is told what the model DID — which
# tool, whether it was accepted, which ids appeared — what the model SAID (the narration
# it writes for the reader between tool calls, ``kind="say"``, DE-8c), and, since DE-9,
# what the model THOUGHT on its way there (``kind="think"``).
#
# That last lane is a deliberate reversal. Reasoning used to be dropped on the floor
# here on the grounds that hidden thinking is not ours to publish. The user asked for it
# back, and the shape they asked for is the one that makes it defensible: captured while
# the turn runs, folded shut, and shown only when a reader presses for it. Two limits
# survive the reversal and are not negotiable — the model is still never asked to reveal
# its prompt, and every thought passes `secret_redaction` before it becomes a row, the
# same choke point workspace events go through.
#
# The two lanes below emit the same vocabulary so a caller cannot tell an HTTP tool loop
# from a CLI one, which is the same promise the return dict already makes.
EventSink = Optional[Callable[[dict], Awaitable[None]]]

# One narration line's ceiling. A model that writes an essay between two tool calls
# should not be able to push the rest of the timeline out of a row-capped activity log,
# and the panel this feeds is a column beside a viewport, not a document.
SAY_LIMIT = 600

# A thought's ceiling, larger than a narration's because reasoning is the long form and
# clipping it to a sentence would defeat the disclosure it sits behind. The real guard
# against a runaway turn is the per-job budget in `cad_jobs`, not this number: activity
# is persisted by rewriting the whole list on every append, so the cost of one enormous
# thought is paid again on every row that follows it.
THINK_LIMIT = 2000

# The extended-thinking budget handed to the Claude Code sidecar, and off by default.
#
# Measured on this deployment: with a budget set, the CLI does emit a `thinking` block —
# but its body is the empty string and only a signature comes with it. The reasoning
# text is never released on the subscription path, so paying for the thinking tokens
# buys nothing the panel could show. The knob stays because a future CLI may release it
# and because thinking can be worth its cost on its own merits; the default does not
# spend a user's tokens for an empty row.
_THINK_TOKENS = int(os.getenv("HARVIS_CAD_THINK_TOKENS", "0") or 0)


_THINK = re.compile(r"<think>(.*?)(?:</think>|\Z)", re.S | re.I)


def _say(text: Any) -> str:
    """The narration worth showing, or an empty string.

    Two things get removed. ``<think>…</think>`` first: a reasoning model on the HTTP
    lane writes its working into the same `content` field as its answer, and the two are
    different kinds of speech — narration addresses a person, a thought does not. It is
    lifted out by `_thought` and reported on its own row rather than discarded. The
    unterminated form goes too, because a response cut off mid-thought is still a
    thought. Whitespace second, because a model that emits one space before a tool call
    would otherwise get a blank row in the timeline for it."""
    s = _THINK.sub("", str(text or "")).strip()
    return s[:SAY_LIMIT] if s else ""


def _thought(*candidates: Any) -> tuple[str, bool]:
    """The reasoning worth keeping out of whichever field this provider used.

    There is no agreement across providers about where thinking goes, and a lane that
    only knew one shape would silently show nothing for the others: Anthropic sends
    typed `thinking` blocks, OpenAI-compatible reasoning models send `reasoning_content`
    or `reasoning` beside the content, and local models under Ollama write
    ``<think>…</think>`` inline. All four are checked, first non-empty wins, and the
    inline form is unwrapped rather than reported with its tags.

    The second return value says whether the clip fired. A long thought stops at
    `THINK_LIMIT` mid-word, and a body that just stops reads to the reader as a broken
    panel rather than as a bounded one — so the caller is told, and the UI says it.
    """
    for c in candidates:
        s = str(c or "").strip()
        if not s:
            continue
        inline = _THINK.search(s)
        if inline:
            s = (inline.group(1) or "").strip()
        if s:
            return s[:THINK_LIMIT], len(s) > THINK_LIMIT
    return "", False


async def _emit(on_event: EventSink, **event) -> None:
    """Report progress without letting the observer break the run.

    A swallowed exception here is deliberate. The sink writes to a database and a set
    of live subscribers, and neither of those failing is a reason to lose a part the
    model already built."""
    if on_event is None:
        return
    try:
        await on_event(event)
    except Exception:
        logger.debug("cad_agent: event sink raised", exc_info=True)

# One authoring turn's ceiling. Each round is one model call plus its tool work, and
# the expected shape is four: create → build → read the verdict → done. A repair now
# costs two more (open the experiment, build inside it), so the ceiling rose with the
# repair budget below — a budget the round cap will not let the model spend is not a
# budget, it is a number in a prompt. Fourteen still stops a model that has lost the
# plot from running forever on the user's key, and TURN_BUDGET_S stops it sooner.
MAX_ROUNDS = int(os.getenv("HARVIS_CAD_AGENT_ROUNDS", "14"))

# How many times a *conformance* failure may be sent back. Distinct from a rejected
# document, which the model sees as a tool error and may fix within the round budget.
#
# This was 1 for as long as a repair meant `cad_propose_revision` — every attempt burned
# a permanent revision and a permanent build, so three attempts bought one part and two
# pieces of wreckage in the user's history. HE-8 made a repair disposable: it happens
# inside an experiment, and an experiment that goes nowhere is abandoned and leaves the
# project exactly as it was. That is what pays for the rise to three, and it is why the
# number may not go back up ahead of the workflow that routes repairs through
# experiments — the two changed together and mean nothing apart.
MAX_REPAIRS = int(os.getenv("HARVIS_CAD_AGENT_REPAIRS", "3"))

MODEL_TIMEOUT_S = float(os.getenv("HARVIS_CAD_AGENT_TIMEOUT", "180"))
TURN_BUDGET_S = float(os.getenv("HARVIS_CAD_AGENT_BUDGET", "420"))

# How long to wait on a build the model started before handing back whatever state it
# is in. Longer than a normal build by a wide margin; a build that outruns this is
# reported as still running rather than waited on forever.
BUILD_WAIT_S = float(os.getenv("HARVIS_CAD_AGENT_BUILD_WAIT", "120"))
_POLL_S = 1.0

_TERMINAL = ("succeeded", "failed", "cancelled")

MAX_OBSERVATION_CHARS = 6000


class Lane:
    """Which provider will actually serve this model, and how to call it."""

    def __init__(self, kind: str, provider: str, model: str, *,
                 api_key: str | None = None, pool=None, user_id: int | None = None,
                 engine: str | None = None):
        self.kind = kind          # "openai_compatible" | "anthropic" | "claude_code"
        self.provider = provider  # for the audit line and the revision row
        self.model = model
        # Which `user_engine_auth` row serves this lane, for the kinds that run a
        # sidecar CLI rather than calling an HTTP API directly.
        self.engine = engine
        # Held rather than passed around because the per-user cloud route has to be
        # re-resolved on every call, and it can only be resolved with the credential
        # owner in hand. Never logged.
        self.api_key = api_key
        self.pool = pool
        self.user_id = user_id

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<Lane {self.provider}:{self.model} via {self.kind}>"


async def resolve_lane(model_name: str, pool, user_id: int | None) -> Lane | None:
    """The cloud lane for this model, or ``None`` if there isn't one.

    Asked in the same order the chat lane asks, and for the same reason: the per-user
    providers own their model namespaces, and Anthropic is the one provider whose wire
    format is not OpenAI's. Anything else — a local tag, a DB-configured Ollama — is
    not a native tool lane and gets ``None``, which sends the caller to
    :mod:`cad_generate` rather than to a provider the user did not pick.
    """
    model_name = (model_name or "").strip()
    if not model_name:
        return None

    # 0. Kimi Code. It carries its own catalog prefix, and `provider_route` declines
    #    that prefix by name (`OWN_TOOLS_PREFIXES`) because Kimi Code is not served
    #    over an OpenAI-compatible endpoint here — it is the real Claude Code CLI with
    #    ANTHROPIC_BASE_URL repointed. Until this branch existed the decline was the
    #    whole story: step 1 declined it, `is_anthropic_model` does not match
    #    `kimi-code/` so steps 2 and 3 never looked at it, and the model fell out of
    #    the function as `None` — which is the answer that means "local tag, send it
    #    to cad_generate". A user who picked Kimi got a part authored by whatever
    #    Ollama had, with nothing on screen saying so.
    if model_name.startswith("kimi-code/"):
        if pool is not None and user_id:
            try:
                from .engine_auth import get_verified_auth_mode
                if await get_verified_auth_mode(pool, int(user_id), "kimi-code"):
                    return Lane("claude_code", "kimi-code", model_name,
                                pool=pool, user_id=int(user_id), engine="kimi-code")
            except Exception:
                logger.warning("cad_agent: kimi-code lane lookup failed",
                               exc_info=True)
                return None
        logger.info("cad_agent: %s selected and this user has no verified Kimi Code "
                    "membership key", model_name)
        return None

    # 1. Per-user cloud credentials (the free tiers, OpenAI, Moonshot/Kimi).
    if pool is not None and user_id:
        try:
            from workspace.orchestration.provider_route import (
                ToolRouteUnavailable, resolve_tool_route,
            )
            route = await resolve_tool_route(model_name, pool, int(user_id))
            if route is not None:
                return Lane("openai_compatible", route.provider, model_name,
                            pool=pool, user_id=int(user_id))
        except Exception as e:
            # A provider that matched but has no key raises ToolRouteUnavailable, and
            # that is a *no* for this lane rather than an error: the user has selected
            # a model they cannot currently use, and the honest next step is the same
            # refusal the chat lane would give them.
            if type(e).__name__ == "ToolRouteUnavailable":
                logger.info("cad_agent: %s matched %s but has no credential",
                            model_name, getattr(e, "provider_label", "?"))
                return None
            logger.warning("cad_agent: provider route lookup failed", exc_info=True)

    # 2. Anthropic, whose Messages API needs the translation the chat lane already has.
    try:
        from workspace.model_proxy import _get_openclaw_config
        from workspace.model_proxy_anthropic import is_anthropic_model
        if is_anthropic_model(model_name):
            cfg = await _get_openclaw_config()
            key = (cfg or {}).get("api_key") if (cfg or {}).get(
                "provider_type") == "anthropic" else None
            if key:
                return Lane("anthropic", "anthropic", model_name, api_key=key,
                            pool=pool, user_id=user_id)

            # 3. A Claude SUBSCRIPTION. This is not a lesser case of the one above —
            # it is the common one, and for a long time it was the one that lost. A
            # subscription credential is a Claude Code token, not an API key: it does
            # not authenticate `/v1/messages` (see `engine_auth._verify_oauth_token_
            # via_cli`, which says so and verifies through the CLI for that reason).
            # So the model reaches the CAD tools the only way it can — the real CLI
            # in the sidecar, driving the same nine tools over MCP. Falling through
            # to the local generator here is what made a user who picked Opus get a
            # part authored by a 4B model with nothing on screen saying so.
            if pool is not None and user_id:
                from .engine_auth import get_verified_auth_mode
                mode = await get_verified_auth_mode(pool, int(user_id), "claude-code")
                if mode:
                    return Lane("claude_code", "anthropic", model_name,
                                pool=pool, user_id=int(user_id), engine="claude-code")
            logger.info("cad_agent: %s is a Claude model and this user has no "
                        "Anthropic credential of any kind", model_name)
    except Exception:
        logger.warning("cad_agent: anthropic lane lookup failed", exc_info=True)

    return None


async def unavailable_reason(model_name: str, pool, user_id: int | None) -> str | None:
    """Why this model can't author a part, in the user's terms — or ``None``.

    :func:`resolve_lane` returns ``None`` for two unrelated reasons: the model is a
    local tag that belongs in :mod:`cad_generate`, or it is a cloud model this user
    cannot currently use. Only the caller can tell those apart, and until it could,
    the second silently became the first: the request was quietly finished by
    whatever Ollama had. This answers the second case and stays quiet on the first,
    so a local pick is still a local pick and a cloud pick that cannot run says so.
    """
    model_name = (model_name or "").strip()
    if not model_name:
        return None
    if model_name.startswith("kimi-code/"):
        # The half of the routing fix the user actually sees. `resolve_lane` now
        # refuses this model when the membership key is missing, and a refusal with
        # no reason attached is exactly the silent fallback it was meant to end.
        return (f"**{model_name}** can't build parts here — there's no verified Kimi "
                "Code membership key on your account. Connect Kimi Code in "
                "Settings → Integrations (it has to be a Kimi Code membership key; "
                "a Moonshot platform key won't work).")
    try:
        from workspace.model_proxy_anthropic import is_anthropic_model
        if is_anthropic_model(model_name):
            return (f"**{model_name}** can't build parts here — there's no verified "
                    "Claude credential on your account. Connect Claude Code in "
                    "Settings → Integrations (a subscription token from "
                    "`claude setup-token` works; an API key also works).")
    except Exception:
        logger.debug("cad_agent: anthropic check failed", exc_info=True)

    # Every other cloud namespace routes through the same resolver the chat lane
    # uses, so "matched a provider, has no key" is a question already answered
    # there rather than a second list of prefixes kept in step by hand.
    if pool is None or not user_id:
        return None
    try:
        from workspace.orchestration.provider_route import (
            ToolRouteUnavailable, resolve_tool_route,
        )
        await resolve_tool_route(model_name, pool, int(user_id))
    except Exception as e:
        if type(e).__name__ == "ToolRouteUnavailable":
            label = getattr(e, "provider_label", None) or "that provider"
            return (f"**{model_name}** can't build parts here — there's no verified "
                    f"{label} key on your account. Add one in Settings → Integrations.")
    return None


# ---------------------------------------------------------------------------
# One model call, per lane
# ---------------------------------------------------------------------------

async def _complete(lane: Lane, messages: list[dict], tools: list[dict]) -> dict:
    """One assistant message, in OpenAI shape, whichever provider served it."""
    if lane.kind == "anthropic":
        return await _complete_anthropic(lane, messages, tools)

    from workspace.orchestration.model_router import ModelRouter
    return await ModelRouter().complete(
        model_name=lane.model, messages=messages, tools=tools,
        temperature=0.1, max_tokens=4096, timeout=MODEL_TIMEOUT_S,
        pool=lane.pool, user_id=lane.user_id,
    )


async def _complete_anthropic(lane: Lane, messages: list[dict],
                              tools: list[dict]) -> dict:
    """Anthropic's Messages API, through the translation the chat lane already owns.

    ``openai_to_anthropic_request`` / ``anthropic_response_to_openai`` are reused
    rather than reimplemented: they are what the OpenClaw path uses, so a tool-calling
    quirk fixed for one lane is fixed for both. The HTTP call is made here instead of
    through ``proxy_anthropic_chat`` only because that returns a ``JSONResponse`` for
    a browser and this loop needs the message.
    """
    import httpx
    from workspace.model_proxy_anthropic import (
        _ANTHROPIC_URL, _ANTHROPIC_VERSION,
        anthropic_response_to_openai, openai_to_anthropic_request,
    )

    body = {"model": lane.model, "messages": messages, "tools": tools,
            "temperature": 0.1, "max_tokens": 4096, "stream": False}
    payload = openai_to_anthropic_request(body, lane.model)
    headers = {"x-api-key": lane.api_key, "anthropic-version": _ANTHROPIC_VERSION,
               "content-type": "application/json"}
    async with httpx.AsyncClient(
            timeout=httpx.Timeout(MODEL_TIMEOUT_S, connect=10.0)) as client:
        r = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
    if r.status_code >= 400:
        # The provider's own body is not surfaced — it can carry account details.
        logger.warning("cad_agent: anthropic HTTP %s", r.status_code)
        raise RuntimeError(f"Anthropic returned HTTP {r.status_code}")
    out = anthropic_response_to_openai(r.json(), lane.model)
    msg = ((out.get("choices") or [{}])[0] or {}).get("message") or {}
    msg.setdefault("role", "assistant")
    if msg.get("content") is None:
        msg["content"] = ""
    msg["_usage"] = out.get("usage") or {}
    return msg


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_WORKFLOW = """\
You are authoring a part inside Harvis, which owns the CAD engine, the project
history and the acceptance decision. You do this entirely through the cad_* tools.

The sequence is:

0. cad_lookup_pattern with the user's request. If it matches a mating part
   (jar/lid, bushing, hook), follow that pattern's CadIR shape and checklist
   BEFORE writing a document. Grammar-valid sculpture that will not assemble
   is the wrong part. The user's stated millimetres override the pattern's
   defaults. If nothing matches, continue.

1. cad_create_project — title, the user's request in their own words as
   `description`, and `document` as a CadIR document encoded as JSON TEXT (a
   string, not an object). Use `recipe` instead only if the part IS one of the
   named recipes.
2. cad_start_build with the revision_id you got back.
3. Read the finished build. It carries TWO verdicts and they answer different
   questions: `status: succeeded` means the solid is well formed, and
   `conformance_status` means it is the part that was asked for. A build can
   succeed and be the wrong part.
4. If `conformance_status` is "failed", read the failed checks. Each one names a
   dimension, the number that was measured, and the faces it was measured between,
   so it tells you which operation produced the wrong result. Do NOT fix it with
   cad_propose_revision: a revision is permanent and an attempt that misses would
   stay in the user's history forever. Repair it in an experiment instead:

   a. cad_open_experiment on the revision that failed.
   b. cad_experiment_build with the corrected document — or with `params` alone if
      only a number is wrong — and read the build it returns, exactly as in step 3.
   c. When one of those builds comes back "passed" or "unverified",
      cad_promote_experiment turns THAT build into a revision and closes the
      experiment. Nothing else in it is kept.
   d. If nothing works, cad_abandon_experiment and tell the user plainly which
      measurement you could not hit. That is a better answer than a wrong part.

   You get at most %(repairs)d corrections, and the experiment caps its own attempts
   as well. If two attempts measure the same thing, stop: the same document will
   keep measuring the same thing.
5. When you are done, reply with one short plain sentence. Do not paste the
   document, do not list the ids, and do not describe the geometry: the user is
   shown a live card with the real measurements and the download links.

Rules you cannot work around, so do not try:

* The requirements you are graded on are extracted from the user's own message by
  Harvis, before you run. Your `description` argument is recorded as a label and
  is never what gets measured. Rewriting the request in easier numbers changes
  nothing except the honesty of your answer.
* You cannot accept a revision. Anything you author is a PROPOSAL and stays one
  until the person accepts it in CAD Studio. That is correct — do not look for a
  way around it and do not tell the user their part is final.
* You never see a file path, a storage key or a database. Ids are opaque and the
  only handles that exist.
* If a tool refuses, the refusal says why. Fix the call or explain the problem;
  do not repeat the identical call.
"""


def _system_prompt() -> str:
    return (
        cad_generate.grammar_reference()
        + "\n\n--- How this works ---\n"
        + (_WORKFLOW % {"repairs": MAX_REPAIRS})
    )


def _selection_brief(sel: dict) -> str:
    """What the model is told about the user's selection. Server words only.

    Every value here came back from ``cad_store.resolve_selection``, so the label the
    model reads is the label the database holds — a page that sent a selection cannot
    also narrate what it was. The ids are opaque and are the only handles the model
    gets: no storage key, no path, no user id.

    The last paragraph is what makes this a brief rather than a hint. A model told only
    "the user selected X" will still reach for ``cad_create_project``, because that is
    the move it knows; naming the two tools that edit an existing project gives it an
    obviously correct alternative.
    """
    op = sel.get("cadir_operation_id")
    lines = [
        "--- What the user has selected ---",
        f'They are looking at project "{sel["project_title"]}" '
        f'(project_id {sel["project_id"]}), revision {sel["revision_seq"]} '
        f'(revision_id {sel["revision_id"]}).',
        f'Selected: {sel["label"]} — a {sel["kind"]}, currently {sel["status"]}.',
    ]
    if op:
        lines.append(f'That row is CadIR operation "{op}". '
                     "Edit that operation rather than rewriting the document.")
    lines += [
        "",
        "This is an EDIT of that existing part, not a new one. Read it first with "
        "cad_inspect_revision(revision_id), then change it with "
        "cad_propose_revision(project_id, base_revision_id=<that revision>, …) and "
        "build the revision you get back. Do not call cad_create_project.",
    ]
    return "\n".join(lines)


def _session_brief(sess: dict) -> str:
    """What the model is told when the turn was sent from inside a CAD session (CS-1).

    A session is a room with one part in it, so every message after the first is an
    edit of that part whether or not anything is selected. Without this the model
    reaches for ``cad_create_project`` again — the same failure ``_selection_brief``
    exists to prevent — and the room ends up holding a project it is not showing.

    Only the ids and the stored title appear here. The session row is read server-side
    at the start of the turn, so a browser cannot claim to be in a room it is not in.
    """
    return "\n".join([
        "--- The project this conversation is about ---",
        f'This conversation is the CAD session for "{sess.get("title") or "this part"}" '
        f'(project_id {sess["project_id"]}).',
        f'Its newest revision is {sess["revision_seq"]} '
        f'(revision_id {sess["revision_id"]}).',
        "",
        "Every message here is about THAT project. This is an EDIT of it, not a new "
        "part. Read it first with cad_inspect_revision(revision_id), then change it "
        "with cad_propose_revision(project_id, base_revision_id=<that revision>, …) "
        "and build the revision you get back. Do not call cad_create_project — this "
        "session already has a project, and a second one would not be shown to the "
        "user.",
    ])


async def _bind_session(ctx: cad_tools.CadToolContext) -> dict | None:
    """Re-read the turn's session so the brief names the project that exists *now*.

    The binding cannot be settled when the turn is queued: on the first turn of a
    session the project does not exist yet — the model creates it seconds later — and
    a follow-up may well have been enqueued before that happened. Reading it here, at
    the moment the model is about to be asked, is the only point where the answer is
    current. A session with no project yet returns ``None`` and the turn is briefed as
    an ordinary build, which is exactly what it is.

    The *newest* revision is what the brief names, not the project's head. Head can lag
    behind an unaccepted proposal, and basing an edit on it would silently throw away
    the change the previous turn just made — the same staleness Gate 7C fixed for
    bounded repair.
    """
    extra = ctx.extra or {}
    session_id = extra.get("cad_session_id")
    if not session_id or ctx.pool is None:
        return None
    try:
        from . import cad_store
        sess = await cad_store.get_session(ctx.pool, str(session_id), ctx.user_id)
        if not sess or not sess.get("project_id"):
            return None
        newest = await cad_store.list_revisions(ctx.pool, sess["project_id"],
                                                ctx.user_id, limit=1)
    except Exception:
        logger.warning("cad_agent: could not read the session for this turn",
                       exc_info=True)
        return None
    if not newest:
        # A project with no revision at all is a project mid-creation; briefing an edit
        # against a revision that does not exist yet would send the model looking for
        # an id nothing can resolve.
        return None
    sess = dict(sess)
    sess["revision_id"] = newest[0]["id"]
    sess["revision_seq"] = newest[0]["seq"]
    extra["session"] = sess
    ctx.extra = extra
    return sess


def _task_text(description: str, ctx: cad_tools.CadToolContext) -> str:
    """The request as the model sees it — a build, or an edit of what it is looking at.

    Both lanes read it from here so a selection cannot mean one thing in the HTTP tool
    loop and something else in the CLI sidecar.

    A selection outranks the session because it is the narrower fact: it names a body
    inside the same project and carries the revision the user is actually looking at.
    """
    said = description.strip()[:2000]
    extra = ctx.extra or {}
    sel = extra.get("selection")
    if sel:
        return f"{_selection_brief(sel)}\n\n--- What they asked ---\n{said}"
    sess = extra.get("session")
    if sess and sess.get("project_id"):
        return f"{_session_brief(sess)}\n\n--- What they asked ---\n{said}"
    return f"Build this part:\n{said}"


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

async def _await_terminal(ctx: cad_tools.CadToolContext, build_id: str) -> dict | None:
    """Wait for a build to finish, or give up and report it unfinished.

    Read through :func:`cad_tools.dispatch` rather than through the store directly, so
    the state this loop sees is byte-for-byte the state the model would have seen by
    polling. A shortcut here would be a second view of a build.
    """
    deadline = time.monotonic() + BUILD_WAIT_S
    payload: dict | None = None
    while time.monotonic() < deadline:
        payload, ok = await cad_tools.dispatch("cad_get_build", {"build_id": build_id}, ctx)
        if not ok:
            return payload
        if payload.get("status") in _TERMINAL:
            return payload
        await asyncio.sleep(_POLL_S)
    return payload


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OBSERVATION_CHARS else (
        text[:MAX_OBSERVATION_CHARS] + " …[truncated]")


# ---------------------------------------------------------------------------
# The Claude Code sidecar lane
# ---------------------------------------------------------------------------

# The sidecar's scratch directory, on the shared artifact volume it already mounts.
# Nothing is written there by the CAD tools — the CLI just needs a cwd it can use.
_SIDECAR_WORKDIR = "/data/artifacts/cad-agent"

# Claude Code's built-in tools that have no business in a CAD authoring turn. The
# CAD tools arrive over MCP and are named separately, so withholding these leaves
# the model exactly the nine it is supposed to use plus harmless local reads.
_SIDECAR_DISALLOWED = ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit",
                       "WebFetch", "WebSearch", "Task"]


def _sidecar_ids(payload: dict, found: dict) -> None:
    """Pick the ids out of one tool result. Last writer wins, which is what we want:
    a repair's revision supersedes the one before it."""
    for key in ("project_id", "revision_id", "build_id", "title",
                "conformance_status"):
        val = payload.get(key)
        if val:
            found[key] = val
    rev = payload.get("revision")
    if isinstance(rev, dict) and rev.get("revision_id"):
        found["revision_id"] = rev["revision_id"]


def sidecar_launch_env(engine: str, secret: str, auth_mode: str, model_name: str,
                       *, think_tokens: int = 0) -> tuple[list[str], str]:
    """The `docker exec -e` flags one sidecar run launches with, and the model to pin.

    Lifted out of :func:`_author_via_sidecar` because it is both the part that has to
    stay exactly right and the part a test could not otherwise reach — everything
    around it spawns a container. Getting it wrong does not fail loudly: a Claude
    subscription run with ``CLAUDE_CODE_SIMPLE=1`` authenticates against nothing, and
    a Kimi run with an unpinned model slot dies partway through on a model id Kimi
    never served, long after the first token made it look healthy.
    """
    model_id = (model_name or "").split("/", 1)[-1].strip()
    if engine == "kimi-code":
        from .engine_auth import (KIMI_CODE_BASE_URL, KIMI_CODE_CONTEXT_TOKENS,
                                  KIMI_CODE_DEFAULT_MODEL, KIMI_CODE_MODELS)
        if model_id not in KIMI_CODE_MODELS:
            model_id = KIMI_CODE_DEFAULT_MODEL
        # EVERY model slot is pinned, not just ANTHROPIC_MODEL. The CLI resolves its
        # own aliases internally — a Sonnet-tier model for the main loop, Haiku-tier
        # for cheap side calls, another for subagents — and each of those would ask
        # Kimi for an Anthropic model id it does not serve, so the run dies PARTWAY
        # THROUGH, long after the first token made it look healthy. This is the same
        # env block as `engine_adapter._build_kimi_code_command`; keep the two in
        # agreement.
        cred = ["-e", f"ANTHROPIC_BASE_URL={KIMI_CODE_BASE_URL}",
                "-e", f"ANTHROPIC_API_KEY={secret}",
                "-e", f"ANTHROPIC_MODEL={model_id}",
                "-e", f"ANTHROPIC_DEFAULT_OPUS_MODEL={model_id}",
                "-e", f"ANTHROPIC_DEFAULT_SONNET_MODEL={model_id}",
                "-e", f"ANTHROPIC_DEFAULT_HAIKU_MODEL={model_id}",
                "-e", f"CLAUDE_CODE_SUBAGENT_MODEL={model_id}",
                # Kimi Code is API-key only, so simple mode — which reads auth
                # strictly from ANTHROPIC_API_KEY — is right here, unlike a Claude
                # subscription, which has to clear it.
                "-e", "CLAUDE_CODE_SIMPLE=1"]
        window = KIMI_CODE_CONTEXT_TOKENS.get(model_id)
        if window:
            cred += ["-e", f"CLAUDE_CODE_MAX_CONTEXT_TOKENS={window}",
                     "-e", f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={window}"]
    elif auth_mode == "oauth_token":
        # CLAUDE_CODE_SIMPLE (baked into the sidecar image) reads ANTHROPIC_API_KEY
        # only and ignores the OAuth token, so subscription mode must clear it.
        cred = ["-e", f"CLAUDE_CODE_OAUTH_TOKEN={secret}", "-e", "CLAUDE_CODE_SIMPLE="]
    else:
        cred = ["-e", f"ANTHROPIC_API_KEY={secret}", "-e", "CLAUDE_CODE_SIMPLE=1"]
    if think_tokens > 0 and engine != "kimi-code":
        # Extended thinking is an Anthropic feature and the budget is an Anthropic
        # parameter. Kimi Code serves an Anthropic-COMPATIBLE API, not Anthropic, and
        # the proven Kimi launch in `engine_adapter` sends no such variable — so
        # neither does this one, rather than finding out mid-run which way that
        # endpoint answers an argument it was never promised.
        cred = [*cred, "-e", f"MAX_THINKING_TOKENS={think_tokens}"]
    return cred, model_id


async def _author_via_sidecar(description: str, *, lane: Lane,
                              ctx: cad_tools.CadToolContext,
                              on_event: EventSink = None) -> dict:
    """Let the real Claude Code CLI author the part, over the MCP door.

    This is the same nine tools through the same :func:`cad_tools.dispatch` as every
    other lane — what differs is only *who dials*. A subscription credential cannot
    call ``/v1/messages``, so Harvis cannot run the tool loop itself; the CLI runs it,
    inside the sidecar, with the CAD server registered and its own file and shell
    tools withheld.

    The ids come out of the CLI's own ``stream-json``: every ``tool_result`` block
    carries the JSON payload :func:`cad_tools.as_text` produced, so what this function
    learns is byte-for-byte what the model was told. Nothing is inferred from
    timestamps, and nothing is read back out of the store on a guess about which row
    was newest — two builds running for one user at once would make that a lie.
    """
    started = time.monotonic()
    from .engine_auth import get_verified_engine_auth

    engine = lane.engine or "claude-code"
    auth = await get_verified_engine_auth(lane.pool, int(lane.user_id or 0), engine)
    if not auth:
        # Only reachable if the credential was removed between resolve and launch.
        label = "Kimi Code membership" if engine == "kimi-code" else "Claude"
        return {"ok": False, "provider": lane.provider, "model": lane.model,
                "error_code": "no_credential",
                "message": f"your {label} credential is no longer verified"}
    secret, auth_mode = auth

    from workspace.orchestration.engine_adapter import _CONTAINERS, _cad_mcp_args
    # Read from the engine the lane named, because the credential lookup above already
    # does. Kimi Code shares the claude-code sidecar today, so this resolves to the
    # same container — but it resolves it rather than assuming it, and the assumption
    # was the asymmetry that made a Kimi lane unreachable from here.
    container = _CONTAINERS.get(engine, "harvis-claude-code")
    workdir = f"{_SIDECAR_WORKDIR}/{uuid.uuid4().hex[:12]}"
    try:
        mk = await asyncio.create_subprocess_exec(
            "docker", "exec", "-u", "1001", container, "mkdir", "-p", workdir,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(mk.wait(), timeout=15)
    except Exception:
        # A missing workdir is not fatal on its own — the CLI falls back to its own
        # cwd. A missing *sidecar* is, and that surfaces on the real launch below
        # with the error the user can act on.
        logger.debug("cad_agent: could not prepare sidecar workdir", exc_info=True)

    mcp_args = _cad_mcp_args(
        lane.user_id,
        conversation_id=ctx.conversation_id,
        # The answer key. Without this the DesignSpec would be extracted from the
        # model's own paraphrase of the request — see `cad_tools._design_spec`.
        user_text=ctx.user_text or description,
        model_provider=lane.provider,
        model_name=lane.model,
    )
    if not mcp_args:
        return {"ok": False, "provider": lane.provider, "model": lane.model,
                "error_code": "cad_unavailable",
                "message": "the CAD tool server could not be offered to Claude"}

    cred, model_id = sidecar_launch_env(engine, secret, auth_mode, lane.model,
                                       think_tokens=_THINK_TOKENS)
    brief = (_system_prompt()
             + "\n\n--- The request ---\n"
             + _task_text(description, ctx))
    cmd = ["docker", "exec", *cred, "-u", "1001", "-w", workdir, container,
           "claude", "-p", brief,
           "--output-format", "stream-json", "--verbose",
           "--dangerously-skip-permissions",
           "--disallowedTools", *_SIDECAR_DISALLOWED,
           *mcp_args]
    if model_id:
        cmd += ["--model", model_id]

    found: dict[str, Any] = {}
    trace: list[dict] = []
    # Build ids whose conformance came back "failed", deduplicated — see `repairs` below.
    failed_builds: set[str] = set()
    cli_error = ""
    stderr_tail: list[str] = []

    async def _drain(p) -> None:
        try:
            async for raw in p.stderr:
                s = raw.decode("utf-8", "replace").rstrip()
                if s:
                    stderr_tail.append(s)
                    del stderr_tail[:-10]
        except Exception:
            pass

    proc = None
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=1024 * 1024)
        except Exception as exc:
            logger.warning("cad_agent: could not start the Claude sidecar (%s)",
                           type(exc).__name__)
            return {"ok": False, "provider": lane.provider, "model": lane.model,
                    "error_code": "sidecar_unavailable",
                    "message": f"the {container} sidecar could not be started"}
        drain = asyncio.create_task(_drain(proc))
        deadline = time.monotonic() + TURN_BUDGET_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                cli_error = cli_error or "the run exceeded its time budget"
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                cli_error = cli_error or "the run exceeded its time budget"
                break
            if not raw:
                break
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue  # the CLI also prints non-JSON lines; they are not events
            etype = obj.get("type")
            if etype == "assistant":
                for block in ((obj.get("message") or {}).get("content") or []):
                    btype = block.get("type")
                    if btype == "text":
                        # The model's own narration, and the only reason this arm
                        # exists: everything the CLI says between tool calls used to
                        # land here and get dropped, so a turn that explained itself
                        # at every step showed the reader nothing but tool names.
                        said = _say(block.get("text"))
                        if said:
                            await _emit(on_event, kind="say", text=said)
                    elif btype in ("thinking", "redacted_thinking"):
                        # Arrives on the same wire as the text blocks. `thinking` holds
                        # the summary Anthropic returns for extended thinking; the
                        # `redacted_thinking` variant is encrypted and carries no
                        # readable field at all, so it produces nothing here rather
                        # than a row promising a thought the reader cannot be shown.
                        thought, clipped = _thought(block.get("thinking"))
                        if thought:
                            await _emit(on_event, kind="think", text=thought,
                                        clipped=clipped)
                    elif btype == "tool_use":
                        trace.append({"tool": str(block.get("name") or "tool"),
                                      "ok": None, "error_code": None})
                        await _emit(on_event, kind="tool_start",
                                    tool=str(block.get("name") or "tool"))
            elif etype == "user":
                for block in ((obj.get("message") or {}).get("content") or []):
                    if block.get("type") != "tool_result":
                        continue
                    c = block.get("content")
                    if isinstance(c, list):
                        c = "".join(str(b.get("text") or "") for b in c
                                    if isinstance(b, dict))
                    try:
                        payload = json.loads(c) if isinstance(c, str) else None
                    except ValueError:
                        payload = None
                    if not isinstance(payload, dict):
                        continue
                    ok = not block.get("is_error") and not payload.get("error_code")
                    if trace:
                        trace[-1]["ok"] = ok
                        trace[-1]["error_code"] = payload.get("error_code")
                    await _emit(on_event, kind="tool",
                                tool=trace[-1]["tool"] if trace else "tool", ok=ok,
                                error_code=payload.get("error_code"))
                    if ok:
                        before = dict(found)
                        # Counted by build id rather than by occurrence: the CLI polls
                        # cad_get_build, so one failed build is reported several times
                        # and a running total would report a model that waited patiently
                        # as a model that repaired four times.
                        if (payload.get("conformance_status") == "failed"
                                and payload.get("build_id")):
                            failed_builds.add(str(payload["build_id"]))
                        _sidecar_ids(payload, found)
                        if found.get("project_id") and (
                                found.get("project_id") != before.get("project_id")
                                or found.get("revision_id") != before.get("revision_id")):
                            await _emit(on_event, kind="ids",
                                        project_id=found.get("project_id"),
                                        revision_id=found.get("revision_id"),
                                        title=found.get("title"))
                        if found.get("build_id") and found.get("build_id") != before.get("build_id"):
                            await _emit(on_event, kind="build",
                                        build_id=found.get("build_id"),
                                        conformance=found.get("conformance_status"))
            elif etype == "result":
                # `is_error` first, and `subtype` never on its own: an auth failure
                # arrives as {"subtype":"success","is_error":true,…} and reading
                # subtype first renders the failure as the model's answer.
                if obj.get("is_error"):
                    cli_error = str(obj.get("result")
                                    or obj.get("subtype") or "error")[:300]
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass
        drain.cancel()
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            # `rmdir`, not `rm -rf`: the CAD tools write nothing here and the CLI's own
            # file tools are withheld, so an empty directory is the expected state and a
            # non-empty one is a surprise worth leaving intact to look at.
            rm = await asyncio.create_subprocess_exec(
                "docker", "exec", "-u", "1001", container, "rmdir", workdir,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(rm.wait(), timeout=10)
        except Exception:
            logger.debug("cad_agent: sidecar workdir left behind", exc_info=True)

    build_id = found.get("build_id")
    conformance = found.get("conformance_status")
    if build_id and conformance is None:
        # The CLI is told to poll, and mostly does. When it stops early we wait
        # ourselves rather than reporting a build as unfinished that is seconds from
        # done — read through `dispatch`, so this is the same view the model had.
        finished = await _await_terminal(ctx, str(build_id))
        if finished:
            conformance = finished.get("conformance_status") or conformance

    out: dict[str, Any] = {
        "ok": bool(build_id),
        "provider": lane.provider,
        "model": lane.model,
        "project_id": found.get("project_id"),
        "revision_id": found.get("revision_id"),
        "build_id": build_id,
        "title": found.get("title"),
        "conformance": conformance,
        # Builds that came back the wrong part — the same definition the native lane
        # counts, so the two lanes' numbers mean the same thing. Reported as 0 since
        # this lane was written, which made every sidecar run look like a first-time
        # success no matter how many corrections it took.
        "repairs": len(failed_builds),
        "rounds": len(trace),
        "trace": trace,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    if not build_id:
        detail = cli_error or (stderr_tail[-1] if stderr_tail else "")
        out.update({
            "error_code": "no_build",
            "message": (f"Claude Code did not build anything"
                        + (f" — {detail[:200]}" if detail else "")),
        })
    logger.info("cad_agent: claude-code sidecar %s tools=%d build=%s conformance=%s "
                "%dms", model_id or "(subscription)", len(trace), build_id,
                conformance, out["latency_ms"])
    return out


async def author(description: str, *, lane: Lane, ctx: cad_tools.CadToolContext,
                 max_rounds: int = MAX_ROUNDS, on_event: EventSink = None) -> dict:
    """Run the tool loop. Returns what happened — never raises for a model failure.

    The return value is the evidence, not a summary: which provider and model ran,
    every tool call in order, how many rounds it took, and the ids of whatever it
    created. A caller that wants to show a card needs ``build_id``; a caller auditing
    the lane needs the trace, and both come out of the same dict.

    ``on_event`` is how a caller watches instead of waiting. It changes nothing about
    the return value — the dict is byte-identical with or without a sink — because a
    turn that behaves differently when someone is looking is a turn nobody can debug.
    """
    # Before either lane, and before anything is asked: does this turn belong to a CAD
    # session that already has a part? Resolved here rather than at dispatch time
    # because a queued follow-up may have been recorded before the project existed.
    await _bind_session(ctx)

    if lane.kind == "claude_code":
        # A subscription credential cannot drive an HTTP tool loop at all, so this
        # lane's "model call" is a CLI process. Same tools, same dispatcher, same
        # return shape — the caller cannot tell the difference and should not.
        return await _author_via_sidecar(description, lane=lane, ctx=ctx,
                                         on_event=on_event)

    started = time.monotonic()
    tools = cad_tools.openai_tools(strict=False)
    messages: list[dict] = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _task_text(description, ctx)},
    ]

    trace: list[dict] = []
    project_id: str | None = None
    revision_id: str | None = None
    build_id: str | None = None
    title: str | None = None
    conformance: str | None = None
    repairs = 0
    rounds = 0
    last_error: dict | None = None
    # The graded report of the last build that came back the wrong part, and whether the
    # one after it moved any of those numbers. A model that answers a measurement with
    # the same measurement has stopped repairing, whatever budget is left.
    last_failed: dict | None = None
    stalled = False

    for rounds in range(1, max_rounds + 1):
        if time.monotonic() - started > TURN_BUDGET_S:
            last_error = {"error_code": "agent_timeout",
                          "message": "the model ran out of time authoring this part"}
            break
        try:
            msg = await _complete(lane, messages, tools)
        except Exception as e:
            logger.warning("cad_agent: %s completion failed (%s)",
                           lane.provider, type(e).__name__, exc_info=True)
            last_error = {"error_code": "model_error",
                          "message": f"{lane.model} did not answer "
                                     f"({type(e).__name__})"}
            break

        # Emitted before the calls are parsed, and outside the `if calls` below, so
        # both halves of a turn are reported: the narration a model writes alongside
        # its tool calls, and the prose it ends on when it has stopped calling tools.
        #
        # The thought goes first because it came first — it is the working that produced
        # the narration, and a timeline that printed them the other way round would read
        # as the model justifying itself after the fact.
        thought, clipped = _thought(msg.get("reasoning_content"), msg.get("reasoning"),
                                    msg.get("thinking"), msg.get("content"))
        if thought:
            await _emit(on_event, kind="think", text=thought, clipped=clipped)
        said = _say(msg.get("content"))
        if said:
            await _emit(on_event, kind="say", text=said)

        from workspace.orchestration.tools import parse_tool_calls
        calls = parse_tool_calls(msg, known={
            (s.get("function") or {}).get("name")
            for s in tools if isinstance(s, dict)
        })
        if not calls:
            # The model stopped calling tools. That is the end of the turn whether or
            # not it built anything; a model that answers in prose has answered.
            break

        # Ids come from the provider's own tool_calls when it sent them, so the
        # tool results below can be addressed back to the exact call.
        raw_calls = msg.get("tool_calls") if isinstance(msg.get("tool_calls"), list) else []
        observations: list[str] = []
        results: list[tuple[str, str]] = []
        for idx, call in enumerate(calls):
            name, args = call.get("name"), call.get("args") or {}
            await _emit(on_event, kind="tool_start", tool=name)
            payload, ok = await cad_tools.dispatch(name, args, ctx)
            trace.append({"tool": name, "ok": ok,
                          "error_code": None if ok else payload.get("error_code")})
            await _emit(on_event, kind="tool", tool=name, ok=ok,
                        error_code=None if ok else payload.get("error_code"))
            if not ok:
                last_error = {"error_code": payload.get("error_code") or "tool_failed",
                              "message": payload.get("message") or "the tool refused"}
            elif last_error and last_error.get("error_code") not in ("agent_timeout",
                                                                     "model_error"):
                # A model that recovers from a rejected argument shape has not failed.
                # Without this the run reports the stale refusal as its outcome.
                last_error = None
            text = _clip(cad_tools.as_text(payload, ok))
            observations.append(f"{name} -> {text}")
            call_id = str((raw_calls[idx] or {}).get("id") or "") if idx < len(raw_calls) else ""
            results.append((call_id, text))

            if ok and name in ("cad_create_project", "cad_propose_revision"):
                project_id = payload.get("project_id") or project_id
                title = payload.get("title") or title
                rev = payload.get("revision") or {}
                revision_id = rev.get("revision_id") or revision_id
                # Emitted here rather than at the end of the turn: this is the instant
                # the workspace becomes openable, and it is the whole point of UX-0.
                await _emit(on_event, kind="ids", project_id=project_id,
                            revision_id=revision_id, title=title)
            elif ok and name == "cad_start_build":
                build_id = payload.get("build_id") or build_id
                # Announced before the wait rather than after it. ``kind="build"``
                # below fires once the geometry is already finished, which is exactly
                # too late for a cancel: the seconds worth interrupting are the ones
                # spent inside ``_await_terminal``. A caller holding the build id here
                # can kill the engine's build as well as this coroutine — and the
                # engine only stops when it is told, because dropping the HTTP
                # connection does nothing to a build that has already started.
                await _emit(on_event, kind="build_started", build_id=build_id)
                # See the module docstring: waited on here, not by the model.
                finished = await _await_terminal(ctx, str(build_id))
                if finished:
                    conformance = finished.get("conformance_status") or conformance
                    await _emit(on_event, kind="build", build_id=build_id,
                                conformance=conformance)
                    done = "\n\nthe build finished: " + _clip(
                        cad_tools.as_text(finished, True))
                    observations.append("cad_get_build -> " + done)
                    # Folded into this call's own result: a tool message may only
                    # answer a call the model actually made.
                    results[idx] = (results[idx][0], results[idx][1] + done)
                    if finished.get("conformance_status") == "failed":
                        repairs += 1
                        report = finished.get("conformance")
                        if isinstance(report, dict):
                            if last_failed is not None and not (
                                    cad_generate.repair_made_progress(last_failed,
                                                                      report)):
                                stalled = True
                            last_failed = report
            elif ok and name == "cad_get_build":
                conformance = payload.get("conformance_status") or conformance

        # A part that built and conforms is finished, and one more model round would
        # only invite it to keep editing something that is already right. This holds
        # after a successful repair too — the repair worked, so the turn is over.
        if build_id and conformance in ("passed", "unverified"):
            break
        if stalled:
            # Not an error and not a refusal: the part exists, it is marked failed, and
            # the reason to stop is that the evidence stopped changing. Spending the
            # rest of the budget here buys the user the identical part and two more
            # model calls.
            logger.info("cad_agent: repair %d moved no measurement, stopping "
                        "provider=%s model=%s", repairs, lane.provider, lane.model)
            break
        if repairs > MAX_REPAIRS:
            break

        # Write the round back in the protocol we advertised. The model is sent
        # OpenAI `tools`, so it must get its own tool_calls echoed and one `tool`
        # message per call — not a paraphrase on a user turn. Two things break
        # otherwise: the model cannot see which calls it already made (measured —
        # every model stopped before cad_start_build), and Gemini 3 rejects the
        # next request outright because the thought_signature it hides inside
        # tool_calls[].extra_content never comes back. The assistant message is
        # echoed VERBATIM for that reason — rebuilding it drops those fields.
        if all(cid for cid, _ in results) and len(results) == len(raw_calls):
            messages.append({k: v for k, v in msg.items() if k != "_usage"})
            for call_id, text in results:
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": text[:20_000]})
        else:
            # A provider that answered with calls embedded in prose has no ids to
            # address, so the readable form is the only one available.
            messages.append({"role": "assistant",
                             "content": msg.get("content") or "(tool calls)"})
            messages.append({"role": "user",
                             "content": "\n\n".join(observations)[:20_000]})

    out: dict[str, Any] = {
        "ok": bool(build_id),
        "provider": lane.provider,
        "model": lane.model,
        "project_id": project_id,
        "revision_id": revision_id,
        "build_id": build_id,
        "title": title,
        "conformance": conformance,
        "repairs": repairs,
        "rounds": rounds,
        "trace": trace,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    if not build_id:
        # Nothing was built, so say which failure it was. "The model declined" and
        # "the tool refused" and "the provider was down" need different answers from
        # the user, and collapsing them into one sentence hides which one happened.
        out.update(last_error or {
            "error_code": "no_build",
            "message": f"{lane.model} did not build anything",
        })
    logger.info("cad_agent: %s/%s rounds=%d tools=%d build=%s conformance=%s",
                lane.provider, lane.model, rounds, len(trace), build_id, conformance)
    return out
