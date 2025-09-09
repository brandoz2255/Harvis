from pydantic import BaseModel
from typing import List, Any, Dict
import csv, json, io, xml.etree.ElementTree as ET
from ...registry import Tool, register
from ...sandbox import assert_in_jail

class ParseCSVArgs(BaseModel):
    path: str
    has_header: bool = True

class ParseOut(BaseModel):
    data: Any

async def csv_parse(args: ParseCSVArgs):
    p = assert_in_jail(args.path)
    text = p.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if args.has_header and rows:
        header, *rest = rows
        data = [dict(zip(header, r)) for r in rest]
    else:
        data = rows
    return {"data": data}

class ParseJSONArgs(BaseModel):
    path: str

async def json_parse(args: ParseJSONArgs):
    p = assert_in_jail(args.path)
    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    return {"data": data}

class ParseXMLArgs(BaseModel):
    path: str
    xpath: str | None = None

async def xml_parse(args: ParseXMLArgs):
    p = assert_in_jail(args.path)
    tree = ET.parse(p)
    root = tree.getroot()
    if args.xpath:
        found = [ET.tostring(e, encoding="unicode") for e in root.findall(args.xpath)]
        return {"data": found}
    else:
        return {"data": ET.tostring(root, encoding="unicode")}

def register_parse_tools():
    register(Tool("csv_parse", ParseCSVArgs, ParseOut, "scope:file.read", csv_parse))
    register(Tool("json_parse", ParseJSONArgs, ParseOut, "scope:file.read", json_parse))
    register(Tool("xml_parse", ParseXMLArgs, ParseOut, "scope:file.read", xml_parse))
