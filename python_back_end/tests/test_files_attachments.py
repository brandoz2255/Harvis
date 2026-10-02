"""Attachments reach the model as something it can be honest about.

A 50,000-row CSV used to go in as its first 24,000 characters with a bare
``…[truncated]``; the model then invented totals. PDFs went in as raw bytes. A
file whose bytes were gone after a restart was silently skipped. The upload route
read everything into memory with no cap of its own. These tests pin the fixes.

Run inside the backend container (see the task note for the symlink-tree recipe):
    python -m pytest tests/test_files_attachments.py -q
"""
from __future__ import annotations

import asyncio
import importlib
import io
import os
import random
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from owui_compat import file_content, upload_store

CAP = file_content.MAX_TEXT_FILE_CHARS


def run(coro):
    return asyncio.run(coro)


# ── fixtures: real file bytes of each kind ───────────────────────────────────
def _big_csv(rows: int = 50_000) -> tuple[bytes, list[float]]:
    rnd = random.Random(7)
    amounts = []
    lines = ["id,name,city,amount"]
    for i in range(1, rows + 1):
        amt = round(rnd.uniform(100, 50_000), 2) if i != 10 else 1234.56
        amounts.append(amt)
        city = ["Reno", "Kyoto", "Oslo"][i % 3]
        lines.append(f"{i},Person {i:06d},{city},{amt:.2f}")
    lines[-1] = f"{rows},LAST-ROW-SENTINEL,Oslo,{amounts[-1]:.2f}"
    return ("\r\n".join(lines) + "\r\n").encode(), amounts


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# ── classification ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,ctype,kind", [
    ("sales.csv", "application/octet-stream", "table"),
    ("sales.tsv", "text/tab-separated-values", "table"),
    ("book.xlsx", "application/octet-stream", "xlsx"),
    ("memo.pdf", "application/pdf", "pdf"),
    ("report", "application/pdf", "pdf"),
    ("notes.docx", "", "docx"),
    ("deck.pptx", "", "pptx"),
    ("photo.png", "image/png", "image"),
    ("talk.mp3", "audio/mpeg", "media"),
    ("readme.md", "text/markdown", "text"),
])
def test_classify(name, ctype, kind):
    assert file_content.classify(name, ctype) == kind


# ── large CSV: exact overview + visible partial-view note ────────────────────
def test_large_csv_gets_exact_overview_and_partial_note():
    raw, amounts = _big_csv()
    text = file_content.render_attachment("sales.csv", "text/csv", raw)

    assert len(text) <= CAP + 200, "stays inside the context budget"
    assert "Rows: 50,000 data rows" in text
    assert "Columns: 4" in text
    assert f"min {min(amounts):,.2f}" in text and f"max {max(amounts):,.2f}" in text
    assert f"mean {sum(amounts) / len(amounts):,.2f}" in text
    assert f"sum {sum(amounts):,.2f}" in text
    assert "id — integer; min 1, max 50,000" in text
    assert "city — text; 3 distinct" in text
    assert "PARTIAL VIEW" in text and "of 50,000 rows are reproduced" in text
    assert "Do NOT estimate totals" in text
    assert "LAST-ROW-SENTINEL" in text, "the last rows are shown even when the middle is cut"
    assert "1234.56" in text, "row 10 is inside the head excerpt"
    assert "…[truncated]" not in text
    shown = int(text.split("only ")[1].split(" of ")[0].replace(",", ""))
    assert 100 < shown < 50_000


def test_small_csv_goes_in_whole_with_counts():
    raw = b"name,city,amount\nPico Sentinel,Kyoto,4321.75\nAda,Reno,10.00\n"
    text = file_content.render_attachment("small.csv", "text/csv", raw)
    assert "Rows: 2 data rows" in text
    assert "Pico Sentinel,Kyoto,4321.75" in text
    assert "nothing omitted" in text
    assert "PARTIAL VIEW" not in text


def test_tsv_delimiter_and_empty_cells():
    raw = "a\tb\n1\t\n2\tx\n3\ty\n".encode()
    text = file_content.render_attachment("t.tsv", "", raw)
    assert "(TSV," in text
    assert "a — integer; min 1, max 3" in text
    assert "1 empty" in text


def test_empty_csv_is_said_not_crashed():
    assert "empty" in file_content.render_attachment("e.csv", "text/csv", b"")


# ── xlsx / pdf / docx / pptx go through text extraction ─────────────────────
def test_xlsx_first_sheet_profiled_other_sheets_named():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["sku", "qty"])
    for i in range(1, 2001):
        ws.append([f"S{i}", i])
    wb.create_sheet("Notes").append(["ignored"])
    buf = io.BytesIO()
    wb.save(buf)
    text = file_content.render_attachment("book.xlsx", "application/octet-stream", buf.getvalue())
    assert "Excel workbook" in text
    assert "Sheet shown: 'Data'" in text and "'Notes'" in text
    assert "Rows: 2,000 data rows" in text
    assert "qty — integer; min 1, max 2,000, mean 1,000.50, sum 2,001,000" in text
    assert "S2000" in text


def test_pdf_is_text_not_bytes():
    pytest.importorskip("pypdf")
    text = file_content.render_attachment("invoice.pdf", "application/pdf", _minimal_pdf("Invoice total 42.00"))
    assert "Invoice total 42.00" in text
    assert "%PDF" not in text and "obj" not in text
    assert "1 page(s)" in text


def test_pdf_without_text_is_declared():
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    text = file_content.render_attachment("scan.pdf", "application/pdf", buf.getvalue())
    assert "no extractable text" in text


