"""Per-user OpenAI-compatible endpoints for the Hermes facade.

Endpoint keys are encrypted before they reach Postgres.  Public payloads are
intentionally shaped without ciphertext (or the original key), because these
records are returned directly to the browser settings page.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import urlparse

SETTINGS_KEY = "hermes_ui"
ENDPOINTS_KEY = "custom_endpoints"
ACTIVE_KEY = "active_endpoint_id"
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class EndpointValidationError(ValueError):
    """A client-supplied endpoint cannot be stored or called."""


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise EndpointValidationError(f"{field} must be text")
    value = value.strip()
    if not value:
        raise EndpointValidationError(f"{field} is required")
    if len(value) > limit:
        raise EndpointValidationError(f"{field} is too long")
    return value


def _endpoint_id(value: Any, name: str) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        candidate = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not candidate:
        candidate = f"endpoint-{uuid.uuid4().hex[:12]}"
    if not _ID_RE.fullmatch(candidate):
        raise EndpointValidationError("Provider ID must start with a letter and use lowercase letters, numbers, _ or -")
    return candidate


def _base_url(value: Any) -> str:
    url = _text(value, "Endpoint URL", 512).rstrip("/")
    parsed = urlparse(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise EndpointValidationError("Endpoint URL must be a plain http(s) URL")
    return url


def _models(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EndpointValidationError("models must be a list")
    seen: set[str] = set()
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise EndpointValidationError("model names must be text")
        model = raw.strip()
        if model and model not in seen:
            if len(model) > 255:
                raise EndpointValidationError("model name is too long")
            seen.add(model)
            out.append(model)
    if len(out) > 100:
        raise EndpointValidationError("too many models")
    return out


def normalize_endpoint(payload: dict[str, Any], *, require_model: bool = True) -> dict[str, Any]:
    """Validate a browser payload and return only non-secret storage fields."""
    if not isinstance(payload, dict):
        raise EndpointValidationError("Endpoint payload must be an object")
    name = _text(payload.get("name"), "Name", 80)
    model = str(payload.get("model") or "").strip()
    if require_model and not model:
        raise EndpointValidationError("Default model is required")
    if len(model) > 255:
        raise EndpointValidationError("Default model is too long")
    context = payload.get("context_length")
    if context is not None:
        if isinstance(context, bool):
            raise EndpointValidationError("Context length must be a number")
        try:
            context = int(context)
        except (TypeError, ValueError) as exc:
            raise EndpointValidationError("Context length must be a number") from exc
        if not 1 <= context <= 10_000_000:
            raise EndpointValidationError("Context length is out of range")
    return {
        "id": _endpoint_id(payload.get("id"), name),
        "name": name,
        "base_url": _base_url(payload.get("base_url")),
        "model": model,
        "models": _models(payload.get("models")),
        "discover_models": bool(payload.get("discover_models", True)),
        "context_length": context,
    }


def public_endpoint(raw: dict[str, Any], *, active_id: str | None = None) -> dict[str, Any]:
    """The browser-safe endpoint representation; no secret-derived preview."""
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or ""),
        "base_url": str(raw.get("base_url") or ""),
        "model": str(raw.get("model") or ""),
        "models": [str(m) for m in raw.get("models", []) if isinstance(m, str)],
        "discover_models": bool(raw.get("discover_models", True)),
        "context_length": raw.get("context_length"),
        "has_api_key": bool(raw.get("api_key_enc")),
        "api_key_preview": "API key saved" if raw.get("api_key_enc") else None,
        "is_current": str(raw.get("id") or "") == (active_id or ""),
    }


def _encrypt(value: str) -> str:
    from main import encrypt_api_key
    return encrypt_api_key(value)


def _decrypt(value: str) -> str:
    from main import decrypt_api_key
    return decrypt_api_key(value)


def _settings(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _endpoint_list(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows = section.get(ENDPOINTS_KEY)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def _read_section(pool, user_id: int) -> dict[str, Any]:
    async with pool.acquire() as conn:
        value = await conn.fetchval("SELECT settings->$2 FROM owui_user_settings WHERE user_id=$1", user_id, SETTINGS_KEY)
    section = _settings(value)
    return section


async def _write_section(pool, user_id: int, section: dict[str, Any]) -> None:
    """Lock + rewrite the full settings blob so no sibling user setting is lost."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", user_id)
            settings = _settings(row["settings"] if row else {})
            settings[SETTINGS_KEY] = section
            await conn.execute(
                "INSERT INTO owui_user_settings (user_id, settings, updated_at) VALUES ($1, $2::jsonb, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                user_id, json.dumps(settings),
            )


