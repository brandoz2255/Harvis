"""A chat's sandbox works as the agent's own computer: the user's uploads are copied
into it, a binary upload is never pasted as decoded garbage, and a file chat cannot
show whole (a pcap, an archive, a long log) starts an agent run in the box.

    python -m pytest tests/test_own_box.py -q
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import file_content  # noqa: E402
from plugins.hermes_ui import attachments, sandbox  # noqa: E402

PCAP = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1) + b"\x00" * 40


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path / "sandboxes"))
    monkeypatch.delenv("HARVIS_SANDBOX_ENABLED", raising=False)
    return tmp_path


# ─── binary detection and the chat paste ─────────────────────────────────────

@pytest.mark.parametrize("raw, binary", [
    (PCAP, True),
    (b"PK\x03\x04\x14\x00" + bytes(range(256)), True),
    (b"plain log line\n" * 50, False),
    ("café ✓\n".encode() * 20, False),
    (("x" * 8190 + "é").encode(), False),     # a multibyte char cut at the 8 KB sample edge
    (b"\xff\xfe\xfa" + b"a" * 100, True),
])
def test_looks_binary(raw, binary):
    assert file_content.looks_binary(raw) is binary


def test_a_binary_upload_is_described_not_decoded():
    text = file_content.render_text("capture.pcap", PCAP)
    assert "binary" in text and "/workspace/uploads/" in text
    assert "�" not in text and "\x00" not in text


def test_text_uploads_still_paste_as_before():
    assert file_content.render_text("memo.txt", b"hello\n") == "### Attached file: memo.txt\nhello\n"


def test_needs_box(tmp_path):
    def f(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return str(p)
    assert file_content.needs_box("capture.pcap", "application/vnd.tcpdump.pcap", f("capture.pcap", PCAP))
    assert file_content.needs_box("firmware.bin", "", f("firmware.bin", b"\x7fELF\x00\x01" * 10))
    big = ("10.0.0.1 - - GET /login 401\n" * 2000).encode()
    assert file_content.needs_box("access.log", "text/plain", f("access.log", big))
    assert not file_content.needs_box("notes.txt", "text/plain", f("notes.txt", b"short\n"))
    # Documents and pictures have their own readers; chat handles them.
    assert not file_content.needs_box("paper.pdf", "application/pdf", f("paper.pdf", b"%PDF-1.4\x00\x01"))
    assert not file_content.needs_box("gone.bin", "", str(tmp_path / "missing"))


# ─── uploads land in the box ─────────────────────────────────────────────────

def test_uploads_are_copied_into_the_box_once(tmp_path, root):
    src = tmp_path / "abc123.pcap"
    src.write_bytes(PCAP)
    staged = sandbox.stage_uploads(7, "sess-1", [("capture.pcap", str(src))])
    assert staged == ["/workspace/uploads/capture.pcap"]
    real = os.path.join(sandbox.session_dir(7, "sess-1"), "uploads", "capture.pcap")
    assert open(real, "rb").read() == PCAP
    # The same file on the next turn is not copied again.
    assert sandbox.stage_uploads(7, "sess-1", [("capture.pcap", str(src))]) == staged
    assert os.listdir(os.path.dirname(real)) == ["capture.pcap"]


def test_a_different_file_with_the_same_name_is_kept_beside_it(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    sandbox.stage_uploads(7, "sess-1", [("log.txt", str(a))])
    assert sandbox.stage_uploads(7, "sess-1", [("log.txt", str(b))]) == ["/workspace/uploads/log-2.txt"]


@pytest.mark.parametrize("name, safe", [
    ("../../etc/passwd", "passwd"),
    ("..", "upload"),
    (".bashrc", "bashrc"),
    ("my report (final).zip", "my_report_final_.zip"),
])
def test_upload_names_cannot_leave_the_uploads_folder(tmp_path, name, safe):
    src = tmp_path / "src"
    src.write_bytes(b"x")
    assert sandbox.stage_uploads(7, "sess-1", [(name, str(src))]) == [f"/workspace/uploads/{safe}"]


def test_the_agent_is_told_it_owns_the_box():
    guide = sandbox.workspace_guide(7, "sess-1")
    assert "your own computer" in guide and "/workspace/uploads/" in guide
    assert "no root/sudo" not in guide


def test_latest_turn_file_ids_are_only_the_newest_message():
    msgs = [{"role": "user", "content": "a", "attachments": [{"id": "old"}]},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "b", "attachments": [{"id": "new"}, {"name": "no id"}]}]
    assert attachments.latest_turn_file_ids(msgs) == ["new"]
    assert attachments.latest_turn_file_ids(msgs[:2] + [{"role": "user", "content": "thanks"}]) == []


# ─── the bridge: which turns start a run, and what the run is handed ─────────

class _Pool:
    """owui_files rows keyed by id; each row belongs to one user."""

    def __init__(self, rows):
        self.rows = rows

    @asynccontextmanager
    async def acquire(self):
        rows = self.rows

        class Conn:
            async def fetch(self, sql, ids, uid):
                return [r for i, r in rows.items() if i in ids and r["_uid"] == uid]

        yield Conn()


def _rows(tmp_path):
    pcap, note = tmp_path / "f-pcap", tmp_path / "f-note"
    pcap.write_bytes(PCAP)
    note.write_bytes(b"remember the milk\n")
    return {
        "p1": {"filename": "capture.pcap", "path": str(pcap), "content_type": "", "_uid": 7},
        "t1": {"filename": "note.txt", "path": str(note), "content_type": "text/plain", "_uid": 7},
        "x1": {"filename": "theirs.pcap", "path": str(pcap), "content_type": "", "_uid": 8},
    }


def _request(rows):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=_Pool(rows))))


def _body(new_ids, all_ids=("p1", "t1")):
    return {"harvis_sandbox_session": "sess-1", "harvis_turn_file_ids": list(new_ids),
            "files": [{"type": "file", "id": i} for i in all_ids]}


def test_a_new_pcap_needs_the_box_but_an_old_one_does_not(tmp_path):
    from owui_compat.workspace_bridge import _box_attachments
    req, user = _request(_rows(tmp_path)), {"id": 7}
    assert [n for n, _ in asyncio.run(_box_attachments(req, _body(["p1"]), user))] == ["capture.pcap"]
    assert asyncio.run(_box_attachments(req, _body([]), user)) == []          # "thanks" after the pcap
    assert asyncio.run(_box_attachments(req, _body(["t1"]), user)) == []      # small text: chat reads it
    assert asyncio.run(_box_attachments(req, _body(["x1"]), user)) == []      # another user's file id


def test_no_sandbox_means_no_forced_run(tmp_path, monkeypatch):
    from owui_compat.workspace_bridge import _box_attachments
    req, user = _request(_rows(tmp_path)), {"id": 7}
    body = _body(["p1"])
    assert asyncio.run(_box_attachments(req, {**body, "harvis_sandbox_session": None}, user)) == []
    monkeypatch.setenv("HARVIS_SANDBOX_ENABLED", "false")
    assert asyncio.run(_box_attachments(req, body, user)) == []


def test_the_run_is_handed_every_chat_upload_in_its_box(tmp_path):
    from owui_compat.workspace_bridge import _sandbox_with_uploads
    box = asyncio.run(_sandbox_with_uploads(_Pool(_rows(tmp_path)), _body(["p1"], ("p1", "t1", "x1")), 7))
    assert "/workspace/uploads/capture.pcap" in box["note"]
    assert "/workspace/uploads/note.txt" in box["note"]
    assert "theirs.pcap" not in box["note"]
    uploads = os.path.join(box["workspace_path"], "uploads")
    assert sorted(os.listdir(uploads)) == ["capture.pcap", "note.txt"]
