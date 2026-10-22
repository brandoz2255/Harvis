"""Descriptions and MCP annotations for the tools in the registry.

Hints are advisory to clients, so they err toward "can change things": a tool
missing from this table is advertised as not read-only and destructive.
"""
from typing import Any, Dict, Optional, Tuple

# name -> (description, readOnly, destructive, idempotent, openWorld)
_RO = (True, False, True, False)
_RO_NET = (True, False, True, True)
_OVERWRITES = (False, True, True, False)

_META: Dict[str, Tuple[str, Tuple[bool, bool, bool, bool]]] = {
    "get_system_info": ("CPU, memory and OS details of the host running this server.", _RO),
    "list_processes": ("List running processes with CPU and memory use.", _RO),
    "kill_process": ("Send SIGTERM to a process by pid.", (False, True, False, False)),
    "execute_command": (
        "Run an allowlisted executable (python3, node, ls, cat, echo) inside the workspace "
        "jail with CPU, memory and time limits.", (False, True, False, False)),
    "environment_get": (
        "Read one environment variable by key. Names that look like secrets are refused.", _RO),
    "environment_set": (
        "Set one environment variable in the server process. Secret-looking names are refused.",
        _OVERWRITES),
    "file_list": ("List every file in the workspace jail.", _RO),
    "file_read": ("Read a text file from the workspace jail (5 MB limit).", _RO),
    "file_write": ("Write a text file in the workspace jail, replacing any existing one.", _OVERWRITES),
    "file_delete": ("Delete a file from the workspace jail.", (False, True, True, False)),
    "zip_create": ("Zip workspace files into an archive, replacing an existing archive.", _OVERWRITES),
    "zip_extract": ("Extract a zip archive into a workspace directory, overwriting files.", _OVERWRITES),
    "csv_parse": ("Parse a CSV file from the workspace jail into rows.", _RO),
    "json_parse": ("Parse a JSON file from the workspace jail.", _RO),
    "xml_parse": ("Parse an XML file from the workspace jail, optionally selecting by xpath.", _RO),
    "pdf_extract_text": ("Extract the text of a PDF in the workspace jail.", _RO),
    "word_extract": ("Extract the text of a .docx in the workspace jail.", _RO),
    # openclaw_read and openclaw_write splice the path into a shell command line,
    # so they are not advertised as read-only or contained.
    "openclaw_exec": ("Run a shell command in the OpenClaw workspace.", (False, True, False, True)),
    "openclaw_read": (
        "Read a file from the OpenClaw workspace (runs cat through the workspace shell).",
        (False, True, True, True)),
    "openclaw_write": ("Write a file in the OpenClaw workspace, replacing any existing one.",
                       (False, True, True, True)),
    "openclaw_edit": ("Replace text in an OpenClaw workspace file.", (False, True, False, True)),
    "openclaw_chat": ("Hand a natural-language task to the OpenClaw agent, which can change files "
                      "and run commands.", (False, True, False, True)),
    "openclaw_search": ("Search the web through the Harvis backend.", _RO_NET),
    "openclaw_web_fetch": ("Fetch a URL through the Harvis backend.", _RO_NET),
    "list_repos": ("List the GitHub repositories cloned into the workspace.", (True, False, True, False)),
    "clone_repo": ("Clone a GitHub repository into the workspace.", (False, False, False, True)),
}


# Tools whose only backend is a route that does not exist yet. They stay in the
# registry (so /mcp/invoke is unchanged) but /mcp neither lists nor runs them.
# Delete an entry the day the backend grows the route.
_NO_EXEC_ROUTE = "the Harvis backend has no /api/tools/openclaw/exec route to run it through"
UNAVAILABLE: Dict[str, str] = {
    "openclaw_exec": _NO_EXEC_ROUTE,
    "openclaw_read": _NO_EXEC_ROUTE,
    "openclaw_write": _NO_EXEC_ROUTE,
    "openclaw_edit": _NO_EXEC_ROUTE,
}


def unavailable_reason(name: str) -> Optional[str]:
    return UNAVAILABLE.get(name)


def failure_reason(payload: Any) -> Optional[str]:
    """Why a tool's returned payload is really a failure, or None if it succeeded.

    Several handlers report a failed backend call as an ordinary dict (exit_code 1,
    ok False, "Error: ..."); /mcp must surface those as isError, not as success.
    """
    if not isinstance(payload, dict):
        return None
    code = payload.get("exit_code")
    if isinstance(code, int) and not isinstance(code, bool) and code != 0:
        return f"exit_code {code}"
    if payload.get("ok") is False:
        return "ok is false"
    status = payload.get("status")
    if isinstance(status, str) and status.lower().startswith("error"):
        return status
    response = payload.get("response")
    if isinstance(response, str) and response.startswith("Error:"):
        return response
    http = payload.get("status_code")
    if isinstance(http, int) and not isinstance(http, bool) and http >= 400:
        return f"HTTP {http}"
    return None


def describe(name: str, scope: str) -> str:
    entry = _META.get(name)
    return entry[0] if entry else f"Tool {name} (scope {scope})."


def annotations(name: str) -> dict:
    ro, destructive, idempotent, open_world = (_META[name][1] if name in _META
                                               else (False, True, False, True))
    return {
        "readOnlyHint": ro,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": open_world,
    }


def has_meta(name: str) -> bool:
    return name in _META
