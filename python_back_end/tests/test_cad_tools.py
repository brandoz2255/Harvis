"""Gate 7C-3: the provider-neutral CAD tool registry.

Two halves, and they fail for different reasons.

The **shape** half needs no database. It asserts that one declaration really does
produce three wire formats that agree with each other, and that the strict variant
is legal where strict mode is enforced — because a schema an upstream rejects takes
the whole CAD surface offline for that provider, silently, at request time.

The **dispatch** half needs the real database, because everything worth asserting
here is about ownership: that user B asking for user A's build gets ``not_found``
and not a 403, that a model-authored project has no head, and that nothing on the
way out carries a storage key or a path. A mocked pool would agree with whatever
the test said and prove none of it.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_cad_tools.py -q
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import asyncpg
import pytest

from owui_compat import cad_store, cad_tools

DATABASE_URL = os.getenv("DATABASE_URL")


# ---------------------------------------------------------------------------
# Shape — no database needed
# ---------------------------------------------------------------------------

def _walk_objects(schema: dict):
    """Every object-typed subschema, including the ones inside array items."""
    t = schema.get("type")
    types = t if isinstance(t, list) else [t]
    if "object" in types:
        yield schema
    for sub in (schema.get("properties") or {}).values():
        yield from _walk_objects(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from _walk_objects(items)


def test_the_three_wire_formats_describe_the_same_tools():
    """One declaration, three encodings. A tool that exists for Claude and not for
    Kimi is the drift this module was written to prevent, and it would show up as a
    model insisting a capability does not exist rather than as an error.

    Counted against each other, never against a literal: a hardcoded total fails on
    the day a tool is added, which is the one day the drift check should still pass.
    """
    names = set(cad_tools.TOOL_NAMES)
    assert names
    assert {t["function"]["name"] for t in cad_tools.openai_tools()} == names
    assert {t["name"] for t in cad_tools.anthropic_tools()} == names
    assert {t["name"] for t in cad_tools.mcp_tools()} == names
    assert set(cad_tools._HANDLERS) == names


def test_every_strict_schema_is_legal_under_openai_strict_mode():
    """Strict mode requires ``additionalProperties: false`` and *every* property
    listed in ``required`` — on nested objects too. A schema that misses either is
    rejected outright, so this is the difference between the lane working on Kimi
    and the lane not existing there."""
    for entry in cad_tools.openai_tools(strict=True):
        fn = entry["function"]
        assert fn["strict"] is True, fn["name"]
        for obj in _walk_objects(fn["parameters"]):
            assert obj.get("additionalProperties") is False, fn["name"]
            assert set(obj.get("required") or []) == set(obj.get("properties") or {}), \
                fn["name"]


def test_an_optional_argument_stays_optional_by_allowing_null():
    """Strict mode has no way to say "may be omitted", so optional is spelled as
    nullable. The meaning has to survive that translation: a caller that would have
    left `recipe` out sends null, and both mean the default."""
    strict = [t for t in cad_tools.openai_tools(strict=True)
              if t["function"]["name"] == "cad_create_project"][0]
    props = strict["function"]["parameters"]["properties"]
    assert "null" in props["recipe"]["type"]
    # …and the required ones did not become nullable on the way through.
    assert props["title"]["type"] == "string"

    loose = [t for t in cad_tools.openai_tools(strict=False)
             if t["function"]["name"] == "cad_create_project"][0]
    assert loose["function"]["parameters"]["required"] == ["title", "description"]
    assert "strict" not in loose["function"]


def test_parameters_survive_strict_mode():
    """The regression this shape exists for: `params` was first written as a
    free-form map, which strict mode cannot express, so the strict variant dropped
    the property — leaving a model unable to set a single dimension while every
    other check still passed."""
    for name in ("cad_create_project", "cad_propose_revision"):
        fn = [t for t in cad_tools.openai_tools(strict=True)
              if t["function"]["name"] == name][0]["function"]
        params = fn["parameters"]["properties"]["params"]
        assert "array" in params["type"]
        assert set(params["items"]["properties"]) == {"name", "value"}


def test_the_cadir_document_crosses_the_wire_as_text():
    """Same failure mode as `params`, one level deeper. CadIR is recursive, so as a
    declared object it needs `additionalProperties: true` — which strict mode
    forbids outright. Sent as JSON text it survives on every provider, and the
    grammar check that actually matters still runs server-side."""
    for name in ("cad_create_project", "cad_propose_revision"):
        fn = [t for t in cad_tools.openai_tools(strict=True)
              if t["function"]["name"] == name][0]["function"]
        assert "string" in fn["parameters"]["properties"]["document"]["type"]


def test_no_tool_offers_an_argument_that_names_a_user_a_key_or_a_path():
    """The rule the whole module exists to enforce: the model never receives — or
    sends — filesystem paths, storage keys, or a user identity. Identity arrives in
    the context, which the model cannot write to."""
    banned = {"user_id", "user", "storage_key", "path", "file_path", "storage_path",
              "sql", "query", "conn", "pool"}
    for t in cad_tools.CAD_TOOLS:
        assert not (set(t["schema"]["properties"]) & banned), t["name"]


def test_accepting_a_revision_is_not_a_tool():
    """Gate 7C-2 says a model-authored revision stays a proposal until a person
    accepts it. A `cad_accept_revision` tool would hand that decision straight back
    to the model, so its absence is the feature."""
    assert not [n for n in cad_tools.TOOL_NAMES if "accept" in n]


def test_the_emitters_hand_out_copies():
    """A caller that mutates a returned schema — adding a provider-specific key,
    say — must not be editing the registry every other caller reads."""
    first = cad_tools.anthropic_tools()[0]
    first["input_schema"]["properties"]["injected"] = {"type": "string"}
    assert "injected" not in cad_tools.anthropic_tools()[0]["input_schema"]["properties"]
    assert "injected" not in cad_tools.CAD_TOOLS[0]["schema"].get("properties", {})


def test_read_only_tools_are_the_ones_that_write_nothing():
    assert cad_tools.READ_ONLY_TOOLS == {
        "cad_get_capabilities", "cad_get_schema", "cad_get_build",
        "cad_inspect_revision", "cad_compare_revisions", "cad_list_artifacts",
        # Asks the engine to plan a document and answers with the plan. Nothing is
        # parsed into a row, so a model may run it as often as it likes — which is
        # the whole point of having it (HE-6).
        "cad_dry_compile",
        # Local shop-practice catalog. Pure function, no I/O.
        "cad_lookup_pattern",
        # Reports which renders a build already has. It cannot capture one — the
        # user's own viewport does that — so asking writes nothing.
        "cad_render_views",
    }


def test_every_advertised_tool_can_actually_be_called():
    """A tool in the registry but not in the dispatch table is advertised in
    `tools/list`, chosen by the model, and then refused as `unknown_tool` — which
    reads to the model as its own mistake. The registry and the handler map are two
    lists that must agree, so the test is the thing that makes them agree."""
    assert set(cad_tools.TOOL_NAMES) == set(cad_tools._HANDLERS)


# ---------------------------------------------------------------------------
# Dispatch — against the real database
# ---------------------------------------------------------------------------

db = pytest.mark.skipif(
    not DATABASE_URL, reason="no DATABASE_URL — dispatch has nothing to talk to")


@pytest.fixture(scope="module")
def tmp_artifacts():
    with tempfile.TemporaryDirectory(prefix="cadtools-test-") as d:
        old = os.environ.get("ARTIFACT_STORAGE_DIR")
        os.environ["ARTIFACT_STORAGE_DIR"] = d
        try:
            yield d
        finally:
            if old is None:
                os.environ.pop("ARTIFACT_STORAGE_DIR", None)
            else:
                os.environ["ARTIFACT_STORAGE_DIR"] = old


@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.close()


@pytest.fixture(scope="module")
def env(loop, tmp_artifacts):
    if not DATABASE_URL:
        pytest.skip("no DATABASE_URL")

    async def setup():
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=6)
        async with pool.acquire() as conn:
            for stmt in cad_store.CAD_SCHEMA_SQL:
                await conn.execute(stmt)
            ids = []
            for tag in ("a", "b"):
                nonce = uuid.uuid4().hex[:12]
                ids.append(await conn.fetchval(
                    "INSERT INTO users (username, email, password) "
                    "VALUES ($1, $2, $3) RETURNING id",
                    f"cadtool-{tag}-{nonce}", f"cadtool-{tag}-{nonce}@invalid.test", "x",
                ))
        return pool, ids[0], ids[1]

    pool, ua, ub = loop.run_until_complete(setup())
    try:
        yield {"pool": pool, "user_a": ua, "user_b": ub, "loop": loop}
    finally:
        async def teardown():
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM users WHERE id = ANY($1::int[])", [ua, ub])
            await pool.close()
        loop.run_until_complete(teardown())


def run(env, coro):
    return env["loop"].run_until_complete(coro)


def ctx(env, user=None, **kw):
    return cad_tools.CadToolContext(
        pool=env["pool"], user_id=user if user is not None else env["user_a"], **kw)


def call(env, name, args, user=None, **kw):
    return run(env, cad_tools.dispatch(name, args, ctx(env, user, **kw)))


@db
def test_an_unknown_tool_is_an_answer_not_an_exception(env):
    payload, ok = call(env, "cad_delete_everything", {})
    assert ok is False and payload["error_code"] == "unknown_tool"


@db
def test_an_argument_that_names_a_user_or_a_path_is_refused(env):
    """These keys are in no published schema, so their presence means the call was
    built from something other than the contract. Refusing by name is cheap and it
    fails loudly rather than being quietly ignored."""
    for bad in ({"user_id": 1}, {"storage_key": "x"}, {"path": "/etc/passwd"}):
        payload, ok = call(env, "cad_get_capabilities", bad)
        assert ok is False and payload["error_code"] == "forbidden_argument"


@db
def test_a_disabled_lane_answers_the_same_way_a_missing_one_would(env, monkeypatch):
    monkeypatch.setattr(cad_tools.fab_cad, "cad_enabled", lambda: False)
    payload, ok = call(env, "cad_get_capabilities", {})
    assert ok is False and payload["error_code"] == "cad_unavailable"


@db
def test_a_model_authored_project_has_no_head(env):
    """The Gate 7C-2 rule reaching the tool surface. A model can create a project;
    what it cannot do is make its own work the thing the project *is*."""
    payload, ok = call(env, "cad_create_project", {
        "title": "Tool-made part",
        "description": "a 30 mm cube",
        "recipe": "helmet_hanger_v1",
    })
    assert ok, payload
    assert payload["head_revision"] is None
    assert payload["revision"]["state"] == "proposal"
    assert payload["revision"]["created_by"] == "ai"


@db
def test_the_design_spec_is_read_from_the_user_not_from_the_model(env):
    """The answer key comes from the person. When the context carries the user's own
    message, that is what gets extracted — a model that rounded 30 mm to 35 mm on
    its way into `description` would otherwise be writing the exam again."""
    payload, ok = call(
        env, "cad_create_project",
        {"title": "Cube", "description": "a 35 mm cube", "recipe": "helmet_hanger_v1"},
        user_text="a 30 mm cube",
    )
    assert ok, payload
    spec = payload["design_spec"]
    assert spec["source"] == "user_message"
    assert spec["model_description"] == "a 35 mm cube"
    # 30, from the user's sentence — not 35, from the model's.
    assert "30" in str(spec["stated"]) and "35" not in str(spec["stated"])


@db
def test_without_a_user_message_the_spec_says_where_it_came_from(env):
    """A caller that has no user text still gets a spec, and it is labelled — because
    "graded against what the user said" and "graded against what the model said the
    user said" are different claims and a reader is entitled to know which."""
    payload, ok = call(env, "cad_create_project", {
        "title": "Cube", "description": "a 30 mm cube", "recipe": "helmet_hanger_v1"})
    assert ok and payload["design_spec"]["source"] == "tool_argument"


