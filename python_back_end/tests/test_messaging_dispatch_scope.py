"""Which Harvis user a message runs as depends on the bot that received it.

A user's own bot (the sidecar sends `bot_owner_user_id`) answers that user's links and
allowlist only; the house bot, and a sidecar too old to send the owner, resolve house
links. Everything stops at the admin's message limit so no agent runs."""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.messaging import dispatcher, routes  # noqa: E402
from plugins.messaging.types import MessageEvent, MessageType, Platform, SessionSource  # noqa: E402
from tests.test_messaging_link_ownership import FakePool, row  # noqa: E402

A, B = 7, 9
NO_USER = "no harvis user mapped to this sender"


class AuditedPool(FakePool):
    """FakePool that also records the messaging_audit inserts."""

    def __init__(self, rows=None):
        super().__init__(rows)
        self.audits = []
        inner = self.conn.execute

        async def execute(sql, *args):
            if "messaging_audit" in sql:
                self.audits.append(args)
                return None
            return await inner(sql, *args)

        self.conn.execute = execute

    @property
    def statuses(self):
        return [a[-1] for a in self.audits]


@pytest.fixture(autouse=True)
def stop_at_the_limit(monkeypatch):
    import plugins.people as people

    async def refuse(pool, user_id, *a, **kw):
        return SimpleNamespace(ok=False, reason="limit")

    monkeypatch.setattr(people, "admit_turn", refuse)


def run(coro):
    return asyncio.run(coro)


def _event(sender="555", text="hi"):
    src = SessionSource(platform=Platform.TELEGRAM, chat_id=sender, sender_id=sender, is_dm=True)
    return MessageEvent(source=src, message_id="m1", message_type=MessageType.TEXT, text=text)


def _dispatch(pool, *, owner=None, fallback=None, sender="555"):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
    kwargs = {} if owner is None else {"bot_owner_user_id": owner}
    return dispatcher.dispatch_inbound(request, _event(sender), fallback_user_id=fallback, **kwargs)


def test_own_bot_runs_the_sender_as_its_owner():
    pool = AuditedPool([row(A)])
    result = run(_dispatch(pool, owner=A))
    assert result.user_id == A and result.error == "limit"


def test_own_bot_ignores_a_sender_paired_to_another_user():
    pool = AuditedPool([row(A)])
    result = run(_dispatch(pool, owner=B))
    assert result.ok is False and result.user_id is None and result.error == NO_USER
    assert pool.statuses == ["rejected_no_user"]


def test_each_users_bot_answers_as_that_user_when_both_paired_the_sender():
    pool = AuditedPool([row(A), row(B)])
    assert run(_dispatch(pool, owner=A)).user_id == A
    assert run(_dispatch(pool, owner=B)).user_id == B


def test_own_bot_ignores_a_house_link_held_by_someone_else():
    pool = AuditedPool([row(A, house=True)])
    assert run(_dispatch(pool, owner=B)).error == NO_USER


def test_own_bot_honours_the_owners_own_house_link():
    pool = AuditedPool([row(A, house=True)])
    assert run(_dispatch(pool, owner=A)).user_id == A


def test_own_bot_allowlist_runs_the_sender_as_the_owner():
    pool = AuditedPool()
    assert run(_dispatch(pool, owner=B, fallback=B)).user_id == B


def test_own_bot_ignores_a_fallback_naming_another_user():
    pool = AuditedPool([row(A)])
    result = run(_dispatch(pool, owner=B, fallback=A))
    assert result.ok is False and result.user_id is None and result.error == NO_USER
    assert pool.statuses == ["rejected_no_user"]


def test_own_bot_disabled_link_does_not_answer_and_does_not_fall_through_to_others():
    pool = AuditedPool([row(B, enabled=False), row(A)])
    assert run(_dispatch(pool, owner=B)).error == NO_USER


def test_house_bot_ignores_own_bot_links():
    pool = AuditedPool([row(A, house=False)])
    assert run(_dispatch(pool)).error == NO_USER


def test_house_bot_resolves_the_house_link():
    pool = AuditedPool([row(A, house=True), row(B, house=False)])
    assert run(_dispatch(pool)).user_id == A


def test_house_bot_falls_back_to_the_fallback_user():
    pool = AuditedPool([row(B, house=False)])
    assert run(_dispatch(pool, fallback=A)).user_id == A


def test_resolve_user_id_without_an_owner_is_the_house_lookup():
    """The Discord workspace bot calls it this way."""
    pool = AuditedPool([row(A, house=False), row(B, house=True)])
    source = _event().source
    assert run(dispatcher.resolve_user_id(pool, source)) == B
    assert run(dispatcher.resolve_user_id(pool, source, A)) == A
    assert run(dispatcher.resolve_user_id(pool, source, 12)) is None


def _inbound(monkeypatch, **extra):
    seen = {}

    async def fake_dispatch(request, event, **kwargs):
        seen.update(kwargs)
        return dispatcher.DispatchResult(ok=False, error="stop")

    monkeypatch.setattr(routes, "dispatch_inbound", fake_dispatch)
    payload = routes.InboundMessagePayload(
        source=routes.InboundSourcePayload(platform=Platform.TELEGRAM, chat_id="c", sender_id="555"),
        message_id="m1", text="hi", **extra)
    run(routes.inbound(payload, SimpleNamespace(), None))
    return seen


def test_inbound_route_passes_the_bot_owner_to_the_dispatcher(monkeypatch):
    assert _inbound(monkeypatch, bot_owner_user_id=B, fallback_user_id=B) == {
        "fallback_user_id": B, "bot_owner_user_id": B}


def test_inbound_route_from_an_old_sidecar_has_no_bot_owner(monkeypatch):
    assert _inbound(monkeypatch, fallback_user_id=A) == {"fallback_user_id": A, "bot_owner_user_id": None}
