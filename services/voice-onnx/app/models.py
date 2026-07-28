"""Model bundles for the ONNX voice service.

Everything here downloads into VOICE_MODELS_DIR (a persistent volume) at first
use. Nothing is baked into the image: the image stays ~400 MB and the models
survive a rebuild, which is the whole reason they live in a volume.

The URLs are immutable GitHub release assets from k2-fsa/sherpa-onnx.
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("voice-onnx.models")

MODELS_DIR = Path(os.getenv("VOICE_MODELS_DIR", "/models"))
_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"


@dataclass(frozen=True)
class Bundle:
    """One downloadable model bundle."""

    name: str
    url: str
    kind: str  # "asr" | "vad" | "tts"
    # An archive extracts to a directory; a bare .onnx lands as a single file.
    archive: bool = True
    engine: str = ""  # asr only: "whisper" | "sense_voice"
    languages: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.kind / self.name


ASR_BUNDLES: dict[str, Bundle] = {
    # The default. 112 MB download, and the same model family the CTranslate2
    # baseline was measured on, so the two are directly comparable.
    "whisper-tiny.en": Bundle(
        name="sherpa-onnx-whisper-tiny.en",
        url=f"{_RELEASE}/asr-models/sherpa-onnx-whisper-tiny.en.tar.bz2",
        kind="asr",
        engine="whisper",
        languages=("en",),
        note="fastest; English only",
    ),
    "whisper-base.en": Bundle(
        name="sherpa-onnx-whisper-base.en",
        url=f"{_RELEASE}/asr-models/sherpa-onnx-whisper-base.en.tar.bz2",
        kind="asr",
        engine="whisper",
        languages=("en",),
        note="better accuracy; English only",
    ),
    "whisper-small.en": Bundle(
        name="sherpa-onnx-whisper-small.en",
        url=f"{_RELEASE}/asr-models/sherpa-onnx-whisper-small.en.tar.bz2",
        kind="asr",
        engine="whisper",
        languages=("en",),
        note="most accurate English; ~3x the CPU cost of base",
    ),
    # Multilingual and non-autoregressive, so it stays fast on CPU. The archive
    # is ~1 GB because it ships both fp32 and int8 weights.
    "sense-voice": Bundle(
        name="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        url=f"{_RELEASE}/asr-models/"
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
        kind="asr",
        engine="sense_voice",
        languages=("en", "zh", "ja", "ko", "yue"),
        note="multilingual; large download",
    ),
}

VAD_BUNDLE = Bundle(
    name="silero_vad.onnx",
    url=f"{_RELEASE}/asr-models/silero_vad.onnx",
    kind="vad",
    archive=False,
)

TTS_BUNDLES: dict[str, Bundle] = {
    # Matches the model the browser path already uses (Kokoro 82M v1.0), so a
    # voice picked in the UI sounds the same whether it rendered in the browser
    # or on the server.
    "kokoro-v1.0": Bundle(
        name="kokoro-multi-lang-v1_0",
        url=f"{_RELEASE}/tts-models/kokoro-multi-lang-v1_0.tar.bz2",
        kind="tts",
        languages=("en", "zh", "ja", "ko", "fr", "it", "pt", "es", "hi"),
    ),
    "kokoro-v0.19": Bundle(
        name="kokoro-en-v0_19",
        url=f"{_RELEASE}/tts-models/kokoro-en-v0_19.tar.bz2",
        kind="tts",
        languages=("en",),
        note="English only, 11 voices",
    ),
}

def read_speaker_names(model_path: Path) -> tuple[str, ...]:
    """Pull the `speaker_names` entry out of an ONNX model's metadata.

    k2-fsa stamps the authoritative voice order into the model itself, which is
    the only source that cannot drift from the weights. Parsed by hand because
    the alternative is adding an onnx/protobuf dependency to read one string.
    """
    key = b"speaker_names"
    size = model_path.stat().st_size
    window = 8 << 20
    with model_path.open("rb") as f:
        # Metadata sits at the tail in practice; fall back to the head, then to
        # a full scan for a model that puts it somewhere else.
        spans = [(max(0, size - window), min(size, window))]
        if size > window:
            spans.append((0, window))
        if size > 2 * window:
            spans.append((0, size))
        for offset, length in spans:
            f.seek(offset)
            blob = f.read(length)
            i = blob.find(key)
            if i < 0:
                continue
            p = i + len(key)
            if p >= len(blob) or blob[p] != 0x12:  # protobuf field 2, length-delimited
                continue
            p += 1
            n, shift = 0, 0
            while p < len(blob):
                b = blob[p]
                p += 1
                n |= (b & 0x7F) << shift
                if not b & 0x80:
                    break
                shift += 7
            value = blob[p:p + n].decode("utf-8", "replace")
            names = tuple(v.strip() for v in value.split(",") if v.strip())
            if names:
                return names
    return ()


# Fallback speaker order, used only when a bundle's model carries no
# `speaker_names` metadata. Verified against `tts.num_speakers` at load time — a
# mismatch drops to numeric ids rather than handing the UI a wrong name.
KOKORO_VOICES: dict[str, tuple[str, ...]] = {
    "kokoro-en-v0_19": (
        "af", "af_bella", "af_nicole", "af_sarah", "af_sky",
        "am_adam", "am_michael", "bf_emma", "bf_isabella",
        "bm_george", "bm_lewis",
    ),
    "kokoro-multi-lang-v1_0": (
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
    ),
}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("downloading %s", url)
    with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    tmp.replace(dest)


def _extract(archive: Path, target: Path) -> None:
    """Extract into a temp dir and rename, so a killed download never leaves a
    half-populated bundle that later looks complete."""
    staging = Path(tempfile.mkdtemp(dir=str(target.parent), prefix=".x-"))
    try:
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                # Refuse absolute paths and traversal, whatever the archive says.
                name = member.name.lstrip("/")
                if ".." in Path(name).parts:
                    raise ValueError(f"unsafe path in archive: {member.name}")
                member.name = name
                tf.extract(member, staging)
        roots = [p for p in staging.iterdir() if p.is_dir()]
        src = roots[0] if len(roots) == 1 else staging
        if target.exists():
            shutil.rmtree(target)
        src.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def ensure(bundle: Bundle) -> Path:
    """Return the local path for `bundle`, downloading it if it isn't there."""
    if bundle.path.exists():
        return bundle.path
    with _lock_for(f"{bundle.kind}/{bundle.name}"):
        if bundle.path.exists():
            return bundle.path
        bundle.path.parent.mkdir(parents=True, exist_ok=True)
        if not bundle.archive:
            _download(bundle.url, bundle.path)
            return bundle.path
        with tempfile.TemporaryDirectory(dir=str(bundle.path.parent)) as td:
            archive = Path(td) / "bundle.tar.bz2"
            _download(bundle.url, archive)
            _extract(archive, bundle.path)
        log.info("installed %s", bundle.path)
        return bundle.path


def is_present(bundle: Bundle) -> bool:
    return bundle.path.exists()


def pick_asr(name: str | None = None) -> Bundle:
    key = name or os.getenv("VOICE_ASR_MODEL", "whisper-tiny.en")
    if key not in ASR_BUNDLES:
        raise KeyError(f"unknown ASR model {key!r}; have {sorted(ASR_BUNDLES)}")
    return ASR_BUNDLES[key]


def pick_tts(name: str | None = None) -> Bundle:
    key = name or os.getenv("VOICE_TTS_MODEL", "kokoro-v1.0")
    if key not in TTS_BUNDLES:
        raise KeyError(f"unknown TTS model {key!r}; have {sorted(TTS_BUNDLES)}")
    return TTS_BUNDLES[key]
