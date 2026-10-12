#!/usr/bin/env python3
"""Harvis inference node: share this computer's Ollama with a Harvis server.

Run it, read the PIN it prints, and type the PIN into Harvis. After pairing,
only requests carrying the issued bearer token reach Ollama. Standard library
only, Python 3.10+.
"""
import argparse
import hashlib
import hmac
import http.client
import json
import os
import secrets
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

VERSION = "1"
DIALECT = "ollama"
DEFAULT_LISTEN = "0.0.0.0:11437"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_STATE = "~/.config/harvis-node/state.json"
MAX_BODY = 32 * 1024 * 1024
PAIR_BODY_MAX = 4096
PIN_TRIES = 5
UPSTREAM_TIMEOUT = 600

ALLOWED = {
    ("GET", "/api/tags"), ("GET", "/api/version"), ("GET", "/api/ps"),
    ("POST", "/api/show"), ("POST", "/api/chat"), ("POST", "/api/generate"),
    ("POST", "/api/embed"), ("POST", "/api/embeddings"),
    ("GET", "/v1/models"), ("POST", "/v1/chat/completions"),
    ("POST", "/v1/completions"), ("POST", "/v1/embeddings"),
}
PULL = ("POST", "/api/pull")


def say(text, stream):
    try:
        print(text, file=stream, flush=True)
    except UnicodeEncodeError:
        print(text.replace("→", "->").encode("ascii", "replace").decode(),
              file=stream, flush=True)


def open_terminal():
    """A stream a person is looking at, or None. Never a log."""
    try:
        return open("/dev/tty", "w", encoding="utf-8")
    except OSError:
        return sys.stderr if sys.stderr.isatty() else None


