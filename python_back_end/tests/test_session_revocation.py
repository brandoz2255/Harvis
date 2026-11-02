"""Scoped MCP tokens and server-side sign-out.

A sidecar's MCP token is readable from the process list, so it must work only at the
four MCP endpoints and live minutes. A password change, turning an account off or
"sign out everywhere" must end every sign-in minted before it. Postgres and the
network are replaced with in-memory fakes.
"""
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import JWTError, jwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("IMAGES_DIR", "/tmp/harvis-test-images")
os.environ.setdefault("OWUI_FILES_DIR", "/tmp/harvis-test-owui-files")

import auth_optimized  # noqa: E402
import jwt_secret  # noqa: E402
import main  # noqa: E402
from plugins.people import gate  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in ("HARVIS_EXPOSURE", "HARVIS_BIND_ADDR_PUBLIC", "KUBERNETES_SERVICE_HOST",
                "ACCESS_TOKEN_EXPIRE_MINUTES", "HARVIS_MCP_TOKEN_MINUTES"):
        monkeypatch.delenv(key, raising=False)
    auth_optimized.TOKEN_CACHE.clear()
    auth_optimized._cutoffs.clear()
    yield
    auth_optimized.TOKEN_CACHE.clear()
    auth_optimized._cutoffs.clear()


class FakeConn:
    def __init__(self, cutoff=None):
        self.cutoff = cutoff
        self.updated = []

    async def fetchval(self, sql, *args):
        if sql.startswith("UPDATE users SET tokens_valid_after"):
            self.cutoff = time.time()
            self.updated.append(args[0])
            return self.cutoff
        if "tokens_valid_after" in sql:
            return self.cutoff
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        return []

    async def fetchrow(self, sql, *args):
        return {"id": args[0], "username": "u", "email": "u@example.test", "avatar": None,
                "name": None, "bio": None, "gender": None, "date_of_birth": None}


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self, **_kw):
        yield self.conn


def normal_token(uid=5, minutes=5):
    return main.create_access_token({"sub": str(uid)}, timedelta(minutes=minutes))


def mcp_token(uid=5):
    return main.create_mcp_token(uid)


def scope_for(path, token):
    return {"type": "http", "method": "POST", "path": path, "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())]}


# --- F1: scoped tokens -----------------------------------------------------------

def test_mcp_token_is_scoped_and_short_lived():
    claims = jwt.decode(mcp_token(), main.SECRET_KEY, algorithms=["HS256"], audience="harvis-mcp")
    assert claims["scope"] == "mcp" and claims["aud"] == "harvis-mcp"
    assert 14 * 60 <= claims["exp"] - claims["iat"] <= 15 * 60 + 5


@pytest.mark.parametrize("path", sorted(auth_optimized.MCP_PATHS))
def test_mcp_token_accepted_on_each_mcp_endpoint(path):
    assert auth_optimized.decode_claims(mcp_token(), path)["sub"] == "5"
    assert auth_optimized.decode_token_fast(mcp_token(), path)["sub"] == "5"


@pytest.mark.parametrize("path", [None, "/api/auth/me", "/api/cad/projects", "/api/workspace/run",
                                  "/api/docs/mcp/../me", "/hermes-api/api/terminal/x"])
def test_mcp_token_refused_everywhere_else(path):
    with pytest.raises(JWTError):
        auth_optimized.decode_claims(mcp_token(), path)
    assert auth_optimized.decode_token_fast(mcp_token(), path) is None


def test_cached_mcp_payload_is_not_a_way_around_the_path_check():
    token = mcp_token()
    assert auth_optimized.decode_token_fast(token, "/api/docs/mcp")
    assert auth_optimized.decode_token_fast(token, "/api/auth/me") is None
    assert auth_optimized.decode_token_fast(token) is None


def test_cached_payload_is_not_trusted_past_its_expiry():
    # The key is not a decodable token, so only the cache can answer.
    auth_optimized.TOKEN_CACHE["cache-only"] = {"payload": {"sub": "5", "exp": time.time() + 60},
                                                 "timestamp": time.time()}
    assert auth_optimized.decode_token_fast("cache-only")["sub"] == "5"
    auth_optimized.TOKEN_CACHE["cache-only"]["payload"]["exp"] = time.time() - 1
    assert auth_optimized.decode_token_fast("cache-only") is None
    assert "cache-only" not in auth_optimized.TOKEN_CACHE


def test_mcp_token_is_not_a_login_for_the_account_gate():
    ids = gate._user_ids(scope_for("/api/auth/me", mcp_token(7)))
    assert ids == set()
    assert gate._user_ids(scope_for("/api/cad/mcp", mcp_token(7))) == {7}


def test_get_current_user_refuses_mcp_token_off_its_endpoint():
    request = SimpleNamespace(cookies={}, url=SimpleNamespace(path="/api/auth/me"),
                              app=SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(FakeConn()))))
    creds = SimpleNamespace(credentials=mcp_token())
    with pytest.raises(HTTPException) as exc:
        run(main.get_current_user(request, creds))
    assert exc.value.status_code == 401
    request.url.path = "/api/docs/mcp"
    assert run(main.get_current_user(request, creds)).id == 5


