"""sherpa-onnx engines: recognition, voice activity detection, Kokoro synthesis.

Each engine loads lazily on first use and is cached for the process lifetime.
Loading is what downloads the model bundle, so the container starts instantly
and the first request pays the download once.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sherpa_onnx

from . import models

log = logging.getLogger("voice-onnx.engines")

SAMPLE_RATE = 16000
NUM_THREADS = int(os.getenv("VOICE_NUM_THREADS", "2"))

_load_lock = threading.Lock()
_asr_cache: dict[str, "Recognizer"] = {}
_tts_cache: dict[str, "Synthesizer"] = {}
_vad_holder: list = []


class VoiceError(RuntimeError):
    """Anything the caller should see as a clean 4xx/503 rather than a crash."""


# --------------------------------------------------------------------------- #
# audio
# --------------------------------------------------------------------------- #

def decode_audio(raw: bytes, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any browser-produced container (webm/ogg/mp4/wav/mp3) to mono
    float32 at `sample_rate`. ffmpeg handles the format zoo so we don't have to."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "f32le", "-ac", "1", "-ar", str(sample_rate),
        "pipe:1",
    ]
    proc = subprocess.run(cmd, input=raw, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:400]
        raise VoiceError(f"could not decode audio: {detail or 'empty output'}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """float32 samples -> 16-bit PCM WAV, written by hand to keep the
    dependency list at zero for the most common response format."""
    import io
    import wave

    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def encode_audio(samples: np.ndarray, sample_rate: int, fmt: str) -> tuple[bytes, str]:
    """Return (bytes, mime) in the requested format. Anything other than wav
    goes through ffmpeg, which is already in the image for decoding."""
    fmt = (fmt or "wav").lower()
    wav = wav_bytes(samples, sample_rate)
    if fmt == "wav":
        return wav, "audio/wav"
    mimes = {"mp3": "audio/mpeg", "opus": "audio/ogg", "flac": "audio/flac",
             "aac": "audio/aac", "pcm": "audio/L16"}
    if fmt not in mimes:
        raise VoiceError(f"unsupported response_format {fmt!r}")
    if fmt == "pcm":
        return wav[44:], mimes[fmt]
    args = {"mp3": ["-f", "mp3"], "opus": ["-f", "ogg", "-c:a", "libopus"],
            "flac": ["-f", "flac"], "aac": ["-f", "adts"]}[fmt]
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"],
        input=wav, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise VoiceError(f"encoding to {fmt} failed: "
                         f"{proc.stderr.decode('utf-8', 'replace')[:200]}")
    return proc.stdout, mimes[fmt]


# --------------------------------------------------------------------------- #
# VAD
# --------------------------------------------------------------------------- #

@dataclass
class Segment:
    start: float
    end: float
    samples: np.ndarray


_vad_lock = threading.Lock()


def get_vad() -> sherpa_onnx.VoiceActivityDetector:
    if _vad_holder:
        return _vad_holder[0]
    with _load_lock:
        if _vad_holder:
            return _vad_holder[0]
        path = models.ensure(models.VAD_BUNDLE)
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(path)
        cfg.silero_vad.threshold = float(os.getenv("VOICE_VAD_THRESHOLD", "0.5"))
        cfg.silero_vad.min_silence_duration = 0.35
        cfg.silero_vad.min_speech_duration = 0.15
        cfg.silero_vad.max_speech_duration = 20.0
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = NUM_THREADS
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        _vad_holder.append(vad)
        log.info("VAD ready (silero)")
        return vad


def _drain(vad, out: list[Segment]) -> None:
    while not vad.empty():
        seg = vad.front
        samples = np.asarray(seg.samples, dtype=np.float32)
        out.append(Segment(
            start=seg.start / SAMPLE_RATE,
            end=(seg.start + len(samples)) / SAMPLE_RATE,
            samples=samples,
        ))
        vad.pop()


def split_speech(samples: np.ndarray) -> list[Segment]:
    """Return the speech regions of `samples`. An empty list means the clip is
    silence — worth knowing, because it turns 'the model returned nothing' into
    'there was nothing to transcribe'.

    The detector carries state between frames, so one request holds it at a
    time; the model is 2 MB and the work is milliseconds, so the lock costs
    less than reloading it per call.
    """
    vad = get_vad()
    window = vad.config.silero_vad.window_size or 512
    out: list[Segment] = []
    with _vad_lock:
        vad.reset()
        for start in range(0, len(samples), window):
            frame = samples[start:start + window]
            if len(frame) < window:  # silero wants exactly window_size samples
                frame = np.pad(frame, (0, window - len(frame)))
            vad.accept_waveform(frame)
            _drain(vad, out)
        vad.flush()
        _drain(vad, out)
        vad.reset()
    return out


# --------------------------------------------------------------------------- #
# ASR
# --------------------------------------------------------------------------- #

class Recognizer:
    def __init__(self, bundle: models.Bundle, language: str = "en"):
        self.bundle = bundle
        self.language = language
        path = models.ensure(bundle)
        if bundle.engine == "whisper":
            enc = _pick(path, "*encoder*.onnx")
            dec = _pick(path, "*decoder*.onnx")
            tokens = _pick(path, "*tokens.txt")
            self.impl = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=str(enc), decoder=str(dec), tokens=str(tokens),
                language=language or "en", task="transcribe",
                num_threads=NUM_THREADS, provider="cpu",
            )
        elif bundle.engine == "sense_voice":
            self.impl = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(_pick(path, "model*.onnx")),
                tokens=str(_pick(path, "tokens.txt")),
                language=language or "",
                use_itn=True,
                num_threads=NUM_THREADS, provider="cpu",
            )
        else:  # pragma: no cover - registry is closed
            raise VoiceError(f"unsupported ASR engine {bundle.engine!r}")
        log.info("ASR ready (%s, lang=%s)", bundle.name, language)

    # Whisper drops the first and last word of a clip that starts or ends
    # exactly on speech, and VAD hands us segments trimmed to precisely that.
    # A quarter-second of silence on each side costs nothing and gets those
    # words back — measured: "The quick brown fox … on ONNX" lost both "The"
    # and "ONNX" without it.
    PAD_SECONDS = 0.25

    def transcribe(self, samples: np.ndarray) -> str:
        pad = np.zeros(int(self.PAD_SECONDS * SAMPLE_RATE), dtype=np.float32)
        samples = np.concatenate([pad, samples, pad])
        stream = self.impl.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        self.impl.decode_stream(stream)
        return stream.result.text.strip()


def _pick(root: Path, pattern: str) -> Path:
    """Pick one file from a bundle, preferring the int8 build when both exist —
    that is the difference between a 400 MB and a 1 GB resident set on CPU."""
    hits = sorted(root.rglob(pattern))
    if not hits:
        raise VoiceError(f"{pattern} missing from {root}")
    int8 = [h for h in hits if ".int8." in h.name]
    return (int8 or hits)[0]


def get_recognizer(model: str | None = None, language: str | None = None) -> Recognizer:
    bundle = models.pick_asr(model)
    lang = (language or os.getenv("VOICE_ASR_LANGUAGE", "en") or "en").lower()
    if bundle.languages and lang not in bundle.languages:
        raise VoiceError(
            f"model {bundle.name} does not support language {lang!r} "
            f"(supports {', '.join(bundle.languages)})"
        )
    key = f"{bundle.name}:{lang}"
    if key in _asr_cache:
        return _asr_cache[key]
    with _load_lock:
        if key not in _asr_cache:
            _asr_cache[key] = Recognizer(bundle, lang)
    return _asr_cache[key]


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #

class Synthesizer:
    def __init__(self, bundle: models.Bundle):
        self.bundle = bundle
        path = models.ensure(bundle)
        cfg = sherpa_onnx.OfflineTtsConfig()
        k = cfg.model.kokoro
        k.model = str(_pick(path, "model*.onnx"))
        k.voices = str(_pick(path, "voices.bin"))
        k.tokens = str(_pick(path, "tokens.txt"))
        data_dir = path / "espeak-ng-data"
        if data_dir.is_dir():
            k.data_dir = str(data_dir)
        dict_dir = path / "dict"
        if dict_dir.is_dir():
            k.dict_dir = str(dict_dir)
        lexicons = sorted(str(p) for p in path.glob("lexicon*.txt"))
        if lexicons:
            k.lexicon = ",".join(lexicons)
        cfg.model.num_threads = NUM_THREADS
        cfg.model.provider = "cpu"
        cfg.max_num_sentences = 2
        self.impl = sherpa_onnx.OfflineTts(cfg)
        self.sample_rate = self.impl.sample_rate

        names = models.read_speaker_names(Path(k.model))
        source = "model metadata"
        if len(names) != self.impl.num_speakers:
            names = models.KOKORO_VOICES.get(bundle.name, ())
            source = "built-in list"
        if len(names) != self.impl.num_speakers:
            # Never hand the UI a name we can't stand behind.
            log.warning("no voice list matches %s (model reports %d speakers) "
                        "— falling back to numeric ids",
                        bundle.name, self.impl.num_speakers)
            source = "numeric ids"
            names = tuple(f"voice-{i}" for i in range(self.impl.num_speakers))
        self.voices: tuple[str, ...] = names
        self.voice_source = source
        log.info("TTS ready (%s, %d voices from %s, %d Hz)",
                 bundle.name, len(self.voices), source, self.sample_rate)

    def sid_for(self, voice: str | None) -> int:
        if voice is None or voice == "":
            voice = os.getenv("VOICE_TTS_VOICE", self.voices[0])
        if isinstance(voice, str) and voice.isdigit():
            sid = int(voice)
        elif voice in self.voices:
            sid = self.voices.index(voice)
        else:
            raise VoiceError(f"unknown voice {voice!r}")
        if not 0 <= sid < len(self.voices):
            raise VoiceError(f"voice id {sid} out of range 0..{len(self.voices) - 1}")
        return sid

    def synthesize(self, text: str, voice: str | None, speed: float) -> np.ndarray:
        audio = self.impl.generate(text, sid=self.sid_for(voice), speed=speed)
        return np.asarray(audio.samples, dtype=np.float32)


def get_synthesizer(model: str | None = None) -> Synthesizer:
    bundle = models.pick_tts(model)
    if bundle.name in _tts_cache:
        return _tts_cache[bundle.name]
    with _load_lock:
        if bundle.name not in _tts_cache:
            _tts_cache[bundle.name] = Synthesizer(bundle)
    return _tts_cache[bundle.name]


def loaded_state() -> dict:
    """What /health reports: loaded vs merely downloaded vs absent."""
    asr = models.pick_asr()
    tts = models.pick_tts()
    return {
        "asr": {
            "model": asr.name,
            "downloaded": models.is_present(asr),
            "loaded": any(k.startswith(asr.name + ":") for k in _asr_cache),
            "languages": list(asr.languages),
        },
        "vad": {
            "model": models.VAD_BUNDLE.name,
            "downloaded": models.is_present(models.VAD_BUNDLE),
            "loaded": bool(_vad_holder),
        },
        "tts": {
            "model": tts.name,
            "downloaded": models.is_present(tts),
            "loaded": tts.name in _tts_cache,
        },
    }
