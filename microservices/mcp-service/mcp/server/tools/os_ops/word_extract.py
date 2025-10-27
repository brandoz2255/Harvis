from pydantic import BaseModel
from ...registry import Tool, register
from ...sandbox import assert_in_jail

class DocxArgs(BaseModel):
    path: str

class DocxOut(BaseModel):
    text: str

async def word_extract(args: DocxArgs):
    try:
        import docx
    except Exception:
        raise RuntimeError("Please install python-docx for word_extract")
    p = assert_in_jail(args.path)
    d = docx.Document(str(p))
    return {"text": "\n".join([p.text for p in d.paragraphs])}

def register_word_tools():
    register(Tool("word_extract", DocxArgs, DocxOut, "scope:file.read", word_extract))
