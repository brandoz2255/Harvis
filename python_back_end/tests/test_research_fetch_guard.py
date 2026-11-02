"""The research fetchers read URLs that a search engine or a web page picked, not anyone
on this server. On a shared host they must dial public addresses only, whoever asked; a
local install keeps plain ``requests``. Nothing here opens a socket: name resolution and
the inner network backend are replaced."""
import ipaddress
import os
import socket
import sys
import zlib

import httpcore
import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import providers  # noqa: E402
from research import safe_fetch  # noqa: E402
from research import web_search  # noqa: E402
from research.extract import html_trafilatura, pdf, router, youtube  # noqa: E402

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"
PAGE = b"<html><head><title>T</title></head><body><p>" + b"hello world " * 40 + b"</p></body></html>"


def reply(status=200, body=b"", headers=None):
    lines = [f"HTTP/1.1 {status} X"]
    for k, v in {"Content-Length": str(len(body)), **(headers or {})}.items():
        lines.append(f"{k}: {v}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)


class FakeStream(httpcore.NetworkStream):
    def __init__(self, replies):
        self.replies = replies
        self.sent = bytearray()

    def read(self, max_bytes, timeout=None):
        data, self.replies = self.replies[:max_bytes], self.replies[max_bytes:]
        return data

    def write(self, buffer, timeout=None):
        self.sent += buffer

    def close(self):
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return None


class FakeBackend(httpcore.NetworkBackend):
    """One reply per connection, in order; the last one repeats."""

    def __init__(self, *replies):
        self.replies = list(replies) or [reply(200, PAGE)]
        self.calls = []
        self.streams = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port))
        data = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        stream = FakeStream(data)
        self.streams.append(stream)
        return stream

    def sleep(self, seconds):
        pass


@pytest.fixture
def dns(monkeypatch):
    """dns({"host": ["1.2.3.4"]}) or dns({"host": [["1.2.3.4"], ["10.0.0.1"]]}) for a name that changes its answer."""
    def script(table):
        queues = {h: [list(a) if isinstance(a, list) else [a] for a in v] if v and isinstance(v[0], list) else [list(v)]
                  for h, v in table.items()}
        seen = []

        def getaddrinfo(host, port, *args, **kwargs):
            seen.append(host)
            try:
                ipaddress.ip_address(host.strip("[]"))
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host.strip("[]"), 0))]
            except ValueError:
                pass
            if host not in queues:
                raise socket.gaierror("no such name")
            q = queues[host]
            ips = q.pop(0) if len(q) > 1 else q[0]
            return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        return seen

    return script


@pytest.fixture
def backend(monkeypatch):
    """Every guarded sync client the research code builds dials this backend instead of a socket."""
    holder = {}
    real = providers.guarded_sync_client

    def build(network_backend=None, vet=providers._require_global, **kwargs):
        return real(holder["fake"], vet, **kwargs)

    def install(*replies):
        holder["fake"] = FakeBackend(*replies)
        monkeypatch.setattr(providers, "guarded_sync_client", build)
        return holder["fake"]

    return install


# -- safe_fetch ----------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.1.2.3/x", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.9/", "http://[::1]/", "http://[::ffff:10.0.0.1]/", "http://[fd00::1]/",
])
def test_private_address_literals_are_refused_before_anything_is_sent(url):
    fake = FakeBackend()
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch(url, network_backend=fake)
    assert fake.calls == []


@pytest.mark.parametrize("name,ip", [("pgsql", "172.18.0.2"), ("evil.example", "10.0.0.5"), ("tailnet.example", "100.100.1.1"),
                                     ("meta.example", "169.254.169.254"), ("lo.example", "127.0.0.1")])
def test_a_name_that_resolves_to_a_private_address_is_refused(dns, name, ip):
    dns({name: [ip]})
    fake = FakeBackend()
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch(f"http://{name}/", network_backend=fake)
    assert fake.calls == []


def test_one_private_answer_among_public_ones_refuses_the_name(dns):
    dns({"mixed.example": [PUBLIC_IP, "10.0.0.5"]})
    fake = FakeBackend()
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://mixed.example/", network_backend=fake)
    assert fake.calls == []


def test_the_refusal_names_neither_the_address_nor_the_host(dns):
    dns({"pgsql": ["172.18.0.2"]})
    with pytest.raises(safe_fetch.FetchBlocked) as excinfo:
        safe_fetch.fetch("http://pgsql:5432/", network_backend=FakeBackend())
    assert "172.18" not in str(excinfo.value) and "pgsql" not in str(excinfo.value)


def test_a_name_that_does_not_resolve_dials_nothing(dns):
    dns({})
    fake = FakeBackend()
    with pytest.raises(httpx.HTTPError):
        safe_fetch.fetch("http://nowhere.example/", network_backend=fake)
    assert fake.calls == []


def test_a_public_page_is_fetched_from_the_vetted_address_not_the_name(dns):
    dns({"good.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(200, b"ok", {"Content-Type": "text/plain"}))
    resp = safe_fetch.fetch("http://good.example/a", network_backend=fake)
    assert resp.status_code == 200 and resp.text == "ok" and resp.headers["content-type"] == "text/plain"
    assert fake.calls == [(PUBLIC_IP, 80)]


def test_a_name_that_rebinds_after_the_first_lookup_cannot_redirect_the_request(dns):
    seen = dns({"rebind.example": [[PUBLIC_IP], ["10.0.0.5"]]})
    fake = FakeBackend(reply(200, b"ok"))
    safe_fetch.fetch("http://rebind.example/", network_backend=fake)
    assert fake.calls == [(PUBLIC_IP, 80)] and seen == ["rebind.example"]
    # the next lookup of that name is the private one, and is refused
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://rebind.example/", network_backend=FakeBackend())


def test_a_redirect_to_a_private_address_is_refused_after_the_public_hop(dns):
    dns({"good.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(302, b"", {"Location": "http://169.254.169.254/latest/meta-data/"}))
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://good.example/", network_backend=fake)
    assert fake.calls == [(PUBLIC_IP, 80)]


def test_a_redirect_to_a_name_that_resolves_privately_is_refused(dns):
    dns({"good.example": [PUBLIC_IP], "pgsql": ["172.18.0.2"]})
    fake = FakeBackend(reply(301, b"", {"Location": "http://pgsql:5432/"}))
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://good.example/", network_backend=fake)
    assert fake.calls == [(PUBLIC_IP, 80)]


def test_public_redirects_are_followed_with_relative_locations(dns):
    dns({"a.example": [PUBLIC_IP], "b.example": [OTHER_PUBLIC_IP]})
    fake = FakeBackend(reply(302, b"", {"Location": "http://b.example/final"}), reply(302, b"", {"Location": "/x"}),
                       reply(200, b"done"))
    resp = safe_fetch.fetch("http://a.example/", network_backend=fake)
    assert resp.text == "done"
    assert [c[0] for c in fake.calls] == [PUBLIC_IP, OTHER_PUBLIC_IP, OTHER_PUBLIC_IP]


def test_a_redirect_loop_stops(dns):
    dns({"a.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(302, b"", {"Location": "http://a.example/"}))
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://a.example/", network_backend=fake)
    assert len(fake.calls) == safe_fetch.MAX_REDIRECTS + 1


@pytest.mark.parametrize("url", ["ftp://a.example/x", "file:///etc/passwd", "gopher://a.example/", "//a.example/x"])
def test_only_http_and_https_are_fetched(dns, url):
    dns({"a.example": [PUBLIC_IP]})
    fake = FakeBackend()
    with pytest.raises((safe_fetch.FetchBlocked, httpx.HTTPError)):
        safe_fetch.fetch(url, network_backend=fake)
    assert fake.calls == []


def test_a_redirect_to_another_scheme_is_refused(dns):
    dns({"a.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(302, b"", {"Location": "file:///etc/passwd"}))
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://a.example/", network_backend=fake)


def test_an_oversized_body_is_refused(dns):
    dns({"a.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(200, b"x" * 5000))
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch("http://a.example/", network_backend=fake, max_bytes=1000)


def test_head_requests_send_head(dns):
    dns({"a.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(200, b"", {"Content-Type": "application/pdf"}))
    resp = safe_fetch.fetch("http://a.example/f", method="HEAD", network_backend=fake)
    assert resp.headers["content-type"] == "application/pdf"
    assert bytes(fake.streams[0].sent).startswith(b"HEAD /f ")


def test_environment_proxies_are_ignored(monkeypatch, dns):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("http_proxy", "http://proxy.internal:3128")
    dns({"a.example": [PUBLIC_IP]})
    fake = FakeBackend(reply(200, b"ok"))
    safe_fetch.fetch("http://a.example/", network_backend=fake)
    assert fake.calls == [(PUBLIC_IP, 80)]


def test_gzip_bodies_are_decoded_once(dns):
    import gzip

    dns({"a.example": [PUBLIC_IP]})
    body = gzip.compress(b"plain text")
    fake = FakeBackend(reply(200, body, {"Content-Encoding": "gzip"}))
    assert safe_fetch.fetch("http://a.example/", network_backend=fake).text == "plain text"


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc", True), ("https://youtu.be/abc", True), ("https://m.youtube.com/x", True),
    ("http://pgsql:5432/?youtube.com", False), ("http://youtube.com.evil.example/", False),
    ("http://evil.example/youtu.be", False), ("http://169.254.169.254/#youtube.com", False),
])
def test_only_youtube_hosts_count_as_youtube(url, expected):
    assert safe_fetch.is_youtube_host(url) is expected


def test_the_guard_is_on_for_a_shared_host_whoever_asks_and_off_locally(shared):
    assert safe_fetch.enabled() is True


def test_the_guard_is_off_on_a_local_install(local):
    assert safe_fetch.enabled() is False


# -- the extractors ------------------------------------------------------------

def _no_requests(monkeypatch, *modules):
    def boom(*a, **k):
        raise AssertionError("plain requests must not be used on a shared host")

    for mod in modules:
        monkeypatch.setattr(mod.requests, "get", boom)
        monkeypatch.setattr(mod.requests, "head", boom, raising=False)


def test_html_fetch_on_a_shared_host_refuses_a_private_target_for_everyone(shared, dns, backend, monkeypatch):
    dns({"pgsql": ["172.18.0.2"]})
    fake = backend()
    _no_requests(monkeypatch, html_trafilatura)
    out = html_trafilatura.extract_html("http://pgsql:5432/", None, "ua", 5)
    assert out["success"] is False and "172.18" not in str(out) and fake.calls == []


def test_html_fetch_on_a_shared_host_reads_a_public_page(shared, dns, backend, monkeypatch):
    dns({"good.example": [PUBLIC_IP]})
    fake = backend(reply(200, PAGE, {"Content-Type": "text/html"}))
    _no_requests(monkeypatch, html_trafilatura)
    out = html_trafilatura.extract_html("http://good.example/a", None, "ua", 5)
    assert out["success"] is True and "hello world" in out["text"]
    assert fake.calls == [(PUBLIC_IP, 80)]
    assert b"User-Agent: ua" in bytes(fake.streams[0].sent)


def test_html_fetch_on_a_shared_host_refuses_a_public_page_that_redirects_inward(shared, dns, backend, monkeypatch):
    dns({"good.example": [PUBLIC_IP]})
    fake = backend(reply(302, b"", {"Location": "http://169.254.169.254/latest/meta-data/"}))
    _no_requests(monkeypatch, html_trafilatura)
    out = html_trafilatura.extract_html("http://good.example/", None, "ua", 5)
    assert out["success"] is False and fake.calls == [(PUBLIC_IP, 80)]


def test_html_fetch_on_a_local_install_is_plain_requests(local, monkeypatch):
    calls = []

    class R:
        text = "<html><body>" + "local text " * 40 + "</body></html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(html_trafilatura.requests, "get", lambda url, **kw: calls.append((url, kw)) or R())
    out = html_trafilatura.extract_html("http://192.168.1.5/page", None, "ua", 5)
    assert calls and calls[0][0] == "http://192.168.1.5/page" and out["success"] is True


def test_pdf_download_on_a_shared_host_refuses_private_targets_and_uses_the_guard(shared, dns, backend, monkeypatch):
    dns({"pgsql": ["172.18.0.2"], "good.example": [PUBLIC_IP]})
    fake = backend(reply(200, b"%PDF-1.4 bytes"))
    _no_requests(monkeypatch, pdf)
    with pytest.raises(safe_fetch.FetchBlocked):
        pdf._download_pdf_bytes("http://pgsql:5432/x.pdf", "ua", 5)
    assert fake.calls == []
    assert pdf._download_pdf_bytes("http://good.example/x.pdf", "ua", 5) == b"%PDF-1.4 bytes"
    assert fake.calls == [(PUBLIC_IP, 80)]


def test_pdf_download_on_a_local_install_is_plain_requests(local, monkeypatch):
    class R:
        content = b"%PDF"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(pdf.requests, "get", lambda url, **kw: R())
    assert pdf._download_pdf_bytes("http://10.0.0.5/x.pdf", "ua", 5) == b"%PDF"


def test_the_content_type_probe_on_a_shared_host_never_dials_a_private_target(shared, dns, backend, monkeypatch):
    dns({"pgsql": ["172.18.0.2"], "good.example": [PUBLIC_IP]})
    fake = backend(reply(200, b"", {"Content-Type": "application/pdf; charset=x"}))
    _no_requests(monkeypatch, router)
    assert router._head_content_type("http://pgsql:5432/", 5, "ua") is None
    assert fake.calls == []
    assert router._head_content_type("http://good.example/f", 5, "ua") == "application/pdf"


def test_the_content_type_probe_on_a_local_install_is_plain_requests(local, monkeypatch):
    class R:
        status_code = 200
        ok = True
        headers = {"Content-Type": "text/html; charset=utf-8"}

    monkeypatch.setattr(router.requests, "head", lambda url, **kw: R())
    assert router._head_content_type("http://192.168.1.5/", 5, "ua") == "text/html"


def test_a_url_that_only_mentions_youtube_is_not_routed_to_the_video_extractor_on_a_shared_host(shared):
    assert router._is_youtube("http://pgsql:5432/?youtube.com") is False
    assert router._is_youtube("https://www.youtube.com/watch?v=abcdefghijk") is True


def test_the_youtube_substring_test_is_unchanged_on_a_local_install(local):
    assert router._is_youtube("http://pgsql:5432/?youtube.com") is True


def test_the_video_extractor_refuses_a_non_youtube_address_on_a_shared_host(shared, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(youtube.requests, "get", boom)
    out = youtube.extract_youtube("http://169.254.169.254/latest/meta-data/?youtube.com", timeout_s=5)
    assert out["success"] is False and out["meta"]["kind"] == "youtube_refused"


def test_extract_url_on_a_shared_host_does_not_hand_a_private_url_to_ytdlp_or_requests(shared, dns, backend, monkeypatch):
    dns({"pgsql": ["172.18.0.2"]})
    fake = backend()
    _no_requests(monkeypatch, html_trafilatura, pdf, router, youtube)
    doc = router.extract_url("http://pgsql:5432/db.pdf?youtube.com")
    assert doc.success is False and fake.calls == []


# -- web_search ----------------------------------------------------------------

def test_search_result_extraction_on_a_shared_host_refuses_private_targets(shared, dns, backend, monkeypatch):
    dns({"pgsql": ["172.18.0.2"]})
    fake = backend()
    _no_requests(monkeypatch, web_search)
    monkeypatch.setattr(web_search.Article, "download",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("newspaper must not dial")))
    out = web_search.WebSearchAgent().extract_content_from_url("http://pgsql:5432/")
    assert out["success"] is False and "172.18" not in str(out) and fake.calls == []


def test_search_result_extraction_on_a_shared_host_reads_a_public_page_through_the_guard(shared, dns, backend, monkeypatch):
    dns({"good.example": [PUBLIC_IP]})
    fake = backend(reply(200, PAGE, {"Content-Type": "text/html"}))
    _no_requests(monkeypatch, web_search)
    real_download = web_search.Article.download

    def download(self, input_html=None, **kw):
        if input_html is None:
            raise AssertionError("newspaper must not dial")
        return real_download(self, input_html=input_html)

    monkeypatch.setattr(web_search.Article, "download", download)
    out = web_search.WebSearchAgent().extract_content_from_url("http://good.example/a")
    assert out["success"] is True
    assert [c[0] for c in fake.calls] == [PUBLIC_IP, PUBLIC_IP]  # HEAD, then GET


def test_search_result_extraction_never_fetches_the_images_a_public_page_names(shared, dns, backend, monkeypatch):
    """newspaper's parse() requests every <img src> with a plain requests.get that follows
    redirects and honours env proxies; the page author picks those URLs."""
    import requests.adapters

    dns({"good.example": [PUBLIC_IP]})
    page = PAGE.replace(
        b"</p>",
        b'</p><img src="http://169.254.169.254/latest/meta-data/a.png">'
        b'<img src="http://pgsql:5432/x.jpg"><img src="http://127.0.0.1:8099/y.png">',
    )
    backend(reply(200, page, {"Content-Type": "text/html"}))
    dialled = []

    def send(self, request, **kw):
        dialled.append(request.url)
        raise requests.ConnectionError("blocked in test")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    out = web_search.WebSearchAgent().extract_content_from_url("http://good.example/a")
    assert out["success"] is True
    assert dialled == []


def test_search_result_extraction_on_a_shared_host_refuses_a_public_redirect_inward(shared, dns, backend, monkeypatch):
    dns({"good.example": [PUBLIC_IP]})
    fake = backend(reply(302, b"", {"Location": "http://10.0.0.5/"}))
    _no_requests(monkeypatch, web_search)
    out = web_search.WebSearchAgent().extract_content_from_url("http://good.example/")
    assert out["success"] is False and fake.calls == [(PUBLIC_IP, 80)]


def test_search_result_extraction_on_a_local_install_is_unchanged(local, monkeypatch):
    seen = []

    class R:
        status_code = 200

    monkeypatch.setattr(web_search.requests, "head", lambda url, **kw: seen.append(("head", url)) or R())

    def download(self, input_html=None, **kw):
        seen.append(("download", input_html))
        self.set_html("<html><head><title>T</title></head><body><p>" + "x " * 100 + "</p></body></html>")
        self.download_state = 2

    monkeypatch.setattr(web_search.Article, "download", download)
    out = web_search.WebSearchAgent().extract_content_from_url("http://192.168.1.5/a")
    assert out["success"] is True and seen == [("head", "http://192.168.1.5/a"), ("download", None)]


# -- safe_fetch: compressed bodies ----------------------------------------------
# httpx decodes br/zstd a whole raw chunk before any size check; a few KB of brotli
# inflated to hundreds of MB. fetch must ask for gzip/deflate only and inflate under a cap.

def _gzip(data):
    c = zlib.compressobj(9, zlib.DEFLATED, 31)
    return c.compress(data) + c.flush()


def test_fetch_asks_only_for_gzip_and_deflate_whatever_the_caller_sent():
    fake = FakeBackend(reply(200, PAGE))
    safe_fetch.fetch(f"http://{PUBLIC_IP}/", headers={"accept-encoding": "br, zstd"}, network_backend=fake)
    sent = bytes(fake.streams[0].sent).lower()
    assert b"accept-encoding: gzip, deflate\r\n" in sent
    assert b"br" not in sent.split(b"accept-encoding:")[1].split(b"\r\n")[0]


@pytest.mark.parametrize("encoding", ["br", "zstd", "gzip, gzip", "compress"])
def test_fetch_refuses_encodings_it_does_not_inflate_itself(encoding):
    fake = FakeBackend(reply(200, b"x" * 64, {"Content-Encoding": encoding}))
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch(f"http://{PUBLIC_IP}/", network_backend=fake)


def test_fetch_refuses_a_gzip_bomb_without_inflating_it_whole(monkeypatch):
    bomb = _gzip(b"\0" * (64 * 1024 * 1024))
    fake = FakeBackend(reply(200, bomb, {"Content-Encoding": "gzip"}))
    seen = []
    real = zlib.decompressobj

    class Spy:
        def __init__(self, *a):
            self.inner = real(*a)

        def decompress(self, data, max_length=0):
            out = self.inner.decompress(data, max_length)
            seen.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(safe_fetch.zlib, "decompressobj", Spy)
    with pytest.raises(safe_fetch.FetchBlocked):
        safe_fetch.fetch(f"http://{PUBLIC_IP}/", max_bytes=1024 * 1024, network_backend=fake)
    assert seen and max(seen) <= safe_fetch._INFLATE_STEP
    assert sum(seen) <= 1024 * 1024 + safe_fetch._INFLATE_STEP


def test_fetch_still_reads_a_normal_gzip_page():
    fake = FakeBackend(reply(200, _gzip(PAGE), {"Content-Encoding": "gzip"}))
    resp = safe_fetch.fetch(f"http://{PUBLIC_IP}/", network_backend=fake)
    assert resp.content == PAGE and "content-encoding" not in resp.headers
