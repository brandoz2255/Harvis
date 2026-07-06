"""Adaptive Workspace — generic method-layer primitives (Stage 1a-method).

These are the FOUNDATION, built generic from day one: the Resource + Tool
schemas, the 6 permission lanes, the lane-enforcement rule, and the linked_run
event contract. Fabrication is just the first *method pack* that consumes them
(``workspace_methods/fabrication.py``) — it never owns them. Build and Notebook
can adopt the same primitives later.

Design rules (locked):
- **6 permission lanes.** Default-allowed = lanes 1-3 (UI/mock, workspace files,
  sandbox terminal) — no flag, no approval. Lanes 4-6 (local desktop, external
  services, real hardware) require BOTH an env flag AND, where flagged, a human
  approval. This is where "never fake success" is enforced structurally.
- **Honest tool status.** Each tool declares what it can do, its lane, and a
  status the UI shows verbatim: ready | mock | setup | gated | disabled. A tool
  is never optimistic about a capability that isn't wired.
- **``mock: true|false`` is mandatory** on every linked_run tool-execution entry
  so a mock can never be mistaken for a real action.

Pure standard library — the backend picks this up on a plain ``docker restart``
(owui_compat is bind-mounted; no new dependency).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# ── The 6 permission lanes ──────────────────────────────────────────────
LANE_UI_MOCK = 1          # placeholders, previews, criteria, plans
LANE_WORKSPACE_FILES = 2  # create/edit files inside an allowed workspace
LANE_CONTAINER_TERMINAL = 3  # commands inside a sandboxed project container
LANE_LOCAL_DESKTOP = 4    # local apps/devices — only after explicit setup
LANE_EXTERNAL_SERVICES = 5  # user-approved APIs / web services
LANE_REAL_HARDWARE = 6    # real-world actions — strong approval gate

# Default-safe ceiling: lanes at or below this need no env flag / approval.
DEFAULT_SAFE_LANE = LANE_CONTAINER_TERMINAL

LANE_LABELS = {
    LANE_UI_MOCK: "UI / mock",
    LANE_WORKSPACE_FILES: "Workspace files",
    LANE_CONTAINER_TERMINAL: "Sandbox terminal",
    LANE_LOCAL_DESKTOP: "Local desktop",
    LANE_EXTERNAL_SERVICES: "External service",
    LANE_REAL_HARDWARE: "Real hardware",
}

# Honest tool statuses the UI renders verbatim.
TOOL_STATUSES = {"ready", "mock", "setup", "gated", "disabled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_tool(
    key: str,
    label: str,
    *,
    purpose: str,
    lane: int,
    status: str,
    inputs: list | None = None,
    real: bool = False,
    approval: bool = False,
    output: str | None = None,
    href: str | None = None,
    desc: str | None = None,
) -> dict:
    """Build one Tool/capability-registry entry. ``status`` must be honest about
    whether the capability is actually wired (see TOOL_STATUSES)."""
    if status not in TOOL_STATUSES:
        status = "disabled"
    return {
        "key": key,
        "label": label,
        "purpose": purpose,
        "lane": lane,
        "lane_label": LANE_LABELS.get(lane, "?"),
        "status": status,
        "inputs": inputs or [],
        "real": bool(real),
        "approval": bool(approval),
        "output": output,
        "href": href,
        "desc": desc,
    }


def make_resource(
    kind: str,
    role: str,
    label: str,
    *,
    id: str | None = None,
    path: str | None = None,
    measured: bool | None = None,
    structural: bool | None = None,
    meta: dict | None = None,
) -> dict:
    """Build one Resource entry (a thing gathered/created/produced for the task).

    ``measured`` and ``structural`` carry the honesty flags: an image reference
    is ``measured=False``; a generated concept mesh is ``structural=False``.
    """
    return {
        "id": id or uuid.uuid4().hex[:12],
        "kind": kind,
        "role": role,
        "label": label,
        "path": path,
        "measured": measured,
        "structural": structural,
        "meta": meta or {},
        "at": _now(),
    }


def tool_can_execute(tool: dict, *, flag_enabled: bool = False, approved: bool = False) -> tuple[bool, str]:
    """The structural 'never fake success' rule. A tool whose lane is above the
    default-safe ceiling cannot execute without BOTH its enabling env flag and,
    when it is approval-gated, a human approval. Disabled tools never run.

    Returns (allowed, reason-if-blocked).
    """
    if tool.get("status") == "disabled":
        return False, "This capability is disabled."
    try:
        lane = int(tool.get("lane", LANE_UI_MOCK))
    except (TypeError, ValueError):
        return False, "Malformed tool lane."  # a safety gate denies on bad input
    if lane <= DEFAULT_SAFE_LANE:
        return True, ""
    if not flag_enabled:
        return False, f"Requires setup — {LANE_LABELS.get(lane, 'higher-lane')} access is not enabled."
    # Real-hardware actions ALWAYS require explicit human approval — enforced here,
    # regardless of whether the tool set approval=True, so the strong gate can never
    # be lost by a pack author forgetting the flag.
    if (tool.get("approval") or lane >= LANE_REAL_HARDWARE) and not approved:
        return False, "Requires explicit human approval."
    return True, ""


def linked_run_entry(kind: str, *, mock: bool, **extra) -> dict:
    """Build a linked_run breadcrumb. ``mock`` is MANDATORY and explicit so a
    mock execution can never be recorded as if it were real."""
    entry = {"kind": kind, "mock": bool(mock), "at": _now()}
    entry.update(extra)
    return entry


# ── Method-pack registry: template_key -> seed function returning tool list ──
# Packs register themselves on import (see workspace_methods/*). adaptive_space
# imports the packs it wants, then calls seed_tools_for().
_TOOL_PACKS: dict[str, object] = {}


def register_pack(template_key: str, seed_tools_fn) -> None:
    _TOOL_PACKS[template_key] = seed_tools_fn


def seed_tools_for(template_key: str) -> list:
    fn = _TOOL_PACKS.get(template_key)
    try:
        return list(fn()) if fn else []
    except Exception:
        return []


def has_pack(template_key: str) -> bool:
    return template_key in _TOOL_PACKS


def shape_manifest_method(manifest: dict, template_key: str) -> dict:
    """Idempotently give a manifest its method-layer shape for the response:
    a freshly-seeded ``tools`` list (derived data — regenerated each read so
    statuses stay honest) and a ``resources`` list that surfaces gathered inputs
    and produced outputs on top of any persisted resources (uploads etc.).

    Does NOT persist — this only shapes the in-memory dict returned to the client,
    so v1 rows transparently read as v2 with no migration write.
    """
    if not isinstance(manifest, dict):
        return manifest

    manifest["method_version"] = 2
    manifest["tools"] = seed_tools_for(template_key)
    manifest["resources"] = _derive_resources(manifest)
    return manifest


def _derive_resources(manifest: dict) -> list:
    """Persisted resources + honest derived ones (criteria gathered, outputs).

    Type-guarded so a hand-edited or future-migrated manifest with a non-list
    ``resources`` or non-dict ``meta``/``analysis`` degrades rather than crashes.
    """
    existing = manifest.get("resources")
    resources = list(existing) if isinstance(existing, list) else []
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}

    crit_keys = [k for k in meta if k.startswith("crit_") and not k.endswith("_src")]
    if crit_keys:
        resources.append(
            make_resource(
                "criteria",
                "input",
                f"{len(crit_keys)} criteria gathered",
                meta={"keys": crit_keys},
            )
        )

    analysis = manifest.get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    if analysis.get("ok"):
        # An analytical ESTIMATE — never a certified structural artifact. We do NOT
        # set structural=True here (the green 'structural' badge is reserved for real
        # geometry); the UI shows an honest 'analytical' badge for the analysis kind.
        resources.append(
            make_resource(
                "analysis",
                "output",
                "Stress analysis (analytical)",
                meta={
                    "basis": "first-order closed-form",
                    "certified": False,
                    "verdict_code": analysis.get("verdict_code"),
                    "model": analysis.get("model"),
                },
            )
        )
    return resources