def test_normal_token_still_works_on_mcp_endpoint():
    assert auth_optimized.decode_claims(normal_token(), "/api/docs/mcp")["sub"] == "5"


def test_every_sidecar_minting_site_uses_the_scoped_token():
    import inspect

    from owui_compat import cad_mcp, docs_mcp
    from plugins.mcp import sidecar_bridge
    from workspace.orchestration import artifact_mcp

    for module in (cad_mcp, docs_mcp, sidecar_bridge, artifact_mcp):
        source = inspect.getsource(module)
        assert "create_mcp_token" in source and "create_access_token" not in source, module.__name__
        assert module.SIDECAR_TOKEN_MINUTES == jwt_secret.MCP_TOKEN_MINUTES


def test_docs_sidecar_config_carries_a_scoped_token(monkeypatch):
    from owui_compat import docs_mcp

    cfg = docs_mcp.sidecar_mcp_config(9)
    header = next(iter(cfg["mcpServers"].values()))["headers"]["Authorization"]
    claims = jwt.get_unverified_claims(header.split(" ", 1)[1])
    assert claims["scope"] == "mcp" and claims["aud"] == "harvis-mcp"


# --- F3: revocation --------------------------------------------------------------

def test_token_minted_before_the_cutoff_is_revoked():
    payload = auth_optimized.decode_claims(normal_token())
    assert not auth_optimized.revoked(payload, None)
    assert not auth_optimized.revoked(payload, payload["iat"] - 1)
    assert auth_optimized.revoked(payload, payload["iat"] + 0.001)


def test_token_without_issue_time_dies_at_any_cutoff():
    legacy = jwt.encode({"sub": "5", "exp": time.time() + 600}, main.SECRET_KEY, algorithm="HS256")
    payload = auth_optimized.decode_claims(legacy)  # still accepted on a laptop
    assert not auth_optimized.revoked(payload, None)
    assert auth_optimized.revoked(payload, 1.0)


def test_shared_server_refuses_a_token_with_no_issue_time(monkeypatch):
    legacy = jwt.encode({"sub": "5", "exp": time.time() + 600}, main.SECRET_KEY, algorithm="HS256")
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    with pytest.raises(JWTError):
        auth_optimized.decode_claims(legacy)
    assert auth_optimized.decode_claims(normal_token())["sub"] == "5"


def test_get_current_user_refuses_a_token_older_than_the_cutoff():
    token = normal_token()
    conn = FakeConn()
    request = SimpleNamespace(cookies={}, url=SimpleNamespace(path="/api/auth/me"),
                              app=SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(conn))))
    creds = SimpleNamespace(credentials=token)
    assert run(main.get_current_user(request, creds)).id == 5
    conn.cutoff = time.time() + 5
    auth_optimized._cutoffs.clear()
    with pytest.raises(HTTPException) as exc:
        run(main.get_current_user(request, creds))
    assert exc.value.status_code == 401


