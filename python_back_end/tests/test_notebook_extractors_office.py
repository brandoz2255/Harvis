"""PowerPoint, Excel, ePub and scanned-PDF readers. Tiny fixtures are built in the test;
no network, model server or database. The OCR tests need the tesseract CLI (in the image)."""
import asyncio
import os
import shutil
import sys
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import extractors, extractors_office  # noqa: E402
from notebooks.extractors import IngestionError  # noqa: E402
from notebooks.models import SourceType  # noqa: E402
from notebooks.source_types import classify_upload  # noqa: E402

needs_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract is not installed")


def run(coro):
    return asyncio.run(coro)


def source(kind, path, ext=""):
    return SimpleNamespace(id=uuid4(), type=kind, storage_path=str(path), metadata={"extension": ext})


@pytest.mark.parametrize("name", ["deck.pptx", "book.xlsx", "macro.xlsm", "novel.epub"])
def test_office_files_are_accepted_as_doc_sources(name):
    kind, ext = classify_upload(name)
    assert kind == SourceType.DOC and ext == name.rsplit(".", 1)[1]


def test_unknown_binary_message_lists_the_new_kinds():
    from notebooks.source_types import UnsupportedFile

    with pytest.raises(UnsupportedFile) as err:
        classify_upload("x.exe", b"MZ\x00\x01")
    assert "PowerPoint" in str(err.value) and "ePub" in str(err.value)


# --- pptx ------------------------------------------------------------------------------


def make_pptx(path):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[1])
    first.shapes.title.text = "Cell biology"
    first.placeholders[1].text = "Mitochondria make ATP"
    first.notes_slide.notes_text_frame.text = "Mention the Krebs cycle"
    second = prs.slides.add_slide(prs.slide_layouts[5])
    second.shapes.title.text = "Organelles"
    rows = second.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    rows.cell(0, 0).text, rows.cell(0, 1).text = "Organelle", "Job"
    rows.cell(1, 0).text, rows.cell(1, 1).text = "Nucleus", "Holds DNA"
    prs.save(path)


def test_pptx_text_notes_tables_and_slide_offsets(tmp_path):
    f = tmp_path / "d.pptx"
    make_pptx(f)
    out = run(extractors.extract_document(source(SourceType.DOC, f, "pptx")))
    assert "Slide 1: Cell biology" in out.text and "Mitochondria make ATP" in out.text
    assert "Speaker notes: Mention the Krebs cycle" in out.text
    assert "Organelle | Job" in out.text and "Nucleus | Holds DNA" in out.text
    assert out.page_starts and len(out.page_starts) == 2
    assert out.text[out.page_starts[1]:].startswith("Slide 2: Organelles")


def test_pptx_with_only_pictures_is_an_honest_error(tmp_path):
    from pptx import Presentation

    f = tmp_path / "blank.pptx"
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(f)
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_document(source(SourceType.DOC, f, "pptx")))
    assert "No text" in str(err.value)


def test_damaged_office_file_says_what_to_do(tmp_path):
    f = tmp_path / "bad.pptx"
    f.write_bytes(b"not a zip at all")
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_document(source(SourceType.DOC, f, "pptx")))
    assert "damaged" in str(err.value)


# --- xlsx ------------------------------------------------------------------------------


def test_xlsx_sheets_become_pipe_tables_and_rows_are_capped(tmp_path, monkeypatch):
    import openpyxl

    f = tmp_path / "b.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Grades"
    ws.append(["Name", "Score"])
    ws.append(["Ada", 97])
    ws.append([None, None])
    ws.append(["Grace", 99])
    big = wb.create_sheet("Big")
    for i in range(10):
        big.append([f"row{i}", i])
    wb.save(f)
    monkeypatch.setattr(extractors_office, "XLSX_MAX_ROWS", 4)
    out = run(extractors.extract_document(source(SourceType.DOC, f, "xlsx")))
    assert "Sheet: Grades\nName | Score\nAda | 97\nGrace | 99" in out.text
    assert "row3" in out.text and "row4" not in out.text
    assert "first 4 rows of Big" in out.meta["ingest_notice"]
    assert out.page_starts is None


def test_empty_xlsx_is_an_error(tmp_path):
    import openpyxl

    f = tmp_path / "e.xlsx"
    openpyxl.Workbook().save(f)
    with pytest.raises(IngestionError):
        run(extractors.extract_document(source(SourceType.DOC, f, "xlsx")))


# --- epub ------------------------------------------------------------------------------

CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
    "</container>"
)
OPF = (
    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Tiny Book</dc:title></metadata><manifest>'
    '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
    '</manifest><spine><itemref idref="nav"/><itemref idref="c1"/><itemref idref="c2"/></spine></package>'
)


def chapter(body):
    return f"<html><body><article><p>{body}</p></article></body></html>"


def make_epub(path, extra=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/nav.xhtml", chapter("Table of contents entry that must not be read"))
        z.writestr("OEBPS/ch1.xhtml", chapter("Chapter one explains photosynthesis in leaves and algae today."))
        z.writestr("OEBPS/ch2.xhtml", chapter("Chapter two explains respiration in mitochondria of animal cells."))
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def test_epub_reads_spine_order_and_skips_the_nav_document(tmp_path):
    f = tmp_path / "b.epub"
    make_epub(f)
    out = run(extractors.extract_document(source(SourceType.DOC, f, "epub")))
    assert out.text.index("photosynthesis") < out.text.index("respiration")
    assert "must not be read" not in out.text
    assert out.meta["book_title"] == "Tiny Book" and out.meta["chapter_count"] == 2


def test_epub_without_container_is_an_error(tmp_path):
    f = tmp_path / "b.epub"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_document(source(SourceType.DOC, f, "epub")))
    assert "table of contents" in str(err.value)


