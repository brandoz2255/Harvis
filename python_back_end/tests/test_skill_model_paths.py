"""The model's side of the skills loop: it sees a catalog, it can propose a new skill or
an update to one that exists (never edit it), and it is told when a draft was skipped.

Everything that touches ``owui_skills`` runs on the real Postgres in a throwaway schema
(skipped when no database is reachable), so the SQL that gates which skills the model
may see is exercised, not imitated. No test here calls a model: ``learn._complete_json``
is replaced where a draft is written.
"""
import asyncio
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import skill_pending as sp  # noqa: E402
from owui_compat.skills import CREATE_OWUI_SKILLS_SQL  # noqa: E402
from plugins.hermes_ui import learn, skill_select  # noqa: E402
from workspace.orchestration import runner, tools as orch_tools  # noqa: E402

UID = 7
BODY = "# Compose debug\n\n1. Run docker compose logs.\n2. Check the ports.\n3. Restart the service.\n"
NEW_BODY = "# Compose debug\n\n1. Run docker compose logs.\n2. Check the ports and the volumes.\n3. Restart it.\n"


class OnePool:
    """A pool that hands out the one test connection."""

    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def with_db(scenario):
    """Run ``scenario(pool, conn)`` against a throwaway schema on the real database."""
    async def go():
        import asyncpg

        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            pytest.skip("no DATABASE_URL")
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
        except Exception:  # noqa: BLE001
            pytest.skip("no database reachable")
        schema = "t_skillmodel_" + uuid.uuid4().hex[:10]
        try:
            await conn.execute(f"CREATE SCHEMA {schema}")
            await conn.execute(f"SET search_path TO {schema}")
            await conn.execute(CREATE_OWUI_SKILLS_SQL)
            return await scenario(OnePool(conn), conn)
        finally:
            await conn.execute("RESET search_path")
            await conn.execute(f"DROP SCHEMA {schema} CASCADE")
            await conn.close()
    return asyncio.run(go())


async def seed(conn, name, content=BODY, *, enabled=True, verdict="supported", sha=True, files=None,
               desc="Use when a docker compose service will not start."):
    meta: dict = {"audit": {}}
    if verdict:
        meta["audit"] = {"verdict": verdict, "approved_by": UID}
        if sha:
            meta["audit"]["content_sha"] = sp.content_sha(content, files)
    if files:
        meta["files"] = files
    await conn.execute(
        "INSERT INTO owui_skills (id, user_id, name, description, content, meta, enabled) "
        "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)", str(uuid.uuid4()), UID, name, desc, content, json.dumps(meta), enabled)


async def get(conn, name):
    row = await conn.fetchrow("SELECT * FROM owui_skills WHERE user_id=$1 AND name=$2", UID, name)
    if row is None:
        return None
    row = dict(row)
    row["meta"] = sp.meta_dict(row["meta"])
    return row


async def names(conn):
    return sorted(r["name"] for r in await conn.fetch("SELECT name FROM owui_skills WHERE user_id=$1", UID))


def untouched(row):
    """Everything on a row except meta.pending: what a proposal must never change."""
    meta = {k: v for k, v in row["meta"].items() if k != "pending"}
    return (row["description"], row["content"], row["enabled"], json.dumps(meta, sort_keys=True))


# ─── the catalog ─────────────────────────────────────────────────────────────

def test_catalog_lists_only_enabled_approved_unedited_skills_and_no_bodies():
    async def scenario(pool, conn):
        await seed(conn, "good-skill", desc="Use when a good thing happens.")
        await seed(conn, "legacy-skill", sha=False, desc="Approved before hashes existed.")
        await seed(conn, "switched-off", enabled=False)
        await seed(conn, "never-approved", verdict=None)
        await seed(conn, "edited-after-approval")
        await conn.execute("UPDATE owui_skills SET content=$1 WHERE name='edited-after-approval'", BODY + "x")
        await conn.execute(
            "INSERT INTO owui_skills (id, user_id, name, description, content, meta, enabled) "
            "VALUES ($1,$2,'empty-shell','d','','{\"audit\":{\"verdict\":\"supported\"}}'::jsonb,TRUE)",
            str(uuid.uuid4()), UID)
        msg = await skill_select.skill_message(pool, UID, "completely unrelated words zebra")
        text = msg["content"]
        assert "good-skill: Use when a good thing happens." in text
        assert "legacy-skill" in text
        for hidden in ("switched-off", "never-approved", "edited-after-approval", "empty-shell"):
            assert hidden not in text
        assert "docker compose logs" not in text  # a catalog, never a body
    with_db(scenario)