def test_optimized_dependency_refuses_a_token_older_than_the_cutoff(monkeypatch):
    token = normal_token()
    conn = FakeConn(cutoff=time.time() + 5)
    pool = FakePool(conn)
    request = SimpleNamespace(cookies={}, url=SimpleNamespace(path="/api/x"),
                              app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
    creds = SimpleNamespace(credentials=token)
    with pytest.raises(HTTPException) as exc:
        run(auth_optimized.get_current_user_optimized(request, creds, pool))
    assert exc.value.status_code == 401 and "ended" in exc.value.detail


def test_sign_out_everywhere_ends_this_and_earlier_tokens():
    conn = FakeConn()
    pool = FakePool(conn)
    token = normal_token(5)
    payload = auth_optimized.decode_claims(token)
    assert run(auth_optimized.session_cutoff(pool, 5)) is None
    time.sleep(0.01)
    run(auth_optimized.revoke_sessions(conn, 5))
    assert conn.updated == [5]
    # Applies at once in this process, without waiting for the cache window.
    assert auth_optimized.revoked(payload, run(auth_optimized.session_cutoff(pool, 5)))
    # A token minted after it is fine.
    time.sleep(0.01)
    fresh = auth_optimized.decode_claims(normal_token(5))
    assert not auth_optimized.revoked(fresh, run(auth_optimized.session_cutoff(pool, 5)))


def test_signout_all_endpoint_revokes_and_clears_cookies():
    conn = FakeConn()
    app = main.app
    old_pool = getattr(app.state, "pg_pool", None)
    app.state.pg_pool = FakePool(conn)
    try:
        response = run(main.signout_everywhere(SimpleNamespace(id=5)))
    finally:
        app.state.pg_pool = old_pool
    assert conn.updated == [5]
    assert response.status_code == 200
    cleared = [h for h in response.raw_headers if h[0] == b"set-cookie"]
    assert any(b"access_token" in h[1] for h in cleared)


def test_gate_refuses_a_revoked_token_on_http():
    token = normal_token(5)
    conn = FakeConn(cutoff=time.time() + 5)
    app_state = SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(conn)))
    seen, sent = [], []

    async def inner(scope, receive, send):
        seen.append(scope["path"])

    async def send(message):
        sent.append(message)

    scope = scope_for("/api/chat", token)
    scope["app"] = app_state
    run(gate.BlockedAccountGate(inner)(scope, None, send))
    assert not seen
    assert sent[0]["status"] == 401

    scope = scope_for("/api/auth/login", token)  # open path: a stale cookie can still sign in
    scope["app"] = app_state
    run(gate.BlockedAccountGate(inner)(scope, None, send))
    assert seen == ["/api/auth/login"]


def test_gate_lets_a_current_token_through():
    token = normal_token(5)
    conn = FakeConn(cutoff=time.time() - 60)
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["path"])

    scope = scope_for("/api/chat", token)
    scope["app"] = SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(conn)))
    from plugins.people import approval

    approval.note_status(5, approval.ACTIVE_STATUS)
    run(gate.BlockedAccountGate(inner)(scope, None, lambda m: None))
    assert seen == ["/api/chat"]


def test_session_check_answers_401_for_a_revoked_token():
    from plugins.people import session

    token = normal_token(5)
    conn = FakeConn(cutoff=time.time() + 5)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(conn))),
                              scope=scope_for("/api/session/check", token))
    assert run(session.session_check(request)).status_code == 401


def test_migration_sets_the_cutoff_on_password_change_and_block():
    sql = open(os.path.join(os.path.dirname(__file__), "..", "migrations", "027_session_cutoff.sql")).read()
    assert "ADD COLUMN IF NOT EXISTS tokens_valid_after" in sql
    assert "BEFORE UPDATE OF password ON users" in sql
    assert "ON harvis_user_controls" in sql
    assert any("027_session_cutoff.sql" in line for line in open(main.__file__).read().splitlines())


# --- lifetimes -------------------------------------------------------------------

def test_sign_in_lifetime_is_a_day_when_shared_and_a_week_on_a_laptop(monkeypatch):
    assert jwt_secret.access_token_minutes() == 10080
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert jwt_secret.access_token_minutes() == 1440
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    assert jwt_secret.access_token_minutes() == 60