@db
def test_parameters_arrive_as_pairs_and_land_as_a_map(env):
    payload, ok = call(env, "cad_create_project", {
        "title": "Hanger", "description": "a hanger",
        "recipe": "helmet_hanger_v1",
        "params": [{"name": "arm_len_mm", "value": 90}],
    })
    assert ok, payload
    assert payload["revision"]["parameters"] == {"arm_len_mm": 90.0}


@db
def test_a_stale_base_revision_is_a_conflict_not_a_silent_fork(env):
    made, ok = call(env, "cad_create_project", {
        "title": "P", "description": "a part", "recipe": "helmet_hanger_v1"})
    assert ok
    payload, ok = call(env, "cad_propose_revision", {
        "project_id": made["project_id"],
        "base_revision_id": str(uuid.uuid4()),
        "description": "a part",
        "recipe": "helmet_hanger_v1",
    })
    assert ok is False and payload["error_code"] == "stale_revision"
    assert "head_revision" in payload


@db
def test_another_users_project_does_not_exist(env):
    """404-equivalent, never a 403: telling user B that the id is real but not
    theirs confirms it belongs to someone."""
    made, _ = call(env, "cad_create_project", {
        "title": "Private", "description": "a part", "recipe": "helmet_hanger_v1"})
    payload, ok = call(env, "cad_propose_revision",
                       {"project_id": made["project_id"], "description": "x"},
                       user=env["user_b"])
    assert ok is False and payload["error_code"] == "not_found"

    payload, ok = call(env, "cad_inspect_revision",
                       {"revision_id": made["revision"]["revision_id"]},
                       user=env["user_b"])
    assert ok is False and payload["error_code"] == "not_found"


