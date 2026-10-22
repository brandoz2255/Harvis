"""Document code goes to the sandbox over HTTP and is never run in this process."""

import base64
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artifacts import code_generator as cg  # noqa: E402

CODE = "with open(OUTPUT_PATH, 'wb') as fh:\n    fh.write(b'PK-fake-xlsx')"


@pytest.fixture(autouse=True)
def sandbox_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_EXECUTOR_URL", "http://sandbox:8080/")
    monkeypatch.setattr(cg, "ARTIFACT_DIR", str(tmp_path))


def reply(files=(), ok=True, **extra):
    return {"ok": ok, "returncode": 0 if ok else 1, "stdout": "", "stderr": "",
            "files": [{"name": n, "b64": base64.b64encode(b).decode()} for n, b in files], **extra}


def test_file_from_the_sandbox_is_stored_under_the_artifact_dir(monkeypatch, tmp_path):
    seen = {}

    def fake(url, payload, timeout):
        seen.update(url=url, payload=payload, timeout=timeout)
        return reply([("Report.xlsx", b"PK-bytes")], stdout="SUCCESS\n")

    monkeypatch.setattr(cg, "_post_to_sandbox", fake)
    out = cg.execute_document_code(CODE, "art-1", "Report.xlsx", timeout=30)
    assert out["success"] and out["file_size"] == 8 and out["stdout"] == "SUCCESS\n"
    assert out["file_path"] == str(tmp_path / "art-1" / "Report.xlsx")
    assert (tmp_path / "art-1" / "Report.xlsx").read_bytes() == b"PK-bytes"
    assert not list((tmp_path / "art-1").glob("*.part"))
    assert seen["url"] == "http://sandbox:8080" and seen["timeout"] == 30 and seen["payload"]["timeout"] == 30


def test_script_writes_into_the_jobs_output_dir_not_a_host_path(monkeypatch):
    sent = {}
    monkeypatch.setattr(cg, "_post_to_sandbox", lambda u, p, t: sent.update(p) or reply())
    cg.execute_document_code(CODE, "art-2", "Deck.pptx")
    prepared = sent["code"]
    assert 'os.environ.get("OUTPUT_DIR", "out")' in prepared and "'Deck.pptx'" in prepared
    assert "/data/artifacts" not in prepared and CODE in prepared


def test_prepared_script_really_produces_the_file_in_the_real_runner(monkeypatch):
    from sandbox_runner import jobs

    monkeypatch.setattr(cg, "_post_to_sandbox", lambda u, p, t: jobs.run_python(p["code"], p["timeout"]))
    out = cg.execute_document_code(CODE, "art-3", "Real.xlsx")
    assert out["success"], out
    assert open(out["file_path"], "rb").read() == b"PK-fake-xlsx" and "SUCCESS" in out["stdout"]


def test_unset_url_uses_the_sandbox_service_and_never_spawns_a_process(monkeypatch):
    monkeypatch.delenv("CODE_EXECUTOR_URL")
    seen = []

    def boom(*a, **k):
        raise AssertionError("document code must not run locally")

    def unreachable(url, payload, timeout):
        seen.append(url)
        raise urllib.error.URLError("refused")

    import subprocess
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(cg, "_post_to_sandbox", unreachable)
    out = cg.execute_document_code(CODE, "art-4", "x.xlsx")
    assert seen == ["http://sandbox:8080"]
    assert not out["success"] and "the document sandbox is not running" in out["error"]
    assert out["file_path"] is None and out["file_size"] == 0


@pytest.mark.parametrize("exc", [urllib.error.URLError("refused"), ConnectionRefusedError(),
                                 json.JSONDecodeError("bad", "", 0)])
def test_unreachable_sandbox_is_a_clear_error(monkeypatch, exc):
    def fake(*a):
        raise exc

    monkeypatch.setattr(cg, "_post_to_sandbox", fake)
    out = cg.execute_document_code(CODE, "art-5", "x.xlsx")
    assert not out["success"] and "the document sandbox is not running" in out["error"]