# --- round 2: the migration must reach git ---------------------------------------

def _gitignored(rel, patterns):
    """A close-enough reading of .gitignore for plain globs and ``**/`` globs."""
    from fnmatch import fnmatch

    parts = rel.split("/")
    ignored = False
    for pat in patterns:
        negate = pat.startswith("!")
        body = (pat[1:] if negate else pat).rstrip("/")
        body = body[3:] if body.startswith("**/") else body.lstrip("/")
        if "/" in body:
            hit = fnmatch(rel, body)
        else:
            hit = any(fnmatch(part, body) for part in parts)
        if hit:
            ignored = not negate
    return ignored


def test_every_migration_main_applies_exists_and_is_not_gitignored():
    # `**/*token*` in .gitignore once swallowed 027_token_cutoff.sql: it booted fine
    # here, never reached git, and a fresh checkout ran with revocation silently off.
    import re

    root = os.path.join(os.path.dirname(__file__), "..", "..")
    gitignore = os.path.join(root, ".gitignore")
    if not os.path.exists(gitignore):
        pytest.skip("no .gitignore beside the backend (not a repo checkout)")
    patterns = [ln.strip() for ln in open(gitignore, encoding="utf-8")
                if ln.strip() and not ln.lstrip().startswith("#")]
    names = re.findall(r'"(\d{3}_[A-Za-z0-9_]+\.sql)"', open(main.__file__, encoding="utf-8").read())
    assert "027_session_cutoff.sql" in names
    for name in names:
        assert os.path.exists(os.path.join(root, "python_back_end", "migrations", name)), name
        assert not _gitignored(f"python_back_end/migrations/{name}", patterns), name


def test_gitignore_reader_catches_the_original_mistake():
    assert _gitignored("python_back_end/migrations/027_token_cutoff.sql", ["**/*token*"])
    assert not _gitignored("python_back_end/migrations/027_session_cutoff.sql", ["**/*token*"])


# --- round 2: every independent decoder applies the cutoff -------------------------

def legacy_token(uid=5):
    """Signed and unexpired, but minted before tokens carried an issue time."""
    return jwt.encode({"sub": str(uid), "exp": time.time() + 600}, main.SECRET_KEY, algorithm="HS256")


def _artifacts_request(token, conn):
    return SimpleNamespace(headers={"Authorization": f"Bearer {token}"},
                           url=SimpleNamespace(path="/api/artifacts/list"),
                           app=SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(conn))))


def test_artifacts_route_takes_a_current_token_and_refuses_a_revoked_one():
    from artifacts import routes

    token = normal_token(5)
    assert run(routes.get_current_user_from_request(_artifacts_request(token, FakeConn()))).id == 5
    auth_optimized._cutoffs.clear()
    with pytest.raises(HTTPException) as exc:
        run(routes.get_current_user_from_request(_artifacts_request(token, FakeConn(cutoff=time.time() + 5))))
    assert exc.value.status_code == 401


def test_artifacts_route_refuses_a_token_without_issue_time_on_a_shared_server(monkeypatch):
    from artifacts import routes

    token = legacy_token()
    assert run(routes.get_current_user_from_request(_artifacts_request(token, FakeConn()))).id == 5  # laptop
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    with pytest.raises(HTTPException) as exc:
        run(routes.get_current_user_from_request(_artifacts_request(token, FakeConn())))
    assert exc.value.status_code == 401
    monkeypatch.delenv("HARVIS_EXPOSURE")
    auth_optimized._cutoffs.clear()
    with pytest.raises(HTTPException):  # and any cutoff ends it even on a laptop
        run(routes.get_current_user_from_request(_artifacts_request(token, FakeConn(cutoff=1.0))))


def test_artifacts_route_refuses_a_scoped_mcp_token():
    from artifacts import routes

    with pytest.raises(HTTPException) as exc:
        run(routes.get_current_user_from_request(_artifacts_request(mcp_token(), FakeConn())))
    assert exc.value.status_code == 401


