"""Refs, not pixels: the observation and action surface for a watched browser.

The agent never sees a screenshot and never guesses coordinates. It asks for a
**snapshot** — a flat list of the things on the page that can be acted on, each
stamped with a short reference — and then acts by reference. That is what makes
an action reviewable: "click ref_12 (button 'Confirm and pay')" can be read and
gated by a human or by policy, where "click at 640,380" cannot.

The shape mirrors the Camofox API that the Hermes sidecar already speaks, so the
backend facade can forward to this service and Hermes's own browser tool works
against a Harvis-hosted browser without a patch.

Two rules live here rather than in the caller:

* While the user has taken the wheel, every *acting* endpoint answers 423. The
  agent cannot fight the user for the mouse, and cannot act on a page the user
  navigated to while they were driving. Looking (snapshot, screenshot) stays
  allowed, because the agent watching is harmless and useful.
* Refs are per-snapshot. Acting on a stale ref fails loudly rather than hitting
  whatever moved into that position, which is the browser-automation bug that
  quietly does the wrong thing.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import display

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/camofox", tags=["camofox"])

# app.py owns the session table; it hands us a getter rather than importing back
# into us, so this module stays independently testable.
_driver_provider: Optional[Callable[[str], Any]] = None


def set_driver_provider(fn: Callable[[str], Any]) -> None:
    global _driver_provider
    _driver_provider = fn


def _driver(tab_id: str):
    if _driver_provider is None:
        raise HTTPException(status_code=503, detail="browser sessions unavailable")
    return _driver_provider(tab_id)


def _guard_takeover(tab_id: str) -> None:
    screen = display.get(tab_id)
    if screen is not None and screen.taken_over:
        raise HTTPException(
            status_code=423,
            detail="The user has taken over this browser. Hand it back before acting.",
        )


# ── the snapshot ─────────────────────────────────────────────────────────────

# Stamps every actionable element with data-harvis-ref and returns a flat map.
# Kept deliberately small and dependency-free: it runs on hostile pages.
_SNAPSHOT_JS = r"""
const MAX = arguments[0] || 200;
document.querySelectorAll('[data-harvis-ref]').forEach(function (el) {
  el.removeAttribute('data-harvis-ref');
});
const SEL = 'a[href],button,input,select,textarea,summary,' +
  '[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],' +
  '[role=menuitem],[role=option],[role=switch],[contenteditable=""],' +
  '[contenteditable=true],[onclick]';
