"""The teammate's browser is a real Firefox that resolves names and follows redirects on its
own, so the backend cannot vet where it ends up. On a shared host a non-admin gets it only
when the operator says its egress is locked to public addresses, and the URLs the backend
does see are held to public, resolvable names. The runner and name resolution are replaced;
nothing here opens a socket."""
import asyncio
import os
import socket
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.agents import computer as c  # noqa: E402

TOKEN = "81b297c14bb508a3ad8b83df2ac52956"
PUBLIC_IP = "93.184.216.34"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    c._sessions.clear()
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv(c.EGRESS_LOCK_ENV, raising=False)
    yield
    c._sessions.clear()


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)


@pytest.fixture
def runner(monkeypatch):
    calls = []

    async def fake(method, path, *, json=None, timeout=30.0):
        calls.append((method, path, json))
        if path == "/sessions":
            return {"sessions": []}
        if path == "/session":
            return {"sessionId": "s-1", "vncToken": TOKEN, "display": ":100", "width": 1280, "height": 800}
        if path == "/navigate":
            return {"url": json["url"]}
        return {}

    monkeypatch.setattr(c, "_runner", fake)
    return calls


@pytest.fixture
def dns(monkeypatch):
    """Names answer from the table; anything else does not resolve. Literals resolve to themselves."""
    def script(table):
        async def getaddrinfo(self, host, port, **_kwargs):
            if host in table:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in table[host]]
            raise socket.gaierror("no such name")

        def sync_getaddrinfo(host, port, *a, **k):
            if host in table:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in table[host]]
            raise socket.gaierror("no such name")

        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
        monkeypatch.setattr(socket, "getaddrinfo", sync_getaddrinfo)

    return script


# -- starting a session ---------------------------------------------------------------

def test_a_non_admin_on_a_shared_host_gets_no_browser_without_the_operators_attestation(shared, runner):
    with pytest.raises(HTTPException) as excinfo:
        run(c.ensure_session(7, None))
    assert excinfo.value.status_code == 403 and runner == []


def test_the_agents_own_computer_call_gets_the_same_refusal_as_text(shared, runner):
    text, ok = run(c.act({"user_id": 7, "agent_id": None}, "computer_open", {"url": "https://example.com"}))
    assert ok is False and "not available" in text and runner == []


@pytest.mark.parametrize("value", ["0", "", "no", "false", "off", "maybe"])
def test_only_an_explicit_yes_counts_as_an_egress_lock(shared, runner, monkeypatch, value):
    monkeypatch.setenv(c.EGRESS_LOCK_ENV, value)
    with pytest.raises(HTTPException):
        run(c.ensure_session(7, None))


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", " TRUE "])
def test_a_non_admin_gets_the_browser_once_the_operator_attests_the_egress_lock(shared, runner, monkeypatch, value):
    monkeypatch.setenv(c.EGRESS_LOCK_ENV, value)
    rec = run(c.ensure_session(7, None))
    assert rec["session_id"] == "s-1" and ("POST", "/session") in [(m, p) for m, p, _ in runner]


def test_an_admin_on_a_shared_host_needs_no_attestation(shared, runner):
    assert run(c.ensure_session(1, None))["session_id"] == "s-1"


def test_a_local_install_needs_no_attestation_for_any_user(local, runner):
    assert run(c.ensure_session(7, None))["session_id"] == "s-1"


# -- what the backend can see: the URLs ----------------------------------------------

def _rec(uid):
    return {"session_id": "s-1", "user_id": uid}


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/", "https://10.0.0.5/", "https://169.254.169.254/latest/meta-data/", "https://100.64.0.9/",
    "https://[::ffff:10.0.0.1]/", "https://ollama/", "https://pgsql:5432/", "https://nas.local/",
    "https://unresolvable.example/", "https://corp.example/",
])
def test_a_guarded_user_cannot_send_the_browser_to_a_private_or_unresolvable_address(shared, runner, dns, url):
    dns({"corp.example": ["10.1.2.3"]})
    with pytest.raises(HTTPException) as excinfo:
        run(c._navigate(_rec(7), url))
    assert excinfo.value.status_code == 400
    assert "10.1.2.3" not in str(excinfo.value.detail) and "corp" not in str(excinfo.value.detail)
    assert runner == []


def test_a_guarded_user_may_open_a_public_site(shared, runner, dns):
    dns({"good.example": [PUBLIC_IP]})
    run(c._navigate(_rec(7), "https://good.example/page"))
    assert runner == [("POST", "/navigate", {"sessionId": "s-1", "url": "https://good.example/page"})]


def test_an_admin_keeps_the_existing_navigation_policy_on_a_shared_host(shared, runner, dns):
    dns({})
    run(c._navigate(_rec(1), "https://unresolvable.example/"))  # unresolvable names were never refused here
    assert runner and runner[0][1] == "/navigate"


def test_a_local_install_keeps_the_existing_navigation_policy_for_every_user(local, runner, dns):
    dns({})
    run(c._navigate(_rec(7), "https://unresolvable.example/"))
    assert runner and runner[0][1] == "/navigate"


