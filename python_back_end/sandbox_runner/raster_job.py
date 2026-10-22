"""PDF -> PNG pages and text. Runs under ``child.py run`` so a hostile PDF meets pdfium
with no network, an address-space cap and no way out of the process group.

Reads RASTER_PDF, RASTER_OUT, RASTER_MAX_PAGES, RASTER_WIDTH, RASTER_BYTES_CAP from the
environment; writes page-N.png files and pages.json into RASTER_OUT. Exit 2: not a PDF.
"""
import json
import os
import sys

import pypdfium2 as pdfium

MAX_ASPECT = 4  # a page taller than 4x its width is scaled down, not rendered at full width


def main():
    pdf, out = os.environ["RASTER_PDF"], os.environ["RASTER_OUT"]
    max_pages, width = int(os.environ["RASTER_MAX_PAGES"]), int(os.environ["RASTER_WIDTH"])
    bytes_cap = int(os.environ["RASTER_BYTES_CAP"])
    try:
        doc = pdfium.PdfDocument(pdf)
        count = len(doc)
    except Exception:  # noqa: BLE001 - pdfium raises PdfiumError, but any parse failure is the same answer
        sys.exit(2)
    pages, total = [], 0
    for i in range(min(count, max_pages)):
        page = doc[i]
        w_pts, h_pts = page.get_size()
        scale = min(width / max(w_pts, 1.0), MAX_ASPECT * width / max(h_pts, 1.0))
        img = page.render(scale=scale).to_pil().convert("RGB")
        name = f"page-{i}.png"
        path = os.path.join(out, name)
        img.save(path, "PNG")
        total += os.path.getsize(path)
        if total > bytes_cap:
            os.unlink(path)
            break
        text_page = page.get_textpage()
        pages.append({"file": name, "width": img.width, "height": img.height,
                      "text": text_page.get_text_bounded()})
    with open(os.path.join(out, "pages.json"), "w", encoding="utf-8") as fh:
        json.dump({"page_count": count, "pages": pages}, fh)


main()