@db
def test_another_users_build_and_artifacts_do_not_exist(env):
    made, _ = call(env, "cad_create_project", {
        "title": "Private", "description": "a part", "recipe": "helmet_hanger_v1"})
    build, created = run(env, cad_store.create_build(
        env["pool"], made["revision"]["revision_id"], env["user_a"], None))
    assert created

    for tool in ("cad_get_build", "cad_list_artifacts"):
        payload, ok = call(env, tool, {"build_id": build["id"]}, user=env["user_b"])
        assert ok is False and payload["error_code"] == "not_found", tool

    # The owner still reads it. `create_build` inserts straight to 'running' with a
    # started_at — there is no queued state to observe.
    payload, ok = call(env, "cad_get_build", {"build_id": build["id"]})
    assert ok and payload["status"] == "running"


@db
def test_artifacts_never_carry_a_storage_key_or_a_path(env):
    """The bytes are reachable only through the user's own authenticated session.
    What comes back here is an opaque id, a size, a checksum, and the URL that
    session would use — no key, and nothing that resolves on a filesystem."""
    made, _ = call(env, "cad_create_project", {
        "title": "Art", "description": "a part", "recipe": "helmet_hanger_v1"})
    build, _ = run(env, cad_store.create_build(
        env["pool"], made["revision"]["revision_id"], env["user_a"], None))
    run(env, cad_store.finish_build(
        env["pool"], build["id"], env["user_a"], made["project_id"],
        artifacts={"stl": b"solid t\nendsolid t\n"},
        refs=[{"format": "stl", "media_type": "model/stl"}],
        validation={"brep_valid": True, "volume_mm3": 1.0},
        duration_ms=1, peak_rss_bytes=1,
    ))
    payload, ok = call(env, "cad_list_artifacts", {"build_id": build["id"]})
    assert ok, payload
    assert len(payload["artifacts"]) == 1
    art = payload["artifacts"][0]
    assert set(art) == {"artifact_id", "format", "media_type", "size_bytes",
                        "sha256", "url"}
    blob = cad_tools.as_text(payload, ok)
    assert "storage_key" not in blob and "/app" not in blob and "/data" not in blob