def test_the_existing_literal_and_localhost_refusals_still_apply_to_everyone(shared, runner, dns):
    dns({})
    for uid in (1, 7):
        for url in ("https://127.0.0.1/", "https://localhost/", "http://good.example/"):
            with pytest.raises(HTTPException):
                run(c._navigate(_rec(uid), url))
    assert runner == []


# -- a session that outlived the lock -------------------------------------------------

def _live_item(uid, sid="old-1"):
    return {"sessionId": sid, "profile": c.profile_key_for(uid, None), "screen": {"token": TOKEN}}


def _old_session(uid, sid="old-1"):
    c._remember({"session_id": sid, "user_id": uid, "agent_id": None, "profile": c.profile_key_for(uid, None),
                 "token": TOKEN, "taken_over": False, "created_at": 1})


@pytest.fixture
def old_runner(monkeypatch):
    calls = []

    async def fake(method, path, *, json=None, timeout=30.0):
        calls.append((method, path, json))
        if path == "/sessions":
            return {"items": [_live_item(7), _live_item(1, "admin-1")]}
        if path.endswith("/takeover"):
            return {"takenOver": True}
        return {}

    monkeypatch.setattr(c, "_runner", fake)
    return calls


def _closed(calls):
    return [j["sessionId"] for m, p, j in calls if p == "/close"]


def test_a_guarded_user_cannot_take_over_navigate_or_read_a_session_the_lock_no_longer_covers(shared, old_runner):
    for call in (
        lambda: c.computer_takeover("old-1", c.TakeoverForm(taken=True), current_user={"id": 7}),
        lambda: c.computer_navigate("old-1", c.NavigateForm(url="https://example.com"), current_user={"id": 7}),
        lambda: c.computer_get("old-1", current_user={"id": 7}),
    ):
        _old_session(7)
        with pytest.raises(HTTPException) as excinfo:
            run(call())
        assert excinfo.value.status_code == 403
    assert not any(p.endswith(("/takeover", "/navigate")) or p.startswith("/camofox") for _, p, _ in old_runner)
    assert _closed(old_runner) == ["old-1"] * 3
    assert c.owned(7, "old-1") is None


def test_listing_closes_and_does_not_adopt_a_guarded_users_leftover_session(shared, old_runner):
    out = run(c.computer_list(current_user={"id": 7}))
    assert out == {"items": []} and _closed(old_runner) == ["old-1"]


def test_listing_still_adopts_an_admins_session_on_a_shared_host(shared, old_runner):
    out = run(c.computer_list(current_user={"id": 1}))
    assert [i["sessionId"] for i in out["items"]] == ["admin-1"] and _closed(old_runner) == ["old-1"]


def test_a_guarded_user_keeps_their_session_once_the_operator_attests_the_lock(shared, old_runner, monkeypatch):
    monkeypatch.setenv(c.EGRESS_LOCK_ENV, "1")
    out = run(c.computer_list(current_user={"id": 7}))
    assert [i["sessionId"] for i in out["items"]] == ["old-1"] and _closed(old_runner) == []
    assert run(c.computer_takeover("old-1", c.TakeoverForm(taken=True), current_user={"id": 7}))["takenOver"] is True


def test_a_guarded_user_can_still_close_their_own_leftover_session(shared, old_runner):
    _old_session(7)
    assert run(c.computer_close("old-1", current_user={"id": 7})) == {"closed": True}


def test_a_local_install_lists_and_takes_over_sessions_for_any_user(local, old_runner):
    out = run(c.computer_list(current_user={"id": 7}))
    assert [i["sessionId"] for i in out["items"]] == ["old-1"] and _closed(old_runner) == []


# -- the screen never calls the API, so a sweep closes leftovers on its own -------------

def _sweep_once():
    """Run the lock sweeper's first pass, then stop it at its first sleep."""
    class Stop(Exception):
        pass

    async def stop(_interval):
        raise Stop

    async def go():
        real = c.asyncio.sleep
        c.asyncio.sleep = stop
        try:
            await c.run_lock_sweeper()
        except Stop:
            pass
        finally:
            c.asyncio.sleep = real

    run(go())


def test_the_sweeper_closes_a_guarded_users_screen_with_no_request_and_keeps_the_admins(shared, old_runner):
    _old_session(7)
    _sweep_once()
    assert _closed(old_runner) == ["old-1"]
    assert c.owned(7, "old-1") is None
    assert c.owned(1, "admin-1") is not None


def test_the_sweeper_survives_a_missing_runner(shared, monkeypatch):
    async def down(method, path, *, json=None, timeout=30.0):
        raise HTTPException(503, "runner down")

    monkeypatch.setattr(c, "_runner", down)
    _sweep_once()  # returns instead of raising


def test_the_sweeper_leaves_sessions_alone_once_the_lock_is_attested(shared, old_runner, monkeypatch):
    monkeypatch.setenv(c.EGRESS_LOCK_ENV, "1")
    _sweep_once()
    assert _closed(old_runner) == []