def test_catalog_stays_under_the_cap_however_many_skills_there_are():
    async def scenario(pool, conn):
        for i in range(120):
            await seed(conn, f"skill-number-{i:03d}", desc=("A long description that goes on and on. " * 10))
        msg = await skill_select.skill_message(pool, UID, "completely unrelated words zebra")
        assert len(msg["content"]) <= skill_select.CATALOG_MAX_CHARS == 1500
        assert "more)" in msg["content"]  # it says it was cut
        # each line is the name plus at most 90 characters of the description
        line = next(l for l in msg["content"].splitlines() if l.startswith("- skill-number-000"))
        assert len(line) <= len("- skill-number-000: ") + skill_select.CATALOG_DESC_CHARS
    with_db(scenario)


def test_catalog_rides_along_with_the_two_body_lexical_pick():
    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug", desc="Use when a docker compose service fails to start.")
        await seed(conn, "latex-thesis-build", content="# Thesis\n\nRun latexmk twice.\n",
                   desc="Build the thesis PDF with latexmk.")
        msg = await skill_select.skill_message(pool, UID, "my docker compose service fails to start")
        text = msg["content"]
        assert text.index("Your saved skills") < text.index("Saved skills (playbooks)")
        assert "- latex-thesis-build:" in text           # in the catalog ...
        assert "Run latexmk twice" not in text           # ... but only the match carries a body
        assert "Run docker compose logs" in text
    with_db(scenario)


def test_catalog_formatting_is_bounded_without_a_database():
    rows = [{"name": f"n{i}", "description": "d" * 500} for i in range(200)]
    out = skill_select.catalog(rows)
    assert len(out) <= 1500 and out.count("\n") >= 2
    assert skill_select.catalog([{"name": "solo", "description": ""}]).endswith("- solo")


# ─── drafting: update instead of name-2 ──────────────────────────────────────

CHAT = [
    {"role": "user", "content": "my docker compose backend keeps restarting, help me work out why " * 2},
    {"role": "assistant", "content": "Run docker compose logs backend, then check the port mappings. " * 3},
]


def fake_model(monkeypatch, skill, seen=None):
    async def complete(system, user, **kw):
        if seen is not None:
            seen.append((system, user))
        return {"skill": skill}

    async def model(pool, uid):
        return ""

    async def allowed(pool, uid):
        return None
    monkeypatch.setattr(learn, "_complete_json", complete)
    monkeypatch.setattr(learn, "curator_model", model)
    monkeypatch.setattr(learn, "_allowed", allowed)


def test_save_as_skill_with_an_existing_name_is_a_pending_update_not_name_2(monkeypatch):
    fake_model(monkeypatch, {"name": "docker-compose-debug", "description": "Use when compose fails.",
                             "content": NEW_BODY})

    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug")
        before = untouched(await get(conn, "docker-compose-debug"))
        out = await learn.draft_skill(pool, UID, "sess-1", [*CHAT, {"role": "user", "content": "save that as a skill"}])
        assert out["name"] == "docker-compose-debug" and out["kind"] == "update"
        assert await names(conn) == ["docker-compose-debug"]  # no docker-compose-debug-2
        row = await get(conn, "docker-compose-debug")
        assert untouched(row) == before  # body, enabled and audit are exactly as a person left them
        assert "Check the ports and the volumes" in row["meta"]["pending"]["content"]
        assert row["meta"]["pending"]["session_id"] == "sess-1"
    with_db(scenario)


