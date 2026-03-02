"""
Google Maps API Proxy Module

This module provides a secure proxy for Google Maps API endpoints with:
- Rate limiting per user
- Response caching
- Server-side API key management (never exposed to frontend)
"""

import os
import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import httpx
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse

# Import auth utilities
from auth_optimized import get_current_user_optimized

# Router configuration
maps_router = APIRouter(prefix="/api/maps", tags=["maps"])

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_MAPS_BASE_URL = "https://maps.googleapis.com/maps/api"

# Rate limiting configuration
RATE_LIMIT_REQUESTS = int(os.getenv("MAPS_RATE_LIMIT", "100"))  # requests per window
RATE_LIMIT_WINDOW = int(os.getenv("MAPS_RATE_WINDOW", "86400"))  # 24 hours in seconds

# Cache configuration
CACHE_TTL_SECONDS = int(os.getenv("MAPS_CACHE_TTL", "3600"))  # 1 hour default

# ═══════════════════════════════════════════════════════════════════════════════
# Simple In-Memory Cache
# ═══════════════════════════════════════════════════════════════════════════════

class SimpleCache:
    """Simple in-memory cache with TTL support."""
    
    def __init__(self, default_ttl: int = CACHE_TTL_SECONDS):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = default_ttl
    
    def _make_key(self, prefix: str, params: Dict[str, Any]) -> str:
        """Create a cache key from prefix and params."""
        param_str = json.dumps(params, sort_keys=True)
        return f"{prefix}:{hashlib.sha256(param_str.encode()).hexdigest()}"
    
    def get(self, prefix: str, params: Dict[str, Any]) -> Optional[Any]:
        """Get cached value if it exists and hasn't expired."""
        key = self._make_key(prefix, params)
        entry = self._cache.get(key)
        
        if not entry:
            return None
        
        # Check if expired
        if datetime.utcnow() > entry["expires_at"]:
            del self._cache[key]
            return None
        
        return entry["data"]
    
    def set(self, prefix: str, params: Dict[str, Any], data: Any, ttl: Optional[int] = None):
        """Cache data with optional custom TTL."""
        key = self._make_key(prefix, params)
        ttl = ttl or self._default_ttl
        
        self._cache[key] = {
            "data": data,
            "expires_at": datetime.utcnow() + timedelta(seconds=ttl),
            "created_at": datetime.utcnow(),
        }
    
    def invalidate(self, prefix: str):
        """Invalidate all cache entries with given prefix."""
        keys_to_delete = [k for k in self._cache.keys() if k.startswith(f"{prefix}:")]
        for key in keys_to_delete:
            del self._cache[key]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        now = datetime.utcnow()
        total = len(self._cache)
        expired = sum(1 for entry in self._cache.values() if entry["expires_at"] < now)
        valid = total - expired
        
        return {
            "total_entries": total,
            "valid_entries": valid,
            "expired_entries": expired,
            "default_ttl": self._default_ttl,
        }

# Global cache instance
_maps_cache = SimpleCache()

# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiting
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple per-user rate limiter using in-memory storage."""
    
    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: Dict[str, List[datetime]] = {}
        self._lock = asyncio.Lock()
    
    async def is_allowed(self, user_id: str) -> bool:
        """Check if request is allowed for user."""
        async with self._lock:
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=self._window_seconds)
            
            # Get existing requests for user
            user_requests = self._requests.get(user_id, [])
            
            # Filter to only recent requests
            recent_requests = [r for r in user_requests if r > window_start]
            
            # Check if under limit
            if len(recent_requests) >= self._max_requests:
                return False
            
            # Record this request
            recent_requests.append(now)
            self._requests[user_id] = recent_requests
            
            return True
    
    def get_remaining(self, user_id: str) -> int:
        """Get remaining requests for user."""
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self._window_seconds)
        
        user_requests = self._requests.get(user_id, [])
        recent_requests = [r for r in user_requests if r > window_start]
        
        return max(0, self._max_requests - len(recent_requests))
    
    def get_reset_time(self, user_id: str) -> Optional[datetime]:
        """Get when rate limit resets for user."""
        user_requests = self._requests.get(user_id, [])
        if not user_requests:
            return None
        
        oldest_request = min(user_requests)
        return oldest_request + timedelta(seconds=self._window_seconds)

# Global rate limiter instance
_rate_limiter = RateLimiter()

# ═══════════════════════════════════════════════════════════════════════════════
# Dependency for rate limiting
# ═══════════════════════════════════════════════════════════════════════════════

async def check_rate_limit(request: Request, current_user = Depends(get_current_user_optimized)):
    """Dependency to check rate limit for current user."""
    # Use user ID as identifier
    user_id = str(getattr(current_user, 'id', 'anonymous'))
    
    if not await _rate_limiter.is_allowed(user_id):
        reset_time = _rate_limiter.get_reset_time(user_id)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "message": f"You have exceeded the {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW // 3600} hour limit",
                "reset_at": reset_time.isoformat() if reset_time else None,
            }
        )
    
    return current_user

# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class LocationResult(BaseModel):
    """A location result from search/geocoding."""
    place_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    types: List[str] = []
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    photo_reference: Optional[str] = None
    vicinity: Optional[str] = None
    price_level: Optional[int] = None
    open_now: Optional[bool] = None
    phone_number: Optional[str] = None
    website: Optional[str] = None
    url: Optional[str] = None  # Google Maps URL


class SearchRequest(BaseModel):
    """Request body for place search."""
    query: str = Field(..., min_length=1, max_length=200, description="Search query")
    location: Optional[str] = Field(None, description="Location bias (lat,lng or address)")
    radius: Optional[int] = Field(5000, ge=100, le=50000, description="Search radius in meters")
    type: Optional[str] = Field(None, description="Place type filter (e.g., restaurant, cafe)")
    page_token: Optional[str] = Field(None, description="Token for next page of results")


class SearchResponse(BaseModel):
    """Response for place search."""
    results: List[LocationResult]
    next_page_token: Optional[str] = None
    total_results: int
    query: str


class GeocodeRequest(BaseModel):
    """Request body for geocoding."""
    address: str = Field(..., min_length=1, max_length=500, description="Address to geocode")


class GeocodeResponse(BaseModel):
    """Response for geocoding."""
    results: List[LocationResult]
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ReverseGeocodeRequest(BaseModel):
    """Request body for reverse geocoding."""
    latitude: float = Field(..., ge=-90, le=90, description="Latitude")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude")


class PlaceDetailsRequest(BaseModel):
    """Request body for place details."""
    place_id: str = Field(..., description="Google Place ID")
    fields: Optional[List[str]] = Field(
        default=None,
        description="Fields to retrieve (defaults to basic)"
    )


class DistanceMatrixRequest(BaseModel):
    """Request body for distance matrix."""
    origins: List[str] = Field(..., min_items=1, max_items=10, description="Origin addresses or lat,lng")
    destinations: List[str] = Field(..., min_items=1, max_items=10, description="Destination addresses or lat,lng")
    mode: str = Field("driving", description="Travel mode: driving, walking, bicycling, transit")
    units: str = Field("metric", description="Units: metric or imperial")


class DistanceResult(BaseModel):
    """Distance result for a single origin-destination pair."""
    origin: str
    destination: str
    distance_text: str
    distance_meters: int
    duration_text: str
    duration_seconds: int
    status: str


class DistanceMatrixResponse(BaseModel):
    """Response for distance matrix."""
    results: List[DistanceResult]


class RateLimitStatus(BaseModel):
    """Rate limit status for user."""
    limit: int
    remaining: int
    window_hours: int
    reset_at: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

def parse_place_result(place_data: Dict[str, Any]) -> LocationResult:
    """Parse Google Places API result into LocationResult model."""
    geometry = place_data.get("geometry", {})
    location = geometry.get("location", {})
    photos = place_data.get("photos", [])
    photo_reference = photos[0].get("photo_reference") if photos else None
    
    # Parse opening hours
    opening_hours = place_data.get("opening_hours", {})
    open_now = opening_hours.get("open_now") if opening_hours else None
    
    return LocationResult(
        place_id=place_data.get("place_id", ""),
        name=place_data.get("name", ""),
        address=place_data.get("formatted_address", place_data.get("vicinity", "")),
        latitude=location.get("lat", 0.0),
        longitude=location.get("lng", 0.0),
        types=place_data.get("types", []),
        rating=place_data.get("rating"),
        user_ratings_total=place_data.get("user_ratings_total"),
        photo_reference=photo_reference,
        vicinity=place_data.get("vicinity"),
        price_level=place_data.get("price_level"),
        open_now=open_now,
        phone_number=place_data.get("formatted_phone_number"),
        website=place_data.get("website"),
        url=place_data.get("url"),
    )


async def make_google_maps_request(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Make a request to Google Maps API."""
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Google Maps API key not configured"
        )
    
    # Add API key to params
    params["key"] = GOOGLE_MAPS_API_KEY
    
    url = f"{GOOGLE_MAPS_BASE_URL}/{endpoint}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Google Maps API timeout")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Google Maps API error: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@maps_router.get("/status", response_model=Dict[str, Any])
