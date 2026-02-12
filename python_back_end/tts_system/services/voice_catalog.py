"""
Voice Catalog Service - Proxy for voice-models.com
Provides search, browse, and download capabilities for RVC voice models
"""

import os
import re
import json
import logging
import asyncio
import tempfile
import zipfile
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import hashlib

import httpx

logger = logging.getLogger(__name__)

# Configuration
VOICE_MODELS_BASE_URL = os.getenv("VOICE_MODELS_BASE_URL", "https://voice-models.com")
CATALOG_CACHE_HOURS = int(os.getenv("CATALOG_CACHE_HOURS", "24"))
RVC_MODELS_DIR = Path(os.getenv("RVC_MODELS_DIR", "/app/rvc_models"))
DOWNLOAD_TIMEOUT = int(os.getenv("VOICE_DOWNLOAD_TIMEOUT", "300"))  # 5 minutes
VOICE_MODELS_FETCH_URL = os.getenv(
    "VOICE_MODELS_FETCH_URL",
    f"{VOICE_MODELS_BASE_URL.rstrip('/')}/fetch_data.php",
)
VOICE_MODELS_USER_AGENT = os.getenv(
    "VOICE_MODELS_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) HARVIS/1.0",
)


@dataclass
class VoiceModel:
    """Represents a voice model from the catalog"""
    id: str
    name: str
    slug: str
    category: str
    description: Optional[str] = None
    download_url: Optional[str] = None
    preview_url: Optional[str] = None
    file_size: Optional[int] = None
    downloads: int = 0
    rating: float = 0.0
    tags: List[str] = None
    created_at: Optional[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VoiceCatalogService:
    """
    Service for browsing and importing voice models from voice-models.com
    
    Features:
    - Search and browse voice models
    - Cache catalog data to reduce API calls
    - Download and extract model files
    - Per-user model storage
    """
    
    def __init__(self):
        self._catalog_cache: Dict[str, List[VoiceModel]] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._categories_cache: List[str] = []
        self._popular_cache: List[VoiceModel] = []
        self._lock = asyncio.Lock()
        
        # Ensure directories exist
        RVC_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        (RVC_MODELS_DIR / "shared").mkdir(exist_ok=True)
        (RVC_MODELS_DIR / "users").mkdir(exist_ok=True)
    
    def _is_cache_valid(self) -> bool:
        """Check if catalog cache is still valid"""
        if self._cache_timestamp is None:
            return False
        return datetime.utcnow() - self._cache_timestamp < timedelta(hours=CATALOG_CACHE_HOURS)

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags and collapse whitespace."""
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _infer_category(self, name: str) -> str:
        """Best-effort category inference from model name."""
        n = (name or "").lower()
        if "female" in n or "girl" in n or "woman" in n:
            return "female"
        if "male" in n or "man" in n or "boy" in n:
            return "male"
        if "anime" in n or "miku" in n or "teto" in n:
            return "anime"
        return "custom"

    def _parse_pagination_max_page(self, pagination_html: str, current_page: int) -> int:
        """Extract the max page number from pagination HTML (fetchData(N, ...))."""
        if not pagination_html:
            return current_page
        pages = [int(x) for x in re.findall(r"fetchData\((\d+)\s*,", pagination_html)]
        return max(pages) if pages else current_page

    def _parse_table_rows(self, table_html: str) -> List[VoiceModel]:
        """
        Parse the HTML table rows returned by voice-models.com/fetch_data.php.
        Each row contains:
        - model link: <a href='/model/<id>' ...>NAME</a>
        - downloadable URL: data-clipboard-text='https://huggingface.co/...zip?download=true'
        - optional size badge after the link: <span class='badge ...'>196.8</span>
        """
        models: List[VoiceModel] = []
        if not table_html:
            return models

        rows = re.findall(r"<tr>(.*?)</tr>", table_html, flags=re.S)
        for row in rows:
            try:
                m_link = re.search(r"href='(/model/([^']+))'[^>]*>(.*?)</a>", row, flags=re.S)
                if not m_link:
                    continue
                model_href = m_link.group(1)  # /model/<id>
                model_id = m_link.group(2)
                raw_name = m_link.group(3)
                name = self._strip_html(raw_name)
                slug = self._slugify(name or model_id)

                m_dl = re.search(r"data-clipboard-text='([^']*huggingface\.co[^']+)'", row)
                download_url = m_dl.group(1).strip() if m_dl else None

                # Optional file size badge (often MB as a number)
                file_size = None
                m_size = re.search(r"badge[^>]*>\s*([0-9]+(?:\.[0-9]+)?)\s*<", row)
                if m_size:
                    try:
                        mb = float(m_size.group(1))
                        file_size = int(mb * 1024 * 1024)
                    except Exception:
                        file_size = None

                category = self._infer_category(name)

                models.append(
                    VoiceModel(
                        id=model_id,
                        name=name or model_id,
                        slug=slug,
                        category=category,
                        description=None,
                        download_url=download_url,
                        preview_url=None,
                        file_size=file_size,
                        downloads=0,
                        rating=0.0,
                        tags=[],
                        created_at=None,
                    )
                )
            except Exception as e:
                logger.debug(f"Failed to parse row: {e}")
                continue

        return models
    
    async def _fetch_catalog_page(self, page: int = 1, query: str = "", category: str = "") -> Tuple[List[VoiceModel], int]:
        """
        Fetch a page of voice models from voice-models.com.

        voice-models.com/top uses an internal POST endpoint `fetch_data.php` that returns:
        - JSON: { table: "<tr>...</tr>...", pagination: "<ul>...</ul>" }
        This method calls that endpoint directly so we can paginate/search like the site.
        """
        try:
            headers = {
                "User-Agent": VOICE_MODELS_USER_AGENT,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/plain, */*",
            }
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
                resp = await client.post(
                    VOICE_MODELS_FETCH_URL,
                    data={"page": page, "search": query or ""},
                )
                resp.raise_for_status()
                data = resp.json()
                table_html = data.get("table", "")
                pagination_html = data.get("pagination", "")

                models = self._parse_table_rows(table_html)

                # Category filtering isn't supported upstream; apply best-effort filter here.
                if category:
                    cat = category.lower().strip()
                    models = [m for m in models if (m.category or "").lower() == cat]

                max_page = self._parse_pagination_max_page(pagination_html, page)
                # We don't know the exact total; approximate so the UI can show has_more reliably.
                approx_total = max_page * max(len(models), 1)
                return models, approx_total
        except Exception as e:
            logger.error(f"Failed to fetch voice-models.com catalog page: {e}")
            # Fallback to small static list if remote fetch fails
            fallback = self._get_fallback_catalog(query, category)
            return fallback, len(fallback)
    
    def _parse_api_response(self, data: Dict[str, Any]) -> List[VoiceModel]:
        """Parse API response into VoiceModel objects"""
        models = []
        items = data.get("models", data.get("data", data.get("results", [])))
        
        for item in items:
            try:
                model = VoiceModel(
                    id=str(item.get("id", item.get("_id", ""))),
                    name=item.get("name", item.get("title", "Unknown")),
                    slug=self._slugify(item.get("name", item.get("title", "unknown"))),
                    category=item.get("category", item.get("type", "custom")),
                    description=item.get("description", ""),
                    download_url=item.get("download_url", item.get("file_url", "")),
                    preview_url=item.get("preview_url", item.get("sample_url", "")),
                    file_size=item.get("file_size", item.get("size", 0)),
                    downloads=item.get("downloads", item.get("download_count", 0)),
                    rating=float(item.get("rating", item.get("score", 0))),
                    tags=item.get("tags", []),
                    created_at=item.get("created_at", item.get("createdAt", ""))
                )
                models.append(model)
            except Exception as e:
                logger.warning(f"Failed to parse model: {e}")
                continue
        
        return models
    
    def _get_fallback_catalog(self, query: str = "", category: str = "") -> List[VoiceModel]:
        """
        Fallback catalog with popular RVC voices
        Used when API is not available
        """
        # Popular RVC voices that are commonly available
        fallback_models = [
            VoiceModel(
                id="peter_griffin",
                name="Peter Griffin",
                slug="peter_griffin",
                category="cartoon",
                description="Family Guy character voice",
                download_url="https://huggingface.co/Delik/Peter_Griffin_RVCv2/resolve/main/Peter_Griffin.zip",
                downloads=50000,
                rating=4.8,
                tags=["cartoon", "family guy", "comedy"]
            ),
            VoiceModel(
                id="walter_white",
                name="Walter White",
                slug="walter_white",
                category="tv_show",
                description="Breaking Bad character voice",
                download_url="",
                downloads=45000,
                rating=4.9,
                tags=["tv show", "breaking bad", "drama"]
            ),
            VoiceModel(
                id="donald_trump",
                name="Donald Trump",
                slug="donald_trump",
                category="celebrity",
                description="Former US President voice",
                download_url="",
                downloads=60000,
                rating=4.7,
                tags=["celebrity", "politician"]
            ),
            VoiceModel(
                id="spongebob",
                name="SpongeBob SquarePants",
                slug="spongebob",
                category="cartoon",
                description="SpongeBob character voice",
                download_url="",
                downloads=40000,
                rating=4.6,
                tags=["cartoon", "nickelodeon", "comedy"]
            ),
            VoiceModel(
                id="morgan_freeman",
                name="Morgan Freeman",
                slug="morgan_freeman",
                category="celebrity",
                description="Actor with iconic narration voice",
                download_url="",
                downloads=55000,
                rating=4.9,
                tags=["celebrity", "actor", "narrator"]
            ),
            VoiceModel(
                id="homer_simpson",
                name="Homer Simpson",
                slug="homer_simpson",
                category="cartoon",
                description="The Simpsons character voice",
                download_url="",
                downloads=35000,
                rating=4.5,
                tags=["cartoon", "simpsons", "comedy"]
            ),
            VoiceModel(
                id="barack_obama",
                name="Barack Obama",
                slug="barack_obama",
                category="celebrity",
                description="Former US President voice",
                download_url="",
                downloads=42000,
                rating=4.8,
                tags=["celebrity", "politician", "narrator"]
            ),
            VoiceModel(
                id="darth_vader",
                name="Darth Vader",
                slug="darth_vader",
                category="character",
                description="Star Wars villain voice",
                download_url="",
                downloads=38000,
                rating=4.7,
                tags=["star wars", "villain", "sci-fi"]
            ),
        ]
        
        # Filter by query
        if query:
            query_lower = query.lower()
            fallback_models = [
                m for m in fallback_models 
                if query_lower in m.name.lower() 
                or query_lower in m.description.lower()
                or any(query_lower in tag.lower() for tag in m.tags)
            ]
        
        # Filter by category
        if category:
            category_lower = category.lower()
            fallback_models = [
                m for m in fallback_models 
                if m.category.lower() == category_lower
            ]
        
        return fallback_models
    
    def _slugify(self, text: str) -> str:
        """Convert text to URL-friendly slug"""
        text = text.lower()
        text = re.sub(r'[^a-z0-9]+', '_', text)
        text = re.sub(r'^_|_$', '', text)
        return text
    
    async def search(
        self, 
        query: str = "", 
        category: str = "", 
        page: int = 1,
        per_page: int = 20
    ) -> Dict[str, Any]:
        """
        Search voice models
        
        Args:
            query: Search query string
            category: Filter by category
            page: Page number (1-indexed)
            per_page: Results per page
            
        Returns:
            Dict with models, total count, and pagination info
        """
        # voice-models.com paging is already server-side (50-ish per page).
        # We keep per_page for API compatibility but treat it as informational.
        models, total = await self._fetch_catalog_page(page, query, category)

        # Best-effort has_more: fetch next page existence by inferring total pages from total approximation.
        # If total is an approximation, has_more is still correct as long as max_page was detected.
        has_more = len(models) > 0 and (page * max(len(models), 1) < (total or 0))

        return {
            "models": [m.to_dict() for m in models],
            "total": total or len(models),
            "page": page,
            "per_page": per_page,
            "has_more": has_more,
        }
    
    async def get_popular(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get popular voice models"""
        models, _ = await self._fetch_catalog_page(1, "", "")
        # The upstream list is already \"Top\"; just return first N.
        return [m.to_dict() for m in models[:limit]]
    
    async def get_categories(self) -> List[str]:
        """Get available categories"""
        return [
            "cartoon",
            "tv_show", 
            "celebrity",
            "character",
            "gaming",
            "anime",
            "custom"
        ]
    
    async def download_and_import(
        self,
        url: str,
        name: str,
        slug: str,
        category: str,
        user_id: str,
        description: str = "",
        pitch_shift: int = 0,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Download voice model from URL and import to user's library
        
        Args:
            url: Download URL for the voice model (zip file)
            name: Display name for the voice
            slug: URL-friendly identifier
            category: Voice category
            user_id: User ID for per-user storage
            description: Optional description
            pitch_shift: Default pitch shift
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict with success status and imported voice info
        """
        if not url:
            return {"success": False, "error": "No download URL provided"}
        
        # Sanitize slug
        slug = self._slugify(slug)
        
        # Determine storage path
        user_dir = RVC_MODELS_DIR / "users" / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        voice_dir = user_dir / slug
        
        if voice_dir.exists():
            return {"success": False, "error": f"Voice '{slug}' already exists"}
        
        temp_dir = None
        try:
            # Create temp directory for download
            temp_dir = Path(tempfile.mkdtemp(prefix="rvc_download_"))
            zip_path = temp_dir / "model.zip"
            
            # Download file
            if progress_callback:
                progress_callback({"stage": "downloading", "progress": 0})
            
            async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        return {"success": False, "error": f"Download failed: HTTP {response.status_code}"}
                    
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    
                    with open(zip_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if progress_callback and total_size:
                                progress = int((downloaded / total_size) * 50)  # 0-50%
                                progress_callback({"stage": "downloading", "progress": progress})
            
            if progress_callback:
                progress_callback({"stage": "extracting", "progress": 50})
            
            # Extract zip file
            voice_dir.mkdir(parents=True, exist_ok=True)
            
            pth_file = None
            index_file = None
            
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    for member in zf.namelist():
                        # Skip directories and hidden files
                        if member.endswith('/') or member.startswith('__MACOSX'):
                            continue
                        
                        filename = Path(member).name
                        
                        if filename.endswith('.pth'):
                            # Extract .pth file
                            zf.extract(member, temp_dir)
                            extracted = temp_dir / member
                            pth_file = voice_dir / f"{slug}.pth"
                            shutil.move(str(extracted), str(pth_file))
                            
                        elif filename.endswith('.index'):
                            # Extract .index file
                            zf.extract(member, temp_dir)
                            extracted = temp_dir / member
                            index_file = voice_dir / f"{slug}.index"
                            shutil.move(str(extracted), str(index_file))
            except zipfile.BadZipFile:
                # Not a zip file, might be a direct .pth file
                if str(url).endswith('.pth'):
                    pth_file = voice_dir / f"{slug}.pth"
                    shutil.move(str(zip_path), str(pth_file))
            
            if not pth_file or not pth_file.exists():
                shutil.rmtree(voice_dir, ignore_errors=True)
                return {"success": False, "error": "No .pth model file found in download"}
            
            if progress_callback:
                progress_callback({"stage": "saving", "progress": 80})
            
            # Save metadata
            metadata = {
                "name": name,
                "slug": slug,
                "category": category,
                "description": description,
                "pitch_shift": pitch_shift,
                "model_path": str(pth_file),
                "index_path": str(index_file) if index_file else None,
                "user_id": user_id,
                "source_url": url,
                "created_at": datetime.utcnow().isoformat()
            }
            
            metadata_path = voice_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            
            if progress_callback:
                progress_callback({"stage": "complete", "progress": 100})
            
            logger.info(f"✅ Imported voice model: {name} ({slug}) for user {user_id}")
            
            return {
                "success": True,
                "voice": metadata
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to import voice model: {e}")
            if voice_dir.exists():
                shutil.rmtree(voice_dir, ignore_errors=True)
            return {"success": False, "error": str(e)}
        
        finally:
            # Cleanup temp directory
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def get_user_models_dir(self, user_id: str) -> Path:
        """Get the models directory for a specific user"""
        return RVC_MODELS_DIR / "users" / str(user_id)
    
    def get_shared_models_dir(self) -> Path:
        """Get the shared models directory"""
        return RVC_MODELS_DIR / "shared"


# Singleton instance
_catalog_service: Optional[VoiceCatalogService] = None

def get_voice_catalog_service() -> VoiceCatalogService:
    """Get the singleton voice catalog service instance"""
    global _catalog_service
    if _catalog_service is None:
        _catalog_service = VoiceCatalogService()
    return _catalog_service

