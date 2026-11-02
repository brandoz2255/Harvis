"""Podcast audio through the speech sidecar that ships by default.

The notebook podcast code was written against ``tts-service`` (the RVC stack
behind the ``advanced-voice`` profile). A default install doesn't run it, so
every podcast ended as ``script_only``. This speaks each line through the
OpenAI-compatible ``/audio/speech`` endpoint synthesis.py already uses
(``HARVIS_TTS_URL``, voice-onnx by default), gives each speaker their own
voice, and joins the WAV clips with a short pause between turns.
"""
from __future__ import annotations

import io
import os
import uuid
import wave
from pathlib import Path
from typing import Optional

import httpx

AUDIO_DIR = Path(os.getenv("NOTEBOOK_PODCAST_AUDIO_DIR", "/data/artifacts/notebook_podcasts"))
VOICES = ("af_heart", "am_michael", "bf_emma", "bm_george")
# Every voice the speech service's default model (Kokoro v1.0) offers, in the service's own
# order. Copied from KOKORO_VOICES in services/voice-onnx/app/models.py; a test keeps the two
# in step, so a voice picked here is one the service will accept.
KOKORO_VOICES = (
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    "ef_dora", "em_alex", "em_santa",
    "ff_siwis",
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola",
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
)
_LANGUAGE_OF = {"a": "en-US", "b": "en-GB", "e": "es", "f": "fr", "h": "hi",
                "i": "it", "j": "ja", "p": "pt-BR", "z": "zh"}
PAUSE_SECONDS = 0.3
_FILENAME_OK = frozenset("abcdef0123456789-")


def is_voice(voice: object) -> bool:
    return isinstance(voice, str) and voice in KOKORO_VOICES


def voice_catalog() -> list[dict]:
    """The pickable voices: ``{id, name, gender, language}`` (same labels the service reports)."""
    return [
        {
            "id": v,
            "name": v.split("_", 1)[-1].replace("-", " ").title(),
            "gender": {"f": "female", "m": "male"}.get(v[1:2], "unknown"),
            "language": _LANGUAGE_OF.get(v[:1], "en-US"),
        }
        for v in KOKORO_VOICES
    ]


def _speaker_key(speaker: str) -> str:
    return " ".join((speaker or "Speaker").split()).casefold()


def chosen_voices(cast: Optional[list]) -> dict[str, str]:
    """``{speaker key: voice id}`` for the cast members with a real voice picked.

    Members left on "automatic" and ids the service does not offer are skipped, so a bad
    stored value falls back to an automatic voice instead of failing the episode.
    """
    out: dict[str, str] = {}
    for member in cast or []:
        if isinstance(member, dict) and is_voice(member.get("voice_id")):
            out.setdefault(_speaker_key(str(member.get("name") or "")), member["voice_id"])
    return out


def speech_url() -> str:
    base = (os.getenv("HARVIS_TTS_URL") or "http://voice-onnx:8000/v1").rstrip("/")
    return f"{base}/audio/speech"


def voice_for(speaker: str, order: dict[str, str]) -> str:
    """Each new speaker takes the next voice; a fifth reuses the first.

    Speakers are matched ignoring case and spacing, so "Alex" and "alex " are one
    person with one voice for the whole episode. ``order`` may start with voices the
    user picked; automatic speakers then take the next default voice nobody holds.
    """
    key = _speaker_key(speaker)
    if key not in order:
        free = [v for v in VOICES if v not in order.values()]
        order[key] = free[0] if free else VOICES[len(order) % len(VOICES)]
    return order[key]


class PodcastAudioError(Exception):
    """The audio could not be made. ``str(exc)`` says why, in words the user can act on."""


def join_wavs(clips: list[bytes], pause: float = PAUSE_SECONDS) -> tuple[bytes, float]:
    """Concatenate WAV clips that share one format, with silence between them."""
    out = io.BytesIO()
    params = None
    frames = 0
    with wave.open(out, "wb") as dst:
        for i, clip in enumerate(clips):
            with wave.open(io.BytesIO(clip), "rb") as src:
                p = src.getparams()
                if params is None:
                    params = p
                    dst.setnchannels(p.nchannels)
                    dst.setsampwidth(p.sampwidth)
                    dst.setframerate(p.framerate)
                elif (p.nchannels, p.sampwidth, p.framerate) != (params.nchannels, params.sampwidth, params.framerate):
                    raise ValueError("speech clips came back in different formats")
                if i:
                    gap = int(params.framerate * pause)
                    dst.writeframes(b"\x00" * gap * params.sampwidth * params.nchannels)
                    frames += gap
                dst.writeframes(src.readframes(p.nframes))
                frames += p.nframes
    if params is None:
        raise ValueError("no speech to join")
    return out.getvalue(), frames / params.framerate


