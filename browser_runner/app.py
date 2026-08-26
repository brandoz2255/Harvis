import os
import threading
import time
import uuid
import base64
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

app = FastAPI()

# In-memory sessions: session_id -> (driver, created_at)
_sessions: Dict[str, Tuple[webdriver.Firefox, float]] = {}
_sessions_lock = threading.Lock()

_MAX_SESSIONS = max(1, int(os.getenv("HARVIS_BROWSER_MAX_SESSIONS", "8")))
_SESSION_TTL_S = max(30, int(os.getenv("HARVIS_BROWSER_SESSION_TTL_S", "300")))

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY


# Safe mode renders untrusted, model-authored HTML. It is the DEFAULT for the
# preview runner and OFF for the general browsing runner:
#   - JavaScript disabled, so the page cannot script, fetch, or read anything;
#   - every network load routed to a dead proxy, so no CDN, no internal service,
#     no tracking pixel — only inline CSS and data: URIs render;
#   - no plugins, no service workers, no WebGL, no remote fonts.
# Rendering a data: URL of self-contained HTML still works, which is the whole
# job. HARVIS_PREVIEW_SAFE_MODE_FORCED=1 makes a request unable to turn it off.
_SAFE_MODE_DEFAULT = _env_flag("HARVIS_PREVIEW_SAFE_MODE", False)
_SAFE_MODE_FORCED = _env_flag("HARVIS_PREVIEW_SAFE_MODE_FORCED", False)

# Session metadata alongside the driver (safe-mode flag, so /screenshot knows
# whether it is allowed to run JS for full-page measurement).
_session_meta: Dict[str, Dict[str, Any]] = {}


@app.get("/health")
def health() -> Dict[str, Any]:
    with _sessions_lock:
        n = len(_sessions)
    return {
        "ok": True,
        "sessions": n,
        "max_sessions": _MAX_SESSIONS,
        "safe_mode_default": _SAFE_MODE_DEFAULT,
        "safe_mode_forced": _SAFE_MODE_FORCED,
    }


class CreateSessionRequest(BaseModel):
    headless: bool = True
    width: Optional[int] = Field(default=None, ge=320, le=3840)
    height: Optional[int] = Field(default=None, ge=240, le=2160)
    # None = use this deployment's default. Ignored when SAFE_MODE_FORCED.
    safeMode: Optional[bool] = None


class NavigateRequest(BaseModel):
    sessionId: str
    url: str


class ActRequest(BaseModel):
    sessionId: str
    action: str  # "click" | "type" | "press" | "waitForSelector"
    selector: Optional[str] = None
    text: Optional[str] = None
    key: Optional[str] = None
    timeoutMs: int = 10000


class CloseRequest(BaseModel):
    sessionId: str


class ScreenshotRequest(BaseModel):
    sessionId: str
    fullPage: bool = False


