"""Batch embeddings, the embedding provider seam and what gets recorded per source.
Everything is mocked: no Ollama, no remote server, no database."""
import asyncio
import logging
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import embedding_provider as ep  # noqa: E402
from notebooks import ingestion  # noqa: E402
from notebooks.models import SourceStatus, SourceType  # noqa: E402

LONG = "\n\n".join(f"Paragraph {i}: " + "mitochondria are the powerhouse of the cell. " * 12 for i in range(8))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "NOTEBOOK_EMBED_PROVIDER", "NOTEBOOK_EMBED_BASE_URL", "NOTEBOOK_EMBED_MODEL", "NOTEBOOK_EMBED_API_KEY",
        "NOTEBOOK_EMBED_DIMENSIONS", "NOTEBOOK_EMBED_ALLOW_PRIVATE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS", "0")
    monkeypatch.setattr(ingestion.IngestionService, "_working_model", None)


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


# --- Ollama provider --------------------------------------------------------------------


def test_ollama_sends_one_request_with_an_input_list(monkeypatch):
    calls = []

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return Resp(200, {"embeddings": [[1.0, 2.0], [3.0, 4.0]]})

    monkeypatch.setattr(ep.requests, "post", post)
    out = ep.OllamaProvider("http://ollama:11434/", "nomic-embed-text").embed(["a", "b"])
    assert calls == [("http://ollama:11434/api/embed", {"model": "nomic-embed-text", "input": ["a", "b"]})]
    assert out.vectors == [[1.0, 2.0], [3.0, 4.0]] and out.model == "nomic-embed-text"


def test_ollama_falls_back_to_the_legacy_endpoint_when_embed_is_missing(monkeypatch):
    seen = []

    def post(url, json=None, timeout=None):
        seen.append(url.rsplit("/", 1)[-1])
        if url.endswith("/api/embed"):
            return Resp(404, None)  # an old server: 404 without a model error
        return Resp(200, {"embedding": [float(len(json["prompt"]))]})

    monkeypatch.setattr(ep.requests, "post", post)
    out = ep.OllamaProvider("http://o", "m").embed(["aa", "bbb"])
    assert out.vectors == [[2.0], [3.0]]
    assert seen == ["embed", "embeddings", "embeddings"]


def test_a_missing_model_is_not_mistaken_for_an_old_server(monkeypatch):
    seen = []

    def post(url, json=None, timeout=None):
        seen.append(url)
        return Resp(404, {"error": 'model "nope" not found, try pulling it first'})

    monkeypatch.setattr(ep.requests, "post", post)
    out = ep.OllamaProvider("http://o", "nope").embed(["a"])
    assert out.vectors == [None] and len(seen) == 1


def test_ollama_answer_of_the_wrong_length_counts_as_a_failure(monkeypatch):
    monkeypatch.setattr(ep.requests, "post", lambda *a, **k: Resp(200, {"embeddings": [[1.0]]}))
    assert ep.OllamaProvider("http://o", "m").embed(["a", "b"]).vectors == [None, None]


def test_ollama_network_errors_do_not_raise(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(ep.requests, "post", boom)
    assert ep.OllamaProvider("http://o", "m").embed(["a"]).vectors == [None]


# --- provider choice and the remote provider ---------------------------------------------


def test_default_provider_is_ollama_and_unknown_values_stay_local(monkeypatch, caplog):
    assert ep.configured_provider_name() == "ollama"
    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "OpenAI")
    assert ep.configured_provider_name() == "openai"
    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "mystery")
    with caplog.at_level(logging.WARNING):
        assert ep.configured_provider_name() == "ollama"
    assert "documents stay on this machine" in caplog.text