async def synthesize(
    segments: list[dict], model: Optional[str] = None, voices: Optional[dict[str, str]] = None
) -> tuple[str, float]:
    """Speak every ``{speaker, text}`` segment; return (filename, seconds).

    ``voices`` maps speaker keys (see ``chosen_voices``) to the voice the user picked.
    """
    order: dict[str, str] = dict(voices or {})
    clips: list[bytes] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            resp = await client.post(speech_url(), json={
                "model": model or os.getenv("HARVIS_TTS_MODEL") or "kokoro",
                "input": text,
                "voice": voice_for(seg.get("speaker") or "Speaker", order),
                "response_format": "wav",
            })
            resp.raise_for_status()
            clips.append(resp.content)
    if not clips:
        raise ValueError("no speech to join")
    audio, seconds = join_wavs(clips)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4()}.wav"
    (AUDIO_DIR / name).write_bytes(audio)
    return name, seconds


def local_file(filename: str) -> Optional[Path]:
    """The saved podcast for ``filename``, or None. Only our own uuid names resolve."""
    stem, _, ext = filename.partition(".")
    if ext != "wav" or not stem or set(stem) - _FILENAME_OK:
        return None
    path = AUDIO_DIR / filename
    return path if path.is_file() else None


async def user_owns_audio(pool, user_id: int, filename: str) -> bool:
    """True when ``filename`` is the audio of an episode this user generated."""
    if pool is None or not filename:
        return False
    tail = "/" + filename
    async with pool.acquire() as conn:
        for table, cols in (("standalone_podcasts", ("audio_path", "audio_url")),
                            ("notebook_podcasts", ("audio_path",))):
            test = " OR ".join(f"RIGHT({c}, LENGTH($2)) = $2" for c in cols)
            if await conn.fetchval(f"SELECT 1 FROM {table} WHERE user_id = $1 AND ({test}) LIMIT 1",
                                   user_id, tail):
                return True
    return False


async def make_audio(segments: list[dict], voices: Optional[dict[str, str]] = None) -> dict:
    """Speak a script and return ``{audio_path, audio_url, duration_seconds}``.

    Uses the optional ``tts-service`` when ``TTS_URL`` is set (it has its own voices, so
    ``voices`` does not apply there), otherwise the default speech sidecar. Raises PodcastAudioError with a plain message on any failure so
    the caller can save the script and show the reason instead of silently dropping
    the audio.
    """
    segments = [s for s in segments if (s.get("text") or "").strip()]
    if not segments:
        raise PodcastAudioError("There was nothing to say: the script has no spoken lines.")
    tts_url = os.environ.get("TTS_URL")
    where = tts_url or speech_url()
    try:
        if not tts_url:
            name, seconds = await synthesize(segments, voices=voices)
            path = f"/api/notebooks/podcasts/tts-audio/{name}"
            return {"audio_path": path, "audio_url": path, "duration_seconds": seconds}
        voice_mapping = {(s.get("speaker") or "Speaker"): "__default__" for s in segments}
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{tts_url.rstrip('/')}/generate/podcast", json={
                "script": segments,
                "voice_mapping": voice_mapping,
                "output_format": "wav",
                "normalize_audio": True,
                "add_silence_between_speakers": 0.3,
            })
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise PodcastAudioError("The speech service reported that it could not make the audio.")
        filename = (data.get("audio_url") or "").split("/")[-1]
        if not filename:
            raise PodcastAudioError("The speech service did not return an audio file.")
        path = f"/api/notebooks/podcasts/tts-audio/{filename}"
        return {"audio_path": path, "audio_url": path, "duration_seconds": data.get("duration", 0)}
    except PodcastAudioError:
        raise
    except httpx.HTTPStatusError as exc:
        raise PodcastAudioError(
            f"The speech service answered HTTP {exc.response.status_code}. Check that it is running "
            "and has a voice model loaded, then generate the audio again."
        ) from exc
    except httpx.TimeoutException as exc:
        raise PodcastAudioError("The speech service took too long to answer. Try a shorter episode.") from exc
    except httpx.HTTPError as exc:
        raise PodcastAudioError(
            f"The speech service could not be reached at {where.split('//')[-1].split('/')[0]}. "
            "Start it (the voice service) and generate the audio again."
        ) from exc
    except ValueError as exc:
        raise PodcastAudioError(f"The speech service returned audio Notebooks could not join ({str(exc)[:80]}).") from exc
    except OSError as exc:
        raise PodcastAudioError(f"The audio could not be saved on the server ({str(exc)[:80]}).") from exc
