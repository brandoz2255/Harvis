"""JSON-RPC response helpers and error codes shared by ws.py and its method mixins."""
from __future__ import annotations

import time
from typing import Any

REPLAY_EPOCH = str(int(time.time()))

ERR_PARSE = -32700
ERR_INVALID = -32600
ERR_METHOD = -32601
ERR_PARAMS = -32602
ERR_INTERNAL = -32603
# 4007, not 4001. The desktop Bot Mode treats 4007 as "this id was never a
# session" and then session.create's one. 4001 means "the runtime was reaped"
# and it refuses to mint, so every bot in a room reported "hit an error" on
# the first message (the room resumes by the title "Group: …" before any row
# exists). Composer polling uses 4001 only for process.list, which this
# facade answers without a session lookup.
ERR_SESSION_NOT_FOUND = 4007
ERR_SESSION_BUSY = 4002


def ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def err(rid: Any, code: int, message: str, data: Any = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": error}