def test_update_the_x_skill_puts_the_existing_body_in_the_draft_prompt(monkeypatch):
    seen: list = []
    fake_model(monkeypatch, {"name": "ignored-by-update", "description": "Use when compose fails.",
                             "content": NEW_BODY}, seen)

    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug")
        await seed(conn, "latex-thesis-build", content="# Thesis\n\nRun latexmk twice.\n")
        ask = [*CHAT, {"role": "user", "content": "update the docker compose debug skill to also check the volumes"}]
        out = await learn.draft_skill(pool, UID, "sess-2", ask)
        assert out["name"] == "docker-compose-debug" and out["kind"] == "update"
        system, prompt = seen[0]
        assert "revise" in system.lower()
        assert "EXISTING SKILL (docker-compose-debug)" in prompt and "Check the ports." in prompt
        assert "latexmk" not in prompt  # only the skill being revised
        assert await names(conn) == ["docker-compose-debug", "latex-thesis-build"]
        assert "pending" in (await get(conn, "docker-compose-debug"))["meta"]
        assert "pending" not in (await get(conn, "latex-thesis-build"))["meta"]
    with_db(scenario)


def test_update_that_skill_means_the_one_this_chat_touched(monkeypatch):
    seen: list = []
    fake_model(monkeypatch, {"name": "x", "description": "d", "content": NEW_BODY}, seen)

    async def scenario(pool, conn):
        await seed(conn, "aaa-other-skill")
        await seed(conn, "docker-compose-debug")
        await conn.execute(
            "UPDATE owui_skills SET meta = jsonb_set(meta, '{session_id}', '\"sess-3\"') WHERE name='docker-compose-debug'")
        out = await learn.draft_skill(pool, UID, "sess-3", [*CHAT, {"role": "user", "content": "update that skill to also check X"}])
        assert out["name"] == "docker-compose-debug" and out["kind"] == "update"
    with_db(scenario)


def test_a_new_name_is_still_a_disabled_draft(monkeypatch):
    fake_model(monkeypatch, {"name": "compose-restart-loop", "description": "Use when compose restarts.",
                             "content": NEW_BODY})

    async def scenario(pool, conn):
        out = await learn.draft_skill(pool, UID, "s", [*CHAT, {"role": "user", "content": "save that as a skill"}])
        assert out == {"name": "compose-restart-loop", "description": "Use when compose restarts.", "kind": "new"}
        row = await get(conn, "compose-restart-loop")
        assert row["enabled"] is False and row["meta"]["audit"] == {} and "pending" not in row["meta"]
        assert row["content"].startswith("---\nname: compose-restart-loop")
    with_db(scenario)


def test_nothing_to_change_and_no_op_updates_come_back_as_reasons(monkeypatch):
    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug")
        ask = [*CHAT, {"role": "user", "content": "update the docker-compose-debug skill"}]
        fake_model(monkeypatch, None)
        out = await learn.draft_skill(pool, UID, "s", ask)
        assert "nothing to change" in out["reason"] and "name" not in out
        # a revision identical to the stored text is refused by propose, and the reason comes through
        row = await get(conn, "docker-compose-debug")
        md = "---\nname: docker-compose-debug\ndescription: Use when a docker compose service will not start.\n---\n\n" \
             + BODY.strip() + "\n"
        await conn.execute("UPDATE owui_skills SET content=$1, meta=jsonb_set(meta,'{audit,content_sha}', to_jsonb($2::text)) "
                           "WHERE name='docker-compose-debug'", md, sp.content_sha(md, None))
        fake_model(monkeypatch, {"name": "docker-compose-debug", "description": row["description"], "content": BODY.strip()})
        out = await learn.draft_skill(pool, UID, "s", ask)
        assert "already has exactly this text" in out["reason"]
    with_db(scenario)


# ─── the ask patterns ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "save that as a skill", "turn this into a skill please", "update the docker compose skill",
    "update that skill to also check X", "update my deploy skill", "add a skill that checks the ports",
    "remember how you did that", "Remember how you did it next time",
    "Hey, add a skill that checks the ports", "update the docker-compose-debug skill.",
])
def test_skill_asks_are_recognised(text):
    assert learn.wants_skill(text)


