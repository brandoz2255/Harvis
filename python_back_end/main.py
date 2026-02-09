
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import logging
import os
import asyncpg
from jose import JWTError, jwt
from passlib.context import CryptContext

# Import existing managers (mocked or real)
# Assuming model_manager exists
try:
    from model_manager import generate_speech_smart
except ImportError:
    # If not yet updated in model_manager, definining a stub or mocking logic
    pass

from tts_engine_manager import (
    TTSMode, set_mode, get_mode, generate_speech as tts_generate,
    generate_podcast_segment, get_engine_status, unload_all_engines
)
from voice_model_manager import (
    VoiceModelManager, download_popular_model, POPULAR_MODELS
)

app = FastAPI()

# ─── Logging Configuration ────────────────────────────────────────────────────
# Set root logger to DEBUG so all module loggers output full detail
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Reduce noise from chatty third-party libraries
for _noisy in ("httpcore", "httpx", "urllib3", "asyncio", "multipart", "watchfiles"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("uvicorn")

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:9000", "http://127.0.0.1:9000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth Config ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql:5432/database")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─── DB Pool Lifecycle ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    try:
        app.state.pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10, timeout=10)
        logger.info("Database connection pool created")
    except Exception as e:
        logger.error(f"Failed to create database pool: {e}")
        app.state.pg_pool = None

@app.on_event("shutdown")
async def shutdown():
    pool = getattr(app.state, 'pg_pool', None)
    if pool:
        await pool.close()
        logger.info("Database connection pool closed")

# ─── Auth Models ──────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

# ─── Auth Endpoints ───────────────────────────────────────────────────────────
@app.post("/api/auth/login", tags=["auth"])
async def login(req: LoginRequest):
    pool = getattr(app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, email, password, avatar FROM users WHERE email = $1",
            req.email
        )

    if not user or not pwd_context.verify(req.password, user["password"]):
        raise HTTPException(401, "Invalid email or password")

    token = create_access_token(user["id"])
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/auth/signup", tags=["auth"])
async def signup(req: SignupRequest):
    pool = getattr(app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    hashed = pwd_context.hash(req.password)
    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "INSERT INTO users (username, email, password) VALUES ($1, $2, $3) RETURNING id",
                req.username, req.email, hashed
            )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "User with this email or username already exists")

    token = create_access_token(user["id"])
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/auth/me", tags=["auth"])
async def get_me(request: Request):
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "Not authenticated")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid token")

    pool = getattr(app.state, 'pg_pool', None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, email, avatar FROM users WHERE id = $1", user_id
        )
    if not user:
        raise HTTPException(401, "User not found")

    return dict(user)

# Also support /api/me (nginx routes this path too)
@app.get("/api/me", tags=["auth"])
async def get_me_alias(request: Request):
    return await get_me(request)

# ─── Include Routers ──────────────────────────────────────────────────────────
try:
    from notebooks.router import router as notebooks_router
    app.include_router(notebooks_router)
    logger.info("Notebooks router loaded")
except Exception as e:
    logger.warning(f"Could not load notebooks router: {e}")

try:
    from api.tts_routes import router as tts_proxy_router
    app.include_router(tts_proxy_router)
    logger.info("TTS proxy router loaded")
except Exception as e:
    logger.warning(f"Could not load TTS proxy router: {e}")

try:
    from api.local_podcast_routes import router as local_podcast_router
    app.include_router(local_podcast_router)
    logger.info("Local podcast router loaded")
except Exception as e:
    logger.error(f"Could not load local podcast router: {e}")

try:
    from vibecoding.models import router as vibe_models_router
    app.include_router(vibe_models_router)
    logger.info("Vibe models router loaded")
except Exception as e:
    logger.warning(f"Could not load vibe models router: {e}")

voice_manager = VoiceModelManager()

class PodcastSegmentRequest(BaseModel):
    text: str
    character_voice: str
    