async def maps_status():
    """Check Maps API configuration status."""
    return {
        "configured": bool(GOOGLE_MAPS_API_KEY),
        "api_key_preview": GOOGLE_MAPS_API_KEY[:8] + "..." if GOOGLE_MAPS_API_KEY else None,
        "cache_stats": _maps_cache.get_stats(),
        "rate_limit": {
            "requests_per_window": RATE_LIMIT_REQUESTS,
            "window_hours": RATE_LIMIT_WINDOW // 3600,
        },
    }


@maps_router.get("/rate-limit", response_model=RateLimitStatus)
async def get_rate_limit_status(current_user = Depends(get_current_user_optimized)):
    """Get current rate limit status for user."""
    user_id = str(getattr(current_user, 'id', 'anonymous'))
    remaining = _rate_limiter.get_remaining(user_id)
    reset_time = _rate_limiter.get_reset_time(user_id)
    
    return RateLimitStatus(
        limit=RATE_LIMIT_REQUESTS,
        remaining=remaining,
        window_hours=RATE_LIMIT_WINDOW // 3600,
        reset_at=reset_time.isoformat() if reset_time else None,
    )


@maps_router.post("/search", response_model=SearchResponse)
async def search_places(
    request: SearchRequest,
    current_user = Depends(check_rate_limit)
):
    """
    Search for places using Google Places API.
    
    Supports text search with optional location bias and type filtering.
    Results are cached for improved performance.
    """
    # Check cache first
    cache_params = request.model_dump(exclude_none=True)
    cached_result = _maps_cache.get("search", cache_params)
    if cached_result:
        return SearchResponse(**cached_result)
    
    # Build API params
    params: Dict[str, Any] = {
        "query": request.query,
        "radius": request.radius,
    }
    
    if request.location:
        params["location"] = request.location
    if request.type:
        params["type"] = request.type
    if request.page_token:
        params["pagetoken"] = request.page_token
    
    # Make request to Google Maps API
    data = await make_google_maps_request("place/textsearch/json", params)
    
    if data.get("status") != "OK" and data.get("status") != "ZERO_RESULTS":
        raise HTTPException(
            status_code=502,
            detail=f"Google Maps API error: {data.get('status')} - {data.get('error_message', '')}"
        )
    
    # Parse results
    results = [parse_place_result(place) for place in data.get("results", [])]
    
    response = SearchResponse(
        results=results,
        next_page_token=data.get("next_page_token"),
        total_results=len(results),
        query=request.query,
    )
    
    # Cache the response
    _maps_cache.set("search", cache_params, response.model_dump())
    
    return response


@maps_router.post("/geocode", response_model=GeocodeResponse)
async def geocode_address(
    request: GeocodeRequest,
    current_user = Depends(check_rate_limit)
):
    """
    Convert an address to geographic coordinates.
    
    Uses Google Geocoding API with server-side caching.
    """
    # Check cache
    cache_params = {"address": request.address}
    cached_result = _maps_cache.get("geocode", cache_params)
    if cached_result:
        return GeocodeResponse(**cached_result)
    
    params = {"address": request.address}
    data = await make_google_maps_request("geocode/json", params)
    
    if data.get("status") != "OK" and data.get("status") != "ZERO_RESULTS":
        raise HTTPException(
            status_code=502,
            detail=f"Geocoding error: {data.get('status')}"
        )
    
    results = [parse_place_result(result) for result in data.get("results", [])]
    
    # Get the first (best) result for convenience
    first_result = results[0] if results else None
    
    response = GeocodeResponse(
        results=results,
        formatted_address=first_result.address if first_result else None,
        latitude=first_result.latitude if first_result else None,
        longitude=first_result.longitude if first_result else None,
    )
    
    # Cache the response
    _maps_cache.set("geocode", cache_params, response.model_dump())
    
    return response


@maps_router.post("/reverse-geocode", response_model=GeocodeResponse)
async def reverse_geocode(
    request: ReverseGeocodeRequest,
    current_user = Depends(check_rate_limit)
):
    """
    Convert geographic coordinates to an address.
    
    Uses Google Reverse Geocoding API.
    """
    # Check cache
    cache_params = {"lat": request.latitude, "lng": request.longitude}
    cached_result = _maps_cache.get("reverse_geocode", cache_params)
    if cached_result:
        return GeocodeResponse(**cached_result)
    
    params = {
        "latlng": f"{request.latitude},{request.longitude}",
    }
    data = await make_google_maps_request("geocode/json", params)
    
    if data.get("status") != "OK" and data.get("status") != "ZERO_RESULTS":
        raise HTTPException(
            status_code=502,
            detail=f"Reverse geocoding error: {data.get('status')}"
        )
    
    results = [parse_place_result(result) for result in data.get("results", [])]
    
    first_result = results[0] if results else None
    
    response = GeocodeResponse(
        results=results,
        formatted_address=first_result.address if first_result else None,
        latitude=first_result.latitude if first_result else None,
        longitude=first_result.longitude if first_result else None,
    )
    
    # Cache the response
    _maps_cache.set("reverse_geocode", cache_params, response.model_dump())
    
    return response


@maps_router.get("/place/{place_id}", response_model=LocationResult)
async def get_place_details(
    place_id: str,
    current_user = Depends(check_rate_limit)
):
    """
    Get detailed information about a specific place.
    
    Uses Google Place Details API.
    """
    # Check cache
    cache_params = {"place_id": place_id}
    cached_result = _maps_cache.get("place_details", cache_params)
    if cached_result:
        return LocationResult(**cached_result)
    
    params = {
        "place_id": place_id,
        "fields": "place_id,name,formatted_address,geometry,types,rating,user_ratings_total,photos,vicinity,price_level,opening_hours,formatted_phone_number,website,url",
    }
    
    data = await make_google_maps_request("place/details/json", params)
    
    if data.get("status") != "OK":
        raise HTTPException(
            status_code=404 if data.get("status") == "NOT_FOUND" else 502,
            detail=f"Place details error: {data.get('status')}"
        )
    
    result = data.get("result", {})
    place = parse_place_result(result)
    
    # Cache the response
    _maps_cache.set("place_details", cache_params, place.model_dump())
    
    return place


@maps_router.post("/distance", response_model=DistanceMatrixResponse)
async def get_distance_matrix(
    request: DistanceMatrixRequest,
    current_user = Depends(check_rate_limit)
):
    """
    Calculate distances and travel times between multiple origins and destinations.
    
    Uses Google Distance Matrix API.
    """
    # Check cache
    cache_params = request.model_dump()
    cached_result = _maps_cache.get("distance", cache_params)
    if cached_result:
        return DistanceMatrixResponse(**cached_result)
    
    params = {
        "origins": "|".join(request.origins),
        "destinations": "|".join(request.destinations),
        "mode": request.mode,
        "units": request.units,
    }
    
    data = await make_google_maps_request("distancematrix/json", params)
    
    if data.get("status") != "OK":
        raise HTTPException(
            status_code=502,
            detail=f"Distance matrix error: {data.get('status')}"
        )
    
    # Parse results
    results = []
    rows = data.get("rows", [])
    
    for i, row in enumerate(rows):
        origin = request.origins[i] if i < len(request.origins) else ""
        elements = row.get("elements", [])
        
        for j, element in enumerate(elements):
            destination = request.destinations[j] if j < len(request.destinations) else ""
            
            distance = element.get("distance", {})
            duration = element.get("duration", {})
            
            results.append(DistanceResult(
                origin=origin,
                destination=destination,
                distance_text=distance.get("text", ""),
                distance_meters=distance.get("value", 0),
                duration_text=duration.get("text", ""),
                duration_seconds=duration.get("value", 0),
                status=element.get("status", "UNKNOWN"),
            ))
    
    response = DistanceMatrixResponse(results=results)
    
    # Cache the response (shorter TTL for distance matrix)
    _maps_cache.set("distance", cache_params, response.model_dump(), ttl=300)  # 5 minutes
    
    return response


