"""Chunk offsets and page numbers: every chunk says where in the stored text it came from,
and the page it starts on. No database, model server or network."""
import asyncio
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import ingestion  # noqa: E402
from notebooks.models import SourceStatus, SourceType  # noqa: E402

SRC = SimpleNamespace(title="S")


def chunker():
    return ingestion.IngestionService(None)


def paragraphs(n, filler="mitochondria are the powerhouse of the cell. ", reps=12):
    return "\n\n".join(f"Paragraph {i}: " + filler * reps for i in range(n))


def squash(s):
    return " ".join(s.split())


def test_page_of_uses_the_last_start_at_or_before_the_offset():
    starts = [0, 100, 250]
    assert [ingestion.page_of(o, starts) for o in (0, 99, 100, 249, 250, 9999)] == [1, 1, 2, 2, 3, 3]
    assert ingestion.page_of(5, None) is None and ingestion.page_of(5, []) is None
    assert ingestion.page_of(0, [10, 20]) == 1  # before the first marker still counts as page 1


def test_paragraph_chunks_point_back_into_the_text():
    text = paragraphs(8)
    chunks = chunker()._chunk_text(text, SRC)
    assert len(chunks) > 1
    for chunk, meta in chunks:
        s, e = meta["start_char"], meta["end_char"]
        assert 0 <= s < e <= len(text)
        # The source slice is the chunk text, except that paragraph joins are normalised to a blank line.
        assert squash(text[s:e]) == squash(chunk)
        assert "page" not in meta


def test_offsets_survive_leading_whitespace_and_overlap():
    text = "   \n\n" + paragraphs(8)
    chunks = chunker()._chunk_text(text, SRC)
    previous_end = 0
    for chunk, meta in chunks:
        s, e = meta["start_char"], meta["end_char"]
        assert text[s:e].startswith("Paragraph") or text[s:e][0].isalpha()
        assert squash(text[s:e]) == squash(chunk)
        previous_end = e
    # Consecutive chunks overlap, so a later chunk starts before the earlier one ends.
    assert chunks[1][1]["start_char"] < chunks[0][1]["end_char"]
    assert previous_end <= len(text)


def test_chunk_text_is_what_it_was_before_offsets_existed():
    text = paragraphs(8)
    chunks = chunker()._chunk_text(text, SRC)
    assert all(len(c) <= ingestion.CHUNK_SIZE + ingestion.CHUNK_OVERLAP + 200 for c, _m in chunks)
    # The tuple shape owui_compat relies on: (chunk text, metadata dict with the title).
    assert all(isinstance(c, str) and m["source_title"] == "S" and m["paragraphs"] for c, m in chunks)
    # Together the chunks cover the whole text.
    assert chunks[0][1]["start_char"] == 0 and chunks[-1][1]["end_char"] == len(text.rstrip())


def test_sentence_mode_offsets_for_a_single_long_paragraph():
    sentence = "Ribosomes assemble proteins from amino acids inside every living cell."
    text = "  " + " ".join(f"{sentence[:-1]} number {i}." for i in range(120))
    chunks = chunker()._chunk_text(text, SRC)
    assert len(chunks) > 2 and "sentence_indices" in chunks[0][1]
    for chunk, meta in chunks:
        s, e = meta["start_char"], meta["end_char"]
        assert squash(text[s:e]) == squash(chunk)
        assert len(chunk) <= ingestion.CHUNK_SIZE + 100
    assert chunks[0][1]["start_char"] == 2
    # The overlap carries the last sentences forward, never an absolute-index slip.
    for (_a, first), (_b, second) in zip(chunks, chunks[1:]):
        assert second["start_char"] < first["end_char"]
        assert second["start_char"] > first["start_char"]


def test_sentence_overlap_never_swallows_a_whole_chunk():
    # One enormous sentence tail must not be carried forward if it is more than half a chunk.
    huge = "x" * 700 + "."
    text = ". ".join([huge] * 6) + "."
    chunks = chunker()._chunk_by_sentences(text, SRC)
    assert len(chunks) >= 3
    assert all(len(c) <= ingestion.CHUNK_SIZE for c, _m in chunks)