def test_terminal_websocket_login_applies_the_cutoff():
    from vibecoding import terminal

    token = normal_token(5)
    user = run(terminal.authenticate_websocket(token=token, pool=FakePool(FakeConn())))
    assert user["id"] == 5
    auth_optimized._cutoffs.clear()
    with pytest.raises(HTTPException) as exc:
        run(terminal.authenticate_websocket(token=token, pool=FakePool(FakeConn(cutoff=time.time() + 5))))
    assert exc.value.status_code == 401


def test_terminal_websocket_login_reads_the_cutoff_from_the_app_pool_when_none_is_passed(monkeypatch):
    # vibecoding/proxy.py calls authenticate_websocket without a pool.
    from vibecoding import terminal

    monkeypatch.setattr(auth_optimized.auth_optimizer, "db_pool", FakePool(FakeConn(cutoff=time.time() + 5)))
    with pytest.raises(HTTPException):
        run(terminal.authenticate_websocket(token=normal_token(5)))


def test_verified_user_id_covers_every_way_a_sign_in_can_be_bad(monkeypatch):
    pool = FakePool(FakeConn())
    assert run(auth_optimized.verified_user_id(normal_token(5), pool)) == 5
    assert run(auth_optimized.verified_user_id("not-a-token", pool)) is None
    assert run(auth_optimized.verified_user_id(mcp_token(), pool)) is None
    assert run(auth_optimized.verified_user_id(mcp_token(), pool, "/api/cad/mcp")) == 5
    expired = main.create_access_token({"sub": "5"}, timedelta(minutes=-5))
    assert run(auth_optimized.verified_user_id(expired, pool)) is None
    nosub = main.create_access_token({}, timedelta(minutes=5))
    assert run(auth_optimized.verified_user_id(nosub, pool)) is None
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert run(auth_optimized.verified_user_id(legacy_token(), pool)) is None


class _Ws:
    headers = {"host": "localhost:9000"}

    def __init__(self, token, pool):
        self.cookies = {"access_token": token}
        self.query_params = {}
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=pool))
        self.closed = None
        self.accepted = False

    async def close(self, code=1000, reason=""):
        self.closed = code

    async def accept(self):
        self.accepted = True
        raise RuntimeError("stop here: the sign-in was accepted")


def test_hermes_socket_refuses_a_revoked_sign_in():
    from plugins.hermes_ui import ws as ws_mod

    revoked_ws = _Ws(normal_token(5), FakePool(FakeConn(cutoff=time.time() + 5)))
    run(ws_mod.hermes_ws(revoked_ws))
    assert revoked_ws.closed == 4401 and not revoked_ws.accepted

    auth_optimized._cutoffs.clear()
    fine = _Ws(normal_token(5), FakePool(FakeConn()))
    with pytest.raises(RuntimeError, match="accepted"):
        run(ws_mod.hermes_ws(fine))
    assert fine.accepted


def _run_gate(path, token):
    seen, sent = [], []

    async def inner(scope, receive, send):
        seen.append(scope["path"])

    async def send(message):
        sent.append(message)

    scope = scope_for(path, token)
    scope["app"] = SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(FakeConn())))
    run(gate.BlockedAccountGate(inner)(scope, None, send))
    return seen, sent


def test_gate_ends_a_signed_token_without_issue_time_on_a_shared_server(monkeypatch):
    # Without this the gate saw "no sign-in" and passed the request to routes that
    # check only the signature, so the token kept working until it expired.
    token = legacy_token()
    seen, sent = _run_gate("/api/artifacts/list", token)
    assert seen == ["/api/artifacts/list"]  # laptop: still accepted
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    auth_optimized.TOKEN_CACHE.clear()  # the mode never changes in a real process
    seen, sent = _run_gate("/api/artifacts/list", token)
    assert not seen and sent[0]["status"] == 401
    assert any(b"access_token" in h[1] for h in sent[0]["headers"] if h[0] == b"set-cookie")
    seen, sent = _run_gate("/api/auth/login", token)  # a stale cookie must still be able to sign in
    assert seen == ["/api/auth/login"]
    seen, sent = _run_gate("/api/artifacts/list", normal_token(5))
    assert seen == ["/api/artifacts/list"]


