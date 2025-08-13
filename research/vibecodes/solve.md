Thanks—that stack trace actually shows two separate problems happening back-to-back:

Your container terminal task is timing out while reading from the exec socket.

A request that depends on DB auth is timing out trying to asyncpg.connect(...).

Here’s how to fix both cleanly.

1) Terminal WebSocket: stop using the private ._sock and don’t treat timeouts as fatal
Your WebSocket handler for /api/vibecoding/container/{session_id}/terminal grabs the raw socket and calls socket._sock.recv(...) in a tight loop. That private attribute can raise "timed out" and kill the session, which matches ERROR:vibecoding.containers:Error reading from container: timed out in your logs. Use the public API and make timeouts non-fatal. You’re already at the right spot: the read loop lives here. 

Minimal patch (drop private access, add keep-alive semantics):

python
Copy
Edit
# ...after you obtain `socket` from exec_start(...)
raw = getattr(socket, "_sock", socket)   # prefer public; fall back if needed
try:
    raw.settimeout(1.0)                  # short non-blocking-ish reads
except Exception:
    pass

async def read_from_container():
    import socket as pysock
    try:
        while True:
            try:
                data = raw.recv(4096)    # use public recv
                if not data:
                    break
                await websocket.send_text(data.decode("utf-8", errors="replace"))
            except pysock.timeout:
                # just try again; this is normal when there's no output
                await asyncio.sleep(0.05)
    except Exception as e:
        logger.error(f"Error reading from container: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})

async def write_to_container():
    try:
        while True:
            message = await websocket.receive_text()
            raw.send(message.encode("utf-8"))
    except WebSocketDisconnect:
        logger.info("Terminal WebSocket disconnected")
    except Exception as e:
        logger.error(f"Error writing to container: {e}")
This removes reliance on ._sock (the comment in your file says to avoid recv() but the code still uses ._sock.recv()), and converts “no output for a moment” into a non-fatal loop instead of an error. 

Also make sure you close the socket in a finally block (you already do) to avoid dangling FDs. 

2) DB auth: don’t open a brand-new asyncpg.connect() per request
Your failing request is going through a dependency that calls asyncpg.connect(DATABASE_URL, timeout=10) inside get_current_user, which is imported here and used by your JWT-protected session creation endpoint. That’s exactly where the traceback points and why the error occurs on an unrelated request after files/list succeeded. 
 

Opening a fresh connection in a dependency is brittle and often hits timeouts / cancellation (“CancelledError” then asyncio.TimeoutError). Switch to a global connection pool created at startup and acquire from it inside the dependency.

FastAPI lifespan (or startup) → create pool

python
Copy
Edit
# app.py
from fastapi import FastAPI
import asyncpg

async def lifespan(app: FastAPI):
    app.state.pg_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1, max_size=10,
        command_timeout=5,
    )
    yield
    await app.state.pg_pool.close()

app = FastAPI(lifespan=lifespan)
Dependency that reuses the pool

python
Copy
Edit
# auth_utils.py
from fastapi import Depends, Request, HTTPException
from jose import jwt, JWTError

async def get_db_pool(request: Request):
    return request.app.state.pg_pool

async def get_current_user(request: Request, pool = Depends(get_db_pool)):
    token = extract_bearer_token(request)          # however you already do it
    try:
        payload = jwt.decode(token, KEY, ALGO)     # your existing logic
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, username, email FROM users WHERE id=$1", int(payload["sub"]))
        if not row:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(row)
Why this helps

No more per-request TCP handshakes and SSL negotiation—far fewer timeouts/cancellations.

The dependency becomes fast and resilient even under load.

Important config check: if your API runs in Docker, DATABASE_URL must not use localhost (that would point to the API container itself). Use your compose/network hostname, e.g.:

bash
Copy
Edit
postgresql://user:pass@db:5432/appdb
A wrong host is the #1 reason for asyncpg.connect timeouts in containers.

3) Optional: make container APIs more tolerant
Right now, some routes 404 if the container isn’t found (e.g., list_files). You can either eager-create the container before calling those endpoints, or change the endpoints to return a soft "status": "not_found" instead of raising. Your 404 comes from this check: 

4) Quick test plan (copy/paste)
Restart the API so the pool is created at startup.

Hit GET /api/vibecoding/container/{session}/status → should return not_found until created. 

POST /api/vibecoding/container/create → should create volume + container; logs will show the exact code path: create volume, run container, install basics. 
 

Open the terminal WS and type a command; the read loop should no longer blow up on idle timeouts. 

Call your JWT-protected session creation route; it should acquire from the pool instead of trying a fresh connect every time. 

If you want, I can tailor the exact diffs to your repo structure (where app is built, how DATABASE_URL is injected, etc.).