@db
def test_a_build_reports_both_verdicts_separately(env):
    """`status` is about the solid; `conformance` is about the request. Gate 7B was
    a build that reported one of these and was read as answering both."""
    made, _ = call(env, "cad_create_project", {
        "title": "V", "description": "a part", "recipe": "helmet_hanger_v1"})
    build, _ = run(env, cad_store.create_build(
        env["pool"], made["revision"]["revision_id"], env["user_a"], None))
    run(env, cad_store.finish_build(
        env["pool"], build["id"], env["user_a"], made["project_id"],
        artifacts={"stl": b"solid t\nendsolid t\n"},
        refs=[{"format": "stl", "media_type": "model/stl"}],
        validation={"brep_valid": True, "volume_mm3": 1.0},
        duration_ms=1, peak_rss_bytes=1,
        conformance={"schema_version": "0.1", "status": "failed",
                     "summary": "measured 35 mm, asked for 30 mm", "checks": []},
    ))
    payload, ok = call(env, "cad_get_build", {"build_id": build["id"]})
    assert ok
    assert payload["status"] == "succeeded"
    assert payload["conformance_status"] == "failed"
    assert payload["conformance"]["summary"].startswith("measured 35")


@db
def test_starting_a_build_on_someone_elses_revision_finds_nothing(env):
    made, _ = call(env, "cad_create_project", {
        "title": "S", "description": "a part", "recipe": "helmet_hanger_v1"})
    payload, ok = call(env, "cad_start_build",
                       {"revision_id": made["revision"]["revision_id"]},
                       user=env["user_b"])
    assert ok is False and payload["error_code"] == "not_found"


