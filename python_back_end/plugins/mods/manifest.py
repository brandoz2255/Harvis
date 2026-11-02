"""What a mod may declare, checked before anyone is asked to approve it.

Three tiers, nothing else: ``looks`` (plain theme values), ``ui`` (one HTML file
run in the desktop's double-iframe sandbox), ``rules`` (declarative hooks the
backend evaluates; never code). Nothing here runs mod code.

The content hash is computed HERE, from the canonical JSON of everything the
server stores. The harvis-mods reference hashed ``JSON.stringify(m, sortedTopKeys)``,
whose array replacer drops every nested key that is not also a top-level key, so
``ui.csp`` and ``rules.hooks`` details could change without changing the hash.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MOD_FORMAT = "0.1"
SLOTS = ("clock", "pet", "status-line", "side-panel", "slash-command", "pre-send", "chat-widget", "island")
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "PreSend", "SessionStart")
HOOK_ACTIONS = ("require-approval", "block", "prepend-context", "log")
TOOL_EVENTS = ("PreToolUse", "PostToolUse")
PERMISSION_FEATURES = ("camera", "microphone", "geolocation", "clipboard-write")
CSP_KEYS = ("connectDomains", "resourceDomains", "frameDomains", "baseUriDomains")
TOP_KEYS = frozenset({"harvis_mod_version", "name", "version", "author", "description",
                      "looks", "ui", "rules", "user_config"})

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SEMVER_RE = re.compile(r"^\d{1,6}\.\d{1,6}\.\d{1,6}$")
ORIGIN_RE = re.compile(r"^(https://(\*\.)?[\w.-]+(:\d+)?|wss://[\w.-]+(:\d+)?)$")
RESOURCE_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_./-]{0,127}\.html$")
LOOK_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
# A look is a theme value, so it must not be able to fetch anything or break out
# of the declaration it is written into (url(), image-set(), @import, ; { } < >).
LOOK_BAD_RE = re.compile(r"url\s*\(|image-set|@import|expression|[;{}<>\\]", re.I)
MATCH_RE = re.compile(r"^tool:[A-Za-z0-9_.*?-]{1,96}$")

MAX_TEXT = 2000
MAX_HOOKS = 20
MAX_LOOKS = 48
MAX_LOOK_LEN = 96
MAX_RESOURCE_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 32 * 1024


def tiers_of(m: dict) -> list[str]:
    return [t for t in ("looks", "ui", "rules") if t in m]


def validate(manifest: Any, resources: Any = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). No errors = the mod may be staged for approval."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"], warnings
    bad = _not_storable(manifest) or _not_storable(resources or {})
    if bad:
        return [bad], warnings
    m = manifest
    if len(canonical(m)) > MAX_MANIFEST_BYTES:
        errors.append(f"manifest is larger than {MAX_MANIFEST_BYTES // 1024} KB")
    for key in sorted(set(m) - TOP_KEYS):
        errors.append(f"unknown field {key!r}")
    if m.get("harvis_mod_version") != MOD_FORMAT:
        errors.append(f'harvis_mod_version must be "{MOD_FORMAT}"')
    if not isinstance(m.get("name"), str) or not NAME_RE.match(m["name"]):
        errors.append("name: lowercase letters, digits and dashes, up to 64")
    if not isinstance(m.get("version"), str) or not SEMVER_RE.match(m["version"]):
        errors.append("version must look like 1.2.3")
    for key in ("author", "description"):
        if key in m and (not isinstance(m[key], str) or len(m[key]) > 300):
            errors.append(f"{key} must be text up to 300 characters")
        elif not m.get(key):
            warnings.append(f"no {key}")
    if not tiers_of(m):
        errors.append("mod does nothing: it needs looks, ui or rules")

    if "looks" in m:
        _check_looks(m["looks"], errors)
    if "ui" in m:
        _check_ui(m["ui"], resources if isinstance(resources, dict) else {}, errors, warnings)
    if "rules" in m:
        _check_rules(m["rules"], errors)
    if "user_config" in m:
        _check_user_config(m["user_config"], errors)

    extra = set(resources or {}) - ({m["ui"].get("resource")} if isinstance(m.get("ui"), dict) else set())
    for name in sorted(extra):
        errors.append(f"resource {name!r} is not the ui.resource")
    return errors, warnings


def _check_looks(looks: Any, errors: list[str]) -> None:
    if not isinstance(looks, dict):
        errors.append("looks must be an object of setting -> value")
        return
    if len(looks) > MAX_LOOKS:
        errors.append(f"looks: at most {MAX_LOOKS} settings")
    for k, v in looks.items():
        if not LOOK_KEY_RE.match(str(k)):
            errors.append(f"looks.{k}: names are lowercase letters, digits and dashes")
        elif isinstance(v, bool) or isinstance(v, (int, float)):
            continue
        elif not isinstance(v, str):
            errors.append(f"looks.{k}: plain text, number or true/false only")
        elif len(v) > MAX_LOOK_LEN or LOOK_BAD_RE.search(v):
            errors.append(f"looks.{k}: not a plain theme value")


def _check_ui(ui: Any, resources: dict, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(ui, dict):
        errors.append("ui must be an object")
        return
    res = ui.get("resource")
    if not isinstance(res, str) or not RESOURCE_RE.match(res) or ".." in res:
        errors.append("ui.resource must be one .html file inside the package")
    elif not isinstance(resources.get(res), str):
        errors.append(f"ui.resource {res!r} is missing from the package")
    elif len(resources[res].encode("utf-8")) > MAX_RESOURCE_BYTES:
        errors.append(f"ui.resource is larger than {MAX_RESOURCE_BYTES // 1024} KB")
    if ui.get("slot") not in SLOTS:
        errors.append(f"ui.slot must be one of {', '.join(SLOTS)}")
    csp = ui.get("csp", {})
    if not isinstance(csp, dict):
        errors.append("ui.csp must be an object")
        csp = {}
    for key in sorted(set(csp) - set(CSP_KEYS)):
        errors.append(f"ui.csp.{key} is not a known setting")
    for key in CSP_KEYS:
        lst = csp.get(key, [])
        if not isinstance(lst, list):
            errors.append(f"ui.csp.{key} must be a list")
            continue
        for d in lst:
            if not isinstance(d, str) or not ORIGIN_RE.match(d):
                errors.append(f"ui.csp.{key}: bad origin {d!r} (https:// or wss:// only)")
    perms = ui.get("permissions", {})
    if not isinstance(perms, dict):
        errors.append("ui.permissions must be an object")
    else:
        for f in perms:
            if f not in PERMISSION_FEATURES:
                errors.append(f"ui.permissions: unknown feature {f!r}")
        if perms:
            warnings.append("permissions are requests only; Harvis may deny them")
    for key in sorted(set(ui) - {"resource", "slot", "csp", "permissions", "title"}):
        errors.append(f"ui.{key} is not a known setting")


def _check_rules(rules: Any, errors: list[str]) -> None:
    if not isinstance(rules, dict) or not isinstance(rules.get("hooks", []), list):
        errors.append("rules.hooks must be a list")
        return
    hooks = rules.get("hooks", [])
    if len(hooks) > MAX_HOOKS:
        errors.append(f"rules.hooks: at most {MAX_HOOKS}")
    for i, h in enumerate(hooks):
        if not isinstance(h, dict):
            errors.append(f"rules.hooks[{i}] must be an object")
            continue
        ev, act = h.get("event"), h.get("action")
        if ev not in HOOK_EVENTS:
            errors.append(f"rules.hooks[{i}].event must be one of {', '.join(HOOK_EVENTS)}")
        if act not in HOOK_ACTIONS:
            errors.append(f"rules.hooks[{i}].action must be one of {', '.join(HOOK_ACTIONS)}")
        if act == "prepend-context":
            if not isinstance(h.get("text"), str) or not h["text"].strip() or len(h["text"]) > MAX_TEXT:
                errors.append(f"rules.hooks[{i}].text: text up to {MAX_TEXT} characters")
            if ev not in ("PreSend", "SessionStart"):
                errors.append(f"rules.hooks[{i}]: prepend-context runs on PreSend or SessionStart")
        if act in ("require-approval", "block"):
            if ev != "PreToolUse":
                errors.append(f"rules.hooks[{i}]: {act} runs on PreToolUse")
            if not isinstance(h.get("match"), str) or not MATCH_RE.match(h["match"]):
                errors.append(f'rules.hooks[{i}].match must look like "tool:shell*"')
        for key in sorted(set(h) - {"event", "action", "match", "text", "reason"}):
            errors.append(f"rules.hooks[{i}].{key} is not a known setting")
        if "reason" in h and (not isinstance(h["reason"], str) or len(h["reason"]) > 200):
            errors.append(f"rules.hooks[{i}].reason: text up to 200 characters")


def _check_user_config(cfg: Any, errors: list[str]) -> None:
    if not isinstance(cfg, dict):
        errors.append("user_config must be an object")
        return
    for k, v in cfg.items():
        if not isinstance(v, dict) or v.get("type") not in ("string", "number", "boolean"):
            errors.append(f"user_config.{k}.type must be string, number or boolean")


def _not_storable(obj: Any) -> str | None:
    """Postgres jsonb refuses NaN/Infinity, NUL and unpaired surrogates: say so as a 422."""
    try:
        text = json.dumps(obj, allow_nan=False)
        json.dumps(obj, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return "text contains an invalid unicode character"
    except ValueError:
        return "numbers must be finite (no NaN or Infinity)"
    if "\\u0000" in text:
        return "text contains a NUL character"
    return None


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(manifest: dict, resources: dict[str, str]) -> str:
    """sha256 over every byte the server stores for this version."""
    body = canonical({"manifest": manifest, "resources": resources or {}})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def approval_card(manifest: dict, hash_: str, warnings: list[str]) -> dict:
    """What the person sees before saying yes: everything that grants anything."""
    ui = manifest.get("ui") or {}
    return {
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "author": manifest.get("author") or "",
        "description": manifest.get("description") or "",
        "hash": hash_,
        "tiers": tiers_of(manifest),
        "slot": ui.get("slot"),
        "csp": {k: list(ui.get("csp", {}).get(k, [])) for k in CSP_KEYS} if ui else None,
        "permissions": sorted((ui.get("permissions") or {}).keys()) if ui else [],
        "hooks": list((manifest.get("rules") or {}).get("hooks", [])),
        "looks": dict(manifest.get("looks") or {}),
        "warnings": warnings,
    }
