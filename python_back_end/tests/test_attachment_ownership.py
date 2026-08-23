"""Gate 8A — an upload resolves for its owner and for nobody else.

Before this, `vision_to_code/attachments.py` turned a client-supplied file id
straight into bytes. Those bytes go two places that matter: into a model's
context as an image part, and onto an agent's working tree as a real file. So a
missing ownership check was not a listing leak — it was a read of another user's
document, delivered by Harvis on request.

Both upload stores are covered, because they prove ownership differently:
IMAGES_DIR from its `.meta.json` sidecar, OWUI_FILES_DIR from a lookup the app
registers at startup. The third case is the one that is easy to get wrong: with
no lookup registered the OWUI store must refuse, not wave everything through.
"""

import json
import os

import pytest

from vision_to_code import attachments as att_mod


OWNER = 7
STRANGER = 9


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Both upload directories, isolated, with the owner lookup unregistered."""
    images = tmp_path / "images"
    owui = tmp_path / "owui_files"
    images.mkdir()
    owui.mkdir()
    monkeypatch.setenv("IMAGES_DIR", str(images))
    monkeypatch.setenv("OWUI_FILES_DIR", str(owui))
    att_mod.set_owui_owner_lookup(None)
    yield images, owui
    att_mod.set_owui_owner_lookup(None)


def _write_images_upload(images, file_id: str, user_id, data: bytes = b"\x89PNG owned"):
    stored = images / f"{file_id}.png"
    stored.write_bytes(data)
    meta = {"stored_path": str(stored), "mime_type": "image/png"}
    if user_id is not None:
        meta["user_id"] = user_id
    (images / f"{file_id}.meta.json").write_text(json.dumps(meta))
    return stored


# ── IMAGES_DIR: ownership comes from the sidecar ─────────────────────────────

@pytest.mark.asyncio
async def test_images_store_resolves_for_its_owner(stores):
    images, _ = stores
    _write_images_upload(images, "shot", OWNER)

    data, mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "shot", "name": "shot.png"}, owner_id=OWNER
    )

    assert error is None
    assert data == b"\x89PNG owned"
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_images_store_refuses_another_users_upload(stores):
    images, _ = stores
    _write_images_upload(images, "shot", OWNER)

    data, _mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "shot"}, owner_id=STRANGER
    )

    assert data is None
    # Same wording as a file id that was never real: a distinct "not yours" would
    # make this an oracle for which ids exist.
    assert error == "upload shot is no longer on disk"


@pytest.mark.asyncio
async def test_images_store_refuses_a_sidecar_with_no_owner(stores):
    """An upload written before user_id was recorded is unownable, not public."""
    images, _ = stores
    _write_images_upload(images, "legacy", None)

    data, _mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "legacy"}, owner_id=OWNER
    )

    assert data is None
    assert error == "upload legacy is no longer on disk"


@pytest.mark.asyncio
async def test_no_caller_means_no_read(stores):
    images, _ = stores
    _write_images_upload(images, "shot", OWNER)

    data, _mime, error = await att_mod.resolve_attachment_bytes({"file_id": "shot"})

    assert data is None
    assert error == "attachments can only be read for a signed-in user"


# ── OWUI_FILES_DIR: ownership comes from the registered lookup ───────────────

@pytest.mark.asyncio
async def test_owui_store_resolves_for_its_owner(stores):
    _images, owui = stores
    (owui / "abc123.png").write_bytes(b"owui bytes")

    async def lookup(file_id):
        return OWNER if file_id == "abc123" else None

    att_mod.set_owui_owner_lookup(lookup)

    data, _mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "abc123"}, owner_id=OWNER
    )

    assert error is None
    assert data == b"owui bytes"


@pytest.mark.asyncio
async def test_owui_store_refuses_another_users_upload(stores):
    _images, owui = stores
    (owui / "abc123.png").write_bytes(b"owui bytes")

    async def lookup(file_id):
        return OWNER

    att_mod.set_owui_owner_lookup(lookup)

    data, _mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "abc123"}, owner_id=STRANGER
    )

    assert data is None
    assert error == "upload abc123 is no longer on disk"


@pytest.mark.asyncio
async def test_owui_store_refuses_when_no_lookup_is_registered(stores):
    """Fail closed. Refusing a real attachment is a bug report; serving someone
    else's file because the check was never wired is a breach."""
    _images, owui = stores
    (owui / "abc123.png").write_bytes(b"owui bytes")

    data, _mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "abc123"}, owner_id=OWNER
    )

    assert data is None
    assert "no file-ownership lookup is configured" in (error or "")


@pytest.mark.asyncio
async def test_owui_lookup_failure_refuses_rather_than_allows(stores):
    _images, owui = stores
    (owui / "abc123.png").write_bytes(b"owui bytes")

    async def lookup(file_id):
        raise RuntimeError("database is down")

    att_mod.set_owui_owner_lookup(lookup)

    data, _mime, error = await att_mod.resolve_attachment_bytes(
        {"file_id": "abc123"}, owner_id=OWNER
    )

    assert data is None
    assert error == "could not confirm who owns this upload"


# ── The two public entry points carry the owner through ──────────────────────

@pytest.mark.asyncio
async def test_staging_will_not_write_another_users_file(stores, tmp_path):
    """`materialize_attachments` is the path that puts bytes on a working tree a
    CLI agent then reads at will, so its owner check is the load-bearing one."""
    images, _ = stores
    _write_images_upload(images, "secret", OWNER, data=b"private notes")
    workdir = tmp_path / "work"
    workdir.mkdir()

    staged, skipped = await att_mod.materialize_attachments(
        [{"file_id": "secret", "name": "secret.png"}], str(workdir), owner_id=STRANGER
    )

    assert staged == []
    assert len(skipped) == 1
    assert "no longer on disk" in skipped[0]
    # Nothing was written anywhere under the working tree.
    written = [p for p in workdir.rglob("*") if p.is_file()]
    assert written == []


@pytest.mark.asyncio
async def test_staging_writes_the_owners_own_file(stores, tmp_path):
    images, _ = stores
    _write_images_upload(images, "notes", OWNER, data=b"my own notes")
    workdir = tmp_path / "work"
    workdir.mkdir()

    staged, skipped = await att_mod.materialize_attachments(
        [{"file_id": "notes", "name": "notes.png"}], str(workdir), owner_id=OWNER
    )

    assert skipped == []
    assert len(staged) == 1
    on_disk = [p for p in workdir.rglob("*") if p.is_file()]
    assert len(on_disk) == 1
    assert on_disk[0].read_bytes() == b"my own notes"


@pytest.mark.asyncio
async def test_image_parts_will_not_show_a_model_another_users_image(stores):
    images, _ = stores
    _write_images_upload(images, "shot", OWNER)

    parts, skipped = await att_mod.build_image_parts(
        [{"file_id": "shot", "name": "shot.png", "mime_type": "image/png"}],
        owner_id=STRANGER,
    )

    assert parts == []
    assert len(skipped) == 1
    assert "no longer on disk" in skipped[0]


@pytest.mark.asyncio
async def test_inline_data_uri_needs_no_owner(stores):
    """Bytes the client already holds are not a stored upload — the ownership
    rule must not break the inline path."""
    tiny = (
        "data:image/gif;base64,"
        "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    )

    data, mime, error = await att_mod.resolve_attachment_bytes({"url": tiny})

    assert error is None
    assert data and data.startswith(b"GIF")
    assert mime == "image/gif"