@pytest.mark.parametrize("exc", [TimeoutError(), urllib.error.URLError(TimeoutError("timed out"))])
def test_a_slow_sandbox_is_busy_not_down(monkeypatch, exc):
    def fake(*a):
        raise exc

    monkeypatch.setattr(cg, "_post_to_sandbox", fake)
    out = cg.execute_document_code(CODE, "art-5", "x.xlsx")
    assert not out["success"] and "busy" in out["error"] and "not running" not in out["error"]


def test_http_429_is_busy(monkeypatch):
    def fake(*a):
        raise urllib.error.HTTPError("u", 429, "busy", {}, None)

    monkeypatch.setattr(cg, "_post_to_sandbox", fake)
    out = cg.execute_document_code(CODE, "art-5", "x.xlsx")
    assert not out["success"] and "busy" in out["error"]


def test_client_waits_longer_than_the_sandbox_queues_plus_runs(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return b"{}"

    def fake_open(req, timeout):
        seen["timeout"] = timeout
        return Resp()

    monkeypatch.setattr(cg.urllib.request, "urlopen", fake_open)
    cg._post_to_sandbox("http://sandbox:8080", {}, 60)
    assert seen["timeout"] >= cg.SANDBOX_SLOT_WAIT + 60


def test_http_error_from_the_sandbox_is_reported(monkeypatch):
    def fake(*a):
        raise urllib.error.HTTPError("u", 413, "too big", {}, None)

    monkeypatch.setattr(cg, "_post_to_sandbox", fake)
    out = cg.execute_document_code(CODE, "art-6", "x.xlsx")
    assert not out["success"] and "HTTP 413" in out["error"]


def test_script_failure_carries_stderr_through(monkeypatch):
    monkeypatch.setattr(cg, "_post_to_sandbox", lambda *a: reply(ok=False, stderr="Traceback...\nKeyError: 'x'\n",
                                                                  error="x"))
    out = cg.execute_document_code(CODE, "art-7", "x.xlsx")
    assert not out["success"] and "KeyError" in out["stderr"] and out["returncode"] == 1


def test_missing_output_file_is_reported(monkeypatch):
    monkeypatch.setattr(cg, "_post_to_sandbox", lambda *a: reply([("other.txt", b"x")]))
    out = cg.execute_document_code(CODE, "art-8", "x.xlsx")
    assert not out["success"] and "output file was not created" in out["error"]


def test_corrupt_base64_is_rejected(monkeypatch):
    monkeypatch.setattr(cg, "_post_to_sandbox", lambda *a: {"ok": True, "files": [{"name": "x.xlsx", "b64": "@@"}]})
    out = cg.execute_document_code(CODE, "art-9", "x.xlsx")
    assert not out["success"] and "could not be decoded" in out["error"]


@pytest.mark.parametrize("name", ["../evil.xlsx", "a/b.xlsx", ""])
def test_output_filename_cannot_escape_the_artifact_dir(monkeypatch, name):
    monkeypatch.setattr(cg, "_post_to_sandbox", lambda *a: pytest.fail("must not reach the sandbox"))
    assert not cg.execute_document_code(CODE, "art-10", name)["success"]


def test_local_execution_code_is_gone():
    for gone in ("_execute_locally", "_execute_in_docker", "_execute_in_k8s", "CODE_EXECUTOR_LOCAL", "subprocess"):
        assert not hasattr(cg, gone)


def test_full_pipeline_from_an_llm_response(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "_post_to_sandbox", lambda u, p, t: reply([("Q3 Budget.xlsx", b"PK-x")]))
    llm = f"Here you go:\n```python\nimport openpyxl\n{CODE}\n```\n"
    out = cg.generate_document_from_code(llm, "spreadsheet", "Q3 Budget", "art-11", use_docker=False)
    assert out["success"] and out["artifact_id"] == "art-11" and out["mime_type"].endswith("spreadsheetml.sheet")
    assert out["file_path"] == str(tmp_path / "art-11" / "Q3 Budget.xlsx")
