"""The front-door nginx must never expose unowned temp audio."""
from pathlib import Path
import re


def test_legacy_audio_is_rejected_before_regex_locations():
    config = (Path(__file__).resolve().parents[2] / "nginx-harvis.conf").read_text()
    assert re.search(r"location\s+\^~\s+/audio/\s*\{\s*return\s+404\s*;\s*\}", config)
    assert not re.search(r"alias\s+/tmp(?:/|;)", config)
