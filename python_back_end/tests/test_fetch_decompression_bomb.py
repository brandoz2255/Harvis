"""F22: a tiny compressed response must not be able to balloon the backend's memory.

httpx decodes br and zstd, and it decodes a whole raw chunk before our size check runs,
so a ~1.6 KB brotli body used to push the process from 80 MB to 2 GB. The two fetchers
that talk to arbitrary sites (notebooks.extractors._fetch_capped for URL sources and
agent_reach.tools._safe_get for the agent tools) now ask for gzip/deflate only, read the
raw bytes, refuse every other encoding, and inflate with zlib under a hard output limit.

The memory-bound tests run in a fresh child process so ru_maxrss (a high-water mark)
starts from a known baseline, and the bomb is built from small blocks so building it
never raises that baseline itself.
"""
import asyncio
import gzip
import json
import subprocess
import sys
import zlib
from pathlib import Path

import httpx
import pytest

BACKEND = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, BACKEND)

GROWTH_LIMIT_MB = 200

CHILD = r'''
import asyncio, json, resource, sys, zlib
backend, via, kind = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, backend)
import httpx
from agent_reach import tools as reach

BLOCK = b"\0" * (1024 * 1024)
DECODED_MB = 400


def build(kind):
    parts = []
    if kind == "br":
        import brotli
        c = brotli.Compressor(quality=1)
        for _ in range(DECODED_MB):
            parts.append(c.process(BLOCK))
        parts.append(c.finish())
    elif kind == "zstd":
        import zstandard
        c = zstandard.ZstdCompressor(level=1).compressobj()
        for _ in range(DECODED_MB):
            parts.append(c.compress(BLOCK))
        parts.append(c.flush())
    elif kind in ("gzip", "deflate"):
        c = zlib.compressobj(9, zlib.DEFLATED, 31 if kind == "gzip" else zlib.MAX_WBITS)
        for _ in range(DECODED_MB):
            parts.append(c.compress(BLOCK))
        parts.append(c.flush())
    return [p for p in parts if p]


parts = build(kind)


class Body(httpx.AsyncByteStream):
    # One wire chunk: that is what makes httpx decode the whole bomb in a single step.
    async def __aiter__(self):
        yield b"".join(parts)


reach._resolve_public_ips = lambda host, port: ["93.184.216.34"]
real = httpx.AsyncClient


class Client(real):
    def __init__(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(
                200, headers={"content-type": "text/html", "content-encoding": kind}, stream=Body()
            )
        )
        super().__init__(*a, **kw)


httpx.AsyncClient = Client


async def go():
    if via == "extract_url":
        from notebooks import extractors
        try:
            await extractors.extract_url("https://example.test/bomb")
            return "returned"
        except extractors.IngestionError as exc:
            return "refused: " + str(exc)[:120]
    try:
        await reach._safe_get("https://example.test/bomb")
        return "returned"
    except reach.ReachBlocked as exc:
        return "refused: " + str(exc)[:120]


base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
outcome = asyncio.run(go())
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({"outcome": outcome, "growth_mb": (peak - base) / 1024.0,
                  "compressed_bytes": sum(len(p) for p in parts)}))
'''


def _run_child(via, kind):
    done = subprocess.run(
        [sys.executable, "-I", "-c", CHILD, BACKEND, via, kind],
        capture_output=True, text=True, timeout=180,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("via", ["extract_url", "safe_get"])
@pytest.mark.parametrize("kind", ["br", "zstd", "gzip"])
def test_compression_bomb_is_refused_with_bounded_memory(via, kind):
    result = _run_child(via, kind)
    assert result["outcome"].startswith("refused"), result
    assert result["compressed_bytes"] < 8 * 1024 * 1024, "the bomb must be small on the wire"
    assert result["growth_mb"] < GROWTH_LIMIT_MB, result


# ── in-process: what is requested, what is refused, what still works ───────────

class _Once(httpx.AsyncByteStream):
    """A raw wire body. httpx.Response(content=...) would be decoded on construction."""

    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


@pytest.fixture
def served(monkeypatch):
    """Serve one canned response through both fetchers; record the request headers."""
    from agent_reach import tools as reach

    monkeypatch.setattr(reach, "_resolve_public_ips", lambda host, port: ["93.184.216.34"])
    seen = {}
    real = httpx.AsyncClient

    def serve(body: bytes, **headers):
        def handler(request):
            seen["accept_encoding"] = request.headers.get("accept-encoding")
            h = {"content-type": "text/html; charset=utf-8", **headers}
            return httpx.Response(200, headers=h, stream=_Once(body))

        class Client(real):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Client)

    seen["serve"] = serve
    return seen