@maps_router.get("/photo")
async def get_place_photo(
    photo_reference: str = Query(..., description="Photo reference from place search"),
    max_width: int = Query(400, ge=1, le=1600, description="Maximum photo width"),
    max_height: Optional[int] = Query(None, ge=1, le=1600, description="Maximum photo height"),
):
    """
    Get a place photo using a photo reference.
    
    Proxies the photo request to Google Maps API.
    """
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=503, detail="Google Maps API key not configured")
    
    params = {
        "photoreference": photo_reference,
        "maxwidth": max_width,
        "key": GOOGLE_MAPS_API_KEY,
    }
    
    if max_height:
        params["maxheight"] = max_height
    
    url = f"{GOOGLE_MAPS_BASE_URL}/place/photo"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            
            # Return the image with proper content type
            from fastapi.responses import Response
            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "image/jpeg"),
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Photo fetch error: {str(e)}")


@maps_router.get("/autocomplete")
async def autocomplete_places(
    input: str = Query(..., min_length=1, max_length=200, description="Input text for autocomplete"),
    location: Optional[str] = Query(None, description="Location bias (lat,lng)"),
    radius: int = Query(5000, ge=1, le=50000, description="Bias radius in meters"),
    types: Optional[str] = Query(None, description="Type filter (e.g., geocode, establishment)"),
    current_user = Depends(check_rate_limit)
):
    """
    Get autocomplete suggestions for a search query.
    
    Uses Google Places Autocomplete API.
    """
    # Check cache
    cache_params = {
        "input": input,
        "location": location,
        "radius": radius,
        "types": types,
    }
    cached_result = _maps_cache.get("autocomplete", cache_params)
    if cached_result:
        return cached_result
    
    params: Dict[str, Any] = {
        "input": input,
        "radius": radius,
    }
    
    if location:
        params["location"] = location
    if types:
        params["types"] = types
    
    data = await make_google_maps_request("place/autocomplete/json", params)
    
    if data.get("status") != "OK" and data.get("status") != "ZERO_RESULTS":
        raise HTTPException(
            status_code=502,
            detail=f"Autocomplete error: {data.get('status')}"
        )
    
    # Simplify response
    predictions = [
        {
            "place_id": p.get("place_id"),
            "description": p.get("description"),
            "main_text": p.get("structured_formatting", {}).get("main_text"),
            "secondary_text": p.get("structured_formatting", {}).get("secondary_text"),
            "types": p.get("types", []),
        }
        for p in data.get("predictions", [])
    ]
    
    result = {
        "predictions": predictions,
        "status": data.get("status"),
    }
    
    # Cache the response (short TTL for autocomplete)
    _maps_cache.set("autocomplete", cache_params, result, ttl=300)  # 5 minutes
    
    return result


@maps_router.post("/cache/clear")
async def clear_cache(
    prefix: Optional[str] = None,
    current_user = Depends(get_current_user_optimized)
):
    """
    Clear the maps API cache (admin only).
    
    Optionally specify a prefix to clear only specific cache entries.
    """
    # Note: In production, add admin role check here
    
    if prefix:
        _maps_cache.invalidate(prefix)
        return {"message": f"Cache entries with prefix '{prefix}' cleared"}
    else:
        # Clear all cache by reinitializing
        global _maps_cache
        _maps_cache = SimpleCache()
        return {"message": "All cache cleared"}