@pytest.mark.parametrize("text", [
    "what is a skill?", "I update the docs weekly", "add a skill to my resume", "remember that I love cake",
    "remember to buy milk", "how did you do that?",
    "update the resume to show my skill in python", "can you update my cv so it highlights my python skill",
    "Update the skill tree in my game", "add a skill that I have to my linkedin",
    "please update my skills section",
    "update my python skill to expert on my resume", "can you update my python skill to advanced on my CV",
    "Update my linkedin skill. Then go", "update my python skill to expert on my r\u00e9sum\u00e9",
    "update my python skill to expert. It's for my resume",
    "make sure to update my python skill to expert on my resume",
    "can you help me write a better description of my python skill for my resume",
])
def test_ordinary_chat_is_not_a_skill_ask(text):
    assert not learn.wants_skill(text)


_TECHNICAL_UPDATES = [
    ("update the aws deploy skill to use the staging profile", "aws-deploy"),
    ("update my zsh setup skill to source the profile first", "zsh-setup"),
    ("update the deploy skill to read the profile env file", "deploy"),
    ("update the python skill so the venv step uses the profile flag", "python"),
    ("update my deploy skill and add a note about the resume endpoint", "deploy"),
    ("update the postgres reset skill, it should mention the cv table", "postgres-reset"),
    ("update the deploy skill to call the resume endpoint", "deploy"),
    ("update the aws deploy skill to use the staging account", "aws-deploy"),
]


@pytest.mark.parametrize("text,want", _TECHNICAL_UPDATES)
def test_ordinary_technical_words_do_not_veto_a_real_update_ask(text, want):
    rows = [{"name": n, "meta": {}} for n in ("aws-deploy", "zsh-setup", "python", "deploy", "postgres-reset")]
    assert learn.wants_skill(text)
    assert learn.pick_update_target(rows, text, "s1") == want


def test_cv_talk_in_the_next_sentence_is_not_an_update_ask():
    rows = [{"name": "python", "meta": {}}]
    assert learn.pick_update_target(rows, "update my python skill to expert. It's for my resume", "s1") == ""
    assert learn.pick_update_target(rows, "update my python skill to expert. Then fix the build.", "s1") == "python"


def test_a_cv_ask_never_picks_an_update_target():
    rows = [{"name": "python", "meta": {}}, {"name": "linkedin-post", "meta": {}}]
    assert learn.pick_update_target(rows, "update my python skill to expert on my resume", "s1") == ""
    assert learn.pick_update_target(rows, "Update my linkedin skill. Then go", "s1") == ""
    assert learn.pick_update_target(rows, "update my python skill", "s1") == "python"
    assert learn.wants_skill("update the linkedin post skill") and learn.wants_skill("update my python skill.")


def test_remember_how_you_did_that_is_a_skill_ask_not_a_saved_fact():
    assert learn.explicit_memory("remember how you did that") == ""
    assert learn.explicit_memory("remember that I love cake").endswith("I love cake")


# ─── which skill "update the X skill" means ──────────────────────────────────

def _rows(*names):  # newest first, like the query
    return [{"name": n, "meta": {}} for n in names]


@pytest.mark.parametrize("rows, ask, want", [
    (["do", "docker-compose-debug"], "update the docker skill to also check volumes", "docker-compose-debug"),
    (["go"], "update the golang build skill", ""),
    (["python", "python-venv-setup"], "update the python venv setup skill", "python-venv-setup"),
    (["python-venv-setup", "python"], "update the python skill", "python"),                # exact slug beats a longer name
    (["docker-compose-debug-extra", "docker-compose-debug"], "update the docker compose skill", "docker-compose-debug"),
    (["latex-thesis", "docker-compose-debug"], "update the kubernetes skill", ""),   # no shared whole word
    (["a-build", "go-build-release"], "update the go build skill", "go-build-release"),
])
def test_update_target_is_ranked_not_the_first_substring_hit(rows, ask, want):
    assert learn.pick_update_target(_rows(*rows), ask, "s") == want


def test_that_skill_falls_back_to_the_newest_one_the_conversation_names():
    rows = _rows("latex-thesis", "docker-compose-debug")
    talk = "USER: run docker-compose-debug on the api\n\nASSISTANT: done"
    assert learn.pick_update_target(rows, "update that skill to also check volumes", "other", talk) == "docker-compose-debug"
    assert learn.pick_update_target(rows, "update that skill", "other", "USER: hello") == ""


