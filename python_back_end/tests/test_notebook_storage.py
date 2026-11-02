"""Notebook storage: hybrid retrieval, chat config, shares and the additive schema (no DB)."""
import asyncio
import functools
import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from asyncpg.exceptions import UndefinedColumnError

from notebooks import hybrid_search as hs
from notebooks import shares
from notebooks.manager import (
    NotebookAccessError,
    NotebookManager,
    NotebookNotFoundError,
    NotebookValidationError,
)

NB_DIR = Path(__file__).resolve().parent.parent / "notebooks"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def sync(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return run


class FakeConn:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def _match(self, sql):
        for needle, result in self.script:
            if needle in sql:
                if isinstance(result, Exception):
                    raise result
                return result
        return None

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self._match(sql) or []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self._match(sql)

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self._match(sql)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return self._match(sql)

    async def executemany(self, sql, records):
        self.calls.append((sql, records))


class FakePool:
    def __init__(self, script=()):
        self.conn = FakeConn(list(script))

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


def chunk_row(source, vector_score=None, text="x", cid=None):
    return {
        "id": cid or uuid4(), "source_id": source, "notebook_id": uuid4(), "content": text,
        "metadata": {"start_char": 0, "end_char": 1}, "chunk_index": 0, "created_at": NOW,
        "source_title": "T", "vector_score": vector_score,
    }


# ─── fusion helpers ───────────────────────────────────────────────────────────

def test_rrf_adds_reciprocal_ranks_across_legs():
    fused = hs.rrf_fuse(["a", "b"], ["b", "c"])
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)
    assert max(fused, key=fused.get) == "b"


def test_diversify_caps_a_source_at_sixty_percent_of_top_k():
    rows = [{"source_id": "s1", "n": i} for i in range(10)] + [{"source_id": "s2", "n": 99}] * 5
    out = hs.diversify(rows, 5, backfill=False)
    assert len(out) == 5
    assert sum(r["source_id"] == "s1" for r in out) == math.ceil(5 * 0.6) == 3


def test_diversify_backfills_when_other_sources_run_out():
    rows = [{"source_id": "only", "n": i} for i in range(10)]
    assert len(hs.diversify(rows, 5)) == 5
    assert len(hs.diversify(rows, 5, backfill=False)) == 3


def test_keyword_query_drops_stopwords_but_never_returns_empty():
    assert hs.keyword_query("what is the capital of France") == "capital France"
    assert hs.keyword_query("what is the") == "what is the"
    assert hs.keyword_query('the "exact phrase" -unwanted') == '"exact phrase" -unwanted'


# ─── hybrid_search ────────────────────────────────────────────────────────────

@sync
async def test_hybrid_fuses_both_legs_and_scopes_to_the_notebook():
    nb, s1, s2 = uuid4(), uuid4(), uuid4()
    both, vec_only, kw_only = chunk_row(s1, 0.9), chunk_row(s2, 0.8), chunk_row(s2, 0.1)
    pool = FakePool([
        ("<=> $1::vector\n    LIMIT", [both, vec_only]),
        ("websearch_to_tsquery", [{**both}, kw_only]),
    ])
    out = await hs.hybrid_search(pool, nb, "capital of France", [0.1, 0.2], top_k=3)

    assert [c.chunk.id for c in out][0] == both["id"]
    assert {c.chunk.id for c in out} == {both["id"], vec_only["id"], kw_only["id"]}
    assert out[0].score > out[1].score
    assert out[0].vector_score == 0.9
    kw = next(c for c in out if c.chunk.id == kw_only["id"])
    assert kw.vector_score == 0.1 and kw.source_title == "T"
    for sql, args in pool.conn.calls:
        assert "c.notebook_id = $2" in sql
        assert args[1] == nb


@sync
async def test_hybrid_without_an_embedding_is_keyword_only():
    pool = FakePool([("websearch_to_tsquery", [chunk_row(uuid4(), None)])])
    out = await hs.hybrid_search(pool, uuid4(), "alpha beta", None, top_k=5)
    assert len(out) == 1 and out[0].vector_score is None
    assert len(pool.conn.calls) == 1 and "websearch_to_tsquery" in pool.conn.calls[0][0]


@sync
async def test_hybrid_falls_back_to_vector_only_when_the_tsvector_column_is_missing():
    row = chunk_row(uuid4(), 0.7)
    pool = FakePool([("websearch_to_tsquery", UndefinedColumnError("content_tsv")), ("<=> $1::vector", [row])])
    out = await hs.hybrid_search(pool, uuid4(), "alpha", [0.1], top_k=5)
    assert [c.chunk.id for c in out] == [row["id"]]


@sync
async def test_hybrid_with_nothing_to_search_by_returns_nothing_without_querying():
    pool = FakePool()
    assert await hs.hybrid_search(pool, uuid4(), "   ", None) == []
    assert pool.conn.calls == []


