"""Notebook source ingestion: file typing, HTML stripping, and honest failure.

No database, model server or network: the manager is a recording fake and the
embedder, STT and fetcher are replaced where a test needs them.
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import extractors, ingestion  # noqa: E402
from notebooks.models import SourceStatus, SourceType  # noqa: E402
from notebooks.source_types import UnsupportedFile, classify_upload, html_to_text, looks_like_html  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("a.png", SourceType.IMAGE),
        ("a.JPG", SourceType.IMAGE),
        ("a.jpeg", SourceType.IMAGE),
        ("a.webp", SourceType.IMAGE),
        ("a.gif", SourceType.IMAGE),
        ("a.mp3", SourceType.AUDIO),
        ("a.wav", SourceType.AUDIO),
        ("a.m4a", SourceType.AUDIO),
        ("a.ogg", SourceType.AUDIO),
        ("a.webm", SourceType.AUDIO),
        ("a.pdf", SourceType.PDF),
        ("a.docx", SourceType.DOC),
        ("a.md", SourceType.MARKDOWN),
        ("a.html", SourceType.TEXT),
    ],
)
def test_upload_types(name, kind):
    assert classify_upload(name)[0] == kind


def test_unknown_extension_is_text_only_when_the_bytes_are_text():
    assert classify_upload("notes.weird", b"hello there")[0] == SourceType.TEXT
    with pytest.raises(UnsupportedFile) as err:
        classify_upload("thing.exe", b"MZ\x00\x01\x02binary")
    assert ".exe" in str(err.value) and "PDF" in str(err.value)


def test_html_loses_its_tags():
    page = (
        "<!doctype html><html><head><title>t</title><style>p{color:red}</style><script>var x=1;</script></head>"
        "<body><nav>menu</nav><main><h1>Photosynthesis</h1><p>Plants turn light into sugar using chlorophyll, "
        "carbon dioxide and water in their leaves every day.</p></main></body></html>"
    )
    assert looks_like_html(page)
    out = html_to_text(page)
    assert "Photosynthesis" in out and "chlorophyll" in out
    assert "<" not in out and "var x" not in out and "color:red" not in out


def test_html_file_upload_is_read_as_text(tmp_path):
    f = tmp_path / "p.html"
    f.write_text("<html><body><article><p>" + "The quick brown fox jumps over the lazy dog. " * 3 + "</p></article></body></html>")
    out = run(extractors.extract_text_file(str(f), "html"))
    assert "quick brown fox" in out and "<p>" not in out


def test_plain_text_in_latin1_still_reads(tmp_path):
    f = tmp_path / "n.txt"
    f.write_bytes("caf\xe9 au lait".encode("latin-1"))
    assert "caf" in run(extractors.extract_text_file(str(f), "txt"))


def test_image_with_nothing_readable_fails_with_advice(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG")
    monkeypatch.setattr(extractors.shutil, "which", lambda name: None)
    import vison_models.llm_connector as vc

    monkeypatch.setattr(vc, "query_vision", lambda *a, **k: vc.VISION_ERROR_PREFIX + " no model")
    with pytest.raises(extractors.IngestionError) as err:
        run(extractors.extract_image(str(img)))
    assert "vision model" in str(err.value)


def test_audio_is_transcribed_through_the_stt_provider(tmp_path, monkeypatch):
    import transcription

    clip = tmp_path / "a.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(transcription, "status", lambda: {"server_transcribes": True})
    monkeypatch.setattr(transcription, "transcribe", lambda path, **k: {"text": "Hello from the recording, this is a test."})
    monkeypatch.setattr(extractors.shutil, "which", lambda name: None)  # skip ffmpeg
    assert "recording" in run(extractors.extract_audio(str(clip)))


def test_audio_without_stt_says_so(tmp_path, monkeypatch):
    import transcription

    clip = tmp_path / "a.mp3"
    clip.write_bytes(b"x")
    monkeypatch.setattr(transcription, "status", lambda: {"server_transcribes": False})
    with pytest.raises(extractors.IngestionError) as err:
        run(extractors.extract_audio(str(clip)))
    assert "speech-to-text" in str(err.value)


def test_silent_audio_is_an_error(tmp_path, monkeypatch):
    import transcription

    clip = tmp_path / "a.wav"
    clip.write_bytes(b"x")
    monkeypatch.setattr(transcription, "status", lambda: {"server_transcribes": True})
    monkeypatch.setattr(transcription, "transcribe", lambda path, **k: {"text": " "})
    monkeypatch.setattr(extractors.shutil, "which", lambda name: None)
    with pytest.raises(extractors.IngestionError):
        run(extractors.extract_audio(str(clip)))


def test_private_urls_are_refused_not_fetched(monkeypatch):
    import agent_reach.tools as reach

    async def refuse(url, **kw):
        raise reach.ReachBlocked("host resolves to a private address")

    monkeypatch.setattr(reach, "_safe_get", refuse)
    with pytest.raises(extractors.IngestionError) as err:
        run(extractors.extract_url("http://169.254.169.254/latest/meta-data"))
    assert "public web pages" in str(err.value)


# --- the pipeline ---------------------------------------------------------------


class FakeConn:
    def __init__(self, mgr):
        self.mgr = mgr

    async def execute(self, sql, *args):
        self.mgr.executed.append(sql)

    async def fetchval(self, sql, *args):
        return None


class FakeAcquire:
    def __init__(self, mgr):
        self.mgr = mgr

    async def __aenter__(self):
        return FakeConn(self.mgr)

    async def __aexit__(self, *a):
        return False


class FakeManager:
    def __init__(self, source):
        self.source = source
        self.statuses = []
        self.cleared = 0
        self.chunks = []
        self.executed = []
        self.db_pool = SimpleNamespace(acquire=lambda: FakeAcquire(self))

    async def get_source(self, sid, uid):
        return self.source

    async def update_source_status(self, sid, status, error_message=None, metadata_update=None):
        self.statuses.append((status, error_message, metadata_update))

    async def clear_chunks(self, sid):
        self.cleared += 1

    async def create_chunks(self, sid, nid, chunks):
        self.chunks = chunks
        return len(chunks)


def make_source(tmp_path, text):
    f = tmp_path / "s.txt"
    f.write_text(text)
    return SimpleNamespace(
        id=uuid4(), notebook_id=uuid4(), type=SourceType.TEXT, title="S", storage_path=str(f), metadata={"extension": "txt"}
    )


LONG = "\n\n".join(f"Paragraph {i}: " + "mitochondria are the powerhouse of the cell. " * 12 for i in range(8))


def ingest(mgr, embed):
    svc = ingestion.IngestionService(mgr)
    svc._get_embedding = embed
    run(svc.ingest_source(mgr.source.id, 1))


def test_embedding_failure_marks_the_source_error_not_ready(tmp_path):
    mgr = FakeManager(make_source(tmp_path, LONG))

    async def never(text):
        return None

    ingest(mgr, never)
    status, message, _ = mgr.statuses[-1]
    assert status == SourceStatus.ERROR
    assert "embedding model" in message and "Retry" in message
    assert mgr.chunks == []  # no zero vectors stored


def test_embedding_failure_gives_up_after_three_in_a_row(tmp_path):
    mgr = FakeManager(make_source(tmp_path, LONG))
    calls = []

    async def never(text):
        calls.append(1)
        return None

    ingest(mgr, never)
    assert len(calls) == ingestion.MAX_CONSECUTIVE_EMBED_FAILURES


def test_working_embedder_makes_it_ready_and_retry_clears_old_chunks(tmp_path):
    mgr = FakeManager(make_source(tmp_path, LONG))

    async def ok(text):
        return [0.1] * 768

    ingest(mgr, ok)
    ingest(mgr, ok)
    assert mgr.statuses[-1][0] == SourceStatus.READY
    assert mgr.cleared == 2
    assert all(len(vec) == 4096 for (_t, vec, _m, _i) in mgr.chunks)


def test_mostly_failed_embedding_is_an_error(tmp_path):
    mgr = FakeManager(make_source(tmp_path, LONG))
    n = {"i": 0}

    async def flaky(text):
        n["i"] += 1
        return [0.1] * 768 if n["i"] == 1 else None

    ingest(mgr, flaky)
    status, message, _ = mgr.statuses[-1]
    assert status == SourceStatus.ERROR and "passages" in message


def test_extraction_error_message_reaches_the_source(tmp_path):
    src = make_source(tmp_path, "x")
    src.type = SourceType.PDF
    src.storage_path = str(tmp_path / "gone.pdf")
    mgr = FakeManager(src)
    ingest(mgr, None)
    status, message, _ = mgr.statuses[-1]
    assert status == SourceStatus.ERROR and "upload it again" in message