@db
def test_cancelling_a_finished_build_leaves_it_alone(env):
    made, _ = call(env, "cad_create_project", {
        "title": "C", "description": "a part", "recipe": "helmet_hanger_v1"})
    build, _ = run(env, cad_store.create_build(
        env["pool"], made["revision"]["revision_id"], env["user_a"], None))
    run(env, cad_store.fail_build(env["pool"], build["id"], "boom", "it broke"))
    payload, ok = call(env, "cad_cancel_build", {"build_id": build["id"]})
    assert ok and payload["cancelled"] is False and payload["status"] == "failed"


@db
def test_comparing_revisions_that_never_built_says_so(env):
    """null measurements, not an empty diff. "Neither has built" and "nothing
    changed" are different answers, and a model reading `{}` would report the
    second."""
    made, _ = call(env, "cad_create_project", {
        "title": "Cmp", "description": "a part", "recipe": "helmet_hanger_v1",
        "params": [{"name": "arm_len_mm", "value": 90}]})
    second, ok = call(env, "cad_propose_revision", {
        "project_id": made["project_id"], "description": "a part",
        "recipe": "helmet_hanger_v1",
        "params": [{"name": "arm_len_mm", "value": 120}]})
    assert ok, second
    payload, ok = call(env, "cad_compare_revisions", {
        "project_id": made["project_id"],
        "revision_a": made["revision"]["revision_id"],
        "revision_b": second["revision"]["revision_id"],
    })
    assert ok, payload
    assert payload["parameters"] == {"arm_len_mm": {"a": 90.0, "b": 120.0}}
    assert payload["measurements"] is None


@db
def test_an_unreadable_document_is_refused_before_a_revision_exists(env):
    """The routes' own validator, reused. A revision that can never build is history
    nobody can act on, so the refusal has to come before the insert."""
    payload, ok = call(env, "cad_create_project", {
        "title": "Bad", "description": "a part",
        "document": {"schema_version": "0.1", "operations": "not a list"},
    })
    assert ok is False and payload["error_code"] != "internal_error"


@db
def test_capabilities_answers_without_pretending_the_engine_is_up(env):
    payload, ok = call(env, "cad_get_capabilities", {})
    assert ok, payload
    assert payload["units"] == "mm"
    assert isinstance(payload["engine_reachable"], bool)
    assert payload["quota"]["user_used_bytes"] >= 0


# ── The sidecar door ────────────────────────────────────────────────────────
# A Claude Code sidecar reaches these tools only through `--mcp-config`. Until that
# argument existed the tools were unreachable from the Build and chat lanes while
# every unit test here passed, so these cover the argument itself.

def test_a_disabled_lane_registers_no_mcp_server(monkeypatch):
    """A registered server whose every call 404s is worse than no server: the model
    spends a round trip on it and reads the refusal as its own mistake."""
    from owui_compat import cad_mcp, fab_cad
    monkeypatch.setattr(fab_cad, "cad_enabled", lambda: False)
    assert cad_mcp.sidecar_mcp_config(2) is None


def test_an_anonymous_run_registers_no_mcp_server(monkeypatch):
    """No user, no token — CAD is owned per user, and a server that cannot name one
    would hand the sidecar a credential belonging to nobody."""
    from owui_compat import cad_mcp, fab_cad
    monkeypatch.setattr(fab_cad, "cad_enabled", lambda: True)
    assert cad_mcp.sidecar_mcp_config(None) is None
    assert cad_mcp.sidecar_mcp_config(0) is None


def test_read_only_runs_withhold_exactly_the_writing_tools():
    """An auto-escalated run is read-only, and the CAD tools are not exempt: creating
    a revision or taking a build slot lands in the user's project history whether or
    not they asked for the run. Derived from the registry, so a tool added later is
    withheld by default rather than quietly allowed."""
    from workspace.orchestration import engine_adapter as ea
    withheld = set(ea._cad_write_tool_names())
    assert withheld == {f"mcp__harvis-cad__{n}" for n in cad_tools.TOOL_NAMES
                        if n not in cad_tools.READ_ONLY_TOOLS}
    assert "mcp__harvis-cad__cad_start_build" in withheld
    assert "mcp__harvis-cad__cad_get_schema" not in withheld
