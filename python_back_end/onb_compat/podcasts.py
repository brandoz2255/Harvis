"""
open-notebook podcasts compatibility facade — `/onb-api/*`.

Serves the 18 podcast endpoints the vendored open-notebook frontend calls
(`front_end/open-notebook/src/lib/api/podcasts.ts`), backed by Harvis's
standalone podcast pipeline (`standalone_podcasts` table +
`open_notebook.podcast.generator.PodcastGenerator`) and the GPU tts-service
(`http://tts-service:8001`).

Scope decision (built-in profiles cut): episode/speaker/language profiles are
read-only built-ins derived from `open_notebook.podcast.script` (PODCAST_STYLES
+ DEFAULT_SPEAKERS). Profile CRUD (create/update/delete/duplicate) returns 501
"editing not enabled" — only the list endpoints return usable, fully-populated
built-ins so the frontend's `needsModelSetup()` never shows the amber
"setup required" banner.

Episode lifecycle (generate / list / delete / retry) is real and persists to
`standalone_podcasts`. Reuses the native notebooks router's auth + manager
dependencies so a single Harvis JWT authenticates here too.

EXTERNAL DEPENDENCY: audio synthesis requires the `tts-service:8001` container
(SpeechT5/Chatterbox on GPU). If it is down, generation still completes as
`script_only` (transcript saved, no audio) — the same graceful degradation the
native `/api/notebooks/podcasts/generate/stream` route uses.
"""

import os
import json
import logging
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import Response

import httpx

from notebooks.router import (
    get_notebook_manager,
    get_current_user_from_request,
)
from notebooks.manager import NotebookManager

logger = logging.getLogger(__name__)

# Reliable non-reasoning instruct model for outline/transcript generation.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
DEFAULT_CHAT_MODEL = "llama3.1:8b"

# GPU TTS service that synthesizes per-speaker audio. Mirrors the native
# notebooks router (`TTS_URL`). When unreachable, episodes finish as script_only.
TTS_URL = os.environ.get("TTS_URL", "http://tts-service:8001")
DEFAULT_VOICE_MODEL = "chatterbox"

router = APIRouter(prefix="/onb-api", tags=["onb_compat"])


# ─── JSONB normalisation ───────────────────────────────────────────────────────
# asyncpg may hand back a JSONB column as a `str` (when it was inserted via
# json.dumps, as the native helpers do) OR as an already-decoded list/dict
# (depending on codec registration). Normalise both, plus None.