def test_garbage_and_expired_tokens_are_not_mistaken_for_a_legacy_session(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert not auth_optimized.predates_revocation("garbage")
    expired = jwt.encode({"sub": "5", "exp": time.time() - 60}, main.SECRET_KEY, algorithm="HS256")
    assert not auth_optimized.predates_revocation(expired)
    forged = jwt.encode({"sub": "5", "exp": time.time() + 60}, "another-secret-entirely", algorithm="HS256")
    assert not auth_optimized.predates_revocation(forged)
    assert auth_optimized.predates_revocation(legacy_token())
    assert not auth_optimized.predates_revocation(normal_token())
    monkeypatch.delenv("HARVIS_EXPOSURE")
    assert not auth_optimized.predates_revocation(legacy_token())


# --- round 2: HARVIS_MCP_TOKEN_MINUTES --------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, 15), ("", 15), ("45", 45), (" 30 ", 30), ("abc", 15), ("1.5", 15), ("1e3", 15),
    ("0", 1), ("-9", 1), ("99999", 1440), ("1440", 1440),
])
def test_mcp_token_minutes_is_parsed_tolerantly(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("HARVIS_MCP_TOKEN_MINUTES", raising=False)
    else:
        monkeypatch.setenv("HARVIS_MCP_TOKEN_MINUTES", raw)
    assert jwt_secret._mcp_token_minutes() == expected


def test_a_bad_mcp_token_minutes_value_does_not_stop_the_backend_importing_it():
    import subprocess

    backend = os.path.join(os.path.dirname(__file__), "..")
    env = {**os.environ, "HARVIS_MCP_TOKEN_MINUTES": "fifteen", "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", "import jwt_secret; print(jwt_secret.MCP_TOKEN_MINUTES)"],
                         cwd=backend, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "15"


# --- routes that read the JWT themselves (vibecoding GitHub, sandbox terminal) -----

def _cookie_request(token, conn, path="/api/vibecoding/repo/list"):
    return SimpleNamespace(cookies={"access_token": token}, headers={},
                           url=SimpleNamespace(path=path),
                           app=SimpleNamespace(state=SimpleNamespace(pg_pool=FakePool(conn))))


def test_github_status_and_disconnect_refuse_a_revoked_sign_in(monkeypatch):
    from vibecoding import auth_github

    monkeypatch.setenv("JWT_SECRET", main.SECRET_KEY)
    token = normal_token(5)
    assert run(auth_github._uid_from_request(_cookie_request(token, FakeConn()))) == 5
    auth_optimized._cutoffs.clear()
    with pytest.raises(HTTPException) as exc:
        run(auth_github._uid_from_request(_cookie_request(token, FakeConn(cutoff=time.time() + 5))))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("route", ["import_repository", "list_repositories"])
def test_repo_import_routes_refuse_a_revoked_sign_in(route):
    from vibecoding import repo_import

    fn = getattr(repo_import, route)
    request = _cookie_request(normal_token(5), FakeConn(cutoff=time.time() + 5))
    kwargs = {"request": request}
    if route == "import_repository":
        kwargs["request_data"] = SimpleNamespace(repo_url="https://github.com/o/r", session_id="s", branch=None)
    with pytest.raises(HTTPException) as exc:
        run(fn(**{k: v for k, v in kwargs.items() if k in fn.__code__.co_varnames}))
    assert exc.value.status_code == 401


def test_sandbox_terminal_socket_refuses_a_revoked_sign_in():
    from plugins.hermes_ui import rest_sandbox

    revoked_ws = _Ws(normal_token(5), FakePool(FakeConn(cutoff=time.time() + 5)))
    run(rest_sandbox.terminal_ws(revoked_ws))
    assert revoked_ws.closed == 4401 and not revoked_ws.accepted

    auth_optimized._cutoffs.clear()
    fine = _Ws(normal_token(5), FakePool(FakeConn()))
    with pytest.raises(RuntimeError, match="accepted"):
        run(rest_sandbox.terminal_ws(fine))