def test_zip_that_expands_too_far_is_refused(tmp_path, monkeypatch):
    f = tmp_path / "b.epub"
    make_epub(f)
    monkeypatch.setattr(extractors_office, "ZIP_MAX_UNCOMPRESSED", 100)
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_document(source(SourceType.DOC, f, "epub")))
    assert "expands" in str(err.value)


def test_missing_office_file_says_upload_again(tmp_path):
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_document(source(SourceType.DOC, tmp_path / "gone.pptx", "pptx")))
    assert "upload it again" in str(err.value)


# --- PDF pages and OCR -------------------------------------------------------------------


def text_pdf(path, pages):
    """A PDF with a real text layer, one string per page, without extra dependencies."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    for i, page_text in enumerate(pages):
        content = f"BT /F1 12 Tf 50 700 Td ({page_text}) Tj ET"
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        )
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    out, offsets = "%PDF-1.4\n", []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


def scanned_pdf(path, lines):
    """An image-only PDF (no text layer), one page per string."""
    from PIL import Image, ImageDraw, ImageFont

    pages = []
    for line in lines:
        im = Image.new("RGB", (1400, 500), "white")
        ImageDraw.Draw(im).text((60, 60), line, fill="black", font=ImageFont.load_default(size=56))
        pages.append(im)
    pages[0].save(path, save_all=True, append_images=pages[1:])


def test_pdf_pages_and_offsets_follow_the_text_layer(tmp_path):
    f = tmp_path / "t.pdf"
    text_pdf(f, ["First page talks about mitochondria and energy.", "Second page talks about ribosomes and protein."])
    pages = run(extractors.extract_pdf_pages(str(f)))
    assert [n for n, _t in pages] == [1, 2] and "mitochondria" in pages[0][1]
    out = run(extractors.extract_pdf_document(str(f)))
    assert len(out.page_starts) == 2
    assert out.text[out.page_starts[1]:].startswith("Second page")
    assert "ocr" not in out.meta
    assert run(extractors.extract_pdf(str(f))) == out.text


@needs_tesseract
def test_scanned_pdf_is_read_with_ocr(tmp_path):
    f = tmp_path / "scan.pdf"
    scanned_pdf(f, ["Mitochondria are the powerhouse", "Ribosomes build proteins"])
    out = run(extractors.extract_pdf_document(str(f)))
    assert "powerhouse" in out.text and "Ribosomes" in out.text
    assert out.meta["ocr"] is True and out.meta["ocr_pages"] == 2
    assert len(out.page_starts) == 2 and "Ribosomes" in out.text[out.page_starts[1]:]


@needs_tesseract
def test_ocr_is_capped_and_says_what_it_skipped(tmp_path, monkeypatch):
    f = tmp_path / "scan.pdf"
    scanned_pdf(f, ["Alpha page one text here", "Beta page two text here", "Gamma page three text here"])
    monkeypatch.setenv("NOTEBOOK_OCR_MAX_PAGES", "1")
    out = run(extractors.extract_pdf_document(str(f)))
    assert "Alpha" in out.text and "Beta" not in out.text
    assert out.meta["ocr_pages"] == 1 and out.meta["ocr_skipped_pages"] == 2
    assert "NOTEBOOK_OCR_MAX_PAGES" in out.meta["ingest_notice"]


def test_ocr_stops_at_the_time_budget(tmp_path, monkeypatch):
    f = tmp_path / "scan.pdf"
    scanned_pdf(f, ["One page of text", "Two page of text"])
    monkeypatch.setattr(extractors_office.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(extractors_office, "_ocr_one_page", lambda *a, **k: "unreachable")
    monkeypatch.setenv("NOTEBOOK_OCR_MAX_SECONDS", "10")
    clock = iter([0.0, 100.0, 200.0, 300.0, 400.0])
    monkeypatch.setattr(extractors_office.time, "monotonic", lambda: next(clock))
    outcome = extractors_office.ocr_pdf_pages(str(f), [1, 2])
    assert outcome.timed_out and outcome.attempted == 0 and outcome.skipped == 2
    assert "stopped after" in outcome.meta()["ingest_notice"]


def test_scan_without_tesseract_gets_an_honest_message(tmp_path, monkeypatch):
    f = tmp_path / "scan.pdf"
    scanned_pdf(f, ["Some scanned page text"])
    monkeypatch.setattr(extractors_office.shutil, "which", lambda name: None)
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_pdf_document(str(f)))
    assert "scan" in str(err.value) and "tesseract" in str(err.value)


@needs_tesseract
def test_a_blank_scan_is_still_refused(tmp_path):
    from PIL import Image

    f = tmp_path / "blank.pdf"
    Image.new("RGB", (800, 600), "white").save(f)
    with pytest.raises(IngestionError) as err:
        run(extractors.extract_pdf_document(str(f)))
    assert "OCR found no readable text" in str(err.value)