def _json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, dict)):
        return value if isinstance(value, list) else [value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _json_obj(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if hasattr(dt, "isoformat") else (str(dt) if dt else None)


# ─── Built-in profiles (read-only) ─────────────────────────────────────────────
# Mapped from open_notebook.podcast.script.PODCAST_STYLES (5 styles) and
# DEFAULT_SPEAKERS (Host + Guest). outline_llm / transcript_llm / voice_model are
# populated non-null so needsModelSetup() in src/lib/types/podcasts.ts returns
# false (no amber banner).

# A single speaker profile id every episode profile references via speaker_config.
_DEFAULT_SPEAKER_PROFILE_ID = "default-duo"

_LANGUAGES = [
    {"code": "en", "name": "English"},
    {"code": "es", "name": "Spanish"},
    {"code": "fr", "name": "French"},
    {"code": "de", "name": "German"},
    {"code": "pt", "name": "Portuguese"},
    {"code": "it", "name": "Italian"},
    {"code": "zh", "name": "Chinese"},
    {"code": "ja", "name": "Japanese"},
]


def _build_speaker_profiles() -> List[Dict[str, Any]]:
    """Built-in speaker profiles from script.DEFAULT_SPEAKERS, mapped to the
    SpeakerProfile shape (src/lib/types/podcasts.ts)."""
    try:
        from open_notebook.podcast.script import get_default_speakers
        defaults = get_default_speakers()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not load default speakers, using fallback: %s", e)
        defaults = [
            {"name": "Host", "role": "Host", "personality": "Warm, engaging, concise"},
            {"name": "Guest", "role": "Guest", "personality": "Knowledgeable, clear"},
        ]

    speakers = [
        {
            "name": s.get("name", f"Speaker {i + 1}"),
            "voice_id": s.get("voice_id") or "__default__",
            "backstory": s.get("role", "Speaker"),
            "personality": s.get("personality", "Friendly and engaging"),
            "voice_model": DEFAULT_VOICE_MODEL,
        }
        for i, s in enumerate(defaults)
    ]

    return [
        {
            "id": _DEFAULT_SPEAKER_PROFILE_ID,
            "name": "Host & Guest (default)",
            "description": "Built-in two-voice conversational duo synthesized by the GPU TTS service.",
            "voice_model": DEFAULT_VOICE_MODEL,
            "speakers": speakers,
            "tts_provider": DEFAULT_VOICE_MODEL,
            "tts_model": DEFAULT_VOICE_MODEL,
        }
    ]


def _build_episode_profiles() -> List[Dict[str, Any]]:
    """Built-in episode profiles, one per PODCAST_STYLES entry from script.py,
    mapped to the EpisodeProfile shape (src/lib/types/podcasts.ts)."""
    try:
        from open_notebook.podcast.script import get_podcast_styles
        styles = get_podcast_styles()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not load podcast styles, using fallback: %s", e)
        styles = {
            "conversational": "A casual, friendly discussion between two people.",
        }

    profiles = []
    for style_key, description in styles.items():
        profiles.append(
            {
                "id": style_key,  # the style key doubles as the profile id
                "name": style_key.replace("_", " ").title(),
                "description": description,
                "speaker_config": _DEFAULT_SPEAKER_PROFILE_ID,
                # Non-null model refs so needsModelSetup() => false.
                "outline_llm": DEFAULT_CHAT_MODEL,
                "transcript_llm": DEFAULT_CHAT_MODEL,
                "language": "en",
                "default_briefing": (
                    f"Produce a {style_key} podcast episode. {description}"
                ),
                "num_segments": 5,
            }
        )
    return profiles


# ─── Episode (standalone_podcasts) translation ─────────────────────────────────

def _episode_to_onb(row, episode_profiles: List[Dict[str, Any]],
                    speaker_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Map a standalone_podcasts row → the PodcastEpisode shape.

    `status` (pending|generating|completed|error|script_only) → `job_status`
    (the frontend's EpisodeStatus union). `audio_path`/`audio_url` →
    `/onb-api/podcasts/tts-audio/<filename>` so the frontend's
    resolvePodcastAssetUrl() (which prepends the same-origin api base) reaches
    this module's proxy route.
    """
    status = row["status"] or "unknown"
    # Map native statuses → frontend EpisodeStatus union.
    status_map = {
        "pending": "pending",
        "generating": "running",
        "completed": "completed",
        "error": "failed",
        "script_only": "completed",
    }
    job_status = status_map.get(status, "unknown")

    # Match the episode profile by the row's `style`; fall back to first.
    ep_profile = next(
        (p for p in episode_profiles if p["id"] == (row["style"] or "")),
        episode_profiles[0] if episode_profiles else None,
    )
    sp_profile = speaker_profiles[0] if speaker_profiles else None

    audio_path = row["audio_path"]
    audio_url = row["audio_url"] or audio_path
    onb_audio_url = _rewrite_audio_url(audio_url)

    return {
        "id": str(row["id"]),
        "name": row["title"],
        "episode_profile": ep_profile,
        "speaker_profile": sp_profile,
        "briefing": row["outline"] or "",
        "audio_file": onb_audio_url,
        "audio_url": onb_audio_url,
        "transcript": {"segments": _json_list(row["transcript"])},
        "outline": {"text": row["outline"]} if row["outline"] else None,
        "created": _iso(row["created_at"]),
        "job_status": job_status,
        "error_message": row["error_message"],
    }


def _rewrite_audio_url(audio_url: Optional[str]) -> Optional[str]:
    """Native rows store audio_url as `/api/notebooks/podcasts/tts-audio/<file>`.
    Rewrite to this facade's `/onb-api/podcasts/tts-audio/<file>` so the
    open-notebook frontend can fetch it same-origin without the OWUI `/api`
    namespace collision."""
    if not audio_url:
        return None
    if audio_url.startswith("http://") or audio_url.startswith("https://"):
        return audio_url
    filename = audio_url.rstrip("/").split("/")[-1]
    if not filename:
        return audio_url
    # Emit as /api/... (not /onb-api/...): the frontend's resolvePodcastAssetUrl
    # prepends getApiUrl() (→ /onb), and nginx rewrites /onb/api/* → /onb-api/*. So
    # /api/podcasts/tts-audio/X resolves to /onb/api/... → /onb-api/... → this proxy.
    return f"/api/podcasts/tts-audio/{filename}"


# ─── Background generation task ────────────────────────────────────────────────

async def _generate_episode_task(
    db_pool,
    podcast_id: UUID,
    user_id: int,
    title: str,
    content: str,
    style: str,
    speakers: int,
    duration_minutes: int,
):
    """Background task: run the podcast pipeline, synthesize audio via
    tts-service, and write the result back onto the existing
    standalone_podcasts row.

    NOTE: we drive PodcastGenerator with generate_audio=False (script-only) and
    do the audio synthesis ourselves via the GPU tts-service. The convenience
    `run_podcast_generation` wrapper forces generate_audio=True, which uses the
    in-process AudioGenerator (writes to PODCAST_OUTPUT_PATH, a path our
    tts-audio proxy can't serve) — so we bypass it to keep audio reachable
    through /onb-api/podcasts/tts-audio/<file>."""
    from open_notebook.podcast.generator import PodcastGenerator

    audio_path = None
    audio_url = None
    duration_seconds = None
    transcript: List[Any] = []
    outline = None
    error_message = None
    final_status = "completed"

    try:
        # Mark generating.
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE standalone_podcasts SET status = $1 WHERE id = $2",
                "generating", podcast_id,
            )

        # 1. Generate outline + transcript (no audio inside the generator;
        #    we synthesize via the GPU tts-service below to match the native
        #    /generate/stream path).
        generator = PodcastGenerator()
        result = await generator.generate(
            content=content,
            title=title,
            speakers=speakers,
            duration_minutes=duration_minutes,
            style=style,
            generate_audio=False,
        )

        transcript = result.get("transcript", []) or []
        outline = result.get("outline")
        gen_status = result.get("status", "completed")

        if gen_status == "error":
            error_message = result.get("error") or "Script generation failed"
            final_status = "error"
        elif not transcript:
            error_message = "No transcript produced"
            final_status = "error"
        else:
            # 2. Synthesize audio via tts-service (same contract as the native
            #    /generate/stream route).
            audio_path, audio_url, duration_seconds, tts_err = await _synthesize_audio(transcript)
            if audio_path:
                final_status = "completed"
            else:
                # Audio failed but we still have a usable script.
                final_status = "script_only"
                error_message = tts_err

    except Exception as e:
        logger.error("Podcast background generation failed (id=%s): %s", podcast_id, e)
        error_message = str(e)
        final_status = "error"

    # 3. Write result back onto the existing row.
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE standalone_podcasts
                SET status = $1,
                    audio_path = $2,
                    audio_url = $3,
                    transcript = $4,
                    outline = $5,
                    error_message = $6,
                    duration_seconds = $7,
                    completed_at = CASE WHEN $1 IN ('completed', 'script_only', 'error')
                                        THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE id = $8
                """,
                final_status,
                audio_path,
                audio_url,
                json.dumps(transcript),
                outline,
                error_message,
                duration_seconds,
                podcast_id,
            )
    except Exception as e:
        logger.error("Failed to persist podcast result (id=%s): %s", podcast_id, e)


async def _synthesize_audio(transcript: List[Dict[str, Any]]):
    """Call tts-service /generate/podcast. Returns
    (audio_path, audio_url, duration_seconds, error_message)."""
    script_segments = []
    speaker_names = set()
    for seg in transcript:
        if not isinstance(seg, dict):
            continue
        dialogue = (seg.get("dialogue") or seg.get("text") or "").strip()
        speaker = (seg.get("speaker") or "Speaker").strip()
        if dialogue:
            script_segments.append({"speaker": speaker, "text": dialogue})
            speaker_names.add(speaker)

    if not script_segments:
        return None, None, None, "No dialogue segments to synthesize"

    voice_mapping = {name: "__default__" for name in speaker_names}

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{TTS_URL}/generate/podcast",
                json={
                    "script": script_segments,
                    "voice_mapping": voice_mapping,
                    "output_format": "wav",
                    "normalize_audio": True,
                    "add_silence_between_speakers": 0.3,
                },
            )

        if resp.status_code == 200:
            tts_data = resp.json()
            if tts_data.get("success"):
                tts_audio_url = tts_data.get("audio_url", "")
                tts_filename = tts_audio_url.split("/")[-1] if tts_audio_url else ""
                duration_secs = tts_data.get("duration", 0)
                # Store the facade-proxy path so list responses serve it directly.
                # /api/... resolves through nginx's /onb/api → /onb-api rewrite.
                proxy_path = f"/api/podcasts/tts-audio/{tts_filename}"
                return proxy_path, proxy_path, duration_secs, None
            return None, None, None, "TTS returned success=false"
        return None, None, None, f"TTS returned status {resp.status_code}"

    except httpx.RequestError as e:
        logger.warning("tts-service unreachable: %s", e)
        return None, None, None, f"tts-service unreachable: {e}"
    except Exception as e:
        logger.warning("Audio synthesis failed: %s", e)
        return None, None, None, str(e)


async def _resolve_notebook_content(
    manager: NotebookManager,
    notebook_id: Optional[str],
    direct_content: Optional[str],
    source_ids: Optional[List[UUID]] = None,
) -> str:
    """Fetch source/note text for a notebook when the request gives no direct
    content. Mirrors the native _fetch_podcast_content fall-back.

    When `source_ids` is given (Studio "generate from the SELECTED sources"),
    only those sources are used — up to 12, notes excluded — so generation is
    grounded strictly in what the user has checked in the Sources panel."""
    if direct_content and direct_content.strip():
        return direct_content

    if not notebook_id:
        return ""

    # Accept bare uuid or "notebook:<uuid>".
    raw = notebook_id.split(":", 1)[1] if ":" in notebook_id else notebook_id
    try:
        nb_uuid = UUID(raw)
    except (ValueError, AttributeError):
        return ""

    parts: List[str] = []
    try:
        async with manager.db_pool.acquire() as conn:
            if source_ids:
                src_rows = await conn.fetch(
                    """
                    SELECT title, content_text FROM notebook_sources
                    WHERE notebook_id = $1 AND id = ANY($2::uuid[])
                      AND content_text IS NOT NULL
                    ORDER BY created_at ASC LIMIT 12
                    """,
                    nb_uuid, source_ids,
                )
            else:
                src_rows = await conn.fetch(
                    """
                    SELECT title, content_text FROM notebook_sources
                    WHERE notebook_id = $1 AND content_text IS NOT NULL
                    ORDER BY created_at ASC LIMIT 5
                    """,
                    nb_uuid,
                )
            for r in src_rows:
                if r["content_text"]:
                    parts.append(
                        f"\n\n=== SOURCE: {r['title'] or 'Untitled'} ===\n{r['content_text']}"
                    )

            if not source_ids:
                note_rows = await conn.fetch(
                    """
                    SELECT title, content FROM notebook_notes
                    WHERE notebook_id = $1 AND content IS NOT NULL
                    ORDER BY created_at ASC LIMIT 5
                    """,
                    nb_uuid,
                )
                for r in note_rows:
                    if r["content"]:
                        parts.append(
                            f"\n\n=== NOTE: {r['title'] or 'Untitled'} ===\n{r['content']}"
                        )
    except Exception as e:
        logger.warning("Failed to resolve notebook content for %s: %s", notebook_id, e)

    return "".join(parts)


# ─── Profile endpoints (read-only built-ins) ───────────────────────────────────

@router.get("/episode-profiles")
async def list_episode_profiles(
    current_user: Dict = Depends(get_current_user_from_request),
):
    return _build_episode_profiles()


@router.get("/speaker-profiles")
async def list_speaker_profiles(
    current_user: Dict = Depends(get_current_user_from_request),
):
    return _build_speaker_profiles()


@router.get("/languages")
async def list_languages(
    current_user: Dict = Depends(get_current_user_from_request),
):
    return _LANGUAGES


# Profile CRUD is intentionally disabled (built-in profiles cut). The frontend
# only ever calls create/update/delete/duplicate from the profile editor, which
# is not surfaced when built-ins satisfy needsModelSetup(). Return 501 so the
# UI's toast handler shows "editing not enabled" rather than silently echoing.

_EDIT_DISABLED_DETAIL = "Profile editing is not enabled — built-in profiles only."


@router.post("/episode-profiles", status_code=501)
async def create_episode_profile(
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.put("/episode-profiles/{profile_id}", status_code=501)
async def update_episode_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.delete("/episode-profiles/{profile_id}", status_code=501)
async def delete_episode_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.post("/episode-profiles/{profile_id}/duplicate", status_code=501)
async def duplicate_episode_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.post("/speaker-profiles", status_code=501)
async def create_speaker_profile(
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.put("/speaker-profiles/{profile_id}", status_code=501)
async def update_speaker_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.delete("/speaker-profiles/{profile_id}", status_code=501)
async def delete_speaker_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


@router.post("/speaker-profiles/{profile_id}/duplicate", status_code=501)
async def duplicate_speaker_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail=_EDIT_DISABLED_DETAIL)


# ─── Episode endpoints ─────────────────────────────────────────────────────────

@router.post("/podcasts/generate")
async def generate_podcast(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Create a standalone_podcasts row (status=pending) and dispatch the
    generation pipeline as a BackgroundTask. Returns the
    PodcastGenerationResponse shape."""
    body = await request.json()

    episode_profile = body.get("episode_profile") or "conversational"
    speaker_profile = body.get("speaker_profile") or _DEFAULT_SPEAKER_PROFILE_ID
    episode_name = body.get("episode_name") or "Untitled Episode"
    notebook_id = body.get("notebook_id")
    direct_content = body.get("content")
    briefing_suffix = body.get("briefing_suffix")

    # episode_profile id is the style key (see _build_episode_profiles).
    style = episode_profile if episode_profile in {
        p["id"] for p in _build_episode_profiles()
    } else "conversational"

    content = await _resolve_notebook_content(manager, notebook_id, direct_content)
    if briefing_suffix:
        content = f"{content}\n\n{briefing_suffix}" if content else briefing_suffix

    if not content.strip():
        raise HTTPException(
            status_code=400,
            detail="No content available. Provide content, briefing_suffix, or a notebook_id with sources/notes.",
        )

    # standalone_podcasts.notebook_id is TEXT NOT NULL.
    nb_id_text = notebook_id or "notebook:standalone"

    user_id = current_user["id"]

    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO standalone_podcasts
                (notebook_id, user_id, title, status, style, speakers, duration_minutes)
            VALUES ($1, $2, $3, 'pending', $4, 2, 10)
            RETURNING id
            """,
            nb_id_text, user_id, episode_name, style,
        )

    podcast_id = row["id"]

    background_tasks.add_task(
        _generate_episode_task,
        manager.db_pool,
        podcast_id,
        user_id,
        episode_name,
        content,
        style,
        2,   # speakers (Host + Guest built-in duo)
        10,  # duration_minutes
    )

    return {
        "job_id": str(podcast_id),
        "status": "pending",
        "message": f"Podcast generation started for '{episode_name}'",
        "episode_profile": episode_profile,
        "episode_name": episode_name,
    }


@router.get("/podcasts/episodes")
async def list_episodes(
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """List the current user's podcast episodes → PodcastEpisode[]."""
    user_id = current_user["id"]
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, notebook_id, user_id, title, status, style, speakers,
                   duration_minutes, audio_path, audio_url, transcript, outline,
                   error_message, duration_seconds, created_at, completed_at
            FROM standalone_podcasts
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )

    episode_profiles = _build_episode_profiles()
    speaker_profiles = _build_speaker_profiles()
    return [
        _episode_to_onb(row, episode_profiles, speaker_profiles) for row in rows
    ]


@router.delete("/podcasts/episodes/{episode_id}")
async def delete_episode(
    episode_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Delete a podcast episode owned by the current user."""
    try:
        ep_uuid = UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode id")

    user_id = current_user["id"]
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM standalone_podcasts WHERE id = $1 AND user_id = $2",
            ep_uuid, user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Episode not found")
        await conn.execute(
            "DELETE FROM standalone_podcasts WHERE id = $1 AND user_id = $2",
            ep_uuid, user_id,
        )

    return {"success": True, "message": "Episode deleted"}


@router.post("/podcasts/episodes/{episode_id}/retry")
async def retry_episode(
    episode_id: str,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Re-dispatch generation for an existing episode, reusing its stored
    notebook/title/style. Resets status to pending."""
    try:
        ep_uuid = UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid episode id")

    user_id = current_user["id"]
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, notebook_id, title, style, speakers, duration_minutes
            FROM standalone_podcasts
            WHERE id = $1 AND user_id = $2
            """,
            ep_uuid, user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Episode not found")

        await conn.execute(
            """
            UPDATE standalone_podcasts
            SET status = 'pending', error_message = NULL, audio_path = NULL,
                audio_url = NULL, completed_at = NULL
            WHERE id = $1
            """,
            ep_uuid,
        )

    content = await _resolve_notebook_content(manager, row["notebook_id"], None)
    if not content.strip():
        # Re-mark error rather than silently producing an empty podcast.
        async with manager.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE standalone_podcasts SET status = 'error', error_message = $1 WHERE id = $2",
                "No content available to regenerate from", ep_uuid,
            )
        raise HTTPException(
            status_code=400,
            detail="No content available to regenerate this episode.",
        )

    background_tasks.add_task(
        _generate_episode_task,
        manager.db_pool,
        ep_uuid,
        user_id,
        row["title"],
        content,
        row["style"] or "conversational",
        row["speakers"] or 2,
        row["duration_minutes"] or 10,
    )

    return {
        "job_id": str(ep_uuid),
        "message": f"Retrying generation for '{row['title']}'",
    }


# ─── Audio proxy ───────────────────────────────────────────────────────────────

@router.get("/podcasts/tts-audio/{filename}")
async def proxy_tts_audio(filename: str):
    """Proxy audio bytes from the tts-service container. Mirrors the native
    notebooks router's /podcasts/tts-audio/{filename} proxy."""
    safe_filename = os.path.basename(filename)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{TTS_URL}/audio/{safe_filename}")
        if resp.status_code == 200:
            media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else "audio/wav"
            return Response(
                content=resp.content,
                media_type=media_type,
                headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
            )
        raise HTTPException(status_code=404, detail="Audio file not found on TTS service")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"TTS service unreachable: {e}")