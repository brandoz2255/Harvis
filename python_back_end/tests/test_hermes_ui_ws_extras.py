"""ExtraMethods: every gateway method the desktop calls gets an answer it can show or ignore."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui.rpc import ERR_METHOD  # noqa: E402
from plugins.hermes_ui.ws_extras import ERR_UNAVAILABLE, ExtraMethods  # noqa: E402

DSN = os.getenv("DATABASE_URL") or "postgresql://pguser:pgpassword@pgsql:5432/database"


class Conn(ExtraMethods):
    def __init__(self, user_id=1, pool=None):
        self.user_id, self.pool = user_id, pool

    async def call(self, method, **params):
        handler = getattr(self, "m_" + method.replace(".", "_"), None)
        assert handler is not None, f"{method} has no handler"
        return await handler(1, params)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("method", [
    "projects.list", "projects.project_sessions", "projects.discover_repos", "projects.record_repos",
    "projects.set_active", "pet.info.meta", "pet.gallery", "pet.thumb", "pet.generate.status", "wake.start",
    "wake.stop", "wake.pause", "wake.resume", "wake.feed", "browser.manage", "clarify.respond",
    "mcp.setup.respond", "handoff.state", "handoff.fail"])
def test_read_style_methods_answer_with_a_result(method):
    reply = run(Conn().call(method))
    assert "result" in reply and "error" not in reply


@pytest.mark.parametrize("method", [
    "projects.create", "projects.update", "projects.delete", "projects.add_folder", "pet.select", "pet.disable",
    "pet.scale", "pet.export", "pet.rename", "pet.remove", "handoff.request"])
def test_creating_methods_refuse_with_a_readable_reason(method):
    reply = run(Conn().call(method))
    assert reply["error"]["code"] == ERR_UNAVAILABLE and reply["error"]["code"] != ERR_METHOD
    assert len(reply["error"]["message"]) > 20


def test_empty_shapes_match_what_the_ui_reads():
    c = Conn()
    assert run(c.call("projects.list"))["result"] == {"projects": [], "active_id": None}
    assert run(c.call("projects.discover_repos"))["result"]["repos"] == []
    assert run(c.call("pet.gallery"))["result"] == {"enabled": False, "active": "", "pets": []}
    assert run(c.call("wake.start"))["result"]["started"] is False
    assert run(c.call("browser.manage", action="status"))["result"]["connected"] is False


def test_stale_prompt_answers_use_the_ui_drop_the_card_wording():
    # lib/gateway-rpc.ts isMissingPendingPromptRequest matches "no pending <key> request"
    assert "no pending password request" in run(Conn().call("sudo.respond"))["error"]["message"]
    assert "no pending value request" in run(Conn().call("secret.respond"))["error"]["message"]


def test_cron_manage_is_scoped_to_the_caller():
    async def go():
        import asyncpg
        try:
            pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1, timeout=5)
        except Exception as exc:
            pytest.skip(f"no database: {type(exc).__name__}")
        try:
            async with pool.acquire() as conn:
                await conn.execute("CREATE TEMP TABLE cron_jobs (LIKE cron_jobs INCLUDING DEFAULTS)")
            mine, theirs = Conn(1, pool), Conn(2, pool)
            bad = await mine.call("cron.manage", action="add", name="x", schedule="not a schedule", prompt="hi")
            added = await mine.call("cron.manage", action="add", name="[bot:ops] Digest", schedule="every 1h",
                                    prompt="Summarize the day")
            job = added["result"]["job"]
            listed = (await mine.call("cron.manage", action="list"))["result"]["jobs"]
            other = (await theirs.call("cron.manage", action="list"))["result"]["jobs"]
            steal = await theirs.call("cron.manage", action="remove", name=job["job_id"])
            paused = await mine.call("cron.manage", action="pause", name=job["job_id"])
            after = (await mine.call("cron.manage", action="list"))["result"]["jobs"][0]
            gone = await mine.call("cron.manage", action="remove", name=job["job_id"])
            left = (await mine.call("cron.manage", action="list"))["result"]["jobs"]
            return bad, job, listed, other, steal, paused, after, gone, left
        finally:
            await pool.close()

    bad, job, listed, other, steal, paused, after, gone, left = run(go())
    assert "error" in bad
    assert job["name"] == "[bot:ops] Digest" and job["schedule"] and job["job_id"] == job["id"]
    assert [j["job_id"] for j in listed] == [job["job_id"]] and other == []
    assert "error" in steal and paused["result"]["success"] is True
    assert after["enabled"] is False and after["state"] == "paused"
    assert gone["result"]["success"] is True and left == []