def test_a_newer_short_name_does_not_steal_an_update_of_a_longer_one(monkeypatch):
    seen: list = []
    fake_model(monkeypatch, {"name": "x", "description": "d", "content": NEW_BODY}, seen)

    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug")
        await seed(conn, "do", content="# Do\n\nJust do it.\n")  # inserted later, so newest
        ask = [*CHAT, {"role": "user", "content": "update the docker skill to also check volumes"}]
        out = await learn.draft_skill(pool, UID, "s", ask)
        assert out["name"] == "docker-compose-debug" and out["kind"] == "update"
        assert seen[0][1].startswith("EXISTING SKILL (docker-compose-debug)")
        assert "pending" in (await get(conn, "docker-compose-debug"))["meta"]
        assert "pending" not in (await get(conn, "do"))["meta"]
    with_db(scenario)


def test_catalog_header_does_not_promise_a_slash_command():
    head = skill_select.catalog([{"name": "docker-compose-debug", "description": "d"}]).splitlines()[0]
    assert "typing /" not in head and "/name" not in head
    assert "use docker-compose-debug" in head


# ─── being told a draft was skipped ──────────────────────────────────────────

def _after_turn(monkeypatch, drafted, user_text="save that as a skill"):
    heard = {"skill": [], "skipped": []}

    async def prefs(pool, uid):
        return {"memory": False, "skills": True}

    async def draft(pool, uid, sid, messages):
        return drafted
    monkeypatch.setattr(learn, "settings", prefs)
    monkeypatch.setattr(learn, "draft_skill", draft)

    async def on_skill(d):
        heard["skill"].append(d)

    async def on_skipped(d):
        heard["skipped"].append(d)

    async def run():
        learn.after_turn(None, UID, "sess", [{"role": "user", "content": user_text}], "done", False,
                         on_skill=on_skill, on_skipped=on_skipped)
        await asyncio.gather(*list(learn._tasks))
    asyncio.run(run())
    return heard


def test_a_skipped_draft_is_announced_with_its_reason(monkeypatch):
    heard = _after_turn(monkeypatch, {"reason": "The conversation is too short to learn a procedure from."})
    assert heard == {"skill": [], "skipped": [{"reason": "The conversation is too short to learn a procedure from."}]}


def test_a_draft_announces_whether_it_is_new_or_an_update(monkeypatch):
    for kind in ("new", "update"):
        drafted = {"name": "docker-compose-debug", "description": "d", "kind": kind}
        heard = _after_turn(monkeypatch, drafted)
        assert heard == {"skill": [drafted], "skipped": []}


def test_a_skipped_draft_with_no_listener_does_not_break_the_turn(monkeypatch):
    async def prefs(pool, uid):
        return {"memory": False, "skills": True}

    async def draft(pool, uid, sid, messages):
        return {"reason": "nope"}
    monkeypatch.setattr(learn, "settings", prefs)
    monkeypatch.setattr(learn, "draft_skill", draft)

    async def run():
        learn.after_turn(None, UID, "sess", [{"role": "user", "content": "save that as a skill"}], "done", False)
        await asyncio.gather(*list(learn._tasks))
    asyncio.run(run())


# ─── the workspace tools: propose_skill(update_of), list_skills, read_skill ──

def _propose(pool, args):
    return asyncio.run(runner.SubAgentRunner(router=object())._propose_skill(pool, UID, args))


def test_propose_skill_update_of_writes_only_the_pending_revision():
    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug", files={"scripts/check.py": "print('ok')\n"})
        before = untouched(await get(conn, "docker-compose-debug"))
        r = runner.SubAgentRunner(router=object())
        out = await r._propose_skill(pool, UID, {"name": "docker-compose-debug", "update_of": "docker-compose-debug",
                                                 "description": "Use when compose fails.", "content": NEW_BODY})
        assert out.startswith("Proposed an update to 'docker-compose-debug'")
        row = await get(conn, "docker-compose-debug")
        assert untouched(row) == before and row["meta"]["pending"]["content"] == NEW_BODY.strip()
        assert row["meta"]["pending"]["files"] == {"scripts/check.py": "print('ok')\n"}  # the script rides along
        assert row["meta"]["pending"]["proposed_by"] == "workspace-run"
        assert await names(conn) == ["docker-compose-debug"]
    with_db(scenario)


