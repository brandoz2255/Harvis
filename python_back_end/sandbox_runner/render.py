"""Office file or PDF -> page images and text, using headless LibreOffice and pdfium."""
import base64
import binascii
import json
import os
import shutil
import signal
import sys
import tempfile

from sandbox_runner.jobs import (AS_LIMIT, CHILD, HARDEN_FAILED, HERE, NOFILE, OUTPUT_CAP, SAFE_PATH, JobError,
                                 child_env, prepare_job_dir, read_capped, scrub, supervise)

RASTER_JOB = os.path.join(HERE, "raster_job.py")
CONVERT_TIMEOUT = 90
RASTER_TIMEOUT = 60
MAX_PAGES = 30
DEFAULT_WIDTH = 1280
FORMATS = ("pptx", "docx", "xlsx", "pdf")
MAX_PNG_BYTES = 40 * 1024 * 1024  # all pages together; later pages are dropped past this


def to_pdf(data, ext, tmp):
    """Convert with soffice in a profile of its own; returns the PDF bytes."""
    src = os.path.join(tmp, f"input.{ext}")
    with open(src, "wb") as fh:
        fh.write(data)
    profile = os.path.join(tmp, "lo")
    env = {"PATH": SAFE_PATH, "HOME": tmp, "TMPDIR": os.path.join(tmp, "tmp"), "LANG": "C.UTF-8"}
    os.mkdir(env["TMPDIR"])
    # No RLIMIT_AS: LibreOffice maps far more address space than it ever touches.
    cmd = [sys.executable, "-I", CHILD, "exec", "0", str(CONVERT_TIMEOUT + 10), str(200 * 1024 * 1024), "1024", "--",
           "soffice", "--headless", "--norestore", "--nologo", f"-env:UserInstallation=file://{profile}",
           "--convert-to", "pdf", "--outdir", tmp, src]
    rc, reason = supervise(cmd, tmp, env, CONVERT_TIMEOUT, tmp,
                           os.path.join(tmp, "so.txt"), os.path.join(tmp, "se.txt"))
    if rc == HARDEN_FAILED:
        raise JobError("sandbox hardening failed; the file was not converted")
    if reason == "timeout":
        raise JobError(f"converting the file took longer than {CONVERT_TIMEOUT} seconds")
    pdf = os.path.join(tmp, "input.pdf")
    if rc != 0 or not os.path.isfile(pdf):
        detail = scrub(read_capped(os.path.join(tmp, "se.txt")), tmp).strip().splitlines()
        raise JobError("could not convert the file to PDF" + (f": {detail[-1][:200]}" if detail else ""))
    with open(pdf, "rb") as fh:
        return fh.read()


def rasterize(pdf_bytes, max_pages, width, tmp):
    """Run raster_job.py in a hardened child; returns (pages, page_count)."""
    rd = os.path.join(tmp, "raster")
    os.mkdir(rd)
    prepare_job_dir(rd)
    src, out = os.path.join(rd, "source.pdf"), os.path.join(rd, "out")
    with open(src, "wb") as fh:
        fh.write(pdf_bytes)
    env = child_env(rd)
    env.update(RASTER_PDF=src, RASTER_OUT=out, RASTER_MAX_PAGES=str(max_pages),
               RASTER_WIDTH=str(width), RASTER_BYTES_CAP=str(MAX_PNG_BYTES))
    cmd = [sys.executable, "-I", CHILD, "run", RASTER_JOB, str(AS_LIMIT), str(RASTER_TIMEOUT + 5),
           str(OUTPUT_CAP), str(NOFILE)]
    rc, reason = supervise(cmd, rd, env, RASTER_TIMEOUT, rd,
                           os.path.join(rd, "stdout.txt"), os.path.join(rd, "stderr.txt"))
    if rc == HARDEN_FAILED:
        raise JobError("sandbox hardening failed; the file was not rendered")
    if reason == "timeout":
        raise JobError(f"drawing the pages took longer than {RASTER_TIMEOUT} seconds")
    if reason == "disk" or rc == -signal.SIGKILL:
        raise JobError("the file is too large to draw")
    if rc == 2:
        raise JobError("the file is not a readable PDF")
    meta_path = os.path.join(out, "pages.json")
    if rc != 0 or not os.path.isfile(meta_path):
        raise JobError("could not draw the pages of the file")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    pages = []
    for p in meta["pages"]:
        with open(os.path.join(out, p["file"]), "rb") as fh:
            png = base64.b64encode(fh.read()).decode()
        pages.append({"png_b64": png, "width": p["width"], "height": p["height"], "text": p["text"]})
    return pages, meta["page_count"]


def render(b64, ext, max_pages=20, scale=1.0, want_pdf=False):
    ext = str(ext or "").lower().lstrip(".")
    if ext not in FORMATS:
        raise JobError("ext must be one of pptx, docx, xlsx, pdf")
    try:
        data = base64.b64decode(str(b64 or ""), validate=True)
    except (binascii.Error, ValueError):
        raise JobError("b64 is not valid base64") from None
    if not data.startswith(b"%PDF" if ext == "pdf" else b"PK"):
        raise JobError(f"the file is not a valid .{ext} file")
    try:
        max_pages = max(1, min(int(max_pages), MAX_PAGES))
        width = int(DEFAULT_WIDTH * max(0.25, min(float(scale), 2.0)))
    except (TypeError, ValueError, OverflowError):
        raise JobError("max_pages and scale must be numbers") from None
    tmp = tempfile.mkdtemp(prefix="render-")
    try:
        pdf = data if ext == "pdf" else to_pdf(data, ext, tmp)
        pages, count = rasterize(pdf, max_pages, width, tmp)
        out = {"ok": True, "pages": pages, "page_count": count}
        if want_pdf:
            out["pdf_b64"] = base64.b64encode(pdf).decode()
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