@sync
async def test_hybrid_source_filter_never_widens_on_garbage_ids():
    pool = FakePool()
    assert await hs.hybrid_search(pool, uuid4(), "alpha", [0.1], source_ids=["not-a-uuid"]) == []
    assert pool.conn.calls == []

    keep = uuid4()
    pool = FakePool([("<=> $1::vector", [])])
    await hs.hybrid_search(pool, uuid4(), "alpha", [0.1], source_ids=["junk", str(keep)])
    assert pool.conn.calls[0][1][3] == [keep]


@sync
async def test_hybrid_caps_one_source_in_the_result():
    nb, big, small = uuid4(), uuid4(), uuid4()
    rows = [chunk_row(big, 0.9 - i / 100) for i in range(8)] + [chunk_row(small, 0.3)]
    pool = FakePool([("<=> $1::vector", rows)])
    out = await hs.hybrid_search(pool, nb, "alpha", [0.1], top_k=5)
    assert len(out) == 5
    assert sum(c.chunk.source_id == big for c in out) <= 4  # cap 3, plus at most backfill
    assert any(c.chunk.source_id == small for c in out)


@sync
async def test_nan_similarity_from_a_zero_vector_becomes_zero():
    pool = FakePool([("<=> $1::vector", [chunk_row(uuid4(), float("nan"))])])
    out = await hs.hybrid_search(pool, uuid4(), "alpha", [0.1])
    assert out[0].vector_score == 0.0


# ─── manager: access, search, chat config, shares ────────────────────────────

def manager(script=(), access="owner"):
    m = NotebookManager(FakePool(script))

    async def fake_access(notebook_id, user_id):
        return access

    m.get_notebook_access = fake_access
    return m


@sync
async def test_hybrid_search_refuses_a_caller_without_access():
    with pytest.raises(NotebookNotFoundError):
        await manager(access=None).search_chunks_hybrid(uuid4(), 1, "q", [0.1])


@sync
async def test_hybrid_search_allows_a_chat_only_share():
    row = chunk_row(uuid4(), 0.5)
    m = manager([("<=> $1::vector", [row])], access="chat_only")
    assert len(await m.search_chunks_hybrid(uuid4(), 2, "q", [0.1])) == 1


@sync
async def test_chat_config_roundtrip_reads_the_columns():
    m = manager([("chat_persona", {
        "chat_persona": "terse", "chat_style": "analyst", "chat_length": "shorter", "output_language": None,
    })])
    assert await m.get_chat_config(uuid4(), 1) == {
        "persona": "terse", "style": "analyst", "length": "shorter", "output_language": None,
    }


@pytest.mark.parametrize("fields", [
    {"style": "poet"}, {"length": "huge"}, {"persona": "x" * 2001}, {"output_language": "y" * 41},
    {"persona": 5}, {"colour": "red"},
])
@sync
async def test_set_chat_config_rejects_bad_values(fields):
    with pytest.raises(NotebookValidationError):
        await manager().set_chat_config(uuid4(), 1, **fields)


@sync
async def test_set_chat_config_writes_only_given_fields_and_clears_blanks():
    cfg = {"chat_persona": None, "chat_style": "custom", "chat_length": "default", "output_language": None}
    m = manager([("SELECT chat_persona", cfg)])
    nb = uuid4()
    await m.set_chat_config(nb, 1, style="custom", persona="   ", output_language="Spanish")
    sql, args = next(c for c in m.db_pool.conn.calls if c[0].lstrip().startswith("UPDATE"))
    assert "chat_style = $2" in sql and "chat_persona = $3" in sql and "output_language = $4" in sql
    assert "chat_length" not in sql
    assert args == (nb, "custom", None, "Spanish")


@pytest.mark.parametrize("role", ["editor", "viewer", "chat_only"])
@sync
async def test_set_chat_config_is_owner_only(role):
    with pytest.raises(NotebookAccessError):
        await manager(access=role).set_chat_config(uuid4(), 2, style="analyst")


@sync
async def test_owner_may_set_chat_config():
    cfg = {"chat_persona": None, "chat_style": "analyst", "chat_length": "default", "output_language": None}
    m = manager([("SELECT chat_persona", cfg)], access="owner")
    assert (await m.set_chat_config(uuid4(), 1, style="analyst"))["style"] == "analyst"


@sync
async def test_link_share_stores_only_the_hash_and_returns_the_token_once():
    nb = uuid4()
    row = {"id": uuid4(), "notebook_id": nb, "user_id": None, "role": "viewer", "created_by": 1,
           "created_at": NOW, "revoked_at": None}
    pool = FakePool([("INSERT INTO notebook_shares", row)])
    share = await shares.create_link_share(pool, nb, 1, "viewer")

    stored = pool.conn.calls[0][1][1]
    assert share["token"] and stored != share["token"]
    assert stored == hashlib.sha256(share["token"].encode()).hexdigest()
    assert len(share["token"]) >= 32 and share["kind"] == "link"


