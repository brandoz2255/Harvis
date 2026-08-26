"""Shared browser-runner HTML → PNG helpers.

Extracted from integrations/discord_workspace_bot.py so Discord previews and the
Build screenshot_preview tool share one path. Only navigates to data: URLs of
HTML the system itself wrote — never remote URLs (no SSRF work here).

The HTML is nevertheless UNTRUSTED: a model wrote it, often from a user's
screenshot. Every render therefore asks the runner for a **safe-mode** session
(``safeMode: true``) — no JavaScript, and every network protocol pointed at a
dead port so the page cannot fetch a CDN script, reach a sibling container, or
beacon out. Point ``HARVIS_BROWSER_RUNNER_URL`` at the dedicated
``preview-runner`` service, which additionally sits on an internal-only Docker
network and forces safe mode regardless of what a caller asks for.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BROWSER_RUNNER_URL = os.getenv("HARVIS_BROWSER_RUNNER_URL", "http://browser-runner:8765")

# Desktop / mobile viewports matching upstream screenshot-to-code defaults.
DESKTOP_VIEWPORT = (1280, 800)
MOBILE_VIEWPORT = (390, 844)


async def render_html_to_png(
    html: str,
    *,
    out_path: Optional[str] = None,
    width: int = DESKTOP_VIEWPORT[0],
    height: int = DESKTOP_VIEWPORT[1],
    full_page: bool = True,
    settle_ms: int = 700,
) -> Optional[bytes]:
    """Render an HTML/SVG string to PNG bytes via browser-runner (data: URL).

    Returns PNG bytes on success, None on failure. If ``out_path`` is set, also
    writes the file. Always closes the session.
    """
    try:
        b64 = base64.b64encode((html or "").encode("utf-8")).decode()
        data_url = f"data:text/html;charset=utf-8;base64,{b64}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            s = await client.post(
                f"{_BROWSER_RUNNER_URL}/session",
                json={
                    "headless": True,
                    "width": width,
                    "height": height,
                    # Untrusted, model-authored HTML: no JS, no network.
                    "safeMode": True,
                },
            )
            if s.status_code != 200:
                logger.warning("browser-runner /session failed: %s", s.text[:300])
                return None
            sid = (s.json() or {}).get("sessionId") or (s.json() or {}).get("id")
            if not sid:
                return None
            try:
                nav = await client.post(
                    f"{_BROWSER_RUNNER_URL}/navigate",
                    json={"sessionId": sid, "url": data_url},
                )
                # A failed navigation used to be ignored, and the screenshot that
                # followed captured about:blank — a blank PNG returned as a
                # successful render.
                if nav.status_code != 200:
                    logger.warning(
                        "browser-runner /navigate failed (%s): %s",
                        nav.status_code,
                        nav.text[:300],
                    )
                    return None
                await asyncio.sleep(max(0.1, settle_ms / 1000.0))
                shot = await client.post(
                    f"{_BROWSER_RUNNER_URL}/screenshot",
                    json={"sessionId": sid, "fullPage": bool(full_page)},
                )
                if shot.status_code != 200:
                    logger.warning(
                        "browser-runner /screenshot failed (%s): %s",
                        shot.status_code,
                        shot.text[:300],
                    )
                    return None
                body = shot.json() or {}
                png_b64 = body.get("pngBase64") or ""
                if not png_b64:
                    return None
                if full_page and body.get("captureMode") == "viewport":
                    logger.warning(
                        "browser-runner could only capture the viewport; "
                        "the returned PNG is cropped, not full-page"
                    )
                png = base64.b64decode(png_b64)
                if out_path:
                    with open(out_path, "wb") as f:
                        f.write(png)
                return png
            finally:
                try:
                    await client.post(
                        f"{_BROWSER_RUNNER_URL}/close", json={"sessionId": sid}
                    )
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("browser-runner render failed: %s", exc)
        return None


async def render_html_dual_viewport(html: str) -> dict:
    """Render desktop + mobile full-page PNGs. Returns base64 strings (not persisted).

    Keys: ok, desktop_b64, mobile_b64, error. PNGs are for model vision only —
    "for seeing, not keeping."
    """
    desktop = await render_html_to_png(
        html, width=DESKTOP_VIEWPORT[0], height=DESKTOP_VIEWPORT[1], full_page=True
    )
    mobile = await render_html_to_png(
        html, width=MOBILE_VIEWPORT[0], height=MOBILE_VIEWPORT[1], full_page=True
    )
    if not desktop and not mobile:
        return {
            "ok": False,
            "desktop_b64": "",
            "mobile_b64": "",
            "error": "browser-runner failed to render both viewports",
        }
    return {
        "ok": True,
        "desktop_b64": base64.b64encode(desktop).decode("ascii") if desktop else "",
        "mobile_b64": base64.b64encode(mobile).decode("ascii") if mobile else "",
        "error": "",
        "desktop_viewport": list(DESKTOP_VIEWPORT),
        "mobile_viewport": list(MOBILE_VIEWPORT),
    }
