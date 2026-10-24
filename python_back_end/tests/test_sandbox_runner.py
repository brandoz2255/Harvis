"""The document sandbox's server pieces, run without Docker.

Needs only the standard library, plus reportlab and pypdfium2 for the render tests;
the backend image has all of that. Converting pptx/docx/xlsx needs LibreOffice and is
exercised against the real image instead (docker exec harvis-sandbox ...).
"""

import base64
import io
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandbox_runner import child, jobs, render, server  # noqa: E402

OUT = 'os.environ["OUTPUT_DIR"]'


def run(code, **kw):
    return jobs.run_python(code, **kw)


def names(result):
    return {f["name"] for f in result["files"]}


# ── run_python ──────────────────────────────────────────────────────────────

def test_returns_files_written_to_output_dir():
    r = run(f'import os\nopen(os.path.join({OUT}, "a.bin"), "wb").write(b"hello")\nprint("done")')
    assert r["ok"] and r["returncode"] == 0 and r["stdout"] == "done\n"
    assert base64.b64decode(r["files"][0]["b64"]) == b"hello" and names(r) == {"a.bin"}


def test_environment_holds_no_host_variables():
    os.environ["SANDBOX_TEST_SECRET"] = "leak"
    try:
        r = run("import os, json\nprint(json.dumps(sorted(os.environ)))")
    finally:
        del os.environ["SANDBOX_TEST_SECRET"]
    keys = json.loads(r["stdout"])
    assert "SANDBOX_TEST_SECRET" not in keys
    assert {"OUTPUT_DIR", "HOME", "PATH", "MPLBACKEND"} <= set(keys)


def test_inet_sockets_are_refused_but_unix_sockets_work():
    r = run("""
import socket
for fam in (socket.AF_INET, socket.AF_INET6):
    try:
        socket.socket(fam, socket.SOCK_STREAM)
        print("opened", fam)
    except OSError as e:
        print("refused", e.errno)
a, b = socket.socketpair()
print("unix ok")
""")
    assert r["stdout"].splitlines() == ["refused 1", "refused 1", "unix ok"]


def test_cannot_leave_the_process_group():
    r = run('import os\ntry:\n    os.setsid()\n    print("escaped")\nexcept PermissionError:\n    print("blocked")')
    assert r["stdout"] == "blocked\n"


def test_infinite_loop_is_killed_at_the_timeout():
    r = run("while True:\n    pass", timeout=2)
    assert not r["ok"] and r["returncode"] == -9 and "timed out" in r["error"]


def test_children_do_not_outlive_the_job():
    r = run("import subprocess\nsubprocess.Popen(['sleep', '307'])\nprint('spawned')")
    assert r["ok"] and r["stdout"] == "spawned\n"
    alive = [p for p in os.listdir("/proc") if p.isdigit() and b"sleep\x00307" in _cmdline(p)]
    assert alive == []


def _cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def test_memory_limit_stops_a_runaway_allocation():
    r = run("x = bytearray(4 * 1024**3)\nprint(len(x))")
    assert not r["ok"] and "MemoryError" in r["stderr"]


def test_oversized_stdout_is_truncated():
    r = run("print('x' * 200000)")
    assert r["ok"] and len(r["stdout"]) < jobs.STREAM_CAP + 50 and r["stdout"].endswith("[truncated]")


def test_traceback_is_the_scripts_own_and_names_no_host_path():
    r = run("def f():\n    raise ValueError('boom')\nf()")
    assert not r["ok"] and r["returncode"] == 1
    assert "ValueError: boom" in r["stderr"] and "script.py" in r["stderr"]
    assert "child.py" not in r["stderr"] and "runpy" not in r["stderr"] and "/tmp/" not in r["stderr"]


def test_symlinks_and_subdirectories_in_out_are_not_returned():
    r = run(f"""
import os
out = {OUT}
open(os.path.join(out, "real.txt"), "w").write("x")
os.symlink("/etc/passwd", os.path.join(out, "link.txt"))
os.mkdir(os.path.join(out, "sub"))
open(os.path.join(out, "sub", "deep.txt"), "w").write("x")
""")
    assert names(r) == {"real.txt"}


