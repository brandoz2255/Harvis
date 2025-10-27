"""
Core API Service - Authentication Gateway and Service Router
Routes authenticated requests to appropriate microservices
"""
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn, os, logging, httpx
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import asyncpg
from typing import Optional
from pydantic import BaseModel

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Authentication Setup
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql:5432/database")

# Microservice URLs (Docker network)
RESEARCH_SERVICE_URL = os.getenv("RESEARCH_SERVICE_URL", "http://research-service:8001")
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://voice-service:8002")
BROWSER_SERVICE_URL = os.getenv("BROWSER_SERVICE_URL", "http://browser-service:8003")
MCP_SERVICE_URL = os.getenv("MCP_SERVICE_URL", "http://mcp-service:8004")
N8N_SERVICE_URL = os.getenv("N8N_SERVICE_URL", "http://n8n-integration:8005")
VIBE_SERVICE_URL = os.getenv("VIBE_SERVICE_URL", "http://vibe-coding:8006")

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Core API JWT_SECRET loaded: {SECRET_KEY[:10]}... Length: {len(SECRET_KEY)}")

# Pydantic Models
class AuthRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    avatar: Optional[str] = None

# Authentication Utilities
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    logger.info(f"get_current_user called with credentials: {credentials}")
    token = request.cookies.get("access_token")
    if token is None and credentials is not None:
        token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        logger.error("No credentials provided")
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = int(payload.get("sub"))
        logger.info(f"User ID from token: {user_id}")
    except (JWTError, ValueError) as e:
        logger.error(f"JWT decode error: {e}")
        raise credentials_exception

    # Get user from database
    pool = getattr(request.app.state, 'pg_pool', None)
    if pool:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT id, username, email, avatar FROM users WHERE id = $1", user_id)
            if user is None:
                logger.error(f"User not found for ID: {user_id}")
                raise credentials_exception
            return UserResponse(**dict(user))
    else:
        conn = await asyncpg.connect(DATABASE_URL, timeout=10)
        try:
            user = await conn.fetchrow("SELECT id, username, email, avatar FROM users WHERE id = $1", user_id)
            if user is None:
                raise credentials_exception
            return UserResponse(**dict(user))
        finally:
            await conn.close()

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Core API Service starting...")
    try:
        app.state.pg_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60,
            timeout=30
        )
        logger.info("✅ Database connection pool created")
    except Exception as e:
        logger.error(f"❌ Failed to create database pool: {e}")

    yield

    # Shutdown
    logger.info("🛑 Core API Service shutting down...")
    if hasattr(app.state, 'pg_pool'):
        await app.state.pg_pool.close()
        logger.info("✅ Database connection pool closed")

# FastAPI App
app = FastAPI(
    title="Harvis Core API Service",
    description="Authentication Gateway and Service Router",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:9000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health Check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "core-api"}

# Authentication Endpoints
@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: Request, auth_request: AuthRequest):
    logger.info(f"Login attempt for email: {auth_request.email}")

    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, email, password FROM users WHERE email = $1",
            auth_request.email
        )

        if not user or not verify_password(auth_request.password, user['password']):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user['id'])},
            expires_delta=access_token_expires
        )

        logger.info(f"✅ Login successful for user: {user['username']}")
        return TokenResponse(access_token=access_token, token_type="bearer")

@app.post("/api/auth/signup", response_model=TokenResponse)
async def signup(request: Request, signup_request: SignupRequest):
    logger.info(f"Signup attempt for username: {signup_request.username}")

    pool = request.app.state.pg_pool
    async with pool.acquire() as conn:
        # Check if user exists
        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1 OR username = $2",
            signup_request.email, signup_request.username
        )

        if existing:
            raise HTTPException(status_code=400, detail="User already exists")

        # Create user
        hashed_password = get_password_hash(signup_request.password)
        user = await conn.fetchrow(
            "INSERT INTO users (username, email, password) VALUES ($1, $2, $3) RETURNING id",
            signup_request.username, signup_request.email, hashed_password
        )

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user['id'])},
            expires_delta=access_token_expires
        )

        logger.info(f"✅ Signup successful for user: {signup_request.username}")
        return TokenResponse(access_token=access_token, token_type="bearer")

@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user

# Service Proxy Helper
async def proxy_to_service(
    service_url: str,
    path: str,
    method: str,
    request: Request,
    user: Optional[UserResponse] = None
):
    """Proxy request to microservice with authentication context"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Build full URL
        url = f"{service_url}{path}"

        # Get request body
        body = None
        if method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
            except:
                body = None

        # Build headers
        headers = dict(request.headers)
        if user:
            headers["X-User-Id"] = str(user.id)
            headers["X-User-Email"] = user.email
            headers["X-User-Name"] = user.username

        # Remove host header to avoid conflicts
        headers.pop("host", None)

        # Make request
        logger.info(f"Proxying {method} {url}")
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
            params=dict(request.query_params)
        )

        return JSONResponse(
            content=response.json() if response.headers.get("content-type", "").startswith("application/json") else {"data": response.text},
            status_code=response.status_code
        )

# Research Service Routes
@app.api_route("/api/web-search", methods=["POST"])
@app.api_route("/api/research-chat", methods=["POST"])
@app.api_route("/api/fact-check", methods=["POST"])
@app.api_route("/api/comparative-research", methods=["POST"])
async def research_routes(request: Request, user: UserResponse = Depends(get_current_user)):
    return await proxy_to_service(RESEARCH_SERVICE_URL, request.url.path, request.method, request, user)

# Voice Service Routes
@app.api_route("/api/mic-chat", methods=["POST"])
@app.api_route("/api/tts", methods=["POST"])
@app.api_route("/api/stt", methods=["POST"])
async def voice_routes(request: Request, user: UserResponse = Depends(get_current_user)):
    return await proxy_to_service(VOICE_SERVICE_URL, request.url.path, request.method, request, user)

# Browser Service Routes
@app.api_route("/api/browser/{path:path}", methods=["GET", "POST"])
@app.api_route("/api/screen-analyze", methods=["POST"])
async def browser_routes(request: Request, user: UserResponse = Depends(get_current_user)):
    return await proxy_to_service(BROWSER_SERVICE_URL, request.url.path, request.method, request, user)

# MCP Service Routes
@app.api_route("/api/mcp/{path:path}", methods=["GET", "POST"])
async def mcp_routes(request: Request, user: UserResponse = Depends(get_current_user)):
    return await proxy_to_service(MCP_SERVICE_URL, request.url.path, request.method, request, user)

# N8N Integration Routes
@app.api_route("/api/n8n/{path:path}", methods=["GET", "POST"])
async def n8n_routes(request: Request, user: UserResponse = Depends(get_current_user)):
    return await proxy_to_service(N8N_SERVICE_URL, request.url.path, request.method, request, user)

# Vibe Coding Routes
@app.api_route("/api/vibe/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def vibe_routes(request: Request, user: UserResponse = Depends(get_current_user)):
    return await proxy_to_service(VIBE_SERVICE_URL, request.url.path, request.method, request, user)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