def test_docx_paragraphs_and_tables():
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("Code word PLUMBAGO-4471")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "k", "v"
    buf = io.BytesIO()
    d.save(buf)
    text = file_content.render_attachment("memo.docx", "", buf.getvalue())
    assert "PLUMBAGO-4471" in text and "k\tv" in text
    assert "PK\x03" not in text


def test_pptx_slide_text():
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Quarterly plan"
    buf = io.BytesIO()
    prs.save(buf)
    text = file_content.render_attachment("deck.pptx", "", buf.getvalue())
    assert "Quarterly plan" in text and "slide 1" in text


def test_unreadable_document_is_a_note_not_bytes():
    text = file_content.render_attachment("broken.docx", "", b"not a zip at all")
    assert "could not extract text" in text
    assert "not a zip" not in text


# ── plain text keeps its old shape, except the cut is now spelled out ───────
def test_small_text_unchanged():
    text = file_content.render_attachment("memo.txt", "text/plain", b"code word PLUMBAGO-4471\n")
    assert text == "### Attached file: memo.txt\ncode word PLUMBAGO-4471\n"


def test_long_text_cut_is_visible_with_counts():
    raw = ("x" * 100 + "\n") * 500
    text = file_content.render_attachment("big.txt", "text/plain", raw.encode())
    assert len(text) < CAP + 600
    assert "PARTIAL VIEW" in text
    assert f"{len(raw):,} characters" in text
    assert f"first {CAP:,} are shown" in text
    assert "…[truncated]" not in text


# ── _inject_files: missing file → visible note; CSV row → overview ──────────
class _FakePool:
    def __init__(self, row):
        self.row = row

    @asynccontextmanager
    async def acquire(self):
        pool = self

        class Conn:
            async def fetchrow(self, sql, fid, uid):
                return pool.row if pool.row and pool.row["_uid"] == uid else None

        yield Conn()


def _request(row):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=_FakePool(row))))


def _body():
    return {"files": [{"type": "file", "id": "f1"}],
            "messages": [{"role": "user", "content": "What is in the file?"}]}


def _injected_text(body) -> str:
    content = body["messages"][-1]["content"]
    assert isinstance(content, list)
    return " ".join(p["text"] for p in content if p.get("type") == "text")


def test_inject_missing_file_adds_reupload_note(tmp_path, caplog):
    cc = importlib.import_module("owui_compat.chat_completion")
    row = {"filename": "gone.csv", "path": str(tmp_path / "gone.csv"), "content_type": "text/csv", "_uid": 7}
    body = _body()
    with caplog.at_level("WARNING"):
        run(cc._inject_files(_request(row), body, user_id=7))
    text = _injected_text(body)
    assert "gone.csv" in text and "no longer available" in text and "re-upload" in text
    assert any("has a DB row but no file" in r.message for r in caplog.records)


def test_inject_csv_row_uses_overview(tmp_path):
    cc = importlib.import_module("owui_compat.chat_completion")
    raw, _ = _big_csv(5_000)
    p = tmp_path / "f1.csv"
    p.write_bytes(raw)
    row = {"filename": "sales.csv", "path": str(p), "content_type": "application/octet-stream", "_uid": 7}
    body = _body()
    run(cc._inject_files(_request(row), body, user_id=7))
    text = _injected_text(body)
    assert "Rows: 5,000 data rows" in text and "PARTIAL VIEW" in text
    assert "LAST-ROW-SENTINEL" in text


def test_inject_skips_other_users_file(tmp_path):
    cc = importlib.import_module("owui_compat.chat_completion")
    p = tmp_path / "f1.txt"
    p.write_bytes(b"secret")
    row = {"filename": "f1.txt", "path": str(p), "content_type": "text/plain", "_uid": 8}
    body = _body()
    run(cc._inject_files(_request(row), body, user_id=7))
    assert body["messages"][-1]["content"] == "What is in the file?"


# ── upload route helpers: streamed, capped, no half-written file ─────────────
def _upload(data: bytes):
    from starlette.datastructures import UploadFile
    return UploadFile(io.BytesIO(data), filename="x.bin")


def test_save_upload_streams_and_counts(tmp_path):
    dest = tmp_path / "ok.bin"
    data = os.urandom(3 * (1 << 20) + 17)
    assert run(upload_store.save_upload(_upload(data), str(dest), 4 << 20)) == len(data)
    assert dest.read_bytes() == data


def test_save_upload_over_limit_is_413_material_and_leaves_nothing(tmp_path):
    dest = tmp_path / "big.bin"
    with pytest.raises(upload_store.UploadTooLarge) as exc:
        run(upload_store.save_upload(_upload(b"a" * (3 << 20)), str(dest), 2 << 20))
    assert not dest.exists()
    assert "limited to 2 MB" in exc.value.message and "HARVIS_MAX_UPLOAD_MB" in exc.value.message


def test_max_upload_bytes_env(monkeypatch):
    monkeypatch.delenv("HARVIS_MAX_UPLOAD_MB", raising=False)
    assert upload_store.max_upload_bytes() == 50 << 20
    monkeypatch.setenv("HARVIS_MAX_UPLOAD_MB", "7")
    assert upload_store.max_upload_bytes() == 7 << 20
    monkeypatch.setenv("HARVIS_MAX_UPLOAD_MB", "junk")
    assert upload_store.max_upload_bytes() == 50 << 20


def test_content_length_precheck():
    limit = 50 << 20
    assert upload_store.content_length_exceeds({"content-length": str(limit + (2 << 20))}, limit)
    assert not upload_store.content_length_exceeds({"content-length": str(limit + 1000)}, limit)
    assert not upload_store.content_length_exceeds({}, limit)
