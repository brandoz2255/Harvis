"""Two users, one server: user B is refused user A's object.

Each section is one hole found in the per-user isolation audit. Nothing here
touches a real database, container, or network: pools and connections are small
fakes that answer the way Postgres would for the query being asked.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
# main.py creates its images directory when it is imported.
os.environ.setdefault("IMAGES_DIR", tempfile.mkdtemp(prefix="harvis-test-images-"))

A, B = 7, 9


def run(coro):
    return asyncio.run(coro)


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def request_with(pool=None, headers=None, **state):
    return SimpleNamespace(
        headers=headers or {},
        app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool, **state)),
    )


# ── F1 / F13: a messaging identity cannot be taken over ──────────────────────

def _link_conn(*rows):
    from tests.test_messaging_link_ownership import FakeConn

    return FakeConn(list(rows))


def _held(conn, user, identifier="12345"):
    return conn.find(user, "telegram", identifier)


def test_f1_link_platform_refuses_a_house_identity_another_user_holds(monkeypatch):
    from plugins.messaging import routes
    from plugins.messaging.types import Platform

    monkeypatch.setattr(routes, "is_admin", lambda user: True)
    conn = _link_conn()
    request = request_with(FakePool(conn))
    body = routes.PlatformLink(platform=Platform.TELEGRAM, identifier="12345")

    run(routes.link_platform(body, request, current_user={"id": A}))
    with pytest.raises(HTTPException) as err:
        run(routes.link_platform(body, request, current_user={"id": B}))

    assert err.value.status_code == 409
    assert _held(conn, A)["house"] and _held(conn, B) is None
    # The owner can still re-link (change the display name, re-enable).
    run(routes.link_platform(body, request, current_user={"id": A}))


def test_f1_a_non_admin_typed_link_reaches_only_their_own_bot(monkeypatch):
    from plugins.messaging import routes
    from plugins.messaging.types import Platform

    monkeypatch.setattr(routes, "is_admin", lambda user: False)
    conn = _link_conn({"user_id": A, "platform": "telegram", "identifier": "12345", "name": None,
                       "enabled": True, "house": True})
    request = request_with(FakePool(conn))
    body = routes.PlatformLink(platform=Platform.TELEGRAM, identifier="12345", enabled=False)

    assert run(routes.link_platform(body, request, current_user={"id": B})) == {"ok": True}
    # Typing the identity gave B a link to B's own bot; A's link and what it routes are untouched.
    assert not _held(conn, B)["house"] and not _held(conn, B)["enabled"]
    assert _held(conn, A)["house"] and _held(conn, A)["enabled"]


def test_f1_pairing_link_sender_leaves_another_users_link_alone():
    from plugins.hermes_ui import messaging_pairing

    conn = _link_conn()
    pool = FakePool(conn)
    run(messaging_pairing.link_sender(pool, A, "telegram", "12345", "Alice"))
    run(messaging_pairing.link_sender(pool, B, "telegram", "12345", "Mallory"))
    assert _held(conn, A)["name"] == "Alice" and _held(conn, B)["name"] == "Mallory"


def test_f13_gateway_token_is_compared_in_constant_time(monkeypatch):
    from plugins.messaging import routes

    monkeypatch.setenv("MESSAGING_GATEWAY_TOKEN", "right-token")
    routes.require_gateway_token("right-token")
    for wrong in ("", "wrong-token", "right-token ", "right-tokén"):
        with pytest.raises(HTTPException) as err:
            routes.require_gateway_token(wrong)
        assert err.value.status_code == 401


# ── F2: the active-builds list is the caller's own ───────────────────────────

class BuildsConn:
    ROWS = [{"job": "a-build", "user_id": A}, {"job": "b-build", "user_id": B}]

    async def fetch(self, sql, user_id=None):
        assert "a.user_id = $1" in sql
        return [r for r in self.ROWS if user_id is None or r["user_id"] == user_id]


def test_f2_build_manager_filters_by_owner():
    from artifacts.build_manager import ArtifactBuildManager

    manager = ArtifactBuildManager.__new__(ArtifactBuildManager)
    manager.db_pool = FakePool(BuildsConn())

    assert [r["job"] for r in run(manager.get_active_builds(B))] == ["b-build"]
    assert len(run(manager.get_active_builds())) == 2


def test_f2_active_builds_route_scopes_a_non_admin_and_not_an_admin(monkeypatch):
    from artifacts import routes

    seen = []

    class Manager:
        async def get_active_builds(self, user_id=None):
            seen.append(user_id)
            return []

    request = request_with(object(), artifact_build_manager=Manager())
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")

    for uid in (B, 1):
        async def who(_request, uid=uid):
            return SimpleNamespace(id=uid)

        monkeypatch.setattr(routes, "get_current_user_from_request", who)
        run(routes.get_active_builds(request))

    assert seen == [B, None]


@pytest.mark.parametrize("configured,header,expect", [
    ("", "", 503),
    ("", "Bearer anything", 503),
    ("s3cret", "", 401),
    ("s3cret", "Bearer wrong", 401),
    ("s3cret", "Basic s3cret", 401),
    ("s3cret", "Bearer s3cret", 200),
])
def test_build_status_callback_needs_the_configured_token(monkeypatch, configured, header, expect):
    from artifacts import routes
    from artifacts.executor_models import BuildStatusUpdate

    written = []

    class Manager:
        async def update_build_status(self, update):
            written.append(update.job_id)
            return True

    monkeypatch.setenv("EXECUTOR_CALLBACK_TOKEN", configured)
    request = request_with(object(), {"Authorization": header} if header else {}, artifact_build_manager=Manager())
    update = BuildStatusUpdate(job_id=uuid.uuid4(), artifact_id=uuid.uuid4(), status="running")

    if expect == 200:
        assert run(routes.update_build_status(update, request))["status"] == "updated"
        assert written == [update.job_id]
    else:
        with pytest.raises(HTTPException) as err:
            run(routes.update_build_status(update, request))
        assert err.value.status_code == expect
        assert written == []


# ── F3: the code-server proxy checks who owns the container ──────────────────

class FakeManager:
    def __init__(self, labels):
        self.container = SimpleNamespace(labels=labels) if labels is not None else None

    async def get_container(self, session_id):
        return self.container


@pytest.mark.parametrize("labels,caller,allowed", [
    ({"user_id": str(A), "vibecode_host_port": "9000"}, A, True),
    ({"user_id": str(A), "vibecode_host_port": "9000"}, B, False),
    ({"vibecode_host_port": "9000"}, B, False),   # no owner recorded: refuse, not open
    ({"vibecode_host_port": "9000"}, A, False),
])
def test_f3_http_proxy_requires_the_owner_label(monkeypatch, labels, caller, allowed):
    from vibecoding import proxy

    monkeypatch.setattr(proxy, "get_container_manager", lambda: FakeManager(labels))
    if allowed:
        assert "9000" in run(proxy._resolve_target_base_url("s1", {"id": caller}))
    else:
        with pytest.raises(HTTPException) as err:
            run(proxy._resolve_target_base_url("s1", {"id": caller}))
        assert err.value.status_code == 403


class FakeWebSocket:
    def __init__(self, token=None, cookies=None):
        self.query_params = {"token": token} if token else {}
        self.cookies = cookies or {}
        self.scope = {"query_string": b""}
        self.accepted = False
        self.closed_with = None

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed_with = code


def _jwt_for(uid):
    from jose import jwt
    from vibecoding import terminal

    return jwt.encode({"sub": str(uid)}, terminal.SECRET_KEY, algorithm=terminal.ALGORITHM)


@pytest.mark.parametrize("who,expect_close", [
    (None, 1008),       # no token at all
    ("b", 1008),        # a valid user who does not own the container
])
def test_f3_websocket_proxy_never_accepts_a_caller_who_does_not_own_the_container(monkeypatch, who, expect_close):
    from vibecoding import proxy

    monkeypatch.setattr(proxy, "get_container_manager",
                        lambda: FakeManager({"user_id": str(A), "vibecode_host_port": "9000"}))
    ws = FakeWebSocket(token=_jwt_for(B) if who == "b" else None)

    run(proxy.proxy_websocket(ws, "s1", "stable-x/"))

    assert ws.closed_with == expect_close
    assert ws.accepted is False


def test_f3_websocket_proxy_refuses_a_container_with_no_owner_label(monkeypatch):
    from vibecoding import proxy

    monkeypatch.setattr(proxy, "get_container_manager",
                        lambda: FakeManager({"vibecode_host_port": "9000"}))
    ws = FakeWebSocket(cookies={"token": _jwt_for(A)})
    run(proxy.proxy_websocket(ws, "s1", "x"))
    assert ws.closed_with == 1008 and ws.accepted is False


# ── F4: the OpenClaw tool routes act only for the user the token names ───────

def test_f4_byo_gateway_token_cannot_act_for_another_user(monkeypatch):
    from tools import openclaw_proxy as op

    async def caller(_request, _authorization):
        return ("byo", A)

    monkeypatch.setattr(op, "resolve_gateway_caller", caller)
    request = request_with(headers={"Authorization": "Bearer x"})

    assert run(op._gateway_acts_for(request, A)) == A
    with pytest.raises(HTTPException) as err:
        run(op._gateway_acts_for(request, B))
    assert err.value.status_code == 403

    req = op.DocumentSaveRequest(title="t", content="c", user_id=B)
    with pytest.raises(HTTPException) as err:
        run(op.document_save(req, request))
    assert err.value.status_code == 403


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    from tools import openclaw_proxy as op

    async def bundled(_request, _authorization):
        return ("bundled", None)

    monkeypatch.setattr(op, "resolve_gateway_caller", bundled)
    monkeypatch.setattr(op, "_UPLOADS_DIR", str(tmp_path))
    stored = tmp_path / "doc.png"
    stored.write_bytes(b"png")
    (tmp_path / "doc.meta.json").write_text(
        json.dumps({"user_id": A, "stored_path": str(stored), "mime_type": "image/png"}))
    (tmp_path / "orphan.meta.json").write_text(
        json.dumps({"stored_path": str(stored), "mime_type": "image/png"}))
    return op


@pytest.mark.parametrize("file_id,caller", [
    ("doc", B),             # someone else's upload
    ("orphan", A),          # no recorded owner: refused for everyone
    ("../doc", A),          # not a bare upload id
    ("missing", A),
])
def test_f4_file_analyze_refuses_what_the_caller_does_not_own(uploads, file_id, caller):
    request = request_with(object(), headers={"Authorization": "Bearer x"})
    req = uploads.FileAnalyzeRequest(file_id=file_id, user_id=caller)
    with pytest.raises(HTTPException) as err:
        run(uploads.file_analyze(req, request))
    # One answer for "not yours" and "not there".
    assert err.value.status_code == 404
    assert err.value.detail == f"File {file_id} not found"


# ── F5: /api/images serves a user their own images ───────────────────────────

@pytest.fixture
def images(tmp_path, monkeypatch):
    import main

    monkeypatch.setattr(main, "IMAGES_DIR", str(tmp_path))
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    (tmp_path / "mine.png").write_bytes(b"png")
    (tmp_path / "mine.meta.json").write_text(json.dumps({"user_id": A}))
    (tmp_path / "bare.png").write_bytes(b"png")
    (tmp_path / "ownerless.png").write_bytes(b"png")
    (tmp_path / "ownerless.meta.json").write_text(json.dumps({"stored_path": "x"}))
    return main


def test_f5_owner_and_admin_can_read_an_image(images):
    assert run(images.serve_image("mine.png", current_user=SimpleNamespace(id=A))).path.endswith("mine.png")
    assert run(images.serve_image("mine.png", current_user=SimpleNamespace(id=1))).path.endswith("mine.png")


@pytest.mark.parametrize("filename,caller", [
    ("mine.png", B),             # another user's image
    ("bare.png", B),             # no sidecar: admin only
    ("ownerless.png", A),        # sidecar without an owner: admin only
    ("mine.meta.json", A),       # the sidecar itself is not an image
    ("../mine.png", A),
    ("nope.png", A),
])
def test_f5_everyone_else_gets_a_404(images, filename, caller):
    with pytest.raises(HTTPException) as err:
        run(images.serve_image(filename, current_user=SimpleNamespace(id=caller)))
    assert err.value.status_code == 404


# ── F8: a chat only reads project instructions from its own owner's folder ───

class FolderConn:
    """owui_chats joined to owui_folders, evaluated the way the query asks."""

    def __init__(self, chat_id):
        self.chat_id = chat_id

    async def fetchrow(self, sql, chat_id, user_id):
        assert "c.user_id = $2" in sql and "f.user_id = c.user_id" in sql
        chats = [{"id": self.chat_id, "user_id": A, "folder_user_id": A,
                  "data": {"system_prompt": "A's private brief"}}]
        for c in chats:
            if c["id"] == chat_id and c["user_id"] == user_id and c["folder_user_id"] == c["user_id"]:
                return {"data": c["data"]}
        return None


def test_f8_folder_prompt_is_not_returned_to_another_users_chat_id():
    from owui_compat import persistence

    cid = uuid.uuid4()
    pool = FakePool(FolderConn(cid))
    assert run(persistence.get_chat_folder_system_prompt(pool, str(cid), A)) == "A's private brief"
    assert run(persistence.get_chat_folder_system_prompt(pool, str(cid), B)) is None


def test_f8_injection_does_nothing_without_a_known_user(monkeypatch):
    from owui_compat import chat_completion, persistence

    async def boom(*_a, **_k):
        raise AssertionError("looked up a folder prompt for nobody")

    monkeypatch.setattr(persistence, "get_chat_folder_system_prompt", boom)
    body = {"chat_id": "c1", "messages": [{"role": "user", "content": "hi"}]}
    run(chat_completion._inject_project_instructions(request_with(object()), body, user_id=None))
    assert len(body["messages"]) == 1


# ── F10: a file cannot be created under another user's folder ────────────────

class VibeConn:
    def __init__(self):
        self.folder = uuid.uuid4()

    async def fetchval(self, sql, parent_uuid, user_id):
        return 1 if (parent_uuid, user_id) == (self.folder, A) else None

    async def close(self):
        pass


def test_f10_parent_folder_must_be_the_callers():
    from vibecoding import files

    conn = VibeConn()

    async def get_conn():
        return conn

    files.get_db_connection, real = get_conn, files.get_db_connection
    try:
        assert run(files.require_owned_parent(str(conn.folder), A)) == conn.folder
        for parent, caller in ((str(conn.folder), B), (str(uuid.uuid4()), A), ("not-a-uuid", A)):
            with pytest.raises(HTTPException) as err:
                run(files.require_owned_parent(parent, caller))
            assert err.value.status_code == 404
    finally:
        files.get_db_connection = real


def test_f10_create_file_route_answers_404_not_500(monkeypatch):
    from vibecoding import files

    conn = VibeConn()

    async def get_conn():
        return conn

    async def no_table():
        return None

    monkeypatch.setattr(files, "get_db_connection", get_conn)
    monkeypatch.setattr(files, "ensure_vibe_files_table", no_table)
    payload = files.VibeFileCreate(sessionId="s", parentId=str(conn.folder), name="x.txt")
    with pytest.raises(HTTPException) as err:
        run(files.create_vibe_file(payload, user={"id": B}))
    assert err.value.status_code == 404


# ── F11: podcast audio belongs to the user who generated it ──────────────────

class PodcastConn:
    """standalone_podcasts / notebook_podcasts rows: A has one episode."""

    async def fetchval(self, sql, user_id, tail):
        owned = {"standalone_podcasts": {(A, "/api/notebooks/podcasts/tts-audio/ab12.wav")}}
        table = "standalone_podcasts" if "standalone_podcasts" in sql else "notebook_podcasts"
        return 1 if any(user_id == u and p.endswith(tail) for u, p in owned.get(table, ())) else None


def test_f11_ownership_lookup():
    from notebooks import podcast_audio

    pool = FakePool(PodcastConn())
    assert run(podcast_audio.user_owns_audio(pool, A, "ab12.wav")) is True
    assert run(podcast_audio.user_owns_audio(pool, B, "ab12.wav")) is False
    assert run(podcast_audio.user_owns_audio(pool, A, "other.wav")) is False
    assert run(podcast_audio.user_owns_audio(None, A, "ab12.wav")) is False


@pytest.fixture
def episode(tmp_path, monkeypatch):
    from notebooks import podcast_audio

    monkeypatch.setattr(podcast_audio, "AUDIO_DIR", tmp_path)
    (tmp_path / "ab12.wav").write_bytes(b"RIFF")
    return tmp_path


def test_f11_native_tts_audio_route_refuses_another_user(episode):
    from notebooks import router

    request = request_with(FakePool(PodcastConn()))
    assert run(router.proxy_tts_audio("ab12.wav", request, current_user={"id": A})).path.name == "ab12.wav"
    with pytest.raises(HTTPException) as err:
        run(router.proxy_tts_audio("ab12.wav", request, current_user={"id": B}))
    assert err.value.status_code == 404


def test_f11_native_podcast_audio_route_refuses_another_user(episode, monkeypatch):
    from notebooks import router

    monkeypatch.setenv("PODCAST_OUTPUT_PATH", str(episode))
    (episode / "audio").mkdir()
    (episode / "audio" / "ab12.wav").write_bytes(b"RIFF")
    request = request_with(FakePool(PodcastConn()))
    assert run(router.serve_standalone_podcast_audio("ab12.wav", request, current_user={"id": A}))
    with pytest.raises(HTTPException) as err:
        run(router.serve_standalone_podcast_audio("ab12.wav", request, current_user={"id": B}))
    assert err.value.status_code == 404


def test_f11_onb_tts_audio_route_refuses_another_user(episode):
    from onb_compat import podcasts

    manager = SimpleNamespace(db_pool=FakePool(PodcastConn()))
    assert run(podcasts.proxy_tts_audio("ab12.wav", current_user={"id": A}, manager=manager)).body == b"RIFF"
    with pytest.raises(HTTPException) as err:
        run(podcasts.proxy_tts_audio("ab12.wav", current_user={"id": B}, manager=manager))
    assert err.value.status_code == 404


def test_f11_the_tts_audio_routes_require_a_login():
    from fastapi.params import Depends
    from notebooks import router as native
    from onb_compat import podcasts as onb
    import inspect

    for fn in (native.proxy_tts_audio, native.serve_standalone_podcast_audio, onb.proxy_tts_audio):
        default = inspect.signature(fn).parameters["current_user"].default
        assert isinstance(default, Depends), fn.__module__ + "." + fn.__name__


# ── F12: no guessable default signing secret ─────────────────────────────────

def _clear_secret_env(monkeypatch):
    for name in ("JWT_SECRET", "HARVIS_ALLOW_EPHEMERAL_JWT_SECRET", "HARVIS_EXPOSURE",
                 "HARVIS_BIND_ADDR_PUBLIC", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(name, raising=False)


def test_f12_unset_secret_fails_closed_by_default(monkeypatch):
    import jwt_secret

    _clear_secret_env(monkeypatch)
    monkeypatch.setattr(jwt_secret, "_ephemeral", None)
    with pytest.raises(RuntimeError):
        jwt_secret.get_jwt_secret()


def test_f12_unset_secret_is_random_and_shared_only_with_the_local_opt_in(monkeypatch):
    import jwt_secret

    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("HARVIS_ALLOW_EPHEMERAL_JWT_SECRET", "1")
    monkeypatch.setattr(jwt_secret, "_ephemeral", None)
    first = jwt_secret.get_jwt_secret()
    assert first not in jwt_secret.PLACEHOLDERS and len(first) >= 32
    assert jwt_secret.get_jwt_secret() == first


@pytest.mark.parametrize("placeholder", ["key", "Secret", "changeme", "harvis-secret-key"])
def test_f12_a_placeholder_secret_is_refused(monkeypatch, placeholder):
    import jwt_secret

    monkeypatch.setenv("JWT_SECRET", placeholder)
    with pytest.raises(RuntimeError):
        jwt_secret.get_jwt_secret()


def test_f12_a_real_secret_is_used_as_given(monkeypatch):
    import jwt_secret

    monkeypatch.setenv("JWT_SECRET", "test-secret")
    assert jwt_secret.get_jwt_secret() == "test-secret"


def _import_auth(module, env_extra):
    env = {"PATH": os.environ.get("PATH", ""), **env_extra}
    code = (f"import sys; sys.path.insert(0, {BACKEND!r}); "
            f"import {module}; print({module}.SECRET_KEY)")
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        env=env, capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=60,
    )


# Each module in its own interpreter: importing them together lets the first one's
# failure hide a hardcoded fallback in the second.
@pytest.mark.parametrize("module", ["auth_optimized", "auth_utils"])
def test_f12_the_auth_modules_no_longer_fall_back_to_key(module):
    unset = _import_auth(module, {})
    assert unset.returncode != 0
    assert "JWT_SECRET must be set" in unset.stderr

    ephemeral = _import_auth(module, {"HARVIS_ALLOW_EPHEMERAL_JWT_SECRET": "1"})
    assert ephemeral.returncode == 0, ephemeral.stderr
    assert ephemeral.stdout.strip() not in ("", "key")

    placeholder = _import_auth(module, {"JWT_SECRET": "key"})
    assert placeholder.returncode != 0
    assert "placeholder" in placeholder.stderr


# ── BUG: chat-history search took a session_id the manager did not accept ────

class SearchConn:
    ROWS = [
        {"session_id": uuid.UUID(int=1), "content": "alpha one"},
        {"session_id": uuid.UUID(int=2), "content": "alpha two"},
    ]

    async def fetch(self, sql, user_id, pattern, limit, session_id):
        assert "m.user_id = $1" in sql
        return [
            {"id": n, "session_id": r["session_id"], "user_id": user_id, "role": "user",
             "content": r["content"], "reasoning": None, "model_used": None, "input_type": "text",
             "metadata": {}, "created_at": __import__("datetime").datetime.now()}
            for n, r in enumerate(self.ROWS, 1) if session_id is None or r["session_id"] == session_id
        ]


def test_search_messages_accepts_and_applies_a_session_filter():
    from chat_history_module.manager import ChatHistoryManager

    manager = ChatHistoryManager.__new__(ChatHistoryManager)
    manager.storage = SimpleNamespace(db_pool=FakePool(SearchConn()))

    assert len(run(manager.search_messages(A, "alpha"))) == 2
    only = run(manager.search_messages(A, "alpha", session_id=uuid.UUID(int=2)))
    assert [m.content for m in only] == ["alpha two"]


def test_search_route_passes_a_uuid_and_rejects_garbage(monkeypatch):
    import main

    seen = {}

    class Manager:
        async def search_messages(self, **kwargs):
            seen.update(kwargs)
            return []

    monkeypatch.setattr(main, "chat_history_manager", Manager(), raising=False)
    user = SimpleNamespace(id=A)
    sid = uuid.uuid4()

    run(main.search_messages(query="q", session_id=str(sid), limit=5, current_user=user))
    assert seen["session_id"] == sid and seen["user_id"] == A

    with pytest.raises(HTTPException) as err:
        run(main.search_messages(query="q", session_id="not-a-uuid", limit=5, current_user=user))
    assert err.value.status_code == 400
