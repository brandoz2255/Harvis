"""Adaptive Workspace method packs for the non-fabrication templates
(Generalization Track). Each template gets an honest tool/capability registry
over the same generic ``workspace_method`` primitives, so the Resource Board +
Tool Dock render for EVERY workspace type — the "universal session creator"
made real. Statuses are honest: ready = wired to a real Harvis surface, mock =
labeled placeholder, setup = needs local config, gated = approval-gated, disabled
= off. Higher-lane tools (4-6) additionally require an env flag + approval.
"""

from __future__ import annotations

from .. import workspace_method as wm

T = wm.make_tool


def _feature_plan() -> list:
    return [
        T("repo_recon", "Repo context", purpose="Recon the target codebase via Build (Code mode).",
          lane=wm.LANE_CONTAINER_TERMINAL, status="ready", real=True, output="notes", href="/harvis/vibecode"),
        T("design_notes", "Design notes", purpose="Capture the implementation plan in this space.",
          lane=wm.LANE_UI_MOCK, status="ready", real=True, output="notes"),
        T("build_handoff", "Build handoff", purpose="Run the implementation in Build on an isolated clone.",
          lane=wm.LANE_CONTAINER_TERMINAL, status="ready", real=True, output="run", href="/harvis/vibecode"),
        T("diff_review", "Diff review", purpose="Review the diff before merge.",
          lane=wm.LANE_WORKSPACE_FILES, status="gated", approval=True, output="diff",
          desc="Create-PR stays your outer human gate."),
    ]


def _integration_scaffold() -> list:
    return [
        T("scaffold_build", "Scaffold via Build", purpose="Generate candidate adapter code on an isolated clone.",
          lane=wm.LANE_CONTAINER_TERMINAL, status="ready", real=True, output="code", href="/harvis/vibecode"),
        T("connector", "Connector", purpose="Real connector to the target service/device.",
          lane=wm.LANE_LOCAL_DESKTOP, status="setup", real=False, output="connection",
          desc="Needs local setup — surfaced as manual steps; Web Harvis never touches devices."),
        T("mock_test", "Mock test", purpose="Exercise the candidate against a mock endpoint.",
          lane=wm.LANE_UI_MOCK, status="mock", output="report"),
        T("merge_gate", "Merge gate", purpose="Review-before-merge; never self-installed.",
          lane=wm.LANE_WORKSPACE_FILES, status="gated", approval=True, output="diff"),
    ]


def _research_notebook() -> list:
    return [
        T("notebook", "Notebook", purpose="Sources + grounded chat live in Notebooks.",
          lane=wm.LANE_UI_MOCK, status="ready", real=True, output="notebook", href="/harvis/notebooks"),
        T("findings_notes", "Findings notes", purpose="Capture what you learn here.",
          lane=wm.LANE_UI_MOCK, status="ready", real=True, output="notes"),
        T("report_kinds", "Report kinds", purpose="Briefing / FAQ / study guide via the Notebook Studio.",
          lane=wm.LANE_UI_MOCK, status="ready", real=True, output="report", href="/harvis/notebooks"),
    ]


def _social_post() -> list:
    return [
        T("asset_intake", "Asset intake", purpose="Reference the media as a resource.",
          lane=wm.LANE_WORKSPACE_FILES, status="ready", real=True, inputs=["media"], output="resource"),
        T("caption_drafts", "Caption drafts", purpose="Draft caption options in notes/output.",
          lane=wm.LANE_UI_MOCK, status="ready", real=True, output="text"),
        T("preview", "Preview", purpose="Compose exactly what WOULD publish.",
          lane=wm.LANE_UI_MOCK, status="mock", output="preview"),
        T("publish", "Publish", purpose="Post to the platform.",
          lane=wm.LANE_EXTERNAL_SERVICES, status="gated", approval=True, output="post",
          desc="Mock adapter only — nothing posts, ever, without your approval."),
    ]


def _image_to_3d() -> list:
    return [
        T("image_intake", "Image intake", purpose="Attach the source image as a resource.",
          lane=wm.LANE_WORKSPACE_FILES, status="ready", real=True, inputs=["image"], output="resource"),
        T("generation", "Generation", purpose="Image-to-3D mesh generation on the dev rig.",
          lane=wm.LANE_EXTERNAL_SERVICES, status="gated", approval=True, output="concept mesh",
          desc="Concept asset only — runs when the generation adapter lands (Stage 3)."),
        T("repair_checks", "Repair & checks", purpose="Watertight / manifold checks.",
          lane=wm.LANE_UI_MOCK, status="mock", output="report"),
        T("export", "Export", purpose="Slicer dry-run + export.",
          lane=wm.LANE_WORKSPACE_FILES, status="gated", approval=True, output="file"),
    ]


def _repo_runner() -> list:
    from .. import fab_repo
    run_status = "gated" if fab_repo.repo_run_enabled() else "setup"
    return [
        T("fetch_repo", "Fetch repo", purpose="Clone a public repo into an isolated per-space checkout.",
          lane=wm.LANE_WORKSPACE_FILES, status="ready", real=True, inputs=["repo_url"], output="workspace"),
        T("read_setup", "Read setup", purpose="Read the README + manifests and detect the stack + setup commands.",
          lane=wm.LANE_UI_MOCK, status="ready", real=True, output="report"),
        T("install_deps", "Install deps", purpose="Run the install command inside the sandbox.",
          lane=wm.LANE_CONTAINER_TERMINAL, status=run_status, approval=True, output="terminal",
          desc="Runs in an isolated sandbox — visible and logged. Enable HARVIS_ADAPTIVE_REPO_RUN_ENABLED to activate."),
        T("run_app", "Build & start", purpose="Run build/start in the sandbox and surface a preview.",
          lane=wm.LANE_CONTAINER_TERMINAL, status=run_status, approval=True, output="terminal + preview",
          desc="Sandbox execution — approval-gated."),
        T("app_preview", "App preview", purpose="Preview a dev server the app starts.",
          lane=wm.LANE_LOCAL_DESKTOP, status="disabled", output="iframe",
          desc="Port-forward preview — arrives with the sandbox run wiring."),
    ]


def _ssh_workspace() -> list:
    return [
        T("profile_setup", "Profile setup", purpose="Name the target machine — no connection is made.",
          lane=wm.LANE_LOCAL_DESKTOP, status="setup", real=False, output="profile",
          desc="Placeholder — remote access disabled pending a security review."),
        T("connection", "Connection", purpose="Connect to the remote host.",
          lane=wm.LANE_REAL_HARDWARE, status="disabled", approval=True, output="session",
          desc="No sockets, no SSH libs, no credentials. Disabled."),
    ]


def _image_cues() -> list:
    return [
        {"label": "Likely primary form"},
        {"label": "Likely symmetry axis"},
        {"label": "Likely flat base"},
        {"label": "Likely fine-detail regions"},
        {"label": "Likely overhangs (print risk)"},
    ]


# Register all packs on import.
wm.register_pack("feature-plan", _feature_plan)
wm.register_pack("integration-scaffold", _integration_scaffold)
wm.register_pack("research-notebook", _research_notebook)
wm.register_pack("social-post", _social_post)
wm.register_pack("image-to-3d", _image_to_3d)
wm.register_pack("ssh-workspace", _ssh_workspace)
wm.register_pack("repo-runner", _repo_runner)
wm.register_cues("image-to-3d", _image_cues)
