import os
import time
import uuid
import base64
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service as FirefoxService


app = FastAPI()

# In-memory sessions: session_id -> driver
_sessions: Dict[str, webdriver.Firefox] = {}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


class CreateSessionRequest(BaseModel):
    headless: bool = True


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


def _get_driver(session_id: str) -> webdriver.Firefox:
    d = _sessions.get(session_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return d


@app.post("/session")
def create_session(req: CreateSessionRequest) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    opts = FirefoxOptions()
    if req.headless:
        opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    service = FirefoxService(executable_path=GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=opts)
    _sessions[session_id] = driver
    return {"sessionId": session_id}


@app.post("/navigate")
def navigate(req: NavigateRequest) -> Dict[str, Any]:
    d = _get_driver(req.sessionId)
    d.get(req.url)
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
    d = _sessions.pop(req.sessionId, None)
    if d is not None:
        try:
            d.quit()
        except Exception:
            pass
    return {"ok": True}


@app.post("/screenshot")
def screenshot(req: ScreenshotRequest) -> Dict[str, Any]:
    d = _get_driver(req.sessionId)
    png = d.get_screenshot_as_png()
    return {"pngBase64": base64.b64encode(png).decode("ascii")}

