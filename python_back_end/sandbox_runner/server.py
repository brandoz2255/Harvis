"""HTTP front for the document sandbox. Standard library only.

    GET  /health
    POST /run     {code, timeout?, files?: [{name, b64}]}
    POST /render  {b64, ext: pptx|docx|xlsx|pdf, max_pages?, scale?, want_pdf?}
    POST /recalc  {b64}  -> the .xlsx with every formula's value stored

Whoever can reach this port can run Python, so it has no host port and sits on an
internal network shared only with the backend and the document worker.
"""
import ctypes
import json
import logging
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sandbox_runner import jobs, render

MAX_BODY = 20 * 1024 * 1024
# One job at a time: jobs share a uid and one /tmp, so a second job running beside the
# first could read or overwrite its files. Callers add SLOT_WAIT_S to their timeouts.
MAX_CONCURRENT = 1
SLOT_WAIT_S = 30
SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)
SWEEP_DIR = None  # set by main(); tests that use Handler directly must not empty a real /tmp
log = logging.getLogger("sandbox")


class Handler(BaseHTTPRequestHandler):
    server_version = "sandbox"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            self.reply(411, {"ok": False, "error": "Content-Length is required"})
            return None
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self.reply(413, {"ok": False, "error": "request body is over 20 MB"})
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self.reply(400, {"ok": False, "error": "body must be a JSON object"})
            return None
        return body

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"ok": True})
        else:
            self.reply(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path not in ("/run", "/render", "/recalc"):
            self.reply(404, {"ok": False, "error": "not found"})
            return
        body = self.read_json()
        if body is None:
            return
        if not SLOTS.acquire(timeout=SLOT_WAIT_S):
            self.reply(429, {"ok": False, "error": "the sandbox is busy; try again shortly"})
            return
        try:
            if self.path == "/run":
                result = jobs.run_python(body.get("code"), body.get("timeout", jobs.DEFAULT_TIMEOUT), body.get("files"))
            elif self.path == "/recalc":
                result = render.recalc(body.get("b64"))
            else:
                result = render.render(body.get("b64"), body.get("ext"), body.get("max_pages", 20),
                                       body.get("scale", 1.0), bool(body.get("want_pdf")))
            self.reply(200, result)
        except jobs.JobError as exc:
            self.reply(200, {"ok": False, "error": str(exc)})
        except Exception:  # noqa: BLE001 - never leak a traceback with paths to the caller
            log.exception("job failed")
            self.reply(500, {"ok": False, "error": "internal error in the sandbox"})
        finally:
            if SWEEP_DIR:
                jobs.sweep_dir(SWEEP_DIR)
            SLOTS.release()


def make_undumpable():
    """PR_SET_DUMPABLE 0, read back. Jobs run as this uid, so while the server is dumpable
    a job could ptrace it or open /proc/<pid>/mem and /proc/<pid>/environ; refusing to
    start is better than serving jobs next to a readable server."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:  # SET then GET_DUMPABLE
        raise OSError(ctypes.get_errno(), "cannot make the sandbox server non-dumpable")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    make_undumpable()
    global SWEEP_DIR
    SWEEP_DIR = tempfile.gettempdir()
    jobs.sweep_dir(SWEEP_DIR)
    port = int(os.environ.get("SANDBOX_PORT", "8080"))
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
