"""Screenshot-to-code prompts — harvested from abi/screenshot-to-code (MIT).

Source: https://github.com/abi/screenshot-to-code
Pinned commit: d026163f586dfa8c5c10d28c36edd59a9d3b0e88
Copyright (c) 2023 Abi Raja

Substantial portions of the replication discipline, stack recipes, and
verify-loop instructions below are adapted from that MIT-licensed project.
Keep this attribution header when copying or modifying this file.

DIVERGENCE FROM UPSTREAM — no CDNs by default. Upstream generates HTML that
pulls Tailwind/React/Babel/Vue from public CDNs. Harvis renders that HTML in a
locked-down preview container with JavaScript disabled and no network at all
(see ``vision_to_code/preview.py`` and the ``preview-runner`` compose service),
because the HTML is model-authored from a user's screenshot and is therefore
untrusted. A CDN-dependent page renders unstyled there, and the verify loop
would then compare an unstyled render against the screenshot and "fix" problems
that only exist because the stylesheet never loaded. So the default stacks are
self-contained: inline CSS, no external requests, no script tags.

Set ``HARVIS_PREVIEW_ALLOW_CDN=1`` to restore the upstream CDN recipes. That
also requires a preview runner with JavaScript and network access — i.e. it
gives up the sandbox, which is why it is off by default.
"""

from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def cdn_allowed() -> bool:
    return (os.getenv("HARVIS_PREVIEW_ALLOW_CDN") or "").strip().lower() in _TRUTHY


# Self-contained recipes — no network load of any kind. These are the default.
SELF_CONTAINED_RECIPES = {
    "html_css": (
        "Use plain HTML + CSS in a single self-contained file. No frameworks, "
        "no <script> tags, no external stylesheets or fonts. Put all styling in "
        "one <style> block in <head>. Prefer semantic tags, CSS grid/flexbox, "
        "and custom properties for the colour palette."
    ),
    "html_tailwind": (
        "Tailwind's CDN build is NOT available in this environment. Write the "
        "equivalent layout as plain HTML + CSS in a single self-contained file: "
        "one <style> block in <head>, no <script> tags, no external requests. "
        "Reproduce Tailwind's spacing and colour scale by hand where it helps."
    ),
    "bootstrap": (
        "Bootstrap's CDN build is NOT available in this environment. Write the "
        "equivalent layout as plain HTML + CSS in a single self-contained file: "
        "one <style> block in <head>, no <script> tags, no external requests."
    ),
    "react": (
        "React and the in-browser JSX transform are NOT available in this "
        "environment, and JavaScript does not run in the preview at all. "
        "Produce the same UI as static, self-contained HTML + CSS in one file. "
        "Represent interactive states (open menu, active tab, hover) as the "
        "single state shown in the screenshot."
    ),
    "vue": (
        "Vue is NOT available in this environment, and JavaScript does not run "
        "in the preview at all. Produce the same UI as static, self-contained "
        "HTML + CSS in one file, showing the state visible in the screenshot."
    ),
    "ionic": (
        "Ionic's CDN build is NOT available in this environment. Reproduce the "
        "mobile-looking UI with plain HTML + CSS in a single self-contained "
        "file. Do not include a device frame or browser chrome around the "
        "content."
    ),
}

# Upstream CDN recipes — only reachable with HARVIS_PREVIEW_ALLOW_CDN=1.
CDN_RECIPES = {
    "html_css": SELF_CONTAINED_RECIPES["html_css"],
    "html_tailwind": (
        "Single-file HTML using Tailwind via CDN:\n"
        '<script src="https://cdn.tailwindcss.com"></script>\n'
        "Use Tailwind utility classes for layout and styling."
    ),
    "bootstrap": (
        "Single-file HTML using Bootstrap 5 via CDN (css + js bundle). Prefer "
        "Bootstrap utility and component classes."
    ),
    "react": (
        "Single-file HTML that loads React 18 + ReactDOM from CDN and "
        "babel-standalone **pinned to 7.25.6** (Babel 8 breaks the in-browser "
        "JSX transform). Put JSX in a <script type=\"text/babel\"> block. "
        "Use Tailwind CDN if the screenshot looks utility-styled."
    ),
    "vue": (
        "Single-file HTML using the Vue 3 global build from CDN. Mount an app "
        "on a root div. Prefer Tailwind CDN when the design is utility-based."
    ),
    "ionic": (
        "Single-file HTML using Ionic via CDN for mobile-looking UIs. Do not "
        "include a device frame or browser chrome around the content."
    ),
}