def load_state(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            paired = json.load(f).get("paired")
    except (OSError, ValueError, AttributeError):
        return None
    ok = isinstance(paired, dict) and isinstance(paired.get("token_sha256"), str)
    return paired if ok else None


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Node:
    def __init__(self, name, ollama, state_path, allow_pull=False, repair=False,
                 max_body=MAX_BODY, terminal=open_terminal):
        self.name = name
        self._terminal = terminal
        self.ollama_url = ollama.rstrip("/")
        parts = urlsplit(self.ollama_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"--ollama must be an http(s) URL, got {ollama!r}")
        self._https = parts.scheme == "https"
        self._ollama_host = parts.hostname
        self._ollama_port = parts.port or (443 if self._https else 80)
        self.state_path = os.path.expanduser(state_path)
        self.allow_pull = allow_pull
        self.max_body = max_body
        self._lock = threading.Lock()
        self._pin = None
        self._tries = 0
        self._paired = load_state(self.state_path)
        if repair and self._paired:
            self._paired = None
            self._save()
        if not self._paired:
            self._new_pin()

    def _save(self):
        directory = os.path.dirname(self.state_path) or "."
        os.makedirs(directory, mode=0o700, exist_ok=True)
        tmp = self.state_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump({"version": 1, "paired": self._paired}, f, indent=2)
        os.replace(tmp, self.state_path)

    def _new_pin(self):
        self._pin = "%06d" % secrets.randbelow(10**6)
        self._tries = PIN_TRIES
        term = self._terminal()
        if term is None:
            say("Not paired yet. Run harvis_node.py in a terminal on this computer "
                "to see the pairing PIN.", sys.stderr)
            return
        say("Pair this computer from Harvis → Settings → Models → "
            f"Add a computer. PIN: {self._pin}", term)
        if term is not sys.stderr and hasattr(term, "close"):
            term.close()

    def current_pin(self):
        return self._pin

    @property
    def paired(self):
        return self._paired is not None

    def info(self):
        return {"name": self.name, "version": VERSION, "paired": self.paired,
                "dialect": DIALECT}

    def pair(self, pin, hub_name):
        with self._lock:
            if self._paired:
                return 409, {"detail": "This computer is already paired. "
                                       "Run it with --repair to pair again."}
            if hmac.compare_digest(pin.encode("utf-8"), self._pin.encode("utf-8")):
                token = secrets.token_urlsafe(32)
                self._paired = {
                    "token_sha256": sha256_hex(token),
                    "hub_name": hub_name,
                    "paired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                try:
                    self._save()
                except OSError:
                    self._paired = None
                    return 500, {"detail": "Could not save the pairing on this computer."}
                self._pin = None
                return 200, {"token": token, "name": self.name, "dialect": DIALECT}
            self._tries -= 1
            if self._tries <= 0:
                self._new_pin()
                return 403, {"detail": "Too many wrong PINs. A new PIN is on this "
                                       "computer's screen.", "tries_left": 0}
            return 403, {"detail": "That PIN is not right.", "tries_left": self._tries}

    def token_ok(self, token):
        paired = self._paired
        if not paired or not token:
            return False
        return hmac.compare_digest(sha256_hex(token).encode(),
                                   paired["token_sha256"].encode("utf-8", "replace"))

    def allows(self, method, path):
        return (method, path) in ALLOWED or (self.allow_pull and (method, path) == PULL)

    def upstream(self):
        cls = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
        return cls(self._ollama_host, self._ollama_port, timeout=UPSTREAM_TIMEOUT)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarvisNode/" + VERSION
    unread = False

    def log_message(self, *args):
        pass

    def reply(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if self.unread:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def bearer(self):
        value = self.headers.get("Authorization", "")
        scheme, _, token = value.partition(" ")
        return token.strip() if scheme.lower() == "bearer" else ""

    def handle_any(self):
        node = self.server.node
        method, url = self.command, urlsplit(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        self.unread = length != 0
        if length < 0 or self.headers.get("Transfer-Encoding"):
            return self.reply(400, {"detail": "Send a Content-Length, not a chunked body."})
        if method == "GET" and url.path == "/harvis-node/info":
            return self.reply(200, node.info())
        if method == "POST" and url.path == "/harvis-node/pair":
            return self.pair(node, length)
        if not node.token_ok(self.bearer()):
            return self.reply(401, {"detail": "Missing or wrong token. Pair this computer again."})
        if not node.allows(method, url.path):
            return self.reply(403, {"detail": "Not allowed through the Harvis node."})
        if length > node.max_body:
            return self.reply(413, {"detail": "Request body is too large."})
        body = self.rfile.read(length) if length else None
        self.unread = False
        self.proxy(node, method, url, body)

    def pair(self, node, length):
        if length > PAIR_BODY_MAX:
            return self.reply(413, {"detail": "Request body is too large."})
        raw = self.rfile.read(length)
        self.unread = False
        try:
            data = json.loads(raw)
            pin, hub = data["pin"], str(data.get("hub_name") or "")[:80]
            if not isinstance(pin, str):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"detail": 'Send JSON like {"pin": "123456", "hub_name": "..."}.'})
        self.reply(*node.pair(pin, hub))

    def proxy(self, node, method, url, body):
        target = url.path + ("?" + url.query if url.query else "")
        ctype = self.headers.get("Content-Type")
        conn = node.upstream()
        try:
            conn.request(method, target, body, {"Content-Type": ctype} if ctype else {})
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException):
            conn.close()
            return self.reply(502, {"detail": f"Ollama is not answering at {node.ollama_url}."})
        try:
            self.relay(resp)
        except (OSError, http.client.HTTPException):
            self.close_connection = True
        finally:
            conn.close()

    def relay(self, resp):
        has_body = resp.status not in (204, 304)
        length = resp.getheader("Content-Length")
        chunked = has_body and length is None and self.request_version != "HTTP/1.0"
        self.send_response(resp.status)
        if resp.getheader("Content-Type"):
            self.send_header("Content-Type", resp.getheader("Content-Type"))
        if has_body and length is not None:
            self.send_header("Content-Length", length)
        elif chunked:
            self.send_header("Transfer-Encoding", "chunked")
        elif has_body:
            self.send_header("Connection", "close")
        self.end_headers()
        while has_body:
            data = resp.read1(65536)
            if not data:
                break
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data) if chunked else data)
            self.wfile.flush()
        if chunked:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = handle_any


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="harvis_node.py",
        description="Share this computer's Ollama with a Harvis server after PIN pairing.")
    p.add_argument("--listen", default=DEFAULT_LISTEN, metavar="HOST:PORT",
                   help="address to serve on (default %(default)s)")
    p.add_argument("--ollama", default=DEFAULT_OLLAMA, metavar="URL",
                   help="local Ollama to forward to (default %(default)s)")
    p.add_argument("--name", default=socket.gethostname(),
                   help="name shown in Harvis (default: this computer's hostname)")
    p.add_argument("--state", default=DEFAULT_STATE, metavar="PATH",
                   help="pairing state file, mode 0600 (default %(default)s)")
    p.add_argument("--allow-pull", action="store_true",
                   help="let Harvis download models through POST /api/pull")
    p.add_argument("--repair", action="store_true",
                   help="forget the current pairing and show a new PIN")
    p.add_argument("--print-state", action="store_true",
                   help="print the pairing state as JSON and exit")
    p.add_argument("--max-body", type=int, default=MAX_BODY, metavar="BYTES",
                   help="largest request body accepted (default %(default)s)")
    args = p.parse_args(argv)
    host, sep, port = args.listen.rpartition(":")
    if not sep or not port.isdigit() or int(port) > 65535:
        p.error("--listen must look like HOST:PORT")
    args.host, args.port = host, int(port)
    return args


def make_server(argv=None, terminal=open_terminal):
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    try:
        server.node = Node(args.name, args.ollama, args.state, args.allow_pull,
                           args.repair, args.max_body, terminal)
    except ValueError as exc:
        server.server_close()
        raise SystemExit(f"harvis_node.py: error: {exc}")
    return server, server.node


def stop(*_):
    raise KeyboardInterrupt


def main(argv=None):
    args = parse_args(argv)
    if args.print_state:
        paired = load_state(args.state)
        print(json.dumps({"paired": paired is not None, "name": args.name,
                          "hub_name": paired.get("hub_name") if paired else None}))
        return
    try:
        server, node = make_server(argv)
    except OSError as exc:
        raise SystemExit(f"harvis_node.py: cannot listen: {exc}")
    signal.signal(signal.SIGTERM, stop)
    host, port = server.server_address[:2]
    state = "paired" if node.paired else "waiting to be paired"
    print(f"Harvis node '{node.name}' listening on {host}:{port} ({state})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
