"""When a browser session is over, and whether the screen answers before one exists.

The bug these guard: a session died 300 s after it was created, mid-use, while
a person was signing in on the Take-over screen; and the noVNC page was an
nginx 502 until the first headed session had started websockify.

Nothing here starts Firefox. The clocks are checked on the registry with a fake
clock, websockify through a fake Popen, and the HTTP surface through the app
with selenium stubbed out when it is not installed (the backend container has
fastapi and no selenium — see test_snapshot_format.py for where to run this).
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import display  # noqa: E402
import sessions  # noqa: E402


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeDriver:
    def __init__(self):
        self.quit_calls = 0
        self.current_url = "https://www.instagram.com/"
        self.title = "Instagram"

    def quit(self):
        self.quit_calls += 1


# ── the two clocks ───────────────────────────────────────────────────────────

def test_a_session_in_use_outlives_the_old_300s_lifetime():
    clock = FakeClock()
    reg = sessions.Registry(idle_s=300, max_s=3600, clock=clock)
    reg.add("s", FakeDriver())
    # Used every 30 s for twenty minutes, as the ttl probe did.
    for _ in range(40):
        clock.t += 30
        assert reg.touch("s") is not None, f"died at t+{clock.t - 1000:.0f}s while in use"
        assert reg.expire() == []
    assert len(reg) == 1


def test_an_idle_session_expires_after_the_idle_window_not_before():
    clock = FakeClock()
    reg = sessions.Registry(idle_s=300, max_s=3600, clock=clock)
    reg.add("s", FakeDriver())
    clock.t += 299
    assert reg.expire() == []
    clock.t += 2
    gone = reg.expire()
    assert [e.session_id for e in gone] == ["s"]
    assert reg.touch("s") is None


def test_the_max_lifetime_caps_even_a_busy_session():
    clock = FakeClock()
    reg = sessions.Registry(idle_s=300, max_s=900, clock=clock)
    reg.add("s", FakeDriver())
    for _ in range(30):
        clock.t += 30
        reg.touch("s")
    clock.t += 1
    assert [e.session_id for e in reg.expire()] == ["s"]


def test_a_taken_over_screen_never_idles_out_but_still_hits_the_cap():
    clock = FakeClock()
    reg = sessions.Registry(idle_s=300, max_s=900, clock=clock)
    reg.add("mine", FakeDriver())
    reg.add("other", FakeDriver())
    clock.t += 600  # nobody called the runner: the user is driving "mine" in noVNC
    gone = reg.expire(keep_alive=lambda sid: sid == "mine")
    assert [e.session_id for e in gone] == ["other"]
    clock.t += 301
    assert [e.session_id for e in reg.expire(keep_alive=lambda sid: True)] == ["mine"]


def test_env_seconds_floors_and_survives_garbage(monkeypatch):
    monkeypatch.setenv("X_S", "5")
    assert sessions.env_seconds("X_S", 900, 30) == 30
    monkeypatch.setenv("X_S", "not a number")
    assert sessions.env_seconds("X_S", 900, 30) == 900
    monkeypatch.delenv("X_S")
    assert sessions.env_seconds("X_S", 900, 30) == 900
    # The cap can never be shorter than the idle window.
    assert sessions.Registry(idle_s=600, max_s=10).max_s == 600


def test_defaults_are_long_enough_for_a_sign_in_and_a_30_minute_run():
    assert sessions.IDLE_S >= 600
    assert sessions.MAX_S >= 1800


def test_by_profile_finds_the_firefox_already_on_that_profile():
    reg = sessions.Registry(clock=FakeClock())
    reg.add("a", FakeDriver(), profile="u7-default")
    assert reg.by_profile("u7-default").session_id == "a"
    assert reg.by_profile("u8-default") is None
    assert reg.by_profile(None) is None


# ── websockify is up before any session ──────────────────────────────────────

class FakePopen:
    spawned = []

    def __init__(self, cmd, **_kw):
        self.cmd = cmd
        self.rc = None
        FakePopen.spawned.append(self)

    def poll(self):
        return self.rc

    def send_signal(self, _sig):
        self.rc = 0

    def wait(self, timeout=None):
        return self.rc

    def kill(self):
        self.rc = -9


@pytest.fixture
def fake_websockify(monkeypatch, tmp_path):
    FakePopen.spawned = []
    monkeypatch.setattr(display, "TOKEN_DIR", str(tmp_path / "tokens"))
    monkeypatch.setattr(display.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(display, "_have", lambda name: True)
    monkeypatch.setattr(display, "_websockify", None)
    yield
    display._websockify = None


def test_ensure_websockify_starts_it_with_no_session_and_an_empty_token_file(fake_websockify):
    assert not display.websockify_up()
    assert display.ensure_websockify() is True
    assert len(FakePopen.spawned) == 1
    cmd = FakePopen.spawned[0].cmd
    assert cmd[0] == "websockify" and cmd[-1] == str(display.WEBSOCKIFY_PORT)
    assert "--token-plugin=TokenFile" in cmd
    # The token source exists and is empty, so a stale token from a previous
    # life cannot open anything.
    with open(os.path.join(display.TOKEN_DIR, "tokens"), encoding="utf-8") as fh:
        assert fh.read() == ""


def test_ensure_websockify_is_idempotent_and_restarts_a_dead_one(fake_websockify):
    display.ensure_websockify()
    display.ensure_websockify()
    assert len(FakePopen.spawned) == 1
    FakePopen.spawned[0].rc = 1  # it died
    assert not display.websockify_up()
    assert display.ensure_websockify() is True
    assert len(FakePopen.spawned) == 2


# ── the HTTP surface ─────────────────────────────────────────────────────────

def _stub_selenium():
    """app.py imports selenium at the top; the backend container has none."""
    try:
        import selenium  # noqa: F401
        return
    except ImportError:
        pass

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class _Any:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, _n):
            return _Any()

    mod("selenium")
    mod("selenium.webdriver", Firefox=_Any)
    mod("selenium.webdriver.common")
    mod("selenium.webdriver.common.by", By=_Any())
    mod("selenium.webdriver.common.keys", Keys=_Any())
    mod("selenium.webdriver.firefox")
    mod("selenium.webdriver.firefox.options", Options=_Any)
    mod("selenium.webdriver.firefox.service", Service=_Any)


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    _stub_selenium()
    import app as runner_app
    from fastapi.testclient import TestClient

    clock = FakeClock()
    reg = sessions.Registry(idle_s=300, max_s=3600, clock=clock)
    runner_app._registry = reg
    yield TestClient(runner_app.app), runner_app, reg, clock
    for entry in reg.entries():
        reg.pop(entry.session_id)


def test_health_reports_the_clocks_and_whether_the_screen_route_is_up(client):
    tc, _app, reg, _clock = client
    h = tc.get("/health").json()
    assert h["sessionIdleS"] == 300 and h["sessionMaxS"] == 3600
    assert "vncUp" in h


def test_a_second_firefox_on_a_held_profile_is_refused_with_the_live_session_id(client):
    tc, _app, reg, _clock = client
    reg.add("live", FakeDriver(), profile="u7-default", headed=True)
    r = tc.post("/session", json={"headed": True, "headless": False, "profile": "u7-default"})
    assert r.status_code == 409
    assert r.json()["detail"] == {"error": "profile in use", "sessionId": "live"}


def test_sessions_lists_what_the_backend_needs_to_adopt_after_a_restart(client, monkeypatch):
    tc, _app, reg, clock = client
    reg.add("live", FakeDriver(), profile="u7-default", headed=True)
    screen = display.Screen("live", 100, 5900, 1280, 800)
    monkeypatch.setitem(display._screens, "live", screen)
    clock.t += 42
    items = tc.get("/sessions").json()["items"]
    assert [i["sessionId"] for i in items] == ["live"]
    item = items[0]
    assert item["profile"] == "u7-default" and item["idleS"] == 42
    assert item["screen"]["token"] == screen.token and item["screen"]["display"] == ":100"


def test_every_call_through_the_driver_resets_the_idle_clock(client):
    tc, _app, reg, clock = client
    reg.add("live", FakeDriver(), profile="u7-default")
    clock.t += 250
    assert tc.get("/camofox/tabs/live").status_code == 200
    clock.t += 250  # 500 s since creation, 250 s since the last call
    assert tc.get("/camofox/tabs/live").status_code == 200
    clock.t += 301
    r = tc.get("/camofox/tabs/live")
    assert r.status_code == 404
    assert "timed out" in r.json()["detail"]


def test_close_quits_the_driver_and_forgets_the_session(client):
    tc, _app, reg, _clock = client
    drv = FakeDriver()
    reg.add("live", drv, profile="u7-default")
    assert tc.post("/close", json={"sessionId": "live"}).status_code == 200
    assert drv.quit_calls == 1 and len(reg) == 0
    assert tc.get("/sessions").json() == {"items": []}


def test_boot_starts_websockify_and_the_reaper_unless_safe_mode_is_forced(client, monkeypatch):
    _tc, runner_app, _reg, _clock = client
    calls = []
    started = []
    monkeypatch.setattr(display, "ensure_websockify", lambda: calls.append("ws") or True)

    class T:
        def __init__(self, target=None, name=None, daemon=None):
            started.append((name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(runner_app.threading, "Thread", T)
    monkeypatch.setattr(runner_app, "_SAFE_MODE_FORCED", False)
    runner_app._boot()
    assert calls == ["ws"] and started == [("session-reaper", True)]
    monkeypatch.setattr(runner_app, "_SAFE_MODE_FORCED", True)
    runner_app._boot()
    assert calls == ["ws"]  # the preview instance shows no screen