async def list_endpoints(pool, user_id: int) -> tuple[list[dict[str, Any]], str | None]:
    section = await _read_section(pool, user_id)
    active_id = section.get(ACTIVE_KEY)
    active_id = active_id if isinstance(active_id, str) else None
    return _endpoint_list(section), active_id


async def custom_endpoints_payload(pool, user_id: int, fallback: dict[str, str]) -> dict[str, Any]:
    endpoints, active_id = await list_endpoints(pool, user_id)
    active = next((endpoint for endpoint in endpoints if endpoint.get("id") == active_id), None)
    current = ({"base_url": str(active.get("base_url") or ""), "provider": active_id or "harvis",
                "model": str(active.get("model") or "")}
               if active else {"base_url": "", **fallback})
    return {"current": current, "endpoints": [public_endpoint(endpoint, active_id=active_id) for endpoint in endpoints]}


async def save_endpoint(pool, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = normalize_endpoint(payload)
    section = await _read_section(pool, user_id)
    endpoints = _endpoint_list(section)
    existing = next((row for row in endpoints if row.get("id") == endpoint["id"]), None)
    if existing:
        endpoint["api_key_enc"] = existing.get("api_key_enc")
    api_key = payload.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        endpoint["api_key_enc"] = _encrypt(api_key.strip())
    endpoints = [row for row in endpoints if row.get("id") != endpoint["id"]] + [endpoint]
    section[ENDPOINTS_KEY] = endpoints
    if bool(payload.get("make_default")):
        section[ACTIVE_KEY] = endpoint["id"]
        section["model"] = endpoint["model"]
    await _write_section(pool, user_id, section)
    return endpoint


async def activate_endpoint(pool, user_id: int, endpoint_id: str, model: str = "") -> dict[str, Any]:
    """Point chats at an endpoint. A ``model`` the endpoint lists becomes its
    default, so picking one model out of an endpoint's group sticks instead of
    snapping back to whatever model the endpoint was saved with."""
    section = await _read_section(pool, user_id)
    endpoint = next((row for row in _endpoint_list(section) if row.get("id") == endpoint_id), None)
    if not endpoint:
        raise EndpointValidationError("Custom endpoint not found")
    model = (model or "").strip()
    if model and (model == endpoint.get("model") or model in (endpoint.get("models") or [])):
        endpoint["model"] = model
    section[ACTIVE_KEY] = endpoint_id
    section["model"] = str(endpoint.get("model") or "")
    await _write_section(pool, user_id, section)
    return endpoint


async def deactivate_endpoint(pool, user_id: int) -> None:
    section = await _read_section(pool, user_id)
    section.pop(ACTIVE_KEY, None)
    await _write_section(pool, user_id, section)


async def delete_endpoint(pool, user_id: int, endpoint_id: str) -> None:
    section = await _read_section(pool, user_id)
    endpoints = _endpoint_list(section)
    if not any(row.get("id") == endpoint_id for row in endpoints):
        raise EndpointValidationError("Custom endpoint not found")
    section[ENDPOINTS_KEY] = [row for row in endpoints if row.get("id") != endpoint_id]
    if section.get(ACTIVE_KEY) == endpoint_id:
        section.pop(ACTIVE_KEY, None)
    await _write_section(pool, user_id, section)


async def resolve_endpoint(pool, user_id: int, endpoint_id: str) -> dict[str, str] | None:
    endpoints, _ = await list_endpoints(pool, user_id)
    endpoint = next((row for row in endpoints if row.get("id") == endpoint_id), None)
    if not endpoint:
        return None
    encrypted = endpoint.get("api_key_enc")
    return {
        "id": str(endpoint.get("id") or ""),
        "base_url": str(endpoint.get("base_url") or ""),
        "model": str(endpoint.get("model") or ""),
        "api_key": _decrypt(encrypted) if isinstance(encrypted, str) and encrypted else "",
    }


async def resolve_active_endpoint(pool, user_id: int) -> dict[str, str] | None:
    _, active_id = await list_endpoints(pool, user_id)
    return await resolve_endpoint(pool, user_id, active_id) if active_id else None