def test_propose_skill_with_a_name_that_exists_is_an_update_not_a_refusal_or_a_duplicate():
    async def scenario(pool, conn):
        await seed(conn, "docker-compose-debug")
        r = runner.SubAgentRunner(router=object())
        out = await r._propose_skill(pool, UID, {"name": "docker-compose-debug", "description": "d", "content": NEW_BODY})
        assert not out.startswith("ERROR") and "waits" in out
        assert (await get(conn, "docker-compose-debug"))["meta"]["pending"]["content"] == NEW_BODY.strip()
        assert await names(conn) == ["docker-compose-debug"]
    with_db(scenario)


def test_propose_skill_update_of_a_skill_that_does_not_exist_is_an_error_and_writes_nothing():
    async def scenario(pool, conn):
        r = runner.SubAgentRunner(router=object())
        out = await r._propose_skill(pool, UID, {"name": "x", "update_of": "ghost", "description": "d", "content": NEW_BODY})
        assert out.startswith("ERROR") and "ghost" in out
        assert await names(conn) == []
    with_db(scenario)


def test_propose_skill_still_drafts_a_new_skill_disabled():
    async def scenario(pool, conn):
        r = runner.SubAgentRunner(router=object())
        out = await r._propose_skill(pool, UID, {"name": "fresh-skill", "description": "d", "content": NEW_BODY})
        assert out.startswith("Drafted skill 'fresh-skill'")
        row = await get(conn, "fresh-skill")
        assert row["enabled"] is False and row["meta"]["audit"] == {}
    with_db(scenario)


def test_list_and_read_skill_never_return_disabled_unapproved_or_edited_skills():
    async def scenario(pool, conn):
        await seed(conn, "good-skill", desc="Use when something good happens.")
        await seed(conn, "switched-off", enabled=False, content="# Off\n\nSECRET-OFF-BODY\n")
        await seed(conn, "never-approved", verdict=None, content="# Draft\n\nSECRET-DRAFT-BODY\n")
        await seed(conn, "edited-after-approval", content="# Edited\n\nSECRET-EDITED-BODY\n")
        await conn.execute("UPDATE owui_skills SET content=content || 'tampered' WHERE name='edited-after-approval'")
        await conn.execute(
            "INSERT INTO owui_skills (id, user_id, name, description, content, meta, enabled) "
            "VALUES ($1,$2,'pending-only','d','','{\"pending\":{\"content\":\"SECRET-PENDING-BODY\"}}'::jsonb,FALSE)",
            str(uuid.uuid4()), UID)

        listing = await skill_select.run_list_skills(pool, UID)
        assert listing == "good-skill: Use when something good happens."

        assert "Run docker compose logs" in await skill_select.run_read_skill(pool, UID, "good-skill")
        assert "Run docker compose logs" in await skill_select.run_read_skill(pool, UID, "GOOD-SKILL")
        for name, secret in (("switched-off", "SECRET-OFF-BODY"), ("never-approved", "SECRET-DRAFT-BODY"),
                             ("edited-after-approval", "SECRET-EDITED-BODY"), ("pending-only", "SECRET-PENDING-BODY")):
            out = await skill_select.run_read_skill(pool, UID, name)
            assert secret not in out and "tampered" not in out
            assert "no approved, enabled skill" in out
        # another person's skill is invisible too
        assert "no approved, enabled skill" in await skill_select.run_read_skill(pool, UID + 1, "good-skill")
        assert await skill_select.run_list_skills(pool, UID + 1) == "There are no approved skills yet."
    with_db(scenario)


def test_list_and_read_skill_fail_soft_without_a_pool():
    assert asyncio.run(skill_select.run_list_skills(None, UID)).startswith("ERROR")
    assert asyncio.run(skill_select.run_read_skill(None, UID, "x")).startswith("ERROR")


# ─── which runs are offered the skill tools ──────────────────────────────────

