"""
open-notebook podcasts compatibility facade — `/onb-api/*`.

Serves the 18 podcast endpoints the vendored open-notebook frontend calls
(`front_end/open-notebook/src/lib/api/podcasts.ts`), backed by Harvis's
standalone podcast pipeline (`standalone_podcasts` table +
`open_notebook.podcast.generator.PodcastGenerator`) and the GPU tts-service
(`http://tts-service:8001`).

Profiles: the built-in episode/speaker profiles derived from
`open_notebook.podcast.script` (PODCAST_STYLES + DEFAULT_SPEAKERS) are always
listed first, fully populated so the frontend's `needsModelSetup()` never shows
the amber "setup required" banner. Users add their own on top (create / update /
delete / duplicate, stored per user by `notebooks/podcast_profiles.py`); a custom
speaker profile picks a Kokoro voice per speaker, and generation uses it. Built-ins
are read-only (403 on edit).

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
from notebooks.manager import NotebookManager, NotebookNotFoundError
from notebooks import podcast_audio, podcast_profiles
from notebooks.podcast_profiles import DEFAULT_SPEAKER_PROFILE_ID, ProfileError

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")

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
_DEFAULT_SPEAKER_PROFILE_ID = DEFAULT_SPEAKER_PROFILE_ID

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
            "builtin": True,
            "name": "Host & Guest (default)",
            "description": "Built-in two-voice conversational duo synthesized by the GPU TTS service.",
            "voice_model": DEFAULT_VOICE_MODEL,
            "speakers": speakers,
            "tts_provider": DEFAULT_VOICE_MODEL,
            "tts_model": DEFAULT_VOICE_MODEL,
        }
    ]


async def _build_episode_profiles() -> List[Dict[str, Any]]:
    """Built-in episode profiles, one per PODCAST_STYLES entry from script.py,
    mapped to the EpisodeProfile shape (src/lib/types/podcasts.ts)."""
    from .router import _default_chat_model
    chat_model = await _default_chat_model()
    try:
        from open_notebook.podcast.script import get_podcast_styles
        styles = get_podcast_styles()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not load podcast styles, using fallback: %s", e)
        styles = {
            "conversational": "A casual, friendly discussion between two people.",
        }

    # Brief and Critique come from the notebooks script writer, not open_notebook's table.
    from notebooks.podcast_script import PRESET_STYLES
    styles = {**styles, **{p["id"]: p["description"] for p in PRESET_STYLES}}

    profiles = []
    for style_key, description in styles.items():
        profiles.append(
            {
                "id": style_key,  # the style key doubles as the profile id
                "builtin": True,
                "style": style_key,
                "name": style_key.replace("_", " ").title(),
                "description": description,
                "speaker_config": _DEFAULT_SPEAKER_PROFILE_ID,
                # Non-null model refs so needsModelSetup() => false.
                "outline_llm": chat_model,
                "transcript_llm": chat_model,
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
    model: Optional[str] = None,
    cast: Optional[List[Dict[str, Any]]] = None,
):
    """Background task: write the script (notebooks/podcast_script.py), speak it
    (notebooks/podcast_audio.py) and write the result onto the existing
    standalone_podcasts row. Audio failure leaves a readable script with the
    reason in error_message; an unreadable script is an error. `cast` is the chosen
    speaker profile's speakers ([{name, voice_id}]); None means the default duo."""
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

        # 1. Write the script in parts sized to the requested length, with the
        #    asked-for speakers only. A script that cannot be read is an error,
        #    never a finished podcast. See notebooks/podcast_script.py.
        from notebooks.podcast_script import PodcastScriptError, generate_script, ollama_caller, speaker_names
        from notebooks.router import _default_ollama_model

        ollama_url = os.environ.get("OLLAMA_URL", "http://ollama:11434")
        chosen = model or os.environ.get("NOTEBOOK_PODCAST_MODEL") or await _default_ollama_model(ollama_url)
        try:
            script = await generate_script(
                content,
                title=title,
                style=style,
                minutes=duration_minutes,
                names=speaker_names(cast, speakers),
                call=ollama_caller(chosen, ollama_url),
            )
        except PodcastScriptError as exc:
            script = None
            error_message = str(exc)
            final_status = "error"

        if script:
            transcript = script["transcript"]
            outline = script["outline"]
            # 2. Speak it. Failure keeps the script and says why.
            try:
                made = await podcast_audio.make_audio(
                    [{"speaker": t["speaker"], "text": t["dialogue"]} for t in transcript],
                    voices=podcast_audio.chosen_voices(cast),
                )
                audio_path, audio_url, duration_seconds = made["audio_path"], made["audio_url"], made["duration_seconds"]
            except podcast_audio.PodcastAudioError as exc:
                final_status = "script_only"
                error_message = f"The script is saved but the audio could not be made. {exc}"

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