# Kept for callers that still import the old name.
STACK_RECIPES = SELF_CONTAINED_RECIPES

DEFAULT_STACK = "html_css"
CDN_DEFAULT_STACK = "html_tailwind"


def default_stack() -> str:
    return CDN_DEFAULT_STACK if cdn_allowed() else DEFAULT_STACK


def build_selected_stack_policy(stack: str | None = None) -> str:
    recipes = CDN_RECIPES if cdn_allowed() else SELF_CONTAINED_RECIPES
    fallback = default_stack()
    key = (stack or fallback).strip().lower().replace("-", "_")
    if key in ("tailwind", "html+tailwind", "html_tailwind"):
        key = "html_tailwind"
    if key not in recipes:
        key = fallback
    return f"Selected stack: {key}.\n{recipes[key]}"


REPLICATION_RULES = """
## Screenshot replication discipline
- The result must look exactly like the screenshot.
- Use the exact text from the screenshot — do not invent or paraphrase copy.
- For mobile screenshots, do NOT include the device frame or browser chrome.
- Prefer extracting real visual structure over approximating.
- Multi-screenshot organization: pages → linked pages; tabs → navigation;
  unrelated screens → a scaffold with navigation between them.
- Image generation is DISABLED in this Harvis lane. For missing images use
  provided media, CSS effects (gradients, shapes), or an inline SVG `data:` URI.
  Do NOT link a remote placeholder service — the preview has no network, so a
  remote image renders as a broken box.
""".strip()


VERIFY_LOOP_RULES = """
## Screenshot verify loop (when screenshot_preview is available)
After you create or substantially edit the HTML file:
1. Call screenshot_preview with path pointing at your HTML file (usually index.html).
2. Compare the returned desktop + mobile renders against the user's screenshot.
3. Fix visual problems (broken layout, overlapping elements, wrong spacing/colors)
   with str_replace — Do NOT regenerate the entire file.
4. Cap yourself at 1–2 verify→fix iterations, then call finish.
The preview PNGs are for seeing, not keeping — they are not project artifacts.
""".strip()


SELF_CONTAINED_OUTPUT_RULES = """
## Output contract
- Produce a single self-contained HTML file (prefer index.html).
- No external requests of any kind: no CDN <script>, no remote stylesheet, no
  webfont URL, no remote image. The preview renderer has JavaScript disabled
  and no network access, so anything remote silently does not load.
- Everything visual goes in one <style> block in <head>. Fonts: use CSS font
  stacks that name system faces.
- Prefer str_replace for edits to existing files; use edit_file only to create
  brand-new files.
""".strip()


CDN_OUTPUT_RULES = """
## Output contract
- Produce a single self-contained HTML file (prefer index.html).
- Pull stack libraries from public CDNs as specified by the selected stack.
- This output requires network access for CDN scripts at preview time.
- Prefer str_replace for edits to existing files; use edit_file only to create
  brand-new files.
""".strip()


def build_method_pack_prompt(stack: str | None = None, *, verify_enabled: bool = True) -> str:
    parts = [
        "# Screenshot-to-code method pack",
        REPLICATION_RULES,
        build_selected_stack_policy(stack),
        CDN_OUTPUT_RULES if cdn_allowed() else SELF_CONTAINED_OUTPUT_RULES,
    ]
    if verify_enabled:
        parts.append(VERIFY_LOOP_RULES)
    else:
        parts.append(
            "## Verify loop\n"
            "screenshot_preview is disabled on this deployment "
            "(HARVIS_VISION_SELF_CHECK_ENABLED is off). Produce the best "
            "single-file HTML you can from the screenshot alone, then finish."
        )
    return "\n\n".join(parts)
