"""Fabrication method pack — the FIRST consumer of the generic workspace-method
primitives (Stage 1a-method).

It declares the fabrication lane's tool/capability registry with HONEST statuses
that also map the staged roadmap: what is real today (closed-form stress), what
is a mock (concept preview), what needs setup (image reference — Stage 1b), and
what is gated/disabled behind later stages (build123d geometry, generation,
export, slice, print). The status a tool shows is the truth about whether that
capability is actually wired — never optimistic.
"""

from __future__ import annotations

from .. import workspace_method as wm
from .. import fab_cad


def seed_tools() -> list:
    return [
        wm.make_tool(
            "closed_form_stress",
            "Closed-form stress",
            purpose="First-order cantilever + bolt-group estimate (sigma, safety factor).",
            lane=wm.LANE_UI_MOCK,
            status="ready",
            real=True,
            inputs=["load", "geometry", "material"],
            output="analysis",
            desc="Real analytical numbers — not FEA. Runs on the assumed criteria.",
        ),
        wm.make_tool(
            "concept_preview",
            "Concept preview",
            purpose="Rotatable 3D concept of the part with an illustrative stress overlay.",
            lane=wm.LANE_UI_MOCK,
            status="mock",
            real=False,
            output="viewer",
            desc="Mock geometry (procedural). Stage 2 replaces it with real parametric CAD.",
        ),
        wm.make_tool(
            "image_reference",
            "Image reference",
            purpose="Attach a photo as a visual reference (never a measurement).",
            lane=wm.LANE_WORKSPACE_FILES,
            status="ready",
            real=True,
            inputs=["image"],
            output="resource",
            desc="Reference only — the image is stored and shown, never measured or fed to the analysis.",
        ),
        wm.make_tool(
            "cad_build123d",
            "Parametric CAD (build123d)",
            purpose="Generate real BREP geometry from a named-parameter recipe.",
            lane=wm.LANE_CONTAINER_TERMINAL,
            status=fab_cad.cad_status(),
            real=fab_cad.cad_enabled(),
            inputs=["recipe", "params"],
            output="mesh + STEP",
            desc="Real parametric geometry via the isolated build123d CAD engine."
            if fab_cad.cad_enabled()
            else "Enable the CAD engine (HARVIS_ADAPTIVE_CAD_ENABLED + cad-engine sidecar) to build real geometry.",
        ),
        wm.make_tool(
            "generate_mesh",
            "Concept mesh generation",
            purpose="Turn an image into a concept mesh (TripoSR / ComfyUI / Meshy).",
            lane=wm.LANE_EXTERNAL_SERVICES,
            status="gated",
            real=False,
            approval=True,
            inputs=["image"],
            output="concept mesh",
            desc="Concept asset only — never a structural source of truth. Stage 3.",
        ),
        wm.make_tool(
            "export_stl",
            "Export STL",
            purpose="Export the part as an STL/STEP file.",
            lane=wm.LANE_WORKSPACE_FILES,
            status="gated",
            real=False,
            approval=True,
            output="file",
            desc="Approval-gated. Stage 4.",
        ),
        wm.make_tool(
            "slice_gcode",
            "Slice to G-code",
            purpose="Slice the mesh to G-code with a time/filament estimate.",
            lane=wm.LANE_CONTAINER_TERMINAL,
            status="gated",
            real=False,
            approval=True,
            output="gcode",
            desc="Runs a slicer in an isolated sidecar. Approval-gated. Stage 4.",
        ),
        wm.make_tool(
            "print",
            "Send to printer",
            purpose="Upload G-code to a real printer and start a print.",
            lane=wm.LANE_REAL_HARDWARE,
            status="gated",
            real=False,
            approval=True,
            output="physical part",
            desc="Real-hardware action — pending a security review. Local/CLI lane only. Stage 5.",
        ),
    ]


def visual_cues() -> list:
    """What Harvis would ESTIMATE from a reference photo of a hanger/bracket —
    honest placeholders (not real computer vision, never measurements). The panel
    structure is the contract a future vision model fills in."""
    return [
        {"label": "Likely wall plate"},
        {"label": "Likely support arm"},
        {"label": "Likely mounting points"},
        {"label": "Likely load direction"},
        {"label": "Likely stress zone"},
    ]


# Register on import.
wm.register_pack("fabrication", seed_tools)
wm.register_cues("fabrication", visual_cues)

