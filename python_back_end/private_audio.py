"""Owner-bound private audio storage for synthesized speech.

Layout: ``$TMPDIR/harvis-private-audio/<user_id>/<name>.wav``.

Every open is dir_fd-relative with O_NOFOLLOW, so a symlink swapped in after
any check — for the clip itself or for either directory — cannot redirect a
read or write outside the caller's namespace. The FastAPI routes in main.py
and the background TTS worker in job_queue.py both go through here so the
producer and the playback route can never disagree about where owned audio
lives (the worker used to write the shared temp root, which the playback
route rightly refuses to serve).

Clips are read-back-once artifacts: the chat payload they were rendered from
is the durable record. cleanup_private_audio() reaps them after a TTL so /tmp
cannot grow without bound.
"""

from __future__ import annotations

import io
import logging
import os
import re
import stat
import tempfile
import time

log = logging.getLogger(__name__)

ROOT_NAME = "harvis-private-audio"
_NAME_RE = re.compile(r"[^/\\\x00]+\.wav")

# Six hours covers a paused-and-resumed session without turning /tmp into an
# archive. Deployments tune it with HARVIS_PRIVATE_AUDIO_TTL_SECONDS.
DEFAULT_TTL_SECONDS = int(
    os.environ.get("HARVIS_PRIVATE_AUDIO_TTL_SECONDS", str(6 * 60 * 60))
)

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def valid_name(name: str) -> bool:
    """A private clip name is a slash-free *.wav — nothing else is servable."""
    return bool(_NAME_RE.fullmatch(name or ""))


def open_private_dir(user_id: int, *, create: bool = False) -> int:
    """Open the user's private audio directory; the caller closes the fd.

    Refuses (OSError) when any component is missing (without create=True),
    is a symlink, or is a directory someone else could write — a 0700 dir
    owned by this process's euid is the only trusted shape.
    """
    parent = os.open(tempfile.gettempdir(), _DIR_FLAGS)
    try:
        for name in (ROOT_NAME, str(int(user_id))):
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            child = os.open(name, _DIR_FLAGS, dir_fd=parent)
            try:
                info = os.fstat(child)
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077
                ):
                    raise OSError("Unsafe private audio directory")
            except BaseException:
                os.close(child)
                raise
            os.close(parent)
            parent = child
        return parent
    except BaseException:
        os.close(parent)
        raise


def write_private_audio(user_id: int, name: str, data: bytes) -> str:
    """Write bytes as the owner's private clip; returns the playback path."""
    if not valid_name(name):
        raise ValueError(f"Not a private audio name: {name!r}")
    directory = open_private_dir(user_id, create=True)
    try:
        # O_EXCL: names carry a random uuid, so a collision means the name
        # source is broken — and silently overwriting a clip another request
        # may be reading is worse than failing this write.
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(fd, "wb") as clip:
                clip.write(data)
        except BaseException:
            os.unlink(name, dir_fd=directory)
            raise
    finally:
        os.close(directory)
    return f"/api/audio/{name}"


def write_private_wav(user_id: int, name: str, wav, sample_rate) -> str:
    """Encode (wav, sample_rate) as WAV into the owner's namespace.

    soundfile is imported lazily so this module stays importable in minimal
    tooling environments; every runtime caller already has it.
    """
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    return write_private_audio(user_id, name, buffer.getvalue())


def cleanup_private_audio(
    max_age_seconds: int = DEFAULT_TTL_SECONDS, *, now: float | None = None
) -> int:
    """Delete private clips older than the TTL; returns the number removed.

    Best-effort per entry: an unreadable or unsafe user directory is left
    entirely alone (a directory whose ownership/mode we can't trust is not
    ours to delete from). Empty user directories are removed afterwards.
    """
    now = time.time() if now is None else now
    removed = 0
    try:
        base = os.open(tempfile.gettempdir(), _DIR_FLAGS)
    except OSError:
        return 0
    try:
        try:
            root = os.open(ROOT_NAME, _DIR_FLAGS, dir_fd=base)
        except OSError:
            return 0
    finally:
        os.close(base)
    try:
        for entry in os.listdir(root):
            try:
                userdir = os.open(entry, _DIR_FLAGS, dir_fd=root)
            except OSError:
                continue
            try:
                info = os.fstat(userdir)
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077
                ):
                    continue
                for name in os.listdir(userdir):
                    if not valid_name(name):
                        continue
                    try:
                        st = os.stat(name, dir_fd=userdir, follow_symlinks=False)
                    except OSError:
                        continue
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    if now - st.st_mtime < max_age_seconds:
                        continue
                    try:
                        os.unlink(name, dir_fd=userdir)
                        removed += 1
                    except OSError:
                        pass
                if not os.listdir(userdir):
                    try:
                        os.rmdir(entry, dir_fd=root)
                    except OSError:
                        pass
            finally:
                os.close(userdir)
    finally:
        os.close(root)
    if removed:
        log.info("🧹 Reaped %d expired private audio clip(s)", removed)
    return removed
