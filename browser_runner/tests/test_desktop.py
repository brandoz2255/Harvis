"""The optional full desktop on a headed screen.

Nothing here starts an X server. display.start is driven through a fake Popen,
and desktop.sh is run in its seed-only mode, which writes the Xfce config and
stops before Xvnc — that config is where the desktop's limits live (no
terminal, no applications menu, no desktop right-click menu).
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import display  # noqa: E402


class FakePopen:
    spawned: list = []

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.env = kw.get("env") or {}
        self.new_session = kw.get("start_new_session", False)
        self.pid = 4242 + len(FakePopen.spawned)
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
def fake_x(monkeypatch, tmp_path):
    FakePopen.spawned = []
    killed = []
    monkeypatch.setattr(display, "TOKEN_DIR", str(tmp_path / "tokens"))
    monkeypatch.setattr(display, "_DESKTOP_HOME_ROOT", str(tmp_path / "desktops"))
    monkeypatch.setattr(display.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(display, "_have", lambda name: True)
    monkeypatch.setattr(display, "_port_free", lambda port: True)
    monkeypatch.setattr(display, "_wait_for_x", lambda screen, proc: True)
    monkeypatch.setattr(display, "_websockify", None)

    def killpg(pid, sig):
        killed.append((pid, sig))
        for p in FakePopen.spawned:
            if p.pid == pid:
                p.rc = 0

    monkeypatch.setattr(display.os, "killpg", killpg)
    yield killed
    for sid in list(display._screens):
        display._screens.pop(sid, None)
    display._websockify = None


def _cmds():
    return [p.cmd[0] if p.cmd[0] != "bash" else os.path.basename(p.cmd[1]) for p in FakePopen.spawned]


def test_a_desktop_screen_runs_desktop_sh_instead_of_xvfb_and_x11vnc(fake_x):
    screen = display.start("s1", width=1440, height=900, desktop=True)
    assert screen is not None and screen.to_dict()["desktop"] is True
    assert "desktop.sh" in _cmds() and "Xvfb" not in _cmds() and "x11vnc" not in _cmds()
    dt = next(p for p in FakePopen.spawned if p.cmd[0] == "bash")
    assert dt.new_session, "desktop.sh must lead its own process group so stop() can reap all of it"
    assert dt.env["HARVIS_DT_DISPLAY_NUM"] == str(screen.display)
    assert dt.env["HARVIS_DT_RFB_PORT"] == str(screen.vnc_port)
    assert dt.env["HARVIS_DT_GEOMETRY"] == "1440x900"
    # The home dir is named for the session, never for the secret token.
    assert screen.token not in dt.env["HARVIS_DT_HOME"]
    # Same token file entry as a bare screen, so websockify cannot tell them apart.
    with open(os.path.join(display.TOKEN_DIR, "tokens"), encoding="utf-8") as fh:
        assert fh.read() == f"{screen.token}: 127.0.0.1:{screen.vnc_port}\n"


def test_without_the_packages_a_desktop_request_gets_a_bare_display(fake_x, monkeypatch):
    monkeypatch.setattr(display, "desktop_available", lambda: False)
    screen = display.start("s1", desktop=True)
    assert screen is not None and screen.to_dict()["desktop"] is False
    assert _cmds()[:2] == ["Xvfb", "x11vnc"]


def test_a_plain_headed_screen_is_unchanged(fake_x):
    screen = display.start("s1")
    assert screen.to_dict()["desktop"] is False
    assert "desktop.sh" not in _cmds()


def test_stopping_a_desktop_kills_its_whole_process_group(fake_x):
    screen = display.start("s1", desktop=True)
    dt = screen.desktop
    display.stop("s1")
    assert fake_x and fake_x[0][0] == dt.pid
    assert display.get("s1") is None


def test_desktop_available_needs_the_script_and_every_binary(monkeypatch):
    monkeypatch.setattr(display, "_have", lambda name: name != "xfwm4")
    assert display.desktop_available() is False
    monkeypatch.setattr(display, "_have", lambda name: True)
    assert display.desktop_available() is os.path.isfile(display.DESKTOP_SCRIPT)


# ── what the desktop offers ──────────────────────────────────────────────────

@pytest.fixture
def seeded(tmp_path):
    env = {**os.environ, "HARVIS_DT_DISPLAY_NUM": "199", "HARVIS_DT_RFB_PORT": "5999",
           "HARVIS_DT_HOME": str(tmp_path), "HARVIS_DT_SEED_ONLY": "1"}
    subprocess.run(["bash", os.path.join(HERE, "desktop.sh")], env=env, check=True, timeout=30)
    return tmp_path / "config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"


def test_the_panel_has_windows_and_a_clock_and_nothing_to_launch(seeded):
    panel = (seeded / "xfce4-panel.xml").read_text()
    assert 'value="tasklist"' in panel and 'value="clock"' in panel
    assert "applicationsmenu" not in panel and "launcher" not in panel


def test_the_desktop_right_click_menus_are_off(seeded):
    desk = (seeded / "xfce4-desktop.xml").read_text()
    assert '<property name="desktop-menu" type="empty">\n    <property name="show" type="bool" value="false"/>' in desk
    assert '<property name="windowlist-menu" type="empty">\n    <property name="show" type="bool" value="false"/>' in desk


def test_the_image_installs_no_terminal():
    # A shell on a screen anyone can take over runs as `runner`, which reads
    # every teammate's Firefox profile under /profiles.
    with open(os.path.join(HERE, "Dockerfile"), encoding="utf-8") as fh:
        installs = [ln.strip() for ln in fh if ln.strip().rstrip(" \\") in (
            "xfce4-terminal", "xterm", "lxterminal", "xfce4-session", "xfce4")]
    assert installs == []
