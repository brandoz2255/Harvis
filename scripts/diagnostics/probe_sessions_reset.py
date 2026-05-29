#!/usr/bin/env python3
"""
Step 0 probe: confirm the OpenClaw `sessions.reset` RPC is callable by our
client (accepted, not method-not-found / schema-reject / scope-denied).

This is the load-bearing prerequisite for the context-hygiene fix Piece 1
(reset server-side turns before an in-run corrective). The RPC exists in the
2026.5.22 dist; this confirms OUR client, with OUR scopes, can actually call
it on the live gateway.

Run inside the backend container:
  docker exec -e PYTHONPATH=/app harvis-backend python3 /tmp/probe_sessions_reset.py
"""
import asyncio
import json
import sys

sys.path.insert(0, "/app")
from workspace.openclaw_client import OpenClawClient


async def _recv_res(ws, want_id, timeout=10.0):
    """Read frames until we get the res matching want_id (skip events)."""
    import time
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        frame = json.loads(raw)
        if frame.get("type") == "res" and frame.get("id") == want_id:
            return frame
        # otherwise it's an event/other res — keep reading
    return None


async def main():
    client = OpenClawClient(workspace_id="probe-sreset", agent_id="main")
    print(f"gateway_url={client.gateway_url}")
    ws = await client._connect()
    print(f"CONNECTED key={client._session_key}")

    for reason in ("reset", "new"):
        req_id = client._next_id()
        await ws.send(json.dumps({
            "type": "req",
            "id": req_id,
            "method": "sessions.reset",
            "params": {"key": client._session_key, "reason": reason},
        }))
        res = await _recv_res(ws, req_id, timeout=10.0)
        if res is None:
            print(f"reason={reason}: NO RESPONSE (timeout)")
        else:
            ok = res.get("ok")
            err = res.get("error")
            payload = res.get("payload") or res.get("result")
            print(f"reason={reason}: ok={ok} error={err} payload={payload}")

    await ws.close()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
