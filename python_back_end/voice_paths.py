"""Where a client-named voice sample may come from.

``audio_prompt`` and a TTS job's ``voice_id`` used to be opened as server file paths,
so a signed-in user could point voice cloning at any audio file on the box and hear
it back. A name now resolves only inside the voice directory (``HARVIS_VOICE_DIR``,
default ``voices/`` beside this file), symlinks and ``..`` included.
"""
from __future__ import annotations

import os
from typing import Optional

_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


def voice_dir() -> str:
    return os.path.realpath(os.getenv("HARVIS_VOICE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices"))


def resolve_voice_prompt(value: Optional[str]) -> Optional[str]:
    """The real path of a sample under the voice directory, or None (use the default voice)."""
    if not value or not isinstance(value, str) or "\x00" in value:
        return None
    root = voice_dir()
    candidate = os.path.realpath(value if os.path.isabs(value) else os.path.join(root, value))
    if os.path.commonpath([root, candidate]) != root or candidate == root:
        return None
    if not candidate.lower().endswith(_AUDIO_EXTS) or not os.path.isfile(candidate):
        return None
    return candidate