async def _resolve_notebook_content(
    manager: NotebookManager,
    notebook_id: Optional[str],
    direct_content: Optional[str],
    user_id: int,
    source_ids: Optional[List[UUID]] = None,
) -> str:
    """Fetch source/note text for a notebook when the request gives no direct
    content. Mirrors the native _fetch_podcast_content fall-back. Only the
    owning `user_id`'s notebook yields text, so a stored or posted notebook id
    that belongs to someone else resolves to nothing.

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
                    SELECT s.title, s.content_text FROM notebook_sources s
                    JOIN notebooks n ON n.id = s.notebook_id AND n.user_id = $3
                    WHERE s.notebook_id = $1 AND s.id = ANY($2::uuid[])
                      AND s.content_text IS NOT NULL
                    ORDER BY s.created_at ASC LIMIT 12
                    """,
                    nb_uuid, source_ids, user_id,
                )
            else:
                src_rows = await conn.fetch(
                    """
                    SELECT s.title, s.content_text FROM notebook_sources s
                    JOIN notebooks n ON n.id = s.notebook_id AND n.user_id = $2
                    WHERE s.notebook_id = $1 AND s.content_text IS NOT NULL
                    ORDER BY s.created_at ASC LIMIT 5
                    """,
                    nb_uuid, user_id,
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
                    WHERE notebook_id = $1 AND user_id = $2 AND content IS NOT NULL
                    ORDER BY created_at ASC LIMIT 5
                    """,
                    nb_uuid, user_id,
                )
                for r in note_rows:
                    if r["content"]:
                        parts.append(
                            f"\n\n=== NOTE: {r['title'] or 'Untitled'} ===\n{r['content']}"
                        )
    except Exception as e:
        logger.warning("Failed to resolve notebook content for %s: %s", notebook_id, e)

    return "".join(parts)


# ─── Profile endpoints (built-ins first, then the caller's own) ────────────────

def _pool(manager: NotebookManager):
    return manager.db_pool


def _fail(exc: ProfileError):
    raise HTTPException(status_code=exc.status, detail=exc.detail)


async def _own_or_builtin(manager, user_id: int, kind: str, profile_id: str) -> Dict[str, Any]:
    """A profile the caller may read: a built-in, or one they own. Anyone else's is a 404."""
    builtins = _build_speaker_profiles() if kind == "speaker" else await _build_episode_profiles()
    found = next((p for p in builtins if p["id"] == profile_id), None)
    if found is None:
        found = await podcast_profiles.get_profile(_pool(manager), user_id, kind, profile_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return found


async def _refuse_builtin(kind: str, profile_id: str):
    if podcast_profiles.as_uuid(profile_id) is not None:
        return
    builtins = _build_speaker_profiles() if kind == "speaker" else await _build_episode_profiles()
    if any(p["id"] == profile_id for p in builtins):
        raise HTTPException(status_code=403, detail="Built-in profiles are read-only. Duplicate one to change it.")
    raise HTTPException(status_code=404, detail="Profile not found")


async def _clean(manager, user_id: int, kind: str, body: Any) -> Dict[str, Any]:
    try:
        if kind == "speaker":
            return podcast_profiles.clean_speaker(body)
        clean = podcast_profiles.clean_episode(body)
        # An episode profile may only point at a built-in cast or one the caller owns.
        await podcast_profiles.resolve_cast(_pool(manager), user_id, clean["speaker_config"])
        return clean
    except ProfileError as exc:
        _fail(exc)


async def _with_models(profile: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """Custom episode profiles carry the same non-null model refs the built-ins do."""
    if kind != "episode" or profile.get("outline_llm"):
        return profile
    from .router import _default_chat_model
    chat_model = await _default_chat_model()
    return {**profile, "outline_llm": chat_model, "transcript_llm": chat_model}


@router.get("/episode-profiles")
async def list_episode_profiles(
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    own = await podcast_profiles.list_profiles(_pool(manager), int(current_user["id"]), "episode")
    return await _build_episode_profiles() + [await _with_models(p, "episode") for p in own]


@router.get("/speaker-profiles")
async def list_speaker_profiles(
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    own = await podcast_profiles.list_profiles(_pool(manager), int(current_user["id"]), "speaker")
    return _build_speaker_profiles() + own


@router.get("/languages")
async def list_languages(
    current_user: Dict = Depends(get_current_user_from_request),
):
    return _LANGUAGES


@router.get("/podcasts/voices")
async def list_voices(
    current_user: Dict = Depends(get_current_user_from_request),
):
    """The Kokoro voices a speaker can be given (the speech service's own list)."""
    return {"voices": podcast_audio.voice_catalog(), "model": "kokoro"}


async def _create(kind: str, request: Request, user, manager):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected a JSON body.")
    clean = await _clean(manager, int(user["id"]), kind, body)
    try:
        made = await podcast_profiles.create_profile(_pool(manager), int(user["id"]), kind, clean)
    except ProfileError as exc:
        _fail(exc)
    return await _with_models(made, kind)


async def _update(kind: str, profile_id: str, request: Request, user, manager):
    await _refuse_builtin(kind, profile_id)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected a JSON body.")
    clean = await _clean(manager, int(user["id"]), kind, body)
    made = await podcast_profiles.update_profile(_pool(manager), int(user["id"]), kind, profile_id, clean)
    if made is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return await _with_models(made, kind)


async def _delete(kind: str, profile_id: str, user, manager):
    await _refuse_builtin(kind, profile_id)
    if not await podcast_profiles.delete_profile(_pool(manager), int(user["id"]), kind, profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"success": True, "message": "Profile deleted"}


async def _duplicate(kind: str, profile_id: str, user, manager):
    source = await _own_or_builtin(manager, int(user["id"]), kind, profile_id)
    body = {**source, "name": f"{source['name']} (copy)"[:80]}
    if kind == "speaker":
        # Built-in voice ids are "automatic"; keep whatever the source holds.
        body["speakers"] = [dict(s) for s in source.get("speakers", [])]
    clean = await _clean(manager, int(user["id"]), kind, body)
    try:
        made = await podcast_profiles.create_profile(_pool(manager), int(user["id"]), kind, clean)
    except ProfileError as exc:
        _fail(exc)
    return await _with_models(made, kind)


@router.post("/episode-profiles")
async def create_episode_profile(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _create("episode", request, current_user, manager)


@router.put("/episode-profiles/{profile_id}")
async def update_episode_profile(
    profile_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _update("episode", profile_id, request, current_user, manager)


@router.delete("/episode-profiles/{profile_id}")
async def delete_episode_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _delete("episode", profile_id, current_user, manager)


@router.post("/episode-profiles/{profile_id}/duplicate")
async def duplicate_episode_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _duplicate("episode", profile_id, current_user, manager)


@router.post("/speaker-profiles")
async def create_speaker_profile(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _create("speaker", request, current_user, manager)


@router.put("/speaker-profiles/{profile_id}")
async def update_speaker_profile(
    profile_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _update("speaker", profile_id, request, current_user, manager)


@router.delete("/speaker-profiles/{profile_id}")
async def delete_speaker_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _delete("speaker", profile_id, current_user, manager)


@router.post("/speaker-profiles/{profile_id}/duplicate")
async def duplicate_speaker_profile(
    profile_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    return await _duplicate("speaker", profile_id, current_user, manager)


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
    # The admin's limits (Settings ▸ People): refused, or counted, on their own model.
    from plugins.people.controls import require_turn
    model = await require_turn(getattr(request.app.state, "pg_pool", None), int(current_user["id"]), "") or None

    episode_profile = body.get("episode_profile") or "conversational"
    speaker_profile = body.get("speaker_profile")
    episode_name = body.get("episode_name") or "Untitled Episode"
    notebook_id = body.get("notebook_id")
    direct_content = body.get("content")
    briefing_suffix = body.get("briefing_suffix")

    # A built-in episode profile id is its style key (see _build_episode_profiles); a
    # custom one is a uuid that must be the caller's own, and carries its own style,
    # cast and standing briefing. With no profile at all the defaults apply and the
    # profile table is never touched.
    pool = manager.db_pool
    user_id = current_user["id"]
    custom_episode = None
    if podcast_profiles.as_uuid(episode_profile) is not None:
        custom_episode = await podcast_profiles.get_profile(pool, user_id, "episode", episode_profile)
        if custom_episode is None:
            raise HTTPException(status_code=404, detail="Episode profile not found")
        style = custom_episode["style"]
    else:
        style = episode_profile if episode_profile in {
            p["id"] for p in await _build_episode_profiles()
        } else "conversational"

    # An explicitly requested speaker profile must exist for this user; one inherited
    # from the episode profile quietly falls back to the default duo if it was deleted.
    try:
        if speaker_profile:
            cast = await podcast_profiles.resolve_cast(pool, user_id, speaker_profile)
        else:
            cast = await podcast_profiles.resolve_cast(
                pool, user_id, (custom_episode or {}).get("speaker_config"), strict=False
            )
    except ProfileError as exc:
        _fail(exc)

    if notebook_id:
        # Accept bare uuid or "notebook:<uuid>"; 404 unless it is the caller's.
        raw = notebook_id.split(":", 1)[1] if ":" in notebook_id else notebook_id
        try:
            nb_uuid = UUID(raw)
        except (ValueError, AttributeError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid notebook id")
        try:
            await manager.get_notebook(nb_uuid, current_user["id"])
        except NotebookNotFoundError:
            raise HTTPException(status_code=404, detail="Notebook not found")

    content = await _resolve_notebook_content(manager, notebook_id, direct_content, current_user["id"])
    if not briefing_suffix and custom_episode and content.strip():
        briefing_suffix = custom_episode.get("default_briefing") or None
    if briefing_suffix:
        content = f"{content}\n\n{briefing_suffix}" if content else briefing_suffix

    if not content.strip():
        raise HTTPException(
            status_code=400,
            detail="No content available. Provide content, briefing_suffix, or a notebook_id with sources/notes.",
        )

    # standalone_podcasts.notebook_id is TEXT NOT NULL.
    nb_id_text = notebook_id or "notebook:standalone"

    speakers = len(cast) if cast else 2

    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO standalone_podcasts
                (notebook_id, user_id, title, status, style, speakers, duration_minutes, speaker_profiles)
            VALUES ($1, $2, $3, 'pending', $4, $5, 10, $6::jsonb)
            RETURNING id
            """,
            nb_id_text, user_id, episode_name, style, speakers, json.dumps(cast or []),
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
        speakers,  # 2 for the built-in Host + Guest duo
        10,  # duration_minutes
        model,
        cast,
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

    episode_profiles = await _build_episode_profiles()
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
    request: Request,
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
    from plugins.people.controls import require_turn
    model = await require_turn(getattr(request.app.state, "pg_pool", None), int(user_id), "") or None
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, notebook_id, title, style, speakers, duration_minutes, speaker_profiles
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

    content = await _resolve_notebook_content(manager, row["notebook_id"], None, user_id)
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
        model,
        # The cast the episode was made with (empty for the default duo).
        [m for m in _json_list(row.get("speaker_profiles")) if isinstance(m, dict) and m.get("name")] or None,
    )

    return {
        "job_id": str(ep_uuid),
        "message": f"Retrying generation for '{row['title']}'",
    }


# ─── Audio proxy ───────────────────────────────────────────────────────────────

@router.get("/podcasts/tts-audio/{filename}")
async def proxy_tts_audio(
    filename: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Proxy audio bytes from the tts-service container. Mirrors the native
    notebooks router's /podcasts/tts-audio/{filename} proxy."""
    safe_filename = os.path.basename(filename)
    from notebooks import podcast_audio

    if not await podcast_audio.user_owns_audio(manager.db_pool, int(current_user["id"]), safe_filename):
        raise HTTPException(status_code=404, detail="Audio file not found")

    local = podcast_audio.local_file(safe_filename)
    if local is not None:
        return Response(
            content=local.read_bytes(),
            media_type="audio/wav",
            headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
        )
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