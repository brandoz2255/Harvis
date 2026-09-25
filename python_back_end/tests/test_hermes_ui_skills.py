"""Skills in Hermes chat: which trusted skills a turn carries, switching a draft on
approves it, the editor's /learning/node door, and the "learned a skill" event."""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import learn, rest_skills, skill_select  # noqa: E402

DOCKER = {"id": "s1", "name": "docker-compose-debug",
          "description": "Use when a docker compose service fails to start or keeps restarting."}
LATEX = {"id": "s2", "name": "latex-thesis-build",
         "description": "Build the thesis PDF with latexmk and fix bibliography errors."}
PIRATE = {"id": "s3", "name": "pirate", "description": "Talk like a pirate."}


# ─── picking skills for a message ────────────────────────────────────────────

def test_a_matching_message_carries_the_skill():
    assert skill_select.pick("my docker compose backend won't start", [DOCKER, LATEX, PIRATE]) == ["s1"]
    assert skill_select.pick("latexmk says the bibliography is broken in my thesis", [DOCKER, LATEX]) == ["s2"]


def test_one_shared_word_is_not_enough():
    assert skill_select.pick("what does a pirate ship cost?", [PIRATE]) == []  # name word = 2 < 3
    assert skill_select.pick("the service is down", [DOCKER]) == []
    assert skill_select.pick("hello there", [DOCKER, LATEX, PIRATE]) == []


def test_naming_a_skill_always_carries_it_first():
    rows = [DOCKER, LATEX, PIRATE]
    assert skill_select.pick("use /pirate for this", rows) == ["s3"]
    assert skill_select.pick("$pirate docker compose won't start", rows) == ["s3", "s1"]
    assert skill_select.names_skill("run docker-compose-debug please", "docker-compose-debug")
    assert not skill_select.names_skill("pirates ahoy", "pirate")


def test_at_most_two_skills_ride_along():
    rows = [dict(DOCKER, id=f"d{i}", name=f"docker-compose-debug-{i}") for i in range(4)]
    assert len(skill_select.pick("docker compose service fails to start", rows)) == skill_select.MAX_SKILLS


# ─── the turn's system message ───────────────────────────────────────────────

class _Conn:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    async def fetch(self, sql, *args):
        self.log.append((sql, args))
        return self.rows

    async def execute(self, sql, *args):
        self.log.append((sql, args))
        return "UPDATE 1"

    async def fetchrow(self, sql, *args):
        self.log.append((sql, args))
        return self.rows[0] if self.rows else None


class _Pool:
    def __init__(self, rows=()):
        self.rows, self.log = list(rows), []

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _Conn(pool.rows, pool.log)

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def test_skill_message_asks_only_for_trusted_skills_and_gates_the_bodies(monkeypatch):
    pool = _Pool([DOCKER, LATEX])
    seen = {}

    async def gate(p, uid, ids, **kw):
        seen["ids"] = ids
        return ["### docker-compose-debug\n1. docker compose logs"]
    import owui_compat.skills as owui_skills
    monkeypatch.setattr(owui_skills, "gated_skill_blocks", gate)

    msg = asyncio.run(skill_select.skill_message(pool, 7, "docker compose won't start"))
    sql = pool.log[0][0]
    assert "enabled=TRUE" in sql and "'supported'" in sql
    assert seen["ids"] == ["s1"]
    assert msg["role"] == "system" and "docker compose logs" in msg["content"]


def test_skill_message_is_none_when_nothing_matches_or_the_db_fails():
    assert asyncio.run(skill_select.skill_message(_Pool([DOCKER]), 7, "hello")) is None
    assert asyncio.run(skill_select.skill_message(object(), 7, "docker compose")) is None
    assert asyncio.run(skill_select.skill_message(None, 7, "docker compose")) is None


# ─── switching on = approving ────────────────────────────────────────────────

class _Req:
    def __init__(self, pool, body=None, query=None):
        self._body = body or {}
        self.query_params = query or {}
        self.app = type("A", (), {"state": type("S", (), {"pg_pool": pool})()})()

    async def json(self):
        return self._body


def test_switching_a_skill_on_records_the_approval():
    pool = _Pool()
    out = asyncio.run(rest_skills.skill_toggle(_Req(pool, {"name": "x", "enabled": True}), {"id": 7}))
    sql, args = pool.log[0]
    assert out == {"ok": True, "name": "x", "enabled": True}
    assert "jsonb_set(meta, '{audit}'" in sql and "'drafts'" in sql
    audit = json.loads(args[3])
    assert audit["verdict"] == "supported" and audit["approved_by"] == 7


def test_learning_node_reads_edits_and_deletes_by_skill_name():
    pool = _Pool([{"name": "x", "content": "# X"}])
    got = asyncio.run(rest_skills.learning_node(_Req(pool, query={"id": "skill:x"}), {"id": 7}))
    assert got == {"ok": True, "kind": "skill", "label": "x", "content": "# X"}
    assert pool.log[-1][1] == (7, "x")

    asyncio.run(rest_skills.learning_node_edit(_Req(pool, {"id": "x", "content": "# Y"}), {"id": 7}))
    assert pool.log[-1][1] == (7, "x", "# Y")

    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(rest_skills.learning_node_edit(_Req(pool, {"id": "x", "content": "  "}), {"id": 7}))

    asyncio.run(rest_skills.learning_node_delete(_Req(pool, {"id": "x"}), {"id": 7}))
    assert pool.log[-1][0].startswith("DELETE FROM owui_skills")


# ─── "Harvis learned a skill" ────────────────────────────────────────────────

def test_after_turn_announces_a_drafted_skill(monkeypatch):
    heard = []

    async def prefs(pool, uid):
        return {"memory": False, "skills": True}

    async def draft(pool, uid, sid, messages):
        return {"name": "docker-compose-debug", "description": "When compose won't start."}
    monkeypatch.setattr(learn, "settings", prefs)
    monkeypatch.setattr(learn, "draft_skill", draft)

    async def on_skill(d):
        heard.append(d)

    async def run():
        learn.after_turn(None, 7, "sess", [{"role": "user", "content": "save this as a skill"}],
                         "done", False, on_skill=on_skill)
        await asyncio.gather(*list(learn._tasks))
    asyncio.run(run())
    assert heard == [{"name": "docker-compose-debug", "description": "When compose won't start."}]
