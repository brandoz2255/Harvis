# MCP OS-OPS (Module for FastAPI)

This is a drop-in module exposing OS operations as MCP-style tools via one endpoint:
`POST /mcp/invoke` (JSON-RPC 2.0).

## Quick Start
```bash
pip install -r requirements.txt  # or use pyproject dependencies
uvicorn server.app:app --reload
python clients/gradio_demo.py
```
Use header `Authorization: Bearer dev-key` in requests.

## Tools Included
- get_system_info
- execute_command (allowlisted binaries, jailed cwd)
- list_processes / kill_process
- environment_get / environment_set
- zip_create / zip_extract
- csv_parse / json_parse / xml_parse
- pdf_extract_text (requires `pypdf`)
- word_extract (requires `python-docx`)

All file paths are jailed to `workspace/`.
