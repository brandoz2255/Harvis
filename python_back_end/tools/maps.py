"""Google Maps API proxy router for Harvis.

Provides endpoints to proxy Google Maps API requests without exposing API keys to the frontend.
"""

import os
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from fastapi.responses import Response

router = APIRouter(prefix="/api/tools/maps", tags=["maps"])


class MapsHealthResponse(BaseModel):
    status: str
    message: str


class GeocodeRequest(BaseModel):
    address: str = Field(..., description="Address to geocode")


class GeocodeResponse(BaseModel):
    lat: float
    lng: float
    formatted_address: str


class DirectionsRequest(BaseModel):
    origin: str = Field(..., description="Origin location (address or lat,lng)")
    destination: str = Field(..., description="Destination location (address or lat,lng)")
    mode: Optional[str] = Field("driving", description="Travel mode: driving, walking, bicycling, transit")


def get_maps_api_key() -> str:
    """Get Google Maps API key from environment."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="Google Maps API key not configured")
    return api_key


@router.get("/health", response_model=MapsHealthResponse)
async def maps_health():
    """Health check endpoint for maps API."""
    return MapsHealthResponse(status="ok", message="Maps API is operational")


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode_address(
    request: GeocodeRequest,
    api_key: str = Depends(get_maps_api_key)
):
    """Geocode an address to lat/lng coordinates."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": request.address, "key": api_key}
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") != "OK":
                raise HTTPException(400, f"Geocoding error: {data.get('status')}")
            
            result = data["results"][0]
            location = result["geometry"]["location"]
            
            return GeocodeResponse(
                lat=location["lat"],
                lng=location["lng"],
                formatted_address=result["formatted_address"]
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Geocoding service error: {str(e)}")


@router.post("/directions")
async def get_directions(
    request: DirectionsRequest,
    api_key: str = Depends(get_maps_api_key)
):
    """Get directions between two locations."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": request.origin,
                    "destination": request.destination,
                    "mode": request.mode,
                    "key": api_key
                }
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") != "OK":
                raise HTTPException(400, f"Directions error: {data.get('status')}")
            
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Directions service error: {str(e)}")


@router.get("/static")
async def get_static_map(
    center: str = Query(..., description="Format: lat,lng"),
    zoom: int = Query(15, description="Zoom level (1-20)"),
    size: str = Query("600x300", description="Image dimensions (e.g., 600x300)"),
    markers: Optional[str] = Query(None, description="Format: lat,lng"),
    api_key: str = Depends(get_maps_api_key)
):
    """Proxy to Google Maps Static API for map images."""
    try:
        params = {
            "center": center,
            "zoom": zoom,
            "size": size,
            "key": api_key
        }
        if markers:
            params["markers"] = markers
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/staticmap",
                params=params
            )
            resp.raise_for_status()
            
            return Response(
                content=resp.content,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=3600"}
            )
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Static map API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"Static map error: {str(e)}")


@router.get("/places/autocomplete")
async def places_autocomplete(
    input: str = Query(..., description="Search query for places"),
    api_key: str = Depends(get_maps_api_key)
):
    """Get place autocomplete suggestions."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/place/autocomplete/json",
                params={
                    "input": input,
                    "key": api_key
                }
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") not in ["OK", "ZERO_RESULTS"]:
                raise HTTPException(400, f"Places error: {data.get('status')}")
            
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Places service error: {str(e)}")
