from pydantic import BaseModel
from ...registry import Tool, register
from ...sandbox import assert_in_jail

class PdfArgs(BaseModel):
    path: str
    max_pages: int = 5

class PdfOut(BaseModel):
    text: str

async def pdf_extract_text(args: PdfArgs):
    try:
        from pypdf import PdfReader
    except Exception:
        raise RuntimeError("Please install pypdf for pdf_extract_text")
    p = assert_in_jail(args.path)
    reader = PdfReader(str(p))
    texts = []
    for i, page in enumerate(reader.pages[: args.max_pages]):
        texts.append(page.extract_text() or "")
    return {"text": "\n".join(texts)}

def register_pdf_tools():
    register(Tool("pdf_extract_text", PdfArgs, PdfOut, "scope:file.read", pdf_extract_text))