class VoiceModelDownloadRequest(BaseModel):
    url: str
    name: Optional[str] = None
    tags: Optional[List[str]] = None

class TTSModeRequest(BaseModel):
    mode: str  # "interactive", "podcast", "lightweight"

@app.post("/api/tts/set-mode", tags=["tts-engine"])
async def api_set_tts_mode(req: TTSModeRequest):
    """Set the TTS generation mode"""
    mode_map = {
        "interactive": TTSMode.INTERACTIVE,
        "podcast": TTSMode.PODCAST,
        "lightweight": TTSMode.LIGHTWEIGHT
    }
    
    if req.mode not in mode_map:
        raise HTTPException(400, f"Invalid mode. Use: {list(mode_map.keys())}")
    
    set_mode(mode_map[req.mode])
    return {"status": "ok", "mode": req.mode}

@app.get("/api/tts/status", tags=["tts-engine"])
async def api_get_tts_status():
    """Get status of all TTS engines"""
    return get_engine_status()

@app.post("/api/podcast/generate-segment", tags=["podcast"])
async def api_generate_podcast_segment(req: PodcastSegmentRequest):
    """Generate a podcast segment with character voice"""
    try:
        sr, audio = generate_podcast_segment(
            req.text,
            req.character_voice,
            voice_models_dir=str(voice_manager.models_dir)
        )
        
        # Save to temp file
        import soundfile as sf
        import uuid
        
        output_path = f"/tmp/podcast_segment_{uuid.uuid4()}.wav"
        sf.write(output_path, audio, sr)
        
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename=f"segment_{req.character_voice}.wav"
        )
        
    except FileNotFoundError as e:
        raise HTTPException(404, f"Voice model not found: {req.character_voice}")
    except Exception as e:
        logger.error(f"Podcast generation failed: {e}")
        raise HTTPException(500, str(e))

@app.get("/api/voice-models/list", tags=["voice-models"])
async def api_list_voice_models(tag: Optional[str] = None):
    """List available voice models"""
    models = voice_manager.list_models(tag=tag)
    return {
        "count": len(models),
        "models": [
            {
                "name": m.name,
                "epochs": m.epochs,
                "size_mb": m.file_size_mb,
                "tags": m.tags,
                "has_index": m.index_path is not None
            }
            for m in models
        ]
    }

@app.get("/api/voice-models/popular", tags=["voice-models"])
async def api_list_popular_models():
    """List pre-configured popular voice models"""
    return {
        "models": list(POPULAR_MODELS.keys()),
        "note": "Use POST /api/voice-models/download-popular/{name} to download"
    }

@app.post("/api/voice-models/download", tags=["voice-models"])
async def api_download_voice_model(req: VoiceModelDownloadRequest):
    """Download a voice model from HuggingFace URL"""
    info = voice_manager.download_model(
        req.url,
        name=req.name,
        tags=req.tags
    )
    
    if info is None:
        raise HTTPException(500, "Download failed")
    
    return {
        "status": "ok",
        "name": info.name,
        "size_mb": info.file_size_mb,
        "epochs": info.epochs
    }

@app.post("/api/voice-models/download-popular/{name}", tags=["voice-models"])
async def api_download_popular_model(name: str):
    """Download a pre-configured popular voice model"""
    if name not in POPULAR_MODELS:
        raise HTTPException(404, f"Unknown model. Available: {list(POPULAR_MODELS.keys())}")
    
    info = download_popular_model(name, voice_manager)
    
    if info is None:
        raise HTTPException(500, "Download failed")
    
    return {
        "status": "ok",
        "name": info.name,
        "size_mb": info.file_size_mb
    }

@app.delete("/api/voice-models/{name}", tags=["voice-models"])
async def api_delete_voice_model(name: str):
    """Delete a voice model"""
    if voice_manager.delete_model(name):
        return {"status": "ok", "deleted": name}
    raise HTTPException(404, f"Model not found: {name}")

