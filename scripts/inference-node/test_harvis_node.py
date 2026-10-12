import http.client
import io
import json
import os
import socket
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import harvis_node

MODELS = {"models": [{"name": "llama3:8b"}, {"name": "qwen2.5:7b"}]}
CHAT_LINES = [{"message": {"content": c}, "done": c == "c"} for c in "abc"]


class FakeOllama(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FakeHandler)
        self.seen = []
        self.release = threading.Event()
        self.released_in_time = None


class FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send_json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def chunk(self, data):
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def do_GET(self):
        self.server.seen.append(("GET", self.path, b"", None))
        if self.path.split("?")[0] == "/api/tags":
            return self.send_json(MODELS)
        self.send_error(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = self.path.split("?")[0]
        self.server.seen.append(("POST", self.path, body, self.headers.get("Content-Type")))
        if path == "/api/chat":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.chunk(json.dumps(CHAT_LINES[0]).encode() + b"\n")
            self.server.released_in_time = self.server.release.wait(5)
            for line in CHAT_LINES[1:]:
                self.chunk(json.dumps(line).encode() + b"\n")
            self.wfile.write(b"0\r\n\r\n")
            return
        self.send_json({"status": "success"})


class Env:
    def __init__(self, tmp_path):
        self.ollama = FakeOllama()
        self.state = str(tmp_path / "cfg" / "state.json")
        self.running = []
        self.terminal = io.StringIO()
        self.terminal.close = lambda: None
        self.run(self.ollama)

    def run(self, server):
        threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
        self.running.append(server)

    def start(self, *extra, ollama_url=None, terminal=True):
        url = ollama_url or f"http://127.0.0.1:{self.ollama.server_address[1]}"
        server, node = harvis_node.make_server(
            ["--listen", "127.0.0.1:0", "--ollama", url, "--name", "testbox",
             "--state", self.state, *extra],
            terminal=(lambda: self.terminal) if terminal is True else terminal)
        self.run(server)
        return Client(server.server_address[1]), node

    def stop(self):
        for server in self.running:
            server.shutdown()
            server.server_close()


class Client:
    def __init__(self, port):
        self.port = port

    def open(self, method, path, body=None, token=None, headers=None):
        hdrs = dict(headers or {})
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body, hdrs)
        return conn, conn.getresponse()

    def call(self, *args, **kwargs):
        conn, resp = self.open(*args, **kwargs)
        data = resp.read()
        conn.close()
        return resp.status, (json.loads(data) if data else None)

    def pair(self, pin, hub_name="Test Hub"):
        return self.call("POST", "/harvis-node/pair", {"pin": pin, "hub_name": hub_name})


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.stop()


def wrong_pin(node):
    return "%06d" % ((int(node.current_pin()) + 1) % 10**6)


def paired_client(env, *extra):
    client, node = env.start(*extra)
    status, body = client.pair(node.current_pin())
    assert status == 200
    return client, node, body["token"]


def test_info_unpaired_and_paired(env):
    client, node = env.start()
    status, body = client.call("GET", "/harvis-node/info")
    assert status == 200
    assert body == {"name": "testbox", "version": "1", "paired": False, "dialect": "ollama"}
    assert node.current_pin() not in json.dumps(body)

    status, pair = client.pair(node.current_pin())
    assert status == 200
    status, body = client.call("GET", "/harvis-node/info")
    assert body["paired"] is True
    assert set(body) == {"name", "version", "paired", "dialect"}
    assert pair["token"] not in json.dumps(body)


def test_wrong_pin_counts_down(env):
    client, node = env.start()
    for left in (4, 3, 2, 1):
        status, body = client.pair(wrong_pin(node))
        assert (status, body["tries_left"]) == (403, left)
        assert body["detail"] == "That PIN is not right."
    status, body = client.call("POST", "/harvis-node/pair", {"pin": node.current_pin()})
    assert status == 200


def test_five_wrong_pins_retire_the_pin(env):
    client, node = env.start()
    for _ in range(4):
        client.pair(wrong_pin(node))
    status, body = client.pair(wrong_pin(node))
    assert status == 403
    assert "new PIN is on" in body["detail"]
    assert node.current_pin() is not None
    status, body = client.pair(node.current_pin())
    assert status == 200 and "token" in body


def test_pair_success_stores_only_a_hash(env):
    client, node = env.start()
    status, body = client.pair(node.current_pin(), "Lab Hub")
    assert status == 200
    assert body["name"] == "testbox" and body["dialect"] == "ollama"
    token = body["token"]
    assert len(token) >= 43

    text = open(env.state, encoding="utf-8").read()
    saved = json.loads(text)["paired"]
    assert saved["token_sha256"] == harvis_node.sha256_hex(token)
    assert saved["hub_name"] == "Lab Hub" and saved["paired_at"]
    assert token not in text and '"pin"' not in text
    assert stat.S_IMODE(os.stat(env.state).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(env.state)).st_mode) == 0o700
    assert node.current_pin() is None


def test_bad_pair_body_is_400(env):
    client, _ = env.start()
    status, _ = client.call("POST", "/harvis-node/pair", b"not json")
    assert status == 400
    status, _ = client.call("POST", "/harvis-node/pair", {"pin": 123456})
    assert status == 400


def test_second_pair_is_409(env):
    client, node, _ = paired_client(env)
    status, body = client.pair("000000")
    assert status == 409
    assert body["detail"] == ("This computer is already paired. "
                              "Run it with --repair to pair again.")


def test_restart_keeps_pairing_and_repair_resets_it(env):
    client, node, token = paired_client(env)
    again, node2 = env.start()
    assert node2.current_pin() is None
    assert again.call("GET", "/api/tags", token=token)[0] == 200

    fresh, node3 = env.start("--repair")
    assert node3.current_pin() is not None
    assert fresh.call("GET", "/harvis-node/info")[1]["paired"] is False
    assert fresh.call("GET", "/api/tags", token=token)[0] == 401
    status, body = fresh.pair(node3.current_pin())
    assert status == 200 and body["token"] != token
    assert fresh.call("GET", "/api/tags", token=body["token"])[0] == 200


def test_proxy_requires_the_token(env):
    client, node = env.start()
    assert client.call("GET", "/api/tags")[0] == 401
    client.pair(node.current_pin())
    status, body = client.call("GET", "/api/tags")
    assert status == 401 and body["detail"]
    assert client.call("GET", "/api/tags", token="wrong")[0] == 401
    assert client.call("GET", "/api/tags", headers={"Authorization": "Basic abc"})[0] == 401


def test_tags_proxied_with_query(env):
    client, _, token = paired_client(env)
    status, body = client.call("GET", "/api/tags?verbose=1", token=token)
    assert (status, body) == (200, MODELS)
    assert env.ollama.seen[-1][:2] == ("GET", "/api/tags?verbose=1")


def test_post_body_and_content_type_forwarded(env):
    client, _, token = paired_client(env)
    payload = {"model": "llama3:8b"}
    status, _ = client.call("POST", "/api/show", payload, token=token)
    assert status == 200
    method, path, body, ctype = env.ollama.seen[-1]
    assert (method, path, json.loads(body), ctype) == (
        "POST", "/api/show", payload, "application/json")


def test_chat_is_streamed_not_buffered(env):
    client, _, token = paired_client(env)
    conn, resp = client.open("POST", "/api/chat", {"model": "llama3:8b"}, token=token)
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "application/x-ndjson"
    first = json.loads(resp.readline())
    assert first == CHAT_LINES[0]
    env.ollama.release.set()
    rest = [json.loads(line) for line in resp.read().splitlines()]
    conn.close()
    assert [first, *rest] == CHAT_LINES
    assert env.ollama.released_in_time is True


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/api/delete"), ("POST", "/api/delete"), ("POST", "/api/pull"),
    ("POST", "/api/copy"), ("GET", "/"), ("GET", "/harvis-node/other"),
    ("POST", "/api/tags"), ("GET", "/api/chat"),
])
def test_paths_outside_allow_list_are_403(env, method, path):
    client, _, token = paired_client(env)
    status, body = client.call(method, path, b"{}" if method != "GET" else None, token=token)
    assert status == 403
    assert body == {"detail": "Not allowed through the Harvis node."}
    assert not [s for s in env.ollama.seen if s[1] == path]


def test_pull_allowed_with_flag(env):
    client, _, token = paired_client(env, "--allow-pull")
    status, body = client.call("POST", "/api/pull", {"model": "llama3:8b"}, token=token)
    assert (status, body) == (200, {"status": "success"})
    assert client.call("DELETE", "/api/delete", token=token)[0] == 403


def test_ollama_down_is_502(env):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    url = f"http://127.0.0.1:{dead}"
    client, node = env.start(ollama_url=url)
    token = client.pair(node.current_pin())[1]["token"]
    status, body = client.call("GET", "/api/tags", token=token)
    assert status == 502
    assert body == {"detail": f"Ollama is not answering at {url}."}


def test_body_over_cap_is_413(env):
    client, _, token = paired_client(env, "--max-body", "1024")
    ok, _ = client.call("POST", "/api/show", b"x" * 1024, token=token)
    assert ok == 200
    status, body = client.call("POST", "/api/show", b"x" * 4096, token=token)
    assert status == 413 and body["detail"]
    assert all(len(s[2]) <= 1024 for s in env.ollama.seen)


def test_oversize_body_without_token_is_401(env):
    client, _ = env.start("--max-body", "1024")
    assert client.call("POST", "/api/show", b"x" * 4096)[0] == 401


def test_pin_goes_to_the_terminal_only(env):
    _, node = env.start()
    shown = env.terminal.getvalue()
    assert f"PIN: {node.current_pin()}" in shown


def test_no_terminal_means_no_pin_printed(env, capfd):
    client, node = env.start(terminal=lambda: None)
    pin = node.current_pin()
    assert pin is not None
    out, err = capfd.readouterr()
    assert pin not in out + err + env.terminal.getvalue()
    assert ("Not paired yet. Run harvis_node.py in a terminal on this computer "
            "to see the pairing PIN.") in err
    assert client.call("GET", "/harvis-node/info")[1]["paired"] is False


def test_open_terminal_falls_back_to_none(monkeypatch):
    def no_tty(*a, **k):
        raise OSError
    monkeypatch.setattr("builtins.open", no_tty)
    monkeypatch.setattr(harvis_node.sys, "stderr", io.StringIO())
    assert harvis_node.open_terminal() is None


def test_print_state(env, capsys):
    args = ["--name", "testbox", "--state", env.state, "--print-state"]
    harvis_node.main(args)
    assert json.loads(capsys.readouterr().out) == {
        "paired": False, "name": "testbox", "hub_name": None}

    client, node, token = paired_client(env)
    harvis_node.main(args)
    out = capsys.readouterr().out
    assert json.loads(out) == {"paired": True, "name": "testbox", "hub_name": "Test Hub"}
    assert token not in out and "sha256" not in out