def _call(tool, **args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c-{tool}", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}


class OfferRouter:
    """Records the tool names offered on the first step, then finishes."""

    def __init__(self, first_turn=None):
        self.offered: list[str] | None = None
        self.turns = [first_turn] if first_turn else []

    async def complete(self, *, tools, **_):
        if self.offered is None:
            self.offered = [(t.get("function") or {}).get("name") for t in tools or []]
        if self.turns:
            return self.turns.pop(0)
        return _call("finish", summary="done")


def _drive(tmp_path, router, **kw):
    async def go():
        return [e async for e in runner.SubAgentRunner(router).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="do a thing", model_name="m",
            workspace_path=str(tmp_path), **kw)]
    return asyncio.run(go())


SKILL_TOOLS = {"propose_skill", "list_skills", "read_skill"}


def test_the_skill_tools_are_in_the_registry_and_the_agent_toolset():
    from workspace.orchestration import toolsets
    names = {(t.get("function") or {}).get("name") for t in orch_tools.TOOL_SCHEMA}
    assert SKILL_TOOLS <= names
    group = next(g for g in toolsets.TOOLSET_GROUPS if g[0] == "harvis-agent")
    assert SKILL_TOOLS <= set(group[3])
    props = next(t for t in orch_tools.TOOL_SCHEMA if t["function"]["name"] == "propose_skill")["function"]["parameters"]
    assert "update_of" in props["properties"] and "update_of" not in props["required"]


def test_user_launched_runs_with_a_database_are_offered_the_skill_tools(tmp_path):
    async def scenario(pool, conn):
        router = OfferRouter()
        events = [e async for e in runner.SubAgentRunner(router).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="do a thing", model_name="m",
            workspace_path=str(tmp_path), launch_mode="user", pool=pool, user_id=UID)]
        assert SKILL_TOOLS <= set(router.offered)
        assert events
    with_db(scenario)


def test_auto_launched_runs_are_not_offered_any_skill_tool(tmp_path):
    async def scenario(pool, conn):
        router = OfferRouter()
        [e async for e in runner.SubAgentRunner(router).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="do a thing", model_name="m",
            workspace_path=str(tmp_path), launch_mode="auto", pool=pool, user_id=UID)]
        assert not (SKILL_TOOLS & set(router.offered))
    with_db(scenario)


def test_runs_without_a_database_are_not_offered_any_skill_tool(tmp_path):
    router = OfferRouter()
    _drive(tmp_path, router, launch_mode="user")
    assert not (SKILL_TOOLS & set(router.offered))


def test_an_auto_run_that_calls_list_skills_anyway_is_denied(tmp_path):
    async def scenario(pool, conn):
        await seed(conn, "good-skill")
        router = OfferRouter(_call("list_skills"))
        events = [e async for e in runner.SubAgentRunner(router).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="do a thing", model_name="m",
            workspace_path=str(tmp_path), launch_mode="auto", pool=pool, user_id=UID)]
        outs = [str(e.data.get("output")) for e in events if e.type == "tool_result"]
        assert any(o.startswith("DENIED") for o in outs) and not any("good-skill" in o for o in outs)
    with_db(scenario)


def test_a_user_run_can_list_and_read_skills_through_the_real_dispatch(tmp_path):
    async def scenario(pool, conn):
        await seed(conn, "good-skill", desc="Use when something good happens.")
        await seed(conn, "switched-off", enabled=False, content="# Off\n\nSECRET-OFF-BODY\n")
        listed = [e async for e in runner.SubAgentRunner(OfferRouter(_call("list_skills"))).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="t", model_name="m",
            workspace_path=str(tmp_path), launch_mode="user", pool=pool, user_id=UID)]
        outs = [str(e.data.get("output")) for e in listed if e.type == "tool_result"]
        assert "good-skill: Use when something good happens." in outs[0] and "switched-off" not in outs[0]
        read = [e async for e in runner.SubAgentRunner(OfferRouter(_call("read_skill", name="switched-off"))).run(
            run_id="r2", parent_run_id="p1", label="Harvis Agent", task="t", model_name="m",
            workspace_path=str(tmp_path), launch_mode="user", pool=pool, user_id=UID)]
        outs = [str(e.data.get("output")) for e in read if e.type == "tool_result"]
        assert "SECRET-OFF-BODY" not in outs[0] and "no approved, enabled skill" in outs[0]
    with_db(scenario)
