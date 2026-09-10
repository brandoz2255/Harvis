"""The observation surface, the profile path, and the takeover lock.

These are the three places in the browser runner where a mistake is not a
crash but a quiet wrong answer:

* a snapshot that stamps refs the agent cannot act on, or leaks the whole page,
* a profile key that escapes the profiles volume,
* an acting endpoint that still works while the user has the wheel.

Nothing here starts a browser. The snapshot script is checked as the contract
it is (what it stamps, what it caps, what it returns), and the endpoints are
checked through a fake driver, so the suite runs anywhere fastapi is installed.

Where to run it: the browser-runner image does not carry pytest (the size
budget for that image is tight), so run it in the backend container, which has
fastapi and pytest and no selenium:

    docker cp browser_runner harvis-backend:/tmp/br
    docker exec harvis-backend python -m pytest /tmp/br/tests -q
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import display  # noqa: E402

camofox_api = pytest.importorskip(
    "camofox_api", reason="needs fastapi; run in a container that has it"
)
from fastapi import HTTPException  # noqa: E402


# ── the snapshot contract ────────────────────────────────────────────────────

JS = camofox_api._SNAPSHOT_JS


def test_snapshot_clears_old_refs_before_stamping_new_ones():
    # A stale ref left on the page is worse than no ref: the agent would act on
    # whatever still carried the old attribute.
    clear = JS.index("removeAttribute('data-harvis-ref')")
    stamp = JS.index("setAttribute('data-harvis-ref'")
    assert clear < stamp


def test_snapshot_returns_the_four_keys_the_agent_reads():
    tail = JS[JS.rindex("return {"):]
    for key in ("url:", "title:", "text:", "refs:", "truncated:"):
        assert key in tail, key


def test_snapshot_selects_the_things_a_person_can_act_on():
    for sel in ("a[href]", "button", "input", "select", "textarea", "[role=button]"):
        assert sel in JS, sel


def test_snapshot_skips_invisible_elements():
    # An agent that clicks a zero-size or display:none element reports success
    # and changes nothing, which is the hardest failure to notice.
    assert "visibility" in JS and "display" in JS and "getBoundingClientRect" in JS
    assert "if (!visible(el)) continue;" in JS


def test_snapshot_caps_refs_and_page_text():
    # Both caps exist so one enormous page cannot blow the model's context.
    assert "n < MAX" in JS
    assert re.search(r"innerText\s*:\s*''\)\.slice\(0,\s*20000\)", JS)


def test_snapshot_reports_truncation_rather_than_lying():
    assert "truncated: nodes.length > n" in JS


def test_snapshot_records_what_a_hard_limit_check_needs():
    # hard_limits.classify reads role, name, href, type and autocomplete to tell
    # a sign-in button from an ordinary one. If the snapshot stops carrying any
    # of them the gate silently gets blinder, so pin them here.
    for field in ("role:", "entry.href", "entry.type", "entry.autocomplete", "entry.field"):
        assert field in JS, field


def test_snapshot_prefers_an_accessible_name():
    assert "aria-label" in JS and "aria-labelledby" in JS and "label[for=" in JS


def test_snapshot_escapes_an_id_before_building_a_selector():
    # An id like `a"]` would otherwise break out of the label selector.
    assert "CSS.escape" in JS


def test_refs_summary_is_one_readable_line_per_ref():
    snap = {"refs": {"ref_1": {"role": "button", "name": "Confirm and pay"},
                     "ref_2": {"role": "link"}}}
    lines = camofox_api.refs_summary(snap)
    assert lines == ["ref_1: button 'Confirm and pay'", "ref_2: link"]


def test_refs_summary_survives_a_snapshot_with_no_refs():
    assert camofox_api.refs_summary({}) == []


# ── the profile path ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "key",
    ["../etc", "a/b", "/abs", "..", ".", "a\\b", "a b", "agent:1", "", "   ",
     "x" * 65, "café", "a\x00b"],
)
def test_a_profile_key_that_is_not_a_plain_name_is_refused(key):
    assert not display.profile_key_ok(key)
    with pytest.raises(display.BadProfileKey):
        display.profile_dir(key, create=False)


@pytest.mark.parametrize("key", ["scout", "agent-1", "a_b", "abc123", "SCOUT"])
def test_an_ordinary_profile_key_is_accepted(key):
    assert display.profile_key_ok(key)


def test_a_profile_key_is_lowercased_so_two_spellings_share_one_profile():
    # Otherwise "Scout" and "scout" would be two logged-out browsers on a
    # case-sensitive filesystem and one shared browser on a case-insensitive one.
    assert display.profile_dir("SCOUT", create=False) == display.profile_dir("scout", create=False)


def test_a_profile_dir_stays_under_the_profiles_root():
    path = display.profile_dir("scout", create=False)
    assert os.path.dirname(path) == display.PROFILE_ROOT


def test_clean_profile_locks_removes_a_dead_firefox_lock(tmp_path):
    (tmp_path / ".parentlock").write_text("")
    (tmp_path / "lock").write_text("")
    (tmp_path / "prefs.js").write_text("keep me")
    display.clean_profile_locks(str(tmp_path))
    assert not (tmp_path / ".parentlock").exists()
    assert not (tmp_path / "lock").exists()
    assert (tmp_path / "prefs.js").read_text() == "keep me"


def test_clean_profile_locks_is_quiet_when_there_is_nothing_to_clean(tmp_path):
    display.clean_profile_locks(str(tmp_path))  # must not raise


# ── the takeover lock ────────────────────────────────────────────────────────

class FakeElement:
    """A stamped element, as far as the endpoints are concerned."""

    def __init__(self, ref):
        self.ref = ref
        self.clicked = False
        self.typed = []

    def click(self):
        self.clicked = True

    def clear(self):
        self.typed.clear()

    def send_keys(self, value):
        self.typed.append(value)


class FakeDriver:
    """Just enough driver for the endpoints that never touch a real page."""

    current_url = "https://example.test/page"
    title = "Page"

    def get(self, url):
        self.navigated_to = url

    def __init__(self, present_refs=()):
        self.navigated_to = None
        self.present_refs = set(present_refs)

    def execute_script(self, script, *args):
        # Only the ref lookup starts with a bare return; the snapshot script is
        # a whole program, and scrollIntoView takes an element, not a ref.
        if script.startswith("return document.querySelector("):
            ref = args[0] if args else None
            return FakeElement(ref) if ref in self.present_refs else None
        return {"url": self.current_url, "title": self.title, "text": "", "refs": {}}


@pytest.fixture
def driver(monkeypatch):
    d = FakeDriver()
    camofox_api.set_driver_provider(lambda _tab: d)
    yield d
    camofox_api.set_driver_provider(None)


@pytest.fixture
def taken_over():
    display.start  # noqa: B018 - documents the dependency
    screen = display.Screen("tab-1", 100, 5900, 1280, 800)
    screen.taken_over = True
    display._screens["tab-1"] = screen
    yield screen
    display._screens.pop("tab-1", None)


def test_acting_is_locked_out_while_the_user_has_the_wheel(driver, taken_over):
    with pytest.raises(HTTPException) as exc:
        camofox_api.navigate("tab-1", camofox_api.NavigateBody(url="https://x.test"))
    assert exc.value.status_code == 423
    assert driver.navigated_to is None


def test_looking_is_still_allowed_while_the_user_has_the_wheel(driver, taken_over):
    # The agent watching costs the user nothing and keeps the run coherent.
    snap = camofox_api.snapshot("tab-1")
    assert snap["url"] == driver.current_url


def test_handing_the_wheel_back_unlocks_acting(driver, taken_over):
    camofox_api.takeover("tab-1", camofox_api.TakeoverBody(taken=False))
    camofox_api.navigate("tab-1", camofox_api.NavigateBody(url="https://x.test"))
    assert driver.navigated_to == "https://x.test"


def test_takeover_on_a_session_with_no_screen_is_a_404(driver):
    with pytest.raises(HTTPException) as exc:
        camofox_api.takeover("no-such-tab", camofox_api.TakeoverBody(taken=True))
    assert exc.value.status_code == 404


def test_a_ref_the_snapshot_did_stamp_is_found(driver):
    driver.present_refs.add("ref_3")
    result = camofox_api.click("tab-1", camofox_api.RefBody(ref="ref_3"))
    assert result["ok"] is True


def test_a_stale_ref_fails_loudly_instead_of_hitting_whatever_moved_there(driver):
    with pytest.raises(HTTPException) as exc:
        camofox_api.click("tab-1", camofox_api.RefBody(ref="ref_9"))
    assert exc.value.status_code == 409


def test_a_ref_that_is_not_a_ref_is_rejected_before_it_reaches_a_selector(driver):
    for bad in ("", "12", '"] , [x', "ref"):
        with pytest.raises(HTTPException) as exc:
            camofox_api.click("tab-1", camofox_api.RefBody(ref=bad))
        assert exc.value.status_code == 400, bad


def test_no_driver_provider_is_a_503_not_a_crash():
    camofox_api.set_driver_provider(None)
    with pytest.raises(HTTPException) as exc:
        camofox_api.snapshot("tab-1")
    assert exc.value.status_code == 503


# ── the screen ───────────────────────────────────────────────────────────────

def test_a_screen_token_is_per_session_and_not_derived_from_the_id():
    a = display.Screen("same-id", 100, 5900, 1280, 800)
    b = display.Screen("same-id", 101, 5901, 1280, 800)
    assert a.token != b.token
    assert len(a.token) == 32 and re.fullmatch(r"[0-9a-f]{32}", a.token)


def test_a_screen_reports_its_display_and_never_a_password():
    screen = display.Screen("s", 100, 5900, 1280, 800)
    assert screen.display_name == ":100"
    assert screen.env() == {"DISPLAY": ":100"}
    assert "password" not in screen.to_dict()


def test_the_token_file_maps_each_live_screen_to_its_own_loopback_port(tmp_path, monkeypatch):
    monkeypatch.setattr(display, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(display, "_screens", {})
    one = display.Screen("a", 100, 5900, 1280, 800)
    two = display.Screen("b", 101, 5901, 1280, 800)
    display._screens.update({"a": one, "b": two})
    display._write_tokens_locked()
    written = (tmp_path / "tokens").read_text().splitlines()
    assert f"{one.token}: 127.0.0.1:5900" in written
    assert f"{two.token}: 127.0.0.1:5901" in written


def test_a_removed_screens_token_stops_working_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(display, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(display, "_screens", {})
    gone = display.Screen("a", 100, 5900, 1280, 800)
    display._screens["a"] = gone
    display._write_tokens_locked()
    display._screens.pop("a")
    display._write_tokens_locked()
    assert gone.token not in (tmp_path / "tokens").read_text()


class FakeProc:
    def poll(self):
        return None

    def send_signal(self, _sig):
        pass

    def wait(self, timeout=None):
        return 0


def _start_one_screen(monkeypatch, tmp_path):
    """Run display.start() with every subprocess faked; return the argv seen."""
    calls = []
    monkeypatch.setattr(display, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(display, "_screens", {})
    monkeypatch.setattr(display, "_have", lambda _b: True)
    monkeypatch.setattr(display, "_port_free", lambda _p: True)
    monkeypatch.setattr(display, "_ensure_websockify_locked", lambda: None)
    monkeypatch.setattr(os.path, "exists", lambda _p: True)
    monkeypatch.setattr(
        display.subprocess, "Popen", lambda cmd, **_k: calls.append(cmd) or FakeProc()
    )
    screen = display.start("tab-x")
    return screen, calls


def test_the_x11vnc_command_never_listens_beyond_this_container(monkeypatch, tmp_path):
    # -localhost keeps the VNC port inside the container, so the websockify
    # token is genuinely the only way in. Losing that flag would put an
    # unauthenticated screen on the Docker network for anything that can reach
    # browser-runner.
    screen, calls = _start_one_screen(monkeypatch, tmp_path)
    assert screen is not None
    vnc = next(c for c in calls if c[0] == "x11vnc")
    assert "-localhost" in vnc
    assert "-nopw" in vnc
    assert str(screen.vnc_port) in vnc


def test_xvfb_gets_its_own_display_and_no_tcp_listener(monkeypatch, tmp_path):
    _screen, calls = _start_one_screen(monkeypatch, tmp_path)
    xvfb = next(c for c in calls if c[0] == "Xvfb")
    assert "-nolisten" in xvfb and "tcp" in xvfb


def test_starting_a_screen_publishes_exactly_one_token(monkeypatch, tmp_path):
    screen, _calls = _start_one_screen(monkeypatch, tmp_path)
    written = (tmp_path / "tokens").read_text().splitlines()
    assert written == [f"{screen.token}: 127.0.0.1:{screen.vnc_port}"]


def test_asking_twice_for_one_sessions_screen_returns_the_same_screen(monkeypatch, tmp_path):
    screen, _calls = _start_one_screen(monkeypatch, tmp_path)
    assert display.start("tab-x") is screen


def test_display_degrades_instead_of_failing_when_xvfb_is_missing(monkeypatch):
    monkeypatch.setattr(display, "_have", lambda _b: False)
    assert display.available() is False
    assert display.start("some-session") is None