@sync
async def test_share_validation():
    pool = FakePool()
    with pytest.raises(ValueError):
        await shares.create_link_share(pool, uuid4(), 1, "admin")
    with pytest.raises(ValueError):
        await shares.create_user_share(pool, uuid4(), 1, 1, "viewer")  # owner onto themselves
    assert pool.conn.calls == []


@sync
async def test_manager_share_calls_prove_ownership_first():
    m = NotebookManager(FakePool())

    async def not_owner(notebook_id, user_id):
        raise NotebookNotFoundError("nope")

    m.get_notebook = not_owner
    for call in (
        m.create_link_share(uuid4(), 9, "viewer"),
        m.create_user_share(uuid4(), 9, 3, "viewer"),
        m.list_shares(uuid4(), 9),
        m.revoke_share(uuid4(), 9, uuid4()),
    ):
        with pytest.raises(NotebookNotFoundError):
            await call
    assert m.db_pool.conn.calls == []


@sync
async def test_manager_turns_a_bad_role_into_a_validation_error():
    m = NotebookManager(FakePool())

    async def owner(notebook_id, user_id):
        return object()

    m.get_notebook = owner
    with pytest.raises(NotebookValidationError):
        await m.create_link_share(uuid4(), 1, "superuser")


@sync
async def test_resolve_link_token_rejects_junk_without_a_query():
    pool = FakePool()
    for junk in ("", None, "x" * 500, 12):
        assert await shares.resolve_link_token(pool, junk) is None
    assert pool.conn.calls == []


@sync
async def test_get_access_is_owner_then_share_role_then_none():
    uid = 7
    assert await shares.get_access(FakePool([("FROM notebooks n", {"owner_id": uid, "role": None})]), uuid4(), uid) == "owner"
    assert await shares.get_access(FakePool([("FROM notebooks n", {"owner_id": 1, "role": "chat_only"})]), uuid4(), uid) == "chat_only"
    assert await shares.get_access(FakePool([("FROM notebooks n", {"owner_id": 1, "role": None})]), uuid4(), uid) is None
    assert await shares.get_access(FakePool(), uuid4(), uid) is None


@sync
async def test_create_chunks_records_embedder_and_width_and_skips_unembedded():
    m = NotebookManager(FakePool())
    await m.create_chunks(uuid4(), uuid4(), [("a", [0.1], {}, 0), ("b", [], {}, 1)],
                          embedding_model="nomic", embedding_dim=768)
    sql, records = m.db_pool.conn.calls[0]
    assert "embedding_model" in sql and "embedding_dim" in sql
    assert len(records) == 1 and records[0][-2:] == ("nomic", 768)

    m = NotebookManager(FakePool())
    await m.create_chunks(uuid4(), uuid4(), [("a", [0.1], {}, 0)])
    assert m.db_pool.conn.calls[0][1][0][-2:] == (None, None)


# ─── SQL files ────────────────────────────────────────────────────────────────

DESTRUCTIVE = re.compile(r"\b(DROP\s+(TABLE|COLUMN|SCHEMA|DATABASE)|TRUNCATE|DELETE\s+FROM)\b", re.I)


def test_schema_additions_are_additive_and_carry_the_contract_names():
    sql = (NB_DIR / "schema.sql").read_text()
    assert not DESTRUCTIVE.search(sql)
    for needle in (
        "ADD COLUMN IF NOT EXISTS chat_persona", "ADD COLUMN IF NOT EXISTS chat_style",
        "ADD COLUMN IF NOT EXISTS chat_length", "ADD COLUMN IF NOT EXISTS output_language",
        "ADD COLUMN IF NOT EXISTS embedding_model", "ADD COLUMN IF NOT EXISTS embedding_dim",
        "to_tsvector('simple', coalesce(content, ''))", "idx_notebook_chunks_tsv", "USING gin",
        "CREATE TABLE IF NOT EXISTS notebook_shares", "link_token TEXT UNIQUE",
        "'viewer', 'chat_only', 'editor'",
    ):
        assert needle in sql, needle
    assert "embedding vector(4096)" in sql  # live column untouched


def test_the_768_migration_is_opt_in_and_never_deletes():
    sql = re.sub(r"--.*", "", (NB_DIR / "migrate_vector_768.sql").read_text())
    assert not DESTRUCTIVE.search(sql)
    assert "vector(768)" in sql and "hnsw" in sql and "vector_cosine_ops" in sql
    startup = (NB_DIR.parent / "main.py").read_text()
    assert "migrate_vector_768" not in startup