PAGE = "<html><body><p>" + ("Readable sentence. " * 20) + "</p></body></html>"


def _deflate_raw(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    return c.compress(data) + c.flush()


@pytest.mark.parametrize("encoding,body", [
    ("gzip", gzip.compress(PAGE.encode())),
    ("deflate", zlib.compress(PAGE.encode())),
    ("deflate", _deflate_raw(PAGE.encode())),
    ("identity", PAGE.encode()),
])
def test_a_normal_compressed_page_still_extracts(served, encoding, body):
    from notebooks import extractors

    served["serve"](body, **{"content-encoding": encoding})
    text = asyncio.run(extractors.extract_url("https://example.test/ok"))
    assert "Readable sentence." in text


def test_safe_get_still_returns_a_readable_response(served):
    from agent_reach import tools as reach

    served["serve"](gzip.compress(PAGE.encode()), **{"content-encoding": "gzip"})
    resp = asyncio.run(reach._safe_get("https://example.test/ok"))
    assert resp.status_code == 200
    assert "Readable sentence." in resp.text
    assert "content-encoding" not in resp.headers


@pytest.mark.parametrize("caller_headers", [None, {"Accept-Encoding": "br, zstd, gzip"}])
def test_only_gzip_and_deflate_are_requested(served, caller_headers):
    from agent_reach import tools as reach
    from notebooks import extractors

    served["serve"](PAGE.encode())
    asyncio.run(reach._safe_get("https://example.test/ok", headers=caller_headers))
    assert served["accept_encoding"] == "gzip, deflate"
    served["accept_encoding"] = None
    asyncio.run(extractors._fetch_capped("https://example.test/ok", headers=dict(caller_headers or {}), timeout=5))
    assert served["accept_encoding"] == "gzip, deflate"


@pytest.mark.parametrize("encoding", ["br", "zstd", "gzip, gzip", "compress", "gzip, br"])
def test_unsupported_or_stacked_encodings_are_refused_even_when_small(served, encoding):
    from agent_reach import tools as reach
    from notebooks import extractors

    served["serve"](b"tiny", **{"content-encoding": encoding})
    with pytest.raises(reach.ReachBlocked):
        asyncio.run(reach._safe_get("https://example.test/x"))
    with pytest.raises(extractors.IngestionError):
        asyncio.run(extractors.extract_url("https://example.test/x"))


def test_a_corrupt_gzip_body_is_refused_not_crashed(served):
    from agent_reach import tools as reach

    served["serve"](b"definitely not gzip", **{"content-encoding": "gzip"})
    with pytest.raises(reach.ReachBlocked):
        asyncio.run(reach._safe_get("https://example.test/x"))


def test_decoded_output_never_passes_the_cap_by_more_than_one_step(monkeypatch):
    """Direct bound on the inflater: with a 1 MiB cap the call that trips it has produced
    at most cap+1 bytes in total, whatever the bomb would have expanded to."""
    from agent_reach import tools as reach

    real = zlib.decompressobj
    produced = []

    class Spy:
        def __init__(self, *a):
            self._d = real(*a)

        def decompress(self, data, max_length=0):
            out = self._d.decompress(data, max_length)
            produced.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self._d, name)

    monkeypatch.setattr(reach.zlib, "decompressobj", lambda *a: Spy(*a))

    c = zlib.compressobj(9, zlib.DEFLATED, 31)
    bomb = b"".join(c.compress(b"\0" * 1024 * 1024) for _ in range(300)) + c.flush()

    class FakeResp:
        headers = httpx.Headers({"content-encoding": "gzip"})

        async def aiter_raw(self):
            yield bomb

    cap = 1024 * 1024
    with pytest.raises(reach.ReachBlocked):
        asyncio.run(reach._read_capped_body(FakeResp(), cap))
    assert sum(produced) <= cap + 1
    assert max(produced) <= reach._INFLATE_STEP