def test_pages_come_from_page_starts():
    text = paragraphs(8)
    marks = [0, len(text) // 3, 2 * len(text) // 3]
    chunks = chunker()._chunk_text(text, SRC, marks)
    for _c, meta in chunks:
        expected = 1 + sum(1 for m in marks[1:] if m <= meta["start_char"])
        assert meta["page"] == expected
    assert {m["page"] for _c, m in chunks} == {1, 2, 3}


def test_sentence_mode_chunks_carry_pages_too():
    text = " ".join(f"Sentence number {i} is about enzymes and how they work." for i in range(100))
    chunks = chunker()._chunk_text(text, SRC, [0, len(text) // 2])
    assert {m["page"] for _c, m in chunks} == {1, 2}


def test_blank_text_makes_no_chunks():
    assert chunker()._chunk_text("   \n\n  ", SRC) == []


# --- through the pipeline ----------------------------------------------------------------


class Conn:
    def __init__(self, mgr):
        self.mgr = mgr

    async def execute(self, sql, *args):
        self.mgr.executed.append((sql, args))

    async def fetchval(self, sql, *args):
        return None


class Acquire:
    def __init__(self, mgr):
        self.mgr = mgr

    async def __aenter__(self):
        return Conn(self.mgr)

    async def __aexit__(self, *a):
        return False


class Manager:
    def __init__(self, source):
        self.source = source
        self.statuses, self.executed, self.chunks = [], [], []
        self.db_pool = SimpleNamespace(acquire=lambda: Acquire(self))

    async def get_source(self, sid, uid):
        return self.source

    async def update_source_status(self, sid, status, error_message=None, metadata_update=None):
        self.statuses.append((status, error_message, metadata_update))

    async def clear_chunks(self, sid):
        pass

    async def create_chunks(self, sid, nid, chunks):
        self.chunks = chunks
        return len(chunks)


def source_for(tmp_path, text):
    f = tmp_path / "s.txt"
    f.write_text(text)
    return SimpleNamespace(
        id=uuid4(), notebook_id=uuid4(), type=SourceType.TEXT, title="S", storage_path=str(f), metadata={"extension": "txt"}
    )


def run_ingest(mgr):
    svc = ingestion.IngestionService(mgr)

    async def ok(text):
        return [0.1] * 8

    svc._get_embedding = ok
    asyncio.run(svc.ingest_source(mgr.source.id, 1))


def test_ready_metadata_is_written_and_offsets_match_content_text(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS", "0")
    text = paragraphs(8)
    mgr = Manager(source_for(tmp_path, text))
    run_ingest(mgr)
    status, _err, meta = mgr.statuses[-1]
    assert status == SourceStatus.READY
    stored = next(args[0] for sql, args in mgr.executed if "content_text" in sql)
    assert stored == text
    assert meta["chunk_count"] == len(mgr.chunks) and meta["text_length"] == len(text)
    assert meta["embedding_dim"] == 8 and meta["insights_status"] is None and meta["page_starts"] is None
    for chunk, _vec, cmeta, _i in mgr.chunks:
        assert squash(stored[cmeta["start_char"]:cmeta["end_char"]]) == squash(chunk)


def test_a_very_long_source_is_cut_and_the_user_is_told(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS", "0")
    monkeypatch.setenv("NOTEBOOK_MAX_SOURCE_CHARS", "10000")
    mgr = Manager(source_for(tmp_path, paragraphs(40)))
    run_ingest(mgr)
    status, _err, meta = mgr.statuses[-1]
    assert status == SourceStatus.READY
    assert meta["text_length"] == 10000 and meta["text_truncated_from"] > 10000
    assert "10,000" in meta["ingest_notice"]
    assert max(c[2]["end_char"] for c in mgr.chunks) <= 10000


def test_insights_are_marked_pending_only_when_they_will_run(tmp_path, monkeypatch):
    from notebooks import auto_insights

    scheduled = []
    monkeypatch.setattr(auto_insights, "schedule_default_insights", lambda *a: scheduled.append(a) or True)
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS", "1")
    mgr = Manager(source_for(tmp_path, paragraphs(8)))
    run_ingest(mgr)
    assert mgr.statuses[-1][2]["insights_status"] == "pending" and len(scheduled) == 1

    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS_MAX_CHARS", "1000")
    scheduled.clear()
    mgr = Manager(source_for(tmp_path, paragraphs(8)))
    run_ingest(mgr)
    assert mgr.statuses[-1][2]["insights_status"] is None and scheduled == []


def test_scheduling_insights_never_raises(monkeypatch):
    from notebooks import auto_insights

    def boom():
        raise RuntimeError("no event loop")

    monkeypatch.setattr(asyncio, "get_running_loop", boom)
    assert auto_insights.schedule_default_insights(None, uuid4(), 1) is False