def test_output_over_the_cap_is_an_error(monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_CAP", 1000)
    r = run(f"""
import os
for i in range(3):
    open(os.path.join({OUT}, f"f{{i}}.bin"), "wb").write(b"0" * 400)
""")
    assert not r["ok"] and "25 MB" in r["error"] and r["files"] == []


def test_input_files_are_readable_and_names_are_checked():
    data = base64.b64encode(b"csv,data").decode()
    r = run('import os\nprint(open(os.path.join(os.environ["INPUT_DIR"], "in.csv")).read())',
            files=[{"name": "in.csv", "b64": data}])
    assert r["stdout"] == "csv,data\n"
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(jobs.JobError):
            run("pass", files=[{"name": bad, "b64": data}])
    with pytest.raises(jobs.JobError):
        run("pass", files=[{"name": "ok.txt", "b64": "!!not base64"}])


def test_job_directory_is_removed_afterwards():
    before = {d for d in os.listdir(jobs.tempfile.gettempdir()) if d.startswith("job-")}
    run("print(1)")
    after = {d for d in os.listdir(jobs.tempfile.gettempdir()) if d.startswith("job-")}
    assert after <= before


def test_timeout_is_clamped_and_code_is_required():
    with pytest.raises(jobs.JobError):
        run("   ")
    with pytest.raises(jobs.JobError):
        run(None)


# ── isolation between jobs ──────────────────────────────────────────────────

def test_one_job_at_a_time():
    assert server.MAX_CONCURRENT == 1 and server.SLOT_WAIT_S == 30


def test_sweep_empties_the_shared_tmp_whatever_the_modes(tmp_path):
    (tmp_path / "marker").write_text("left by a job")
    locked = tmp_path / "locked" / "inner"
    locked.mkdir(parents=True)
    (locked / "f").write_text("x")
    os.chmod(locked, 0)
    os.chmod(tmp_path / "locked", 0o500)
    (tmp_path / "link").symlink_to("/etc")
    jobs.sweep_dir(str(tmp_path))
    assert os.listdir(tmp_path) == []
    assert os.path.exists("/etc")


def test_server_sweeps_after_each_job(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "SWEEP_DIR", str(tmp_path))
    (tmp_path / "old").write_text("x")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        assert call(url, "/run", {"code": "print(1)"})[1]["ok"]
    finally:
        httpd.shutdown()
    assert os.listdir(tmp_path) == []


def test_a_job_that_fills_the_shared_disk_is_stopped(monkeypatch):
    monkeypatch.setattr(jobs, "free_bytes", lambda path: 0)
    out = run("import time\ntime.sleep(30)", timeout=30)
    assert not out["ok"] and "too much data" in out["error"]


# ── malformed /run input ────────────────────────────────────────────────────

@pytest.mark.parametrize("files", ["abc", {"name": "a"}, [1], [None], [{"name": "a.txt", "b64": "YQ=="}] * 2])
def test_bad_file_lists_are_refused_cleanly(files):
    with pytest.raises(jobs.JobError):
        run("pass", files=files)


def test_infinite_timeout_falls_back_to_the_default():
    assert run("print(1)", timeout=float("inf"))["ok"]


def test_http_gives_no_500_for_malformed_run_bodies(base):
    for body in ({"code": "pass", "files": "abc"}, {"code": "pass", "timeout": 1e400},
                 {"code": "pass", "files": [{"name": "a.txt", "b64": "YQ=="}] * 2}):
        status, reply = call(base, "/run", body)
        assert status == 200 and (reply["ok"] or "error" in reply), body


def test_render_refuses_infinite_max_pages():
    with pytest.raises(jobs.JobError):
        render.render(base64.b64encode(b"%PDF-1.4").decode(), "pdf", max_pages=float("inf"))


# ── render ──────────────────────────────────────────────────────────────────

def make_pdf(pages=3):
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(960, 540))
    for i in range(pages):
        c.drawString(72, 400, f"Page {i + 1} says #VALUE! here")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_pdf_pages_come_back_as_png_with_text():
    pytest.importorskip("pypdfium2")
    out = render.render(base64.b64encode(make_pdf(3)).decode(), "pdf", max_pages=2)
    assert out["ok"] and out["page_count"] == 3 and len(out["pages"]) == 2
    page = out["pages"][0]
    assert page["width"] == 1280 and page["height"] == 720
    assert base64.b64decode(page["png_b64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert "#VALUE!" in page["text"] and "pdf_b64" not in out


def test_render_can_hand_the_pdf_back():
    pytest.importorskip("pypdfium2")
    out = render.render(base64.b64encode(make_pdf(1)).decode(), "pdf", want_pdf=True, scale=0.5)
    assert out["pages"][0]["width"] == 640 and base64.b64decode(out["pdf_b64"])[:4] == b"%PDF"


def test_a_very_tall_page_is_scaled_down_not_rendered_at_full_width():
    pytest.importorskip("pypdfium2")
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(3, 14000))
    c.drawString(1, 100, "x")
    c.showPage()
    c.save()
    out = render.render(base64.b64encode(buf.getvalue()).decode(), "pdf")
    page = out["pages"][0]
    assert page["height"] <= 4 * 1280 + 1 and page["width"] * page["height"] < 8_000_000


def test_pages_stop_at_the_total_size_cap(monkeypatch):
    pytest.importorskip("pypdfium2")
    monkeypatch.setattr(render, "MAX_PNG_BYTES", 1)
    out = render.render(base64.b64encode(make_pdf(3)).decode(), "pdf")
    assert out["ok"] and out["pages"] == [] and out["page_count"] == 3


def test_rasterising_runs_in_the_hardened_child(monkeypatch):
    pytest.importorskip("pypdfium2")
    seen = []
    real = render.supervise

    def spy(cmd, *a, **k):
        seen.append(cmd)
        return real(cmd, *a, **k)

    monkeypatch.setattr(render, "supervise", spy)
    render.render(base64.b64encode(make_pdf(1)).decode(), "pdf")
    assert seen and seen[0][2:5] == [render.CHILD, "run", render.RASTER_JOB]


def test_unreadable_pdf_is_a_clean_error():
    pytest.importorskip("pypdfium2")
    with pytest.raises(jobs.JobError, match="not a readable PDF"):
        render.render(base64.b64encode(b"%PDF-1.4 junk").decode(), "pdf")


@pytest.mark.parametrize("ext,data", [("exe", b"PK1"), ("pptx", b"not a zip"), ("pdf", b"PK\x03\x04")])
def test_render_refuses_wrong_formats(ext, data):
    with pytest.raises(jobs.JobError):
        render.render(base64.b64encode(data).decode(), ext)


def test_render_refuses_bad_base64():
    with pytest.raises(jobs.JobError):
        render.render("%%%", "pdf")


# ── HTTP ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def base():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, payload=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(base + path, data=data, headers=headers or {"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_and_unknown_paths(base):
    assert call(base, "/health") == (200, {"ok": True})
    assert call(base, "/nope")[0] == 404
    assert call(base, "/nope", {})[0] == 404


def test_run_over_http(base):
    status, body = call(base, "/run", {"code": f'import os\nopen(os.path.join({OUT}, "x.txt"), "w").write("hi")'})
    assert status == 200 and body["ok"] and body["files"][0]["name"] == "x.txt"


def test_bad_requests_are_refused_without_a_traceback(base):
    assert call(base, "/run", raw=b"not json")[0] == 400
    assert call(base, "/run", raw=b"[1]")[0] == 400
    status, body = call(base, "/run", {"code": ""})
    assert status == 200 and body == {"ok": False, "error": "code is required"}
    status, body = call(base, "/render", {"b64": "", "ext": "pdf"})
    assert status == 200 and not body["ok"] and "Traceback" not in json.dumps(body)


def test_recalc_is_routed_and_refuses_bad_input_cleanly(base):
    status, body = call(base, "/recalc", {"b64": "%%%"})
    assert status == 200 and body == {"ok": False, "error": "b64 is not valid base64"}
    status, body = call(base, "/recalc", {"b64": base64.b64encode(b"not a zip").decode()})
    assert status == 200 and body == {"ok": False, "error": "the file is not a valid .xlsx file"}


def test_oversized_body_is_refused_before_it_is_read(base):
    status, body = call(base, "/run", raw=b"{}", headers={"Content-Type": "application/json",
                                                           "Content-Length": str(server.MAX_BODY + 1)})
    assert status == 413 and "20 MB" in body["error"]


# ── backend-side render client ──────────────────────────────────────────────

def load_client():
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "plugins", "hermes_ui", "docs_render_client.py")
    spec = importlib.util.spec_from_file_location("docs_render_client_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_client_outwaits_the_sandbox_and_calls_a_slow_one_busy(monkeypatch):
    client = load_client()
    assert client.TIMEOUT_S >= server.SLOT_WAIT_S + render.CONVERT_TIMEOUT + render.RASTER_TIMEOUT

    def slow(req, timeout):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(client.urllib.request, "urlopen", slow)
    with pytest.raises(client.RenderUnavailable, match="busy"):
        client._post("http://sandbox:8080", {})

    def busy(req, timeout):
        raise urllib.error.HTTPError("u", 429, "busy", {}, None)

    monkeypatch.setattr(client.urllib.request, "urlopen", busy)
    with pytest.raises(client.RenderUnavailable, match="busy"):
        client._post("http://sandbox:8080", {})

    def down(req, timeout):
        raise urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr(client.urllib.request, "urlopen", down)
    with pytest.raises(client.RenderUnavailable, match="not running"):
        client._post("http://sandbox:8080", {})
