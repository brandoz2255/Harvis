"""One "remember that X" saves one memory: the regex save and the model extractor word it differently."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.memory import dedupe  # noqa: E402


@pytest.mark.parametrize("a,b", [
    ("Asked Harvis to remember: My exam is Friday", "User's exam is on Friday"),
    ("Asked Harvis to remember: I love cake", "User loves cake"),
    ("User lives in Redlands, California", "User lives in Redlands"),
    ("Asked Harvis to remember: I use a 4090", "Uses a 4090"),
])
def test_rewordings_are_the_same_memory(a, b):
    assert dedupe.same_memory(a, b) and dedupe.same_memory(b, a)


@pytest.mark.parametrize("a,b", [
    ("User likes cake", "User likes pizza"),
    ("My exam is Friday", "My exam is Monday"),
    ("Uses a 4090", "Uses a 3090 Ti"),
    ("", "anything"),
])
def test_different_facts_are_kept(a, b):
    assert not dedupe.same_memory(a, b)


def test_find_duplicate_returns_the_id():
    assert dedupe.find_duplicate("User loves cake", [(4, "Prefers tea"), (7, "Asked Harvis to remember: I love cake")]) == 7
    assert dedupe.find_duplicate("New fact entirely", [(4, "Prefers tea")]) is None


class _Conn:
    def __init__(self, rows):
        self.rows, self.inserted = rows, []

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Tx()

    async def execute(self, *a):
        return "OK"

    async def fetch(self, *a):
        return self.rows

    async def fetchrow(self, sql, *args):
        import datetime
        self.inserted.append(args[1])
        return {"id": 99, "created_at": datetime.datetime(2026, 1, 1)}


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


@pytest.mark.asyncio
async def test_builtin_provider_returns_the_existing_memory_instead_of_inserting_a_twin():
    import datetime
    from plugins.memory.builtin.provider import BuiltinPgMemoryProvider

    row = {"id": 7, "content": "Asked Harvis to remember: I love cake", "source": "session-extract",
           "metadata": "{}", "created_at": datetime.datetime(2026, 1, 1)}
    conn = _Conn([row])
    provider = BuiltinPgMemoryProvider(pool=_Pool(conn))
    entry = await provider.remember(1, "User loves cake", source="session-extract")
    assert entry.duplicate is True and entry.content == row["content"] and conn.inserted == []
    fresh = await provider.remember(1, "User studies information systems", source="session-extract")
    assert fresh.duplicate is False and conn.inserted == ["User studies information systems"]
