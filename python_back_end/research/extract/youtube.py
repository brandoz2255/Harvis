# python_back_end/research/extract/youtube.py
from __future__ import annotations
from typing import Dict, Any, Optional
import logging
import re
import requests

logger = logging.getLogger(__name__)

YOUTUBE_HOSTS = ("youtube.com", "youtu.be")

def _extract_video_id(url: str) -> Optional[str]:
    # Common patterns: youtu.be/<id>, youtube.com/watch?v=<id>, /shorts/<id>
    m = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    return m.group(1) if m else None

def _fetch_oembed_title(url: str, timeout_s: int) -> str:
    try:
        r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=timeout_s)
        if r.ok:
            return (r.json().get("title") or "").strip()
    except Exception:
        pass
    return ""

def extract_youtube(url: str, timeout_s: int) -> Dict[str, Any]:
    """
    Extract human-readable text from YouTube:
    - Prefer the official transcript (youtube-transcript-api).
    - Fallback: ytdlp auto-generated subtitles (if available).
    - Always try to fetch a title via oEmbed for context.
    """
    vid = _extract_video_id(url)
    title = _fetch_oembed_title(url, timeout_s=timeout_s)

    # 1) Try youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
        transcript_list = YouTubeTranscriptApi.list_transcripts(vid)  # may raise
        # prefer English if available, else first transcript
        t = None
        try:
            t = transcript_list.find_transcript(["en"])
        except Exception:
            t = next(iter(transcript_list), None)
        if t:
            items = t.fetch()
            text = " ".join(seg.get("text", "") for seg in items)
            return {
                "url": url,
                "title": title,
                "text": text,
                "language": t.language_code if hasattr(t, "language_code") else None,
                "meta": {"kind": "youtube_transcript", "video_id": vid},
                "success": bool(text),
            }
    except Exception as e:
        logger.debug(f"youtube_transcript_api failed: {e}")

    # 2) Try yt-dlp subtitles
    try:
        import yt_dlp  # type: ignore

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "writesubtitles": True,
            "subtitleslangs": ["en", "en-US", "en-GB", "en.*", "auto"],
            "subtitlesformat": "vtt",
            "noplaylist": True,
            "outtmpl": "%(id)s",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subs = info.get("subtitles") or info.get("automatic_captions") or {}
            # pick first available track
            track = None
            for _, tracks in subs.items():
                if tracks:
                    track = tracks[0]
                    break
            if track and "url" in track:
                r = requests.get(track["url"], timeout=timeout_s)
                r.raise_for_status()
                vtt = r.text
                # rough VTT to text
                import re
                lines = []
                for ln in vtt.splitlines():
                    if ln.strip() and not re.match(r"^\d+$|^\d{2}:\d{2}:\d{2}\.\d{3}", ln):
                        if "-->" in ln or ln.startswith("WEBVTT"):
                            continue
                        lines.append(ln.strip())
                text = " ".join(lines)
                return {
                    "url": url,
                    "title": title,
                    "text": text,
                    "language": None,
                    "meta": {"kind": "yt_dlp_subtitles", "video_id": vid},
                    "success": bool(text),
                }
    except Exception as e:
        logger.debug(f"yt-dlp subtitles fallback failed: {e}")

    # final fallback: just return title (better than nothing)
    return {
        "url": url,
        "title": title or "YouTube Video",
        "text": "",
        "language": None,
        "meta": {"kind": "youtube_fallback", "video_id": vid},
        "success": False,
    }