def test_remote_settings_defaults_and_validation(monkeypatch):
    s = ep.remote_settings()
    assert s.base_url == "https://api.openai.com/v1" and s.model == "text-embedding-3-small"
    assert s.guarded and s.dimensions is None
    monkeypatch.setenv("NOTEBOOK_EMBED_DIMENSIONS", "99999")
    with pytest.raises(ep.ProviderConfigError):
        ep.remote_settings()
    monkeypatch.setenv("NOTEBOOK_EMBED_DIMENSIONS", "abc")
    with pytest.raises(ep.ProviderConfigError):
        ep.remote_settings()
    monkeypatch.delenv("NOTEBOOK_EMBED_DIMENSIONS")
    monkeypatch.setenv("NOTEBOOK_EMBED_BASE_URL", "file:///etc/passwd")
    with pytest.raises(ep.ProviderConfigError) as err:
        ep.remote_settings()
    assert "NOTEBOOK_EMBED_BASE_URL" in str(err.value)


def test_remote_guard_refuses_private_addresses_by_default(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_EMBED_BASE_URL", "http://127.0.0.1:9/v1")
    provider = ep.remote_provider()
    assert provider.embed(["hello"]).vectors == [None]  # blocked by the connect-time guard, no exception


class FakeClient:
    log = []
    answers = []

    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        FakeClient.log.append((url, json, headers))
        answer = FakeClient.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.log, FakeClient.answers = [], []
    monkeypatch.setattr(ep, "remote_sync_client", lambda settings, **kw: FakeClient(**kw))
    monkeypatch.setattr(ep.time, "sleep", lambda s: None)
    return FakeClient


def test_remote_provider_orders_by_index_and_sends_the_key(fake_client, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_EMBED_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("NOTEBOOK_EMBED_DIMENSIONS", "256")
    fake_client.answers = [
        Resp(200, {"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]})
    ]
    out = ep.remote_provider().embed(["a", "b"])
    assert out.vectors == [[1.0], [2.0]] and out.model == "text-embedding-3-small"
    url, body, headers = fake_client.log[0]
    assert url == "https://api.openai.com/v1/embeddings"
    assert body["input"] == ["a", "b"] and body["dimensions"] == 256
    assert headers["Authorization"] == "Bearer sk-test-not-a-real-key"


def test_remote_provider_retries_then_gives_up_without_logging_the_key(fake_client, monkeypatch, caplog):
    monkeypatch.setenv("NOTEBOOK_EMBED_API_KEY", "sk-test-not-a-real-key")
    fake_client.answers = [Resp(429), ConnectionError("sk-test-not-a-real-key leaked?"), Resp(503)]
    with caplog.at_level(logging.DEBUG):
        out = ep.remote_provider().embed(["a"])
    assert out.vectors == [None] and len(fake_client.log) == 3
    assert "sk-test-not-a-real-key" not in caplog.text


def test_remote_provider_does_not_retry_a_rejected_request(fake_client):
    fake_client.answers = [Resp(401, {"error": "bad key"})]
    assert ep.remote_provider().embed(["a"]).vectors == [None]
    assert len(fake_client.log) == 1


def test_remote_provider_rejects_a_malformed_answer(fake_client):
    fake_client.answers = [Resp(200, {"data": [{"index": 0, "embedding": [1.0]}]})]
    assert ep.remote_provider().embed(["a", "b"]).vectors == [None, None]


# --- the pipeline -------------------------------------------------------------------------


class Conn:
    async def execute(self, sql, *args):
        pass

    async def fetchval(self, sql, *args):
        return None


class Acquire:
    async def __aenter__(self):
        return Conn()

    async def __aexit__(self, *a):
        return False


class PlainManager:
    """create_chunks without the new keyword arguments, as before the manager changed."""

    def __init__(self, source):
        self.source = source
        self.statuses, self.chunks = [], []
        self.db_pool = SimpleNamespace(acquire=lambda: Acquire())

    async def get_source(self, sid, uid):
        return self.source

    async def update_source_status(self, sid, status, error_message=None, metadata_update=None):
        self.statuses.append((status, error_message, metadata_update))

    async def clear_chunks(self, sid):
        pass

    async def create_chunks(self, sid, nid, chunks):
        self.chunks = chunks
        return len(chunks)


class RichManager(PlainManager):
    async def create_chunks(self, sid, nid, chunks, embedding_model=None, embedding_dim=None):
        self.recorded = (embedding_model, embedding_dim)
        return await super().create_chunks(sid, nid, chunks)


def source_for(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text(LONG)
    return SimpleNamespace(
        id=uuid4(), notebook_id=uuid4(), type=SourceType.TEXT, title="S", storage_path=str(f), metadata={"extension": "txt"}
    )


def ingest(mgr):
    svc = ingestion.IngestionService(mgr)
    asyncio.run(svc.ingest_source(mgr.source.id, 1))
    return svc


def batch_ollama(monkeypatch, vectors_for=lambda texts: [[0.5] * 6 for _ in texts], model="nomic-embed-text"):
    monkeypatch.setattr(ingestion.IngestionService, "_working_model", model)
    batches = []

    def fake(self, base_url, m, texts):
        batches.append(list(texts))
        return vectors_for(texts)

    monkeypatch.setattr(ingestion.IngestionService, "_try_embedding_batch", fake)
    return batches


def test_chunks_are_embedded_in_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, "EMBED_BATCH_SIZE", 3)
    batches = batch_ollama(monkeypatch)
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    assert mgr.statuses[-1][0] == SourceStatus.READY
    assert len(batches) >= 2 and all(len(b) <= 3 for b in batches)
    assert sum(len(b) for b in batches) == len(mgr.chunks)
    assert [c[3] for c in mgr.chunks] == list(range(len(mgr.chunks)))  # chunk_index stays in order
    assert all(len(c[1]) == ingestion.TARGET_DIM for c in mgr.chunks)


def test_model_and_native_width_are_recorded_and_passed_when_supported(tmp_path, monkeypatch):
    batch_ollama(monkeypatch)
    rich = RichManager(source_for(tmp_path))
    ingest(rich)
    assert rich.recorded == ("nomic-embed-text", 6)
    meta = rich.statuses[-1][2]
    assert meta["embedding_model"] == "nomic-embed-text" and meta["embedding_dim"] == 6  # native, before padding


def test_a_manager_without_the_new_kwargs_still_works_and_metadata_keeps_the_facts(tmp_path, monkeypatch):
    batch_ollama(monkeypatch)
    plain = PlainManager(source_for(tmp_path))
    ingest(plain)
    status, _err, meta = plain.statuses[-1]
    assert status == SourceStatus.READY and meta["embedding_dim"] == 6


def test_manager_taking_any_keywords_gets_them(tmp_path, monkeypatch):
    batch_ollama(monkeypatch)
    seen = {}

    class Kw(PlainManager):
        async def create_chunks(self, sid, nid, chunks, **kwargs):
            seen.update(kwargs)
            return len(chunks)

    ingest(Kw(source_for(tmp_path)))
    assert seen == {"embedding_model": "nomic-embed-text", "embedding_dim": 6}


def test_a_vector_of_another_width_is_dropped_not_stored(tmp_path, monkeypatch):
    def mixed(texts):
        return [[0.5] * 6 if i != 1 else [0.5] * 9 for i, _t in enumerate(texts)]

    batch_ollama(monkeypatch, vectors_for=mixed)
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    status, _err, meta = mgr.statuses[-1]
    assert status == SourceStatus.READY and meta["skipped_chunks"] == 1
    assert meta["embedding_dim"] == 6 and len(mgr.chunks) == meta["chunk_count"]


def test_a_rejected_batch_is_retried_one_text_at_a_time(tmp_path, monkeypatch):
    batch_ollama(monkeypatch, vectors_for=lambda texts: [None] * len(texts))
    singles = []

    async def single(self, text):
        singles.append(text)
        return [0.25] * 4

    monkeypatch.setattr(ingestion.IngestionService, "_get_embedding", single)
    # With _get_embedding replaced on the class the service must not batch at all.
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    assert mgr.statuses[-1][0] == SourceStatus.READY and len(singles) == len(mgr.chunks)


def test_whole_batch_failure_falls_back_to_single_texts(tmp_path, monkeypatch):
    batch_ollama(monkeypatch, vectors_for=lambda texts: [None] * len(texts))
    singles = []

    def one(self, base_url, model, text):
        singles.append(text)
        return [0.25] * 4

    monkeypatch.setattr(ingestion.IngestionService, "_try_embedding", one)
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    assert mgr.statuses[-1][0] == SourceStatus.READY and len(singles) == len(mgr.chunks)


def test_remote_provider_is_used_through_the_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("NOTEBOOK_EMBED_MODEL", "text-embedding-3-small")
    calls = []

    def embed(self, texts):
        calls.append(len(texts))
        return ep.EmbedResult([[0.1] * 12 for _ in texts], self.model)

    monkeypatch.setattr(ep.OpenAICompatProvider, "embed", embed)
    monkeypatch.setattr(ingestion.IngestionService, "_try_embedding_batch", lambda *a: pytest.fail("ollama used"))
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    status, _err, meta = mgr.statuses[-1]
    assert status == SourceStatus.READY and sum(calls) == len(mgr.chunks)
    assert meta["embedding_model"] == "text-embedding-3-small" and meta["embedding_dim"] == 12


def test_remote_failure_says_it_is_the_cloud_embedder(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(
        ep.OpenAICompatProvider, "embed", lambda self, texts: ep.EmbedResult([None] * len(texts), self.model)
    )
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    status, message, _meta = mgr.statuses[-1]
    assert status == SourceStatus.ERROR and message == ingestion.REMOTE_EMBEDDER_MESSAGE
    assert "NOTEBOOK_EMBED" in message


def test_bad_remote_config_is_an_error_on_the_source_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("NOTEBOOK_EMBED_BASE_URL", "ftp://example.test/v1")
    mgr = PlainManager(source_for(tmp_path))
    ingest(mgr)
    assert mgr.statuses[-1][0] == SourceStatus.ERROR


def test_embedder_status_for_a_blocked_private_url_is_unreachable(monkeypatch):
    from notebooks import embedder_status

    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("NOTEBOOK_EMBED_BASE_URL", "http://127.0.0.1:9/v1")
    status = asyncio.run(embedder_status.embedder_status())
    assert status["provider"] == "openai" and status["leaves_machine"] is True
    assert status["state"] == "unreachable" and status["install_tag"] is None


def test_embedder_status_for_a_bad_url_says_what_is_wrong(monkeypatch):
    from notebooks import embedder_status

    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("NOTEBOOK_EMBED_BASE_URL", "gopher://x")
    status = asyncio.run(embedder_status.embedder_status())
    assert status["state"] == "unsupported" and "NOTEBOOK_EMBED_BASE_URL" in status["reason"]


@pytest.mark.parametrize("code,state,word", [(200, "ready", "sent there"), (401, "unreachable", "key"), (500, "unreachable", "500")])
def test_embedder_status_probe_answers(monkeypatch, code, state, word):
    from notebooks import embedder_status
    from plugins.hermes_ui import providers

    class Probe:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            assert url.endswith("/models") and "documents" not in url
            return Resp(code, {"data": []})

    monkeypatch.setenv("NOTEBOOK_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(providers, "guarded_client", lambda **kw: Probe())
    status = asyncio.run(embedder_status.embedder_status())
    assert status["state"] == state and word in status["reason"]


def test_ollama_status_is_unchanged_by_the_provider_seam(monkeypatch):
    from notebooks import embedder_status

    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    status = asyncio.run(embedder_status.embedder_status())
    assert "provider" not in status and status["state"] == "unreachable" and status["install_tag"]