def _firefox_service() -> FirefoxService:
    """Prefer a baked-in geckodriver; fall back to webdriver-manager only if needed.

    Baking the binary removes first-use egress (DNS-blocked clusters) and startup
    latency. Override with GECKODRIVER_PATH.
    """
    candidates = [
        os.getenv("GECKODRIVER_PATH") or "",
        "/usr/local/bin/geckodriver",
        "/usr/bin/geckodriver",
        "/home/runner/.local/bin/geckodriver",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return FirefoxService(executable_path=path)
    from webdriver_manager.firefox import GeckoDriverManager

    return FirefoxService(executable_path=GeckoDriverManager().install())


def _apply_safe_mode_prefs(opts: FirefoxOptions) -> None:
    """Render untrusted HTML with no scripting and no network of any kind.

    The proxy trick is the network kill switch: pointing every protocol at a
    dead local port makes every http(s) load fail inside the browser, so a
    generated page cannot pull a CDN script, reach a sibling container, or
    beacon out — regardless of what the Docker network happens to allow.
    ``data:`` URLs are not network loads, so the preview itself still renders.
    """
    opts.set_preference("javascript.enabled", False)
    # Kill every outbound protocol at the browser level.
    opts.set_preference("network.proxy.type", 1)
    for scheme in ("http", "ssl", "ftp", "socks"):
        opts.set_preference(f"network.proxy.{scheme}", "127.0.0.1")
        opts.set_preference(f"network.proxy.{scheme}_port", 1)
    opts.set_preference("network.proxy.no_proxies_on", "")
    # Without this, localhost is exempted from the proxy and stays reachable.
    opts.set_preference("network.proxy.allow_hijacking_localhost", True)
    opts.set_preference("network.dns.disabled", True)
    # Belt and braces on the features that could still touch the network or
    # persist state across renders.
    opts.set_preference("dom.serviceWorkers.enabled", False)
    opts.set_preference("dom.webnotifications.enabled", False)
    opts.set_preference("dom.push.enabled", False)
    opts.set_preference("media.peerconnection.enabled", False)
    opts.set_preference("webgl.disabled", True)
    opts.set_preference("gfx.font_loader.delay", 0)
    opts.set_preference("browser.safebrowsing.malware.enabled", False)
    opts.set_preference("browser.safebrowsing.phishing.enabled", False)
    opts.set_preference("network.captive-portal-service.enabled", False)
    opts.set_preference("browser.contentblocking.category", "strict")


def _expire_stale_locked() -> None:
    now = time.time()
    stale = [sid for sid, (_d, created) in _sessions.items() if now - created > _SESSION_TTL_S]
    for sid in stale:
        driver, _ = _sessions.pop(sid)
        _session_meta.pop(sid, None)
        try:
            driver.quit()
        except Exception:
            pass


def _get_driver(session_id: str) -> webdriver.Firefox:
    with _sessions_lock:
        _expire_stale_locked()
        entry = _sessions.get(session_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return entry[0]


def _full_page_png(driver: webdriver.Firefox, *, allow_js: bool = True) -> Tuple[bytes, str]:
    """Capture the full document height. Returns (png, mode).

    ``mode`` names which strategy actually produced the image — "native",
    "resize", or "viewport". It is returned to the caller rather than swallowed
    because a viewport-only shot of a tall page looks like a successful
    full-page capture, and the verify loop would then compare a cropped render
    against the user's screenshot and "fix" imaginary problems.
    """
    # Firefox's own full-page screenshot needs no JavaScript, so it is the only
    # strategy that works in safe mode — and it is more accurate anyway.
    try:
        return driver.get_full_page_screenshot_as_png(), "native"
    except Exception:
        pass
    if not allow_js:
        return driver.get_screenshot_as_png(), "viewport"
    try:
        # Fallback for drivers without the native command: measure with JS,
        # grow the window, shoot, restore.
        total_h = driver.execute_script(
            "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);"
        )
        total_w = driver.execute_script(
            "return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth);"
        )
        if not total_h or not total_w:
            return driver.get_screenshot_as_png(), "viewport"
        size = driver.get_window_size()
        # Cap extreme pages so we don't OOM the runner.
        h = min(int(total_h) + 80, 8000)
        w = min(max(int(total_w), int(size.get("width") or 1280)), 3840)
        driver.set_window_size(w, h)
        time.sleep(0.15)
        png = driver.get_screenshot_as_png()
        driver.set_window_size(int(size.get("width") or 1280), int(size.get("height") or 720))
        return png, "resize"
    except Exception:
        return driver.get_screenshot_as_png(), "viewport"


@app.post("/session")
def create_session(req: CreateSessionRequest) -> Dict[str, Any]:
    with _sessions_lock:
        _expire_stale_locked()
        if len(_sessions) >= _MAX_SESSIONS:
            raise HTTPException(
                status_code=429,
                detail=f"Too many browser sessions (max {_MAX_SESSIONS})",
            )

    session_id = str(uuid.uuid4())
    safe = _SAFE_MODE_DEFAULT if req.safeMode is None else bool(req.safeMode)
    if _SAFE_MODE_FORCED:
        safe = True

    opts = FirefoxOptions()
    if req.headless:
        opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    if safe:
        _apply_safe_mode_prefs(opts)

    service = _firefox_service()
    driver = webdriver.Firefox(service=service, options=opts)
    width = int(req.width or 1280)
    height = int(req.height or 720)
    try:
        driver.set_window_size(width, height)
    except Exception:
        pass

    with _sessions_lock:
        _sessions[session_id] = (driver, time.time())
        _session_meta[session_id] = {"safe_mode": safe}
    return {
        "sessionId": session_id,
        "width": width,
        "height": height,
        "safeMode": safe,
    }


@app.post("/navigate")
def navigate(req: NavigateRequest) -> Dict[str, Any]:
    d = _get_driver(req.sessionId)
    try:
        d.get(req.url)
    except Exception as exc:
        # Never report a failed navigation as ok — the caller would go on to
        # screenshot about:blank and hand back a blank PNG as a valid render.
        raise HTTPException(status_code=502, detail=f"navigate failed: {exc}") from exc
    return {"ok": True, "url": d.current_url}


@app.post("/act")
def act(req: ActRequest) -> Dict[str, Any]:
    d = _get_driver(req.sessionId)

    if req.action == "waitForSelector":
        deadline = time.time() + (req.timeoutMs / 1000.0)
        if not req.selector:
            raise HTTPException(status_code=400, detail="selector is required")
        while time.time() < deadline:
            els = d.find_elements(By.CSS_SELECTOR, req.selector)
            if els:
                return {"ok": True, "found": True}
            time.sleep(0.2)
        return {"ok": True, "found": False}

    if req.action == "click":
        if not req.selector:
            raise HTTPException(status_code=400, detail="selector is required")
        el = d.find_element(By.CSS_SELECTOR, req.selector)
        el.click()
        return {"ok": True}

    if req.action == "type":
        if not req.selector:
            raise HTTPException(status_code=400, detail="selector is required")
        el = d.find_element(By.CSS_SELECTOR, req.selector)
        el.clear()
        el.send_keys(req.text or "")
        return {"ok": True}

    if req.action == "press":
        key = (req.key or "").lower()
        mapping = {
            "enter": Keys.ENTER,
            "tab": Keys.TAB,
            "escape": Keys.ESCAPE,
        }
        if key not in mapping:
            raise HTTPException(status_code=400, detail="Unsupported key")
        d.switch_to.active_element.send_keys(mapping[key])
        return {"ok": True}

    raise HTTPException(status_code=400, detail="Unknown action")


@app.post("/close")
def close(req: CloseRequest) -> Dict[str, Any]:
    with _sessions_lock:
        entry = _sessions.pop(req.sessionId, None)
        _session_meta.pop(req.sessionId, None)
    if entry is not None:
        try:
            entry[0].quit()
        except Exception:
            pass
    return {"ok": True}


@app.post("/screenshot")
def screenshot(req: ScreenshotRequest) -> Dict[str, Any]:
    d = _get_driver(req.sessionId)
    with _sessions_lock:
        safe = bool((_session_meta.get(req.sessionId) or {}).get("safe_mode"))
    if req.fullPage:
        png, mode = _full_page_png(d, allow_js=not safe)
    else:
        png, mode = d.get_screenshot_as_png(), "viewport"
    return {
        "pngBase64": base64.b64encode(png).decode("ascii"),
        "fullPage": bool(req.fullPage),
        # "viewport" while fullPage was requested means the capture is CROPPED.
        "captureMode": mode,
        "safeMode": safe,
    }
