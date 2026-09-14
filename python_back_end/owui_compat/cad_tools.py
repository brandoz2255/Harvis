"""One CAD tool surface, four callers (Gate 7C-3).

Claude's native tools, Kimi's OpenAI-shaped function tools, and the MCP servers
that Claude Code and Kimi Code speak are three encodings of the same calls.
Written three times they would drift three ways, and the drift would land in the
one place nobody notices — a tool that exists for one provider and silently does
not for another. So the tools are declared once here, in a provider-neutral form,
and each wire shape is *derived*:

    CAD_TOOLS ──► openai_tools()     Kimi, and any OpenAI-compatible upstream
              ──► anthropic_tools()  Claude, via Anthropic's input_schema
              ──► mcp_tools()        Claude Code / Kimi Code sidecars
              ──► dispatch()         the single execution path for all of them

**The security rule this module exists to enforce**, stated by the person who
asked for it: *the model must never receive filesystem paths, storage keys,
database access, or direct worker access. Harvis injects authenticated
user/session context server-side; models receive opaque IDs.*

Concretely, that means:

* Every argument a model can send is a UUID, a number, an enum or a short
  string. There is no ``user_id`` argument, and there never will be — the caller
  identity arrives in :class:`CadToolContext`, which the model cannot write to.
* Every store read goes through ``cad_store``'s ownership-in-the-WHERE-clause
  helpers, so another user's project answers ``not_found`` rather than 403.
* ``storage_key`` is not returned by anything here (``cad_store._row_artifact``
  already refuses to emit it) and neither is any on-disk path.
* Errors are ``{error_code, message}`` — the same shape the HTTP lane speaks —
  and carry no paths, no argv and no host names.

**What is deliberately NOT a tool: accepting a revision.** Gate 7C-2 exists so a
model-authored revision stays a proposal until a person says otherwise, and a
``cad_accept_revision`` tool would hand that decision straight back to the model.
Acceptance is reachable only from the UI, by a human, through
``POST /api/cad/projects/{id}/revisions/{id}/accept``.

**And the answer key is not an argument either.** ``design_spec`` is never
accepted from the model. The server extracts it from the user's own words with
``cad_designspec`` — no model in the loop — and when the context carries the
user's actual message (the chat lane does), that message is what gets extracted,
not the model's paraphrase of it. A model that could soften "30 mm" on its way
into the spec would be grading its own work again, which is the exact failure
Gate 7C was opened for.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import HTTPException

from . import (cad_designspec, cad_experiments, cad_ir, cad_patterns, cad_router,
               cad_store, fab_cad)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.1"

# Bounds on what a model may ask for in one call. These are not the engine's limits
# — the engine re-checks everything — they are the point past which an argument is
# obviously not a real request and should cost nothing to refuse.
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 2000
MAX_ID_CHARS = 64
MAX_DOCUMENT_CHARS = 40000


@dataclass
class CadToolContext:
    """Everything the model does not get to say.

    ``user_id`` is the authenticated caller, taken from the request's JWT by
    whichever surface is dispatching — never from a tool argument. ``user_text``
    is the user's own most recent message when the caller knows it; it is what the
    DesignSpec is extracted from, so the requirement being graded comes from the
    person rather than from the model's retelling of them.
    """

    pool: Any
    user_id: int
    conversation_id: str | None = None
    user_text: str | None = None
    # Where this dispatch came from, for the audit line. Not a permission — the
    # permissions are identical on every surface, on purpose.
    source: str = "chat"
    # Who is calling, as the *surface* knows it rather than as the caller claims it.
    # A revision records its author, and a model that could name its own author in a
    # tool argument could name someone else's — so this is context, like `user_id`,
    # and there is no tool that accepts it.
    model_provider: str | None = None
    model_name: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Small shared pieces of schema. Written once so the same field means the same
# thing in every tool, including its wording — the description IS the contract as
# far as a model is concerned.
# ---------------------------------------------------------------------------

_ID = {"type": "string", "maxLength": MAX_ID_CHARS,
       "description": "An opaque Harvis id (UUID). Never a path or a filename."}

# A list of name/value pairs rather than the object-keyed map the HTTP routes take.
# The map is the nicer shape and it is the one that cannot survive OpenAI strict
# mode: a free-form `additionalProperties` map is not expressible there, so the
# strict variant would have had to drop the property — leaving Kimi unable to set a
# single dimension. One shape on every provider beats a prettier one on some of them.
_PARAMS = {
    "type": "array",
    "description": (
        "Named numeric parameters for the recipe or document, in millimetres, as "
        "[{name, value}] pairs. Every value is re-checked by the engine."
    ),
    "maxItems": 32,
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": 64},
            "value": {"type": "number"},
        },
        "required": ["name", "value"],
        "additionalProperties": False,
    },
}

_FORMATS = {
    "type": "array",
    "description": "Export formats to produce. Defaults to stl, step and glb.",
    "items": {"type": "string", "enum": ["stl", "step", "glb", "3mf"]},
    "maxItems": 4,
}

# JSON *text*, not a nested object, for the same reason `params` is a pair list:
# strict mode forbids `additionalProperties: true` anywhere in the schema, and CadIR
# is a recursive grammar with no practical closed-form expansion. Declared as an
# object it would be legal for Claude and rejected outright by every strict-mode
# provider — the schema would look healthy while the two authoring tools quietly
# did not exist on that lane. A string survives everywhere and is parsed here.
_DOCUMENT = {
    "type": "string",
    "maxLength": MAX_DOCUMENT_CHARS,
    "description": (
        "A CadIR document as JSON text: "
        '{"schema_version": "0.1", "name": …, "units": "mm", "parameters": […], '
        '"operations": […]}. Use this for a part that is not one of the named '
        "recipes. CALL cad_get_schema FIRST — CadIR is a small fixed grammar and "
        "guessing at its field names is the single most expensive thing you can do "
        "here. It has no move/translate operation (placement is each operation's own "
        "`at`) and no cut/bore operation (a hole is a solid with mode: subtract). "
        "The document is validated against the grammar before anything is written."
    ),
}

_RECIPE = {
    "type": "string",
    "maxLength": 64,
    "description": (
        "The name of a built-in recipe. Call cad_get_capabilities for the list. "
        "Ignored when `document` is given."
    ),
}

_DESCRIPTION = {
    "type": "string",
    "maxLength": MAX_DESCRIPTION_CHARS,
    "description": (
        "What the user asked for, in their own words and with their numbers "
        "unchanged. This is what the finished geometry is measured against, so "
        "paraphrasing it or rounding a dimension changes what counts as correct."
    ),
}


# ---------------------------------------------------------------------------
# The registry. Order is the order a model sees them in, which is roughly the
# order they get used in.
# ---------------------------------------------------------------------------

def _tool(name: str, description: str, properties: dict, required: list[str],
          read_only: bool) -> dict:
    return {
        "name": name,
        "description": description,
        "read_only": read_only,
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


CAD_TOOLS: list[dict] = [
    _tool(
        "cad_get_capabilities",
        "Whether the local CAD lane is available right now, which recipes and "
        "export formats it has, and how much of the user's storage quota is used. "
        "Call this before offering to build anything — the lane can be switched "
        "off by the operator or its engine can be down.",
        {}, [], read_only=True,
    ),
    _tool(
        "cad_get_schema",
        "The CadIR grammar: every operation and its fields, how placement and "
        "profiles are spelled, and one complete document that builds. Call this "
        "before writing any `document` argument. CadIR is a small closed grammar "
        "and it is not the one you would guess — there is no move, translate or "
        "rotate operation, and no cut, bore or hole operation. Only needed for "
        "documents; the named recipes take plain parameters.",
        {}, [], read_only=True,
    ),
    _tool(
        "cad_lookup_pattern",
        "Local mechanical design reference (no internet). Returns the shop "
        "pattern that matches a part description — jar with slip-fit lid, "
        "flanged bushing, wall hook — including CadIR shape, assumed fits, "
        "and what this lane cannot cut (no threads). Call this BEFORE writing "
        "a document for a lid, cap, jar, bushing or hook. A valid solid that "
        "will not assemble is still the wrong part.",
        {
            "description": _DESCRIPTION,
            "pattern_id": {
                "type": "string", "maxLength": 64,
                "description": "Fetch one catalog id directly. Omit to match "
                               "against description.",
            },
        },
        [], read_only=True,
    ),
    _tool(
        "cad_dry_compile",
        "Static-check a CadIR document without building it. Answers what the "
        "document resolves to: how many solids it will produce, its cost against "
        "the cap, every parameter's resolved value, and the planned instance count "
        "for each operation — where a `0` means that operation was skipped, by its "
        "`when` guard or by a grid with no positions, which is the usual way a part "
        "comes out missing a feature it clearly declares. "
        "What it is NOT: it is a plan and budget check, not a geometry solver. It "
        "cannot tell you whether a fillet radius is one the edges will take, whether "
        "a boolean leaves the solid count you expect, or whether two bodies "
        "interfere. Only a build can. Use this to catch a wrong document before it "
        "costs a revision, then build.",
        {"document": _DOCUMENT, "params": _PARAMS}, ["document"], read_only=True,
    ),
    _tool(
        "cad_create_project",
        "Start a new CAD project from a description. Creates the project and its "
        "first revision; it does NOT build anything — call cad_start_build next. "
        "A revision you author arrives as a PROPOSAL: it is real history that can "
        "be built and inspected, but it does not become the project's head until "
        "the user accepts it in CAD Studio.",
        {
            "title": {"type": "string", "maxLength": MAX_TITLE_CHARS,
                      "description": "A short name for the project."},
            "description": _DESCRIPTION,
            "recipe": _RECIPE,
            "document": _DOCUMENT,
            "params": _PARAMS,
        },
        ["title", "description"], read_only=False,
    ),
    _tool(
        "cad_propose_revision",
        "Append a new revision to an existing project — a changed parameter, a "
        "repaired document, a different recipe. Nothing is built yet. Pass "
        "base_revision_id to state which revision you edited; if it is no longer "
        "the project head you get a stale_revision error instead of a silent fork.",
        {
            "project_id": _ID,
            "base_revision_id": dict(
                _ID, description="The revision you based this on. Omit to append "
                                 "to whatever the current head is."),
            "description": _DESCRIPTION,
            "recipe": _RECIPE,
            "document": _DOCUMENT,
            "params": _PARAMS,
        },
        ["project_id"], read_only=False,
    ),
    _tool(
        "cad_start_build",
        "Build a revision's geometry. Returns immediately with a build id — the "
        "geometry runs in the background, so poll cad_get_build until its status "
        "is succeeded, failed or cancelled. What gets built comes from the stored "
        "revision, not from this call.",
        {
            "revision_id": _ID,
            "formats": _FORMATS,
            "idempotency_key": {
                "type": "string", "maxLength": 128,
                "description": "Retrying with the same key returns the existing "
                               "build instead of starting a second one.",
            },
        },
        ["revision_id"], read_only=False,
    ),
    _tool(
        "cad_get_build",
        "The state of one build: status, how long it took, the geometry "
        "measurements, and the conformance verdict. Read both verdicts — "
        "`status: succeeded` only says the solid is well-formed, while "
        "`conformance_status: failed` says it is not the part that was asked for. "
        "A build can be both at once, and when it is, the part is wrong.",
        {"build_id": _ID}, ["build_id"], read_only=True,
    ),
    _tool(
        "cad_cancel_build",
        "Stop a build that is queued or running. Already-finished builds are left "
        "alone and report their existing status.",
        {"build_id": _ID}, ["build_id"], read_only=False,
    ),
    _tool(
        "cad_inspect_revision",
        "One revision in full: its parameters, its document or recipe, whether it "
        "is a proposal or accepted, and its most recent build with that build's "
        "measurements and conformance checks. This is what to read before "
        "proposing a repair — the failed checks name the dimension that missed.",
        {"revision_id": _ID}, ["revision_id"], read_only=True,
    ),
    _tool(
        "cad_compare_revisions",
        "What changed between two revisions of one project: which parameters "
        "differ, and how the measured geometry differs. A revision that has never "
        "built successfully reports null measurements rather than no change.",
        {"project_id": _ID,
         "revision_a": dict(_ID, description="The earlier revision."),
         "revision_b": dict(_ID, description="The later revision.")},
        ["project_id", "revision_a", "revision_b"], read_only=True,
    ),
    _tool(
        "cad_list_artifacts",
        "The exported files a build produced — format, size and checksum, plus the "
        "authenticated URL the user's browser can download each from. There are no "
        "file paths here and the bytes are not readable by you; the user downloads "
        "them from their own session.",
        {"build_id": _ID}, ["build_id"], read_only=True,
    ),
    _tool(
        "cad_render_views",
        "The rendered inspection views a build has, by camera preset. Renders are "
        "captured by the user's own 3D viewport, so a build only has views the user "
        "was shown — an empty list means nobody has opened the workspace on it yet, "
        "not that rendering failed. You cannot see these images and you cannot make "
        "one from here; what you can do is tell the user which views exist and which "
        "do not. A render is a picture of the solid at a camera angle. It is never "
        "evidence of a dimension — cite cad_get_build's measurements for that.",
        {"build_id": _ID,
         "presets": {
             "type": "array",
             "maxItems": len(cad_store.RENDER_PRESETS),
             "items": {"type": "string", "enum": list(cad_store.RENDER_PRESETS)},
             "description": "Only report on these presets. Omit for all of them.",
         }},
        ["build_id"], read_only=True,
    ),

    # -- HE-8. Repair without spending the project's history -----------------
    #
    # These four exist because of one arithmetic fact: a revision's `seq` only ever
    # goes up, so every wrong guess made against the real history burned a number
    # whether or not it produced a part. An experiment absorbs the guesses and hands
    # back at most one revision, at the end, only if something worked.
    _tool(
        "cad_open_experiment",
        "Branch off a revision into a disposable experiment, so a repair attempt can "
        "fail without costing the project a permanent revision. Use this rather than "
        "cad_propose_revision whenever you are fixing a build whose measurements came "
        "back wrong. The experiment starts as a copy of that revision's geometry and "
        "parameters, and carries a frozen copy of what the part is measured against — "
        "you cannot change that copy, which is the point of it. Opening one twice on "
        "the same revision hands back the experiment already running.",
        {"project_id": _ID,
         "base_revision_id": dict(_ID, description=(
             "The revision being repaired. Its geometry is copied into the "
             "experiment; the revision itself is never modified.")),
         "reason": {"type": "string", "maxLength": 500,
                    "description": "Which measurement missed, in one line."}},
        ["project_id", "base_revision_id"], read_only=False,
    ),
    _tool(
        "cad_experiment_build",
        "One repair attempt inside an experiment: write the corrected geometry into "
        "its working copy and build that. Nothing here becomes a revision — that only "
        "happens if you promote it. Omit `document` to rebuild the working copy with "
        "different parameters. Attempts are counted and capped, so read the "
        "measurements from cad_get_build before spending another one.",
        {"experiment_id": _ID, "document": _DOCUMENT, "params": _PARAMS,
         "formats": _FORMATS,
         "reason": {"type": "string", "maxLength": 500,
                    "description": "What this attempt changed, in one line."}},
        ["experiment_id"], read_only=False,
    ),
    _tool(
        "cad_promote_experiment",
        "Turn one succeeded experiment build into a real revision and close the "
        "experiment; the other attempts are discarded. Refused when that build's "
        "conformance came back failed — an attempt that missed its own measurements "
        "does not become history. The revision this creates is still a proposal: a "
        "person accepts it in CAD Studio, not you.",
        {"experiment_id": _ID,
         "build_id": dict(_ID, description="The experiment build worth keeping.")},
        ["experiment_id", "build_id"], read_only=False,
    ),
    _tool(
        "cad_abandon_experiment",
        "Give up on an experiment. Its builds and their files are removed; the record "
        "that this was tried and did not work stays. Call it rather than leaving an "
        "experiment open — an open one is the only experiment allowed on that "
        "revision.",
        {"experiment_id": _ID,
         "reason": {"type": "string", "maxLength": 500,
                    "description": "Why it was given up on."}},
        ["experiment_id"], read_only=False,
    ),
]

TOOL_NAMES: tuple[str, ...] = tuple(t["name"] for t in CAD_TOOLS)
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    t["name"] for t in CAD_TOOLS if t["read_only"])


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------

def _strictify(schema: dict) -> dict:
    """The same schema under OpenAI's strict function-calling rules.

    Strict mode wants ``additionalProperties: false`` and *every* declared
    property listed in ``required``; optionality is expressed by allowing null
    instead of by omission. So this widens each optional property's type to
    include ``"null"`` and then requires the lot. The meaning is unchanged — a
    model that would have omitted the key sends null — but a non-strict schema
    handed to a strict endpoint is rejected outright, which would take the whole
    CAD surface offline for that provider.

    ``additionalProperties: {...}`` on a free-form map (``params``) is not
    expressible under strict mode, so such a property is dropped from the strict
    variant rather than silently mis-declared. The dispatcher validates params
    itself either way.
    """
    out = copy.deepcopy(schema)
    props: dict = out.get("properties") or {}
    required = set(out.get("required") or [])

    keep: dict = {}
    for name, prop in props.items():
        if isinstance(prop.get("additionalProperties"), dict):
            continue  # free-form map — see the docstring
        p = dict(prop)
        if name not in required and "type" in p:
            t = p["type"]
            types = list(t) if isinstance(t, list) else [t]
            if "null" not in types:
                types.append("null")
            p["type"] = types
        if p.get("type") == "object" or "object" in (
                p["type"] if isinstance(p.get("type"), list) else []):
            p.setdefault("additionalProperties", False)
        keep[name] = p

    out["properties"] = keep
    out["required"] = list(keep)
    out["additionalProperties"] = False
    return out


def openai_tools(*, strict: bool = True) -> list[dict]:
    """OpenAI-shaped function tools — Kimi, and any OpenAI-compatible upstream.

    ``strict`` is on by default because a strict schema is what stops a model from
    inventing an argument; the caller can turn it off for an upstream that rejects
    the ``strict`` key rather than ignoring it.
    """
    out = []
    for t in CAD_TOOLS:
        fn: dict[str, Any] = {
            "name": t["name"],
            "description": t["description"],
            "parameters": _strictify(t["schema"]) if strict else copy.deepcopy(t["schema"]),
        }
        if strict:
            fn["strict"] = True
        out.append({"type": "function", "function": fn})
    return out


def anthropic_tools() -> list[dict]:
    """Anthropic-shaped tools — ``input_schema`` rather than ``parameters``.

    Not strictified: Anthropic has no strict flag, and widening every optional
    argument to accept null would make the schema *less* clear to the model for no
    enforcement in return.
    """
    return [
        {"name": t["name"], "description": t["description"],
         "input_schema": copy.deepcopy(t["schema"])}
        for t in CAD_TOOLS
    ]


def mcp_tools() -> list[dict]:
    """MCP ``tools/list`` entries — Claude Code and Kimi Code sidecars."""
    return [
        {"name": t["name"], "description": t["description"],
         "inputSchema": copy.deepcopy(t["schema"])}
        for t in CAD_TOOLS
    ]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _ok(payload: dict) -> tuple[dict, bool]:
    return (payload, True)


def _fail(code: str, message: str, **extra) -> tuple[dict, bool]:
    return ({"error_code": code, "message": message, **extra}, False)


def _from_http(exc: HTTPException) -> tuple[dict, bool]:
    """Reuse the routes' validators rather than writing a second set.

    ``_clean_params`` / ``_clean_source`` raise ``HTTPException`` because they were
    written for the HTTP lane; a tool call is not an HTTP request, so the structured
    body is unwrapped back into this module's ``(payload, ok)`` shape. One validator,
    two callers — which is the point, because two validators would eventually
    disagree about what a legal document is.
    """
    d = exc.detail
    if isinstance(d, dict):
        return ({"error_code": d.get("error_code") or "invalid_request",
                 "message": d.get("message") or "the request was rejected",
                 **{k: v for k, v in d.items()
                    if k not in ("error_code", "message")}}, False)
    return _fail("invalid_request", str(d))


def _params_map(args: dict) -> dict:
    """The wire's ``[{name, value}]`` list as the map the store and engine speak.

    A plain object is accepted too. Not because the schema offers it, but because a
    model that has seen a thousand ``{"width": 30}`` examples will occasionally send
    one anyway, and refusing a request whose meaning is unambiguous teaches nothing
    and costs a turn. ``_clean_params`` still decides what is legal.
    """
    raw = args.get("params")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail={
            "error_code": "invalid_params",
            "message": "params must be a list of {name, value} pairs"})
    out: dict = {}
    for item in raw:
        if not isinstance(item, dict) or "name" not in item:
            raise HTTPException(status_code=400, detail={
                "error_code": "invalid_params",
                "message": "each parameter needs a name and a value"})
        out[str(item.get("name"))] = item.get("value")
    return out


def _document(args: dict) -> dict | None:
    """The wire's JSON text as the dict ``_clean_source`` reads.

    An already-decoded object is accepted for the same reason a params map is: some
    providers hand back parsed JSON, and refusing an unambiguous request to make a
    point about encodings costs a turn and teaches nothing. The CadIR grammar check
    downstream is what actually decides whether the document is legal.
    """
    raw = args.get("document")
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail={
            "error_code": "invalid_document",
            "message": "document must be a CadIR document as JSON text"})
    if len(raw) > MAX_DOCUMENT_CHARS:
        raise HTTPException(status_code=400, detail={
            "error_code": "document_too_large",
            "message": f"the document exceeds {MAX_DOCUMENT_CHARS} characters"})
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        # The parser's own message names the offending position, which is the one
        # piece of information that lets a model fix its own JSON on the retry.
        raise HTTPException(status_code=400, detail={
            "error_code": "invalid_document",
            "message": f"the document is not valid JSON: {e}"}) from None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail={
            "error_code": "invalid_document",
            "message": "the document must be a JSON object"})
    return parsed


def _str(args: dict, key: str, limit: int = MAX_ID_CHARS) -> str:
    v = args.get(key)
    return str(v).strip()[:limit] if isinstance(v, (str, int)) else ""


class _Body:
    """The shape ``cad_router._clean_source`` / ``_spec`` read.

    They take the route's pydantic model; a tiny stand-in with the same attribute
    names lets the tool lane run the identical validation without a second copy of
    it, and without loosening the route models to accept a dict.
    """

    def __init__(self, recipe: str, document: dict | None, params: dict,
                 design_spec: dict, formats: list | None):
        self.recipe = recipe or fab_cad.DEFAULT_RECIPE
        self.document = document
        self.params = params
        self.design_spec = design_spec
        self.formats = formats


def _design_spec(ctx: CadToolContext, description: str) -> dict:
    """The answer key, extracted server-side from the user's words.

    When the context carries the user's own message that is what gets read, and the
    model's ``description`` argument is demoted to a label. Both cases record which
    happened, because "graded against what the user said" and "graded against what
    the model said the user said" are different claims and a reader deserves to
    know which one they are looking at.
    """
    source = "tool_argument"
    text = description
    if ctx.user_text and ctx.user_text.strip():
        text = ctx.user_text
        source = "user_message"
    spec = cad_designspec.extract(text)
    spec["source"] = source
    if source == "user_message" and description:
        spec["model_description"] = description[:500]
    return spec


def _authored(ctx: CadToolContext, spec: dict) -> dict:
    """Stamp the revision with which model actually authored it.

    ``cad_router._spec`` leaves these null because the HTTP routes are driven by a
    person. Here a model is driving, and the surface that resolved the lane is the
    only party that knows which provider really served the call — so it says so, and
    the model is never asked.
    """
    spec["model_provider"] = ctx.model_provider
    spec["model_name"] = ctx.model_name
    return spec


async def _precheck(document: dict | None, params: dict) -> tuple[dict, bool] | None:
    """Refuse a document the engine would refuse, before a revision exists for it.

    ``cad_router._clean_source`` already runs :mod:`cad_ir`'s coarse fence, which
    catches an unknown operation *name*. Everything else about the grammar — a
    required field missing, a field that does not exist on that operation, a profile
    with no ``kind`` — was only ever checked when geometry started, which meant each
    wrong guess cost a revision row, a build row, a seq number and a full round trip.
    Measured on the MCP lane: one plate burned eight revisions and seven builds
    without producing a part.

    ``/cad/validate`` is the same static check ``/cad/v2/build`` runs before it takes
    a concurrency slot, so nothing is being decided twice or decided differently — it
    is the identical verdict, taken several minutes and seven builds earlier.

    An unreachable engine is deliberately *not* a refusal. Authoring a revision while
    the sidecar is down is legitimate and the HTTP lane allows it; turning a transport
    failure into "your document is wrong" would be the dishonest reading.
    """
    if document is None:
        return None
    try:
        await fab_cad.validate_document(document, params)
    except fab_cad.CadError as e:
        if e.code in ("engine_unreachable", "engine_timeout"):
            logger.info("cad propose-time validation skipped: %s", e.code)
            return None
        return _fail(e.code, e.message,
                     hint="Call cad_get_schema for the CadIR grammar.")
    return None


async def _project_of_revision(ctx: CadToolContext, revision_id: str):
    try:
        rev = await cad_store.get_revision(ctx.pool, revision_id, ctx.user_id)
    except ValueError:
        rev = None
    return rev


def _launch(ctx: CadToolContext, build_id: str, project_id: str, recipe: str,
            params: dict, formats: list[str], document: dict | None,
            design_spec: dict | None, revision_id: str | None = None) -> None:
    """Start the background build the HTTP lane starts.

    ``cad_router._run_build`` is reused rather than reimplemented because it is
    where the conformance grade gets recorded against the build row. A second
    runner here would be a second place for that verdict to go missing, and a
    missing verdict reads as "not graded" — which is exactly the state Gate 7C
    removed.
    """
    task = asyncio.create_task(
        cad_router._run_build(ctx.pool, build_id, ctx.user_id, project_id,
                              recipe, params, formats, document, design_spec,
                              revision_id=revision_id))
    cad_router._running.add(task)
    task.add_done_callback(cad_router._running.discard)


# -- individual tools -------------------------------------------------------

async def _t_capabilities(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    out = {
        "enabled": True,
        "engine_reachable": False,
        "recipes": list(fab_cad.KNOWN_RECIPES),
        "formats": list(fab_cad.KNOWN_FORMATS),
        "units": "mm",
        "quota": {
            "user_limit_bytes": cad_store.user_quota_bytes(),
            "project_limit_bytes": cad_store.project_quota_bytes(),
            "user_used_bytes": 0,
        },
    }
    # Probed, not assumed. A lane that reports ready and then fails on the first
    # build is the dishonesty this call is meant to prevent.
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{fab_cad._cad_url()}/health")
            out["engine_reachable"] = r.status_code == 200
    except Exception:
        logger.info("cad tool capability probe failed", exc_info=True)
    try:
        out["quota"]["user_used_bytes"] = await cad_store.usage_bytes(
            ctx.pool, ctx.user_id)
    except Exception:
        logger.warning("cad tool usage read failed", exc_info=True)
    # Said here as well as in the schema of `document`, because this is the call a
    # model makes first and the point at which it decides between a recipe and a
    # document. Learning about the grammar tool only after authoring one is learning
    # about it too late.
    out["authoring"] = (
        "A part that is not one of `recipes` is written as a CadIR document. Call "
        "cad_get_schema for the grammar before writing one."
    )
    return _ok(out)


async def _t_schema(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    """The grammar, from the engine that parses it.

    Not assembled here. The description a model authors against and the parser that
    judges the result have to be the same artifact or the reference becomes a source
    of confident, well-formed, rejected documents.
    """
    try:
        return _ok(await fab_cad.schema())
    except fab_cad.CadError as e:
        return _fail(e.code, e.message)


async def _t_lookup_pattern(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    """Shop practice for this kind of part. No network, no secrets."""
    description = _str(args, "description", MAX_DESCRIPTION_CHARS) or (
        (ctx.user_text or "").strip()[:MAX_DESCRIPTION_CHARS]
    )
    pattern_id = _str(args, "pattern_id", 64) or None
    payload = cad_patterns.tool_payload(description, pattern_id)
    if pattern_id and not payload.get("matched") and pattern_id not in {
        p["id"] for p in payload.get("catalog") or []
    }:
        # Unknown id still returns the catalog so the model can recover.
        payload["note"] = (
            f"no pattern named {pattern_id!r}; pick an id from catalog or omit "
            "pattern_id to match the description"
        )
    return _ok(payload)


async def _t_dry_compile(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    """The propose-time check `_precheck` runs, made callable on its own (HE-6).

    Same engine call, same verdict — the difference is who asks and when. `_precheck`
    fires on the way into `cad_create_project` and `cad_propose_revision`, where its
    only job is to refuse; here a model can ask the question first and read the
    answer, which is the part that makes a wrong document cheap to fix rather than
    merely cheap to reject.

    An unreachable engine IS an error here, unlike in `_precheck`. There, skipping a
    transport failure is the honest reading: authoring a revision while the sidecar is
    down is legitimate, and calling the document wrong would be a lie about the
    document. Here the check is the entire point of the call, so answering `ok` when
    nothing was checked would be a lie about the check.
    """
    try:
        document = _document(args)
        params = cad_router._clean_params(_params_map(args))
    except HTTPException as e:
        return _from_http(e)
    if document is None:
        return _fail("invalid_document",
                     "a CadIR document is required — this tool checks documents, "
                     "not recipes, whose parameters the engine validates on build")
    try:
        return _ok(await fab_cad.validate_document(document, params))
    except fab_cad.CadError as e:
        return _fail(e.code, e.message,
                     hint="Call cad_get_schema for the CadIR grammar.")


async def _t_create_project(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    title = _str(args, "title", MAX_TITLE_CHARS) or "Untitled part"
    description = _str(args, "description", MAX_DESCRIPTION_CHARS)
    try:
        body = _Body(_str(args, "recipe"), _document(args),
                     _params_map(args), {}, None)
        recipe, document = cad_router._clean_source(body)
        params = cad_router._clean_params(body.params)
    except HTTPException as e:
        return _from_http(e)

    if (refused := await _precheck(document, params)) is not None:
        return refused

    body.design_spec = _design_spec(ctx, description)
    project = await cad_store.create_project(
        ctx.pool, ctx.user_id, title, ctx.conversation_id,
        # `created_by: "ai"` is what makes this a proposal. It is set here, from the
        # fact that a model is calling, and is not an argument — a client that could
        # declare its own authorship could declare its work to be the user's.
        revision=_authored(ctx, cad_router._spec(body, recipe, params, "ai", document)),
    )
    rev = project.get("revision") or {}
    return _ok({
        "project_id": project["id"],
        "title": project["title"],
        "head_revision": project["head_revision"],
        "revision": _revision_summary(rev),
        "design_spec": body.design_spec,
        "note": ("Nothing is built yet — call cad_start_build with this "
                 "revision_id. The revision is a proposal until the user accepts "
                 "it in CAD Studio."),
    })


async def _t_propose_revision(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    project_id = _str(args, "project_id")
    project = None
    try:
        project = await cad_store.get_project(ctx.pool, project_id, ctx.user_id)
    except ValueError:
        project = None
    if not project:
        return _fail("not_found", "no such project")

    base = _str(args, "base_revision_id") or None
    description = _str(args, "description", MAX_DESCRIPTION_CHARS)
    try:
        body = _Body(_str(args, "recipe"), _document(args),
                     _params_map(args), {}, None)
        recipe, document = cad_router._clean_source(body)
        params = cad_router._clean_params(body.params)
    except HTTPException as e:
        return _from_http(e)

    if (refused := await _precheck(document, params)) is not None:
        return refused

    body.design_spec = _design_spec(ctx, description)
    try:
        rev = await cad_store.create_revision(
            ctx.pool, project_id, ctx.user_id,
            _authored(ctx, cad_router._spec(body, recipe, params, "ai", document)),
            base_revision_id=base,
        )
    except cad_store.StaleRevision as e:
        return _fail(e.code, e.message, **e.extra)
    if not rev:
        return _fail("not_found", "no such project")
    return _ok({
        "project_id": project_id,
        "revision": _revision_summary(rev),
        "design_spec": body.design_spec,
        "note": "Call cad_start_build to build it.",
    })


async def _t_start_build(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    revision_id = _str(args, "revision_id")
    rev = await _project_of_revision(ctx, revision_id)
    if not rev:
        return _fail("not_found", "no such revision")

    # What gets built is read back off the stored revision, never taken from this
    # call. A build whose geometry came from the arguments would be building
    # something the revision does not record, and the revision is what a person
    # later accepts.
    source_kind = rev.get("source_kind") or "recipe"
    document = rev.get("cadir") if source_kind == "cadir" else None
    recipe = rev.get("recipe_name") or fab_cad.DEFAULT_RECIPE
    if source_kind == "cadir":
        if not isinstance(document, dict):
            return _fail("invalid_document", "that revision has no document to build")
        try:
            cad_ir.check_document(document)
        except cad_ir.CadIRError as e:
            return _fail(e.code, e.message)
    elif recipe not in fab_cad.KNOWN_RECIPES:
        return _fail("unknown_recipe",
                     "that revision names a recipe this engine no longer has")

    try:
        params = cad_router._clean_params(rev.get("parameters") or {})
        formats = cad_router._clean_formats(args.get("formats"))
    except HTTPException as e:
        return _from_http(e)

    try:
        await cad_store.check_quota(ctx.pool, ctx.user_id, rev["project_id"], 1)
    except cad_store.QuotaExceeded as e:
        return _fail(e.code, e.message, **e.extra)

    build, created = await cad_store.create_build(
        ctx.pool, revision_id, ctx.user_id, _str(args, "idempotency_key", 128) or None)
    if not build:
        return _fail("not_found", "no such revision")
    if created:
        _launch(ctx, build["id"], rev["project_id"], recipe, params, formats,
                document, rev.get("design_spec"), revision_id=revision_id)
    return _ok({
        "build_id": build["id"],
        "revision_id": revision_id,
        "status": build["status"],
        "created": created,
        "note": "Poll cad_get_build until status is succeeded, failed or cancelled.",
    })


async def _t_get_build(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    try:
        build = await cad_store.get_build(ctx.pool, _str(args, "build_id"), ctx.user_id)
    except ValueError:
        build = None
    if not build:
        return _fail("not_found", "no such build")
    return _ok(_build_summary(build))


async def _t_cancel_build(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    build_id = _str(args, "build_id")
    try:
        build = await cad_store.get_build(ctx.pool, build_id, ctx.user_id)
    except ValueError:
        build = None
    if not build:
        return _fail("not_found", "no such build")
    if build["status"] not in ("queued", "running"):
        return _ok({"build_id": build_id, "status": build["status"],
                    "cancelled": False,
                    "note": "That build had already finished."})
    await cad_store.request_cancel(ctx.pool, build_id)
    reached = await fab_cad.cancel(build_id)
    return _ok({"build_id": build_id, "status": "cancelling",
                "engine_acknowledged": reached})


async def _t_inspect_revision(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    revision_id = _str(args, "revision_id")
    rev = await _project_of_revision(ctx, revision_id)
    if not rev:
        return _fail("not_found", "no such revision")
    latest = await cad_store.latest_builds_by_revision(
        ctx.pool, rev["project_id"], ctx.user_id)
    build = latest.get(rev["id"])
    return _ok({
        "revision": _revision_summary(rev, full=True),
        "design_spec": rev.get("design_spec") or {},
        "latest_build": _build_summary(build) if build else None,
        "measurements": await cad_store.latest_measurements(ctx.pool, revision_id),
    })


async def _t_compare_revisions(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    project_id = _str(args, "project_id")
    out: dict[str, Any] = {"project_id": project_id}
    revs = []
    for key in ("revision_a", "revision_b"):
        rid = _str(args, key)
        try:
            rev = await cad_store.get_revision(ctx.pool, rid, ctx.user_id)
        except ValueError:
            rev = None
        if not rev or rev["project_id"] != project_id:
            return _fail("not_found", "no such revision in that project")
        rev["measurements"] = await cad_store.latest_measurements(ctx.pool, rid)
        revs.append(rev)

    ra, rb = revs
    pa, pb = ra["parameters"] or {}, rb["parameters"] or {}
    out["parameters"] = {
        k: {"a": pa.get(k), "b": pb.get(k)}
        for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)
    }
    ma, mb = ra["measurements"], rb["measurements"]
    # null, not {} — "neither has built successfully" and "nothing changed" are
    # different answers and a model reading {} would report the second.
    out["measurements"] = None
    if ma is not None and mb is not None:
        out["measurements"] = {
            k: {"a": ma.get(k), "b": mb.get(k)}
            for k in sorted(set(ma) | set(mb)) if ma.get(k) != mb.get(k)
        }
    out["a"] = _revision_summary(ra)
    out["b"] = _revision_summary(rb)
    return _ok(out)


async def _t_list_artifacts(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    build_id = _str(args, "build_id")
    try:
        build = await cad_store.get_build(ctx.pool, build_id, ctx.user_id)
    except ValueError:
        build = None
    if not build:
        return _fail("not_found", "no such build")
    return _ok({
        "build_id": build_id,
        "status": build["status"],
        "artifacts": [
            {
                "artifact_id": a["id"],
                "format": a["format"],
                "media_type": a["media_type"],
                "size_bytes": a["size_bytes"],
                "sha256": a["sha256"],
                # An authenticated route, not a location on disk. It only resolves
                # inside the user's own session, which is why it is safe to name
                # and useless to anyone else.
                "url": f"/api/cad/builds/{build_id}/artifacts/{a['id']}",
            }
            for a in build.get("artifacts") or []
        ],
    })


async def _t_render_views(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    """What views exist, and — just as usefully — which do not.

    There is no queue behind this. Renders come from the user's viewport, so a
    request the model makes here would sit unserviced whenever the workspace is
    closed, which is most of the time. Reporting the real state is the honest
    version of the same tool.
    """
    build_id = _str(args, "build_id")
    try:
        rows = await cad_store.list_renders(ctx.pool, build_id, ctx.user_id)
    except ValueError:
        rows = []
    if not rows:
        # `list_renders` checks ownership in its join, so rows at all means the build
        # is the caller's. Empty is ambiguous — no renders, or no build — and those
        # are different answers to give a user.
        try:
            build = await cad_store.get_build(ctx.pool, build_id, ctx.user_id)
        except ValueError:
            build = None
        if not build:
            return _fail("not_found", "no such build")

    wanted = args.get("presets") or list(cad_store.RENDER_PRESETS)
    wanted = [p for p in wanted if p in cad_store.RENDER_PRESETS]
    have = {(r.get("variant") or ""): r for r in rows}
    return _ok({
        "build_id": build_id,
        "views": [
            {
                "preset": p,
                "artifact_id": have[p]["id"],
                "url": f"/api/cad/builds/{build_id}/artifacts/{have[p]['id']}",
                "captured_from_revision": (have[p].get("meta") or {}).get("revision_id"),
            }
            for p in wanted if p in have
        ],
        "missing": [p for p in wanted if p not in have],
        "how_renders_are_made": (
            "captured by the user's 3D viewport when the CAD workspace is open; "
            "there is no server-side renderer"),
        "disclaimer": "a rendered inspection view, not dimensional proof",
    })


# -- HE-8: experiments ------------------------------------------------------

def _experiment_summary(exp: dict) -> dict:
    """What a repair loop needs to decide its next move.

    The working CadIR is deliberately absent: it is whatever the model just sent,
    it is large, and echoing it back would push the measurements that matter out of
    the context window. The frozen ``design_spec`` is present for the opposite
    reason — it is the thing the attempt is graded against, and quoting it is how a
    repair prompt stays anchored to the user's numbers.
    """
    return {
        "experiment_id": exp.get("id"),
        "project_id": exp.get("project_id"),
        "base_revision_id": exp.get("base_revision_id"),
        "status": exp.get("status"),
        "attempts": exp.get("attempts"),
        "max_attempts": exp.get("max_attempts"),
        "reason": exp.get("reason"),
        "design_spec": exp.get("design_spec") or {},
        "promoted_revision_id": exp.get("promoted_revision_id"),
        "closed_reason": exp.get("closed_reason"),
    }


async def _t_open_experiment(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    try:
        exp = await cad_experiments.open_experiment(
            ctx.pool, _str(args, "project_id"), ctx.user_id,
            _str(args, "base_revision_id"),
            reason=_str(args, "reason", 500), created_by="ai")
    except ValueError:
        exp = {}
    if not exp:
        return _fail("not_found", "no such revision in that project")
    return _ok({
        "experiment": _experiment_summary(exp),
        "note": ("Call cad_experiment_build with the corrected document. Nothing "
                 "here is a revision until you promote it."),
    })


async def _t_experiment_build(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    experiment_id = _str(args, "experiment_id")
    try:
        exp = await cad_experiments.get_experiment(
            ctx.pool, experiment_id, ctx.user_id)
    except ValueError:
        exp = None
    if not exp:
        return _fail("not_found", "no such experiment")
    if exp["status"] != cad_experiments.OPEN:
        return _fail("experiment_closed",
                     f"that experiment is {exp['status']}",
                     experiment_id=experiment_id, status=exp["status"])

    base = await _project_of_revision(ctx, exp["base_revision_id"])
    if not base:
        return _fail("not_found", "the revision this experiment branched from is gone")

    # What actually gets built is the working copy with this call's edits merged in,
    # so a caller who only wants to move a parameter does not have to resend the whole
    # document — and so the thing validated below is the thing the engine will see.
    try:
        sent_doc = _document(args)
        sent_params = _params_map(args)
        formats = cad_router._clean_formats(args.get("formats"))
        merged_doc = sent_doc if sent_doc is not None else exp.get("cadir")
        merged_params = sent_params or exp.get("parameters") or {}
        if (base.get("source_kind") or "recipe") != "cadir":
            merged_doc = None
        body = _Body(base.get("recipe_name") or fab_cad.DEFAULT_RECIPE,
                     merged_doc, merged_params, {}, None)
        recipe, document = cad_router._clean_source(body)
        params = cad_router._clean_params(body.params)
    except HTTPException as e:
        return _from_http(e)

    if (refused := await _precheck(document, params)) is not None:
        return refused

    try:
        await cad_store.check_quota(ctx.pool, ctx.user_id, exp["project_id"], 1)
    except cad_store.QuotaExceeded as e:
        return _fail(e.code, e.message, **e.extra)

    # The attempt is counted first. A build that started and a counter that did not
    # move is how a capped loop becomes an uncapped one.
    exp = await cad_experiments.record_attempt(
        ctx.pool, experiment_id, ctx.user_id,
        cadir=document, parameters=params or None, note=_str(args, "reason", 500))
    if not exp:
        return _fail("not_found", "no such experiment")

    build = await cad_experiments.create_experiment_build(
        ctx.pool, experiment_id, ctx.user_id)
    if not build:
        return _fail("not_found", "no such experiment")
    # The frozen spec, never the base revision's current one. That is what makes the
    # grade on this attempt a grade against the target the experiment opened on.
    _launch(ctx, build["id"], exp["project_id"], recipe, params, formats,
            document, exp.get("design_spec"),
            revision_id=exp["base_revision_id"])
    return _ok({
        "build_id": build["id"],
        "experiment": _experiment_summary(exp),
        "note": ("Poll cad_get_build. If it succeeds and conforms, call "
                 "cad_promote_experiment with this build_id; if it does not, read the "
                 "measurements and spend another attempt."),
    })


async def _t_promote_experiment(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    experiment_id = _str(args, "experiment_id")
    try:
        rev = await cad_experiments.promote(
            ctx.pool, experiment_id, ctx.user_id, _str(args, "build_id"))
    except ValueError:
        rev = {}
    if not rev:
        return _fail("not_found", "no such experiment")
    return _ok({
        "experiment_id": experiment_id,
        "revision": _revision_summary(rev),
        "note": ("The experiment is closed and its other attempts are gone. This "
                 "revision is a proposal until the user accepts it in CAD Studio."),
    })


async def _t_abandon_experiment(args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    experiment_id = _str(args, "experiment_id")
    try:
        exp = await cad_experiments.abandon(
            ctx.pool, experiment_id, ctx.user_id, _str(args, "reason", 500))
    except ValueError:
        exp = {}
    if not exp:
        return _fail("not_found", "no such experiment")
    return _ok({
        "experiment": _experiment_summary(exp),
        "note": ("Nothing was added to the project. Say plainly that the repair did "
                 "not work rather than proposing the failed geometry as a revision."),
    })


_HANDLERS: dict[str, Callable] = {
    "cad_get_capabilities": _t_capabilities,
    "cad_get_schema": _t_schema,
    "cad_lookup_pattern": _t_lookup_pattern,
    "cad_dry_compile": _t_dry_compile,
    "cad_create_project": _t_create_project,
    "cad_propose_revision": _t_propose_revision,
    "cad_start_build": _t_start_build,
    "cad_get_build": _t_get_build,
    "cad_cancel_build": _t_cancel_build,
    "cad_inspect_revision": _t_inspect_revision,
    "cad_compare_revisions": _t_compare_revisions,
    "cad_list_artifacts": _t_list_artifacts,
    "cad_render_views": _t_render_views,
    "cad_open_experiment": _t_open_experiment,
    "cad_experiment_build": _t_experiment_build,
    "cad_promote_experiment": _t_promote_experiment,
    "cad_abandon_experiment": _t_abandon_experiment,
}


def _revision_summary(rev: dict, full: bool = False) -> dict:
    if not rev:
        return {}
    out = {
        "revision_id": rev.get("id"),
        "seq": rev.get("seq"),
        "state": rev.get("state"),
        "created_by": rev.get("created_by"),
        "source_kind": rev.get("source_kind"),
        "recipe_name": rev.get("recipe_name"),
        "parameters": rev.get("parameters") or {},
        "accepted_at": rev.get("accepted_at"),
    }
    if full:
        out["document"] = rev.get("cadir")
        out["parent_id"] = rev.get("parent_id")
    return out


def _build_summary(build: dict) -> dict:
    """What a model needs to decide what to do next, and nothing else.

    Both verdicts are present and neither is folded into the other: ``status`` is
    about the solid, ``conformance`` is about the request. The Gate 7B failure was
    a build that reported one of these and was asked to stand for both.
    """
    conf = build.get("conformance") or None
    return {
        "build_id": build.get("id"),
        "revision_id": build.get("revision_id"),
        "status": build.get("status"),
        "duration_ms": build.get("duration_ms"),
        "validation": build.get("validation") or {},
        "conformance_status": build.get("conformance_status"),
        "conformance": conf,
        "error_code": build.get("error_code"),
        "error_detail": build.get("error_detail"),
        "artifact_count": len(build.get("artifacts") or []),
    }


async def dispatch(name: str, args: dict, ctx: CadToolContext) -> tuple[dict, bool]:
    """Run one CAD tool. Returns ``(payload, ok)`` and never raises.

    Every surface — Claude's native tools, Kimi's function tools, the MCP adapter —
    comes through here, so there is exactly one place where the lane gate, the
    ownership rules and the argument fence are applied. A provider adapter that did
    its own dispatch would be a second place for those to be forgotten.
    """
    if not fab_cad.cad_enabled():
        # The same answer the routes give: a disabled lane is indistinguishable
        # from a backend that never had one.
        return _fail("cad_unavailable",
                     "the local CAD lane is not enabled on this deployment")
    handler = _HANDLERS.get(name)
    if handler is None:
        return _fail("unknown_tool", f"no such CAD tool: {name}")
    if not isinstance(args, dict):
        return _fail("invalid_arguments", "arguments must be an object")
    if ctx.pool is None:
        return _fail("no_database", "the CAD store is unavailable")

    # Nothing a model sends may name a user, a storage key or a path. These keys
    # have no legitimate reason to appear and their presence means the call was
    # built from something other than the published schema.
    for banned in ("user_id", "storage_key", "path", "file_path", "storage_path"):
        if banned in args:
            return _fail("forbidden_argument",
                         f"{banned} is not an argument of any CAD tool")
    try:
        return await handler(args, ctx)
    except HTTPException as e:
        return _from_http(e)
    except cad_store.CadStoreError as e:
        return _fail(e.code, e.message, **getattr(e, "extra", {}))
    except Exception:
        logger.exception("cad tool %s failed unexpectedly", name)
        return _fail("internal_error", "the CAD tool failed unexpectedly")


def as_text(payload: dict, ok: bool) -> str:
    """The tool result as the plain text a chat tool loop consumes."""
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)