function visible(el) {
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  const s = window.getComputedStyle(el);
  if (s.visibility === 'hidden' || s.display === 'none') return false;
  if (parseFloat(s.opacity || '1') === 0) return false;
  return true;
}
function nameOf(el) {
  const aria = el.getAttribute('aria-label');
  if (aria) return aria.trim();
  const labelled = el.getAttribute('aria-labelledby');
  if (labelled) {
    const t = document.getElementById(labelled);
    if (t && t.innerText) return t.innerText.trim();
  }
  if (el.tagName === 'INPUT' && el.id) {
    const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    if (lab && lab.innerText) return lab.innerText.trim();
  }
  const txt = (el.innerText || el.value || el.placeholder || el.title || '').trim();
  if (txt) return txt;
  return (el.getAttribute('name') || el.getAttribute('alt') || '').trim();
}
function roleOf(el) {
  const explicit = el.getAttribute('role');
  if (explicit) return explicit;
  const tag = el.tagName.toLowerCase();
  if (tag === 'a') return 'link';
  if (tag === 'button' || tag === 'summary') return 'button';
  if (tag === 'select') return 'combobox';
  if (tag === 'textarea') return 'textbox';
  if (tag === 'input') {
    const t = (el.getAttribute('type') || 'text').toLowerCase();
    if (t === 'checkbox' || t === 'radio' || t === 'submit' || t === 'button') return t;
    return 'textbox';
  }
  return tag;
}
const refs = {};
let n = 0;
const nodes = document.querySelectorAll(SEL);
for (let i = 0; i < nodes.length && n < MAX; i++) {
  const el = nodes[i];
  if (!visible(el)) continue;
  n += 1;
  const ref = 'ref_' + n;
  el.setAttribute('data-harvis-ref', ref);
  const entry = {
    role: roleOf(el),
    name: (nameOf(el) || '').slice(0, 160)
  };
  const href = el.getAttribute('href');
  if (href) entry.href = href.slice(0, 500);
  const type = el.getAttribute('type');
  if (type) entry.type = type.toLowerCase();
  const nm = el.getAttribute('name');
  if (nm) entry.field = nm.slice(0, 80);
  if (el.getAttribute('autocomplete')) entry.autocomplete = el.getAttribute('autocomplete');
  if (el.disabled) entry.disabled = true;
  refs[ref] = entry;
}
return {
  url: location.href,
  title: document.title || '',
  text: (document.body ? document.body.innerText : '').slice(0, 20000),
  refs: refs,
  truncated: nodes.length > n
};
"""


class NavigateBody(BaseModel):
    url: str


class RefBody(BaseModel):
    ref: str


class TypeBody(BaseModel):
    ref: str
    text: str
    submit: bool = False


class ScrollBody(BaseModel):
    ref: Optional[str] = None
    direction: str = "down"
    amount: int = Field(default=600, ge=1, le=20000)


class PressBody(BaseModel):
    key: str
    ref: Optional[str] = None


class TakeoverBody(BaseModel):
    taken: bool


class SnapshotBody(BaseModel):
    maxRefs: int = Field(default=200, ge=1, le=1000)


# Exactly what a snapshot mints, and nothing else. The shape is checked before
# the value is ever interpolated into a selector, so a ref cannot carry markup.
_REF_RE = re.compile(r"ref_\d{1,4}\Z")


def _by_ref(driver, ref: str):
    """The element a snapshot stamped with ``ref``, or a loud failure.

    Looked up through a script rather than ``find_element`` so this module needs
    no selenium import: the browser is behind a driver object either way, and
    one less import is one less thing that has to be installed to test the gate.
    """
    if not _REF_RE.match(ref or ""):
        raise HTTPException(status_code=400, detail="ref must look like ref_12")
    try:
        el = driver.execute_script(
            "return document.querySelector('[data-harvis-ref=\"' + arguments[0] + '\"]');",
            ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"lookup failed: {exc}") from exc
    if el is None:
        raise HTTPException(
            status_code=409,
            detail=f"{ref} is not on the page any more — take a fresh snapshot.",
        )
    return el


@router.post("/tabs/{tab_id}/snapshot")
def snapshot(tab_id: str, body: SnapshotBody | None = None) -> Dict[str, Any]:
    """What is on the page, as things that can be acted on. Never blocked by a
    takeover: watching is not acting."""
    driver = _driver(tab_id)
    try:
        result = driver.execute_script(_SNAPSHOT_JS, (body or SnapshotBody()).maxRefs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"snapshot failed: {exc}") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="snapshot returned an unexpected shape")
    result.setdefault("refs", {})
    return result


@router.post("/tabs/{tab_id}/navigate")
def navigate(tab_id: str, body: NavigateBody) -> Dict[str, Any]:
    _guard_takeover(tab_id)
    driver = _driver(tab_id)
    try:
        driver.get(body.url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"navigate failed: {exc}") from exc
    return {"ok": True, "url": driver.current_url}


@router.post("/tabs/{tab_id}/click")
def click(tab_id: str, body: RefBody) -> Dict[str, Any]:
    _guard_takeover(tab_id)
    driver = _driver(tab_id)
    el = _by_ref(driver, body.ref)
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.click()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"click failed: {exc}") from exc
    return {"ok": True, "url": driver.current_url}


@router.post("/tabs/{tab_id}/type")
def type_text(tab_id: str, body: TypeBody) -> Dict[str, Any]:
    _guard_takeover(tab_id)
    from selenium.webdriver.common.keys import Keys

    driver = _driver(tab_id)
    el = _by_ref(driver, body.ref)
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.clear()
    except Exception:
        pass
    try:
        el.send_keys(body.text)
        if body.submit:
            el.send_keys(Keys.RETURN)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"type failed: {exc}") from exc
    return {"ok": True, "url": driver.current_url}


@router.post("/tabs/{tab_id}/scroll")
def scroll(tab_id: str, body: ScrollBody) -> Dict[str, Any]:
    _guard_takeover(tab_id)
    driver = _driver(tab_id)
    if body.ref:
        el = _by_ref(driver, body.ref)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        return {"ok": True}
    dy = body.amount if body.direction == "down" else -body.amount
    dx = 0
    if body.direction in ("left", "right"):
        dx = body.amount if body.direction == "right" else -body.amount
        dy = 0
    driver.execute_script("window.scrollBy(arguments[0], arguments[1]);", dx, dy)
    return {"ok": True}


@router.post("/tabs/{tab_id}/back")
def back(tab_id: str) -> Dict[str, Any]:
    _guard_takeover(tab_id)
    driver = _driver(tab_id)
    driver.back()
    return {"ok": True, "url": driver.current_url}


@router.post("/tabs/{tab_id}/press")
def press(tab_id: str, body: PressBody) -> Dict[str, Any]:
    _guard_takeover(tab_id)
    from selenium.webdriver.common.keys import Keys

    driver = _driver(tab_id)
    key = getattr(Keys, (body.key or "").upper().replace(" ", "_"), None)
    if key is None:
        raise HTTPException(status_code=400, detail=f"unknown key: {body.key}")
    target = _by_ref(driver, body.ref) if body.ref else driver.switch_to.active_element
    target.send_keys(key)
    return {"ok": True, "url": driver.current_url}


# Both verbs on purpose. A screenshot takes no body and changes nothing, so GET
# is what a caller reaches for first; POST stays because the rest of this API is
# POST and Hermes's browser tool posts to every endpoint it knows.
@router.get("/tabs/{tab_id}/screenshot")
@router.post("/tabs/{tab_id}/screenshot")
def screenshot(tab_id: str) -> Dict[str, Any]:
    """For the user's eyes, not the agent's — the agent acts on refs."""
    driver = _driver(tab_id)
    png = driver.get_screenshot_as_png()
    return {"ok": True, "imageBase64": base64.b64encode(png).decode("ascii"), "mimeType": "image/png"}


@router.post("/tabs/{tab_id}/takeover")
def takeover(tab_id: str, body: TakeoverBody) -> Dict[str, Any]:
    screen = display.set_takeover(tab_id, body.taken)
    if screen is None:
        raise HTTPException(status_code=404, detail="that session has no screen")
    return {"ok": True, "takenOver": screen.taken_over}


@router.get("/tabs/{tab_id}")
def tab_info(tab_id: str) -> Dict[str, Any]:
    driver = _driver(tab_id)
    screen = display.get(tab_id)
    return {
        "tabId": tab_id,
        "url": driver.current_url,
        "title": driver.title,
        "screen": screen.to_dict() if screen else None,
    }


def refs_summary(snap: Dict[str, Any], limit: int = 40) -> List[str]:
    """One readable line per ref. Used by tests and by the run card's copy."""
    out: List[str] = []
    for ref, meta in list((snap.get("refs") or {}).items())[:limit]:
        name = (meta.get("name") or "").strip()
        role = meta.get("role") or "element"
        out.append(f"{ref}: {role}" + (f" '{name}'" if name else ""))
    return out
