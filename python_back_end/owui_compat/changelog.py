"""Harvis release notes, served at ``GET /api/changelog``.

OWUI's ``ChangelogModal`` ("What's New in Harvis") pops for admins whenever
``/api/config``'s ``version`` differs from the version stored in their user
settings, then fetches this route for the body. The facade never implemented it,
so the modal has been opening empty — which is why a version bump has to land
together with the notes for that version, not before them.

The notes live here as data rather than as a parsed ``CHANGELOG.md`` on purpose.
``front_end/owui/CHANGELOG.md`` is upstream Open WebUI's file, still carrying
open-webui's own version line (0.9.5) and its PR links; writing Harvis entries
into it would mislabel whose changes they are. Harvis's version is
``HARVIS_OWUI_VERSION`` in ``config.py`` — the one ``/api/config`` reports and
the one Settings → About shows.

Shape matches what the modal renders: ``{version: {date, <section>: [{raw}]}}``.
Sections are lowercase (``added`` / ``fixed`` / ``changed``) because the modal
colour-codes on those exact strings. ``raw`` is HTML — it is rendered through
DOMPurify, so keep it to plain inline markup written here in source, never text
that came from a user or a model.

Newest first: ``dict`` preserves insertion order and the modal iterates keys.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter


def _entries(*items: str) -> list[dict]:
    return [{"raw": item} for item in items]


CHANGELOG: dict[str, dict] = {
    "0.2.0": {
        "date": "2026-08-29",
        "added": _entries(
            "<strong>The Build tab writes real projects, not one giant file.</strong> "
            "Ask for a web page and you get the files a person would actually write — "
            "<code>index.html</code> for markup, <code>styles.css</code> for styling, one or more "
            "<code>.js</code> files for behaviour — instead of a 900-line HTML file with everything "
            "inlined. Plain ES modules work too.",
            "<strong>A file list on every Build turn.</strong> Each reply now shows the files that "
            "turn created or changed, so you can see what was written without digging through the "
            "tool log.",
            "<strong>Preview runs multi-file projects.</strong> The preview folds a project's "
            "stylesheets, scripts and ES modules into the sandboxed frame, so a page split across "
            "files renders and runs the same way it does when served. A file the page asks for that "
            "does not exist is named in the preview instead of silently leaving a blank frame.",
            "<strong>Build and chat share one model picker.</strong> The Build tab now uses the same "
            "two-level picker as the main chat, including the reasoning-effort options that appear "
            "when you hover a model that supports them.",
            "<strong>Build reads its answers aloud.</strong> The speak control from the main chat "
            "works in the Build tab.",
            "<strong>Side-panel runs show their state.</strong> A build started from the side rail "
            "shows that it is working, names itself even if you switch away mid-run, and marks "
            "itself with a blue dot when it finishes — the same as the main chat.",
        ),
        "fixed": _entries(
            "<strong>A page that cannot run is no longer reported as a success.</strong> Generated "
            "projects are checked for broken syntax and for files the page links to but never wrote. "
            "When something is wrong the model gets one round to repair it, and if it still does not "
            "hold together the turn says so rather than handing you a blank page.",
            "<strong>Opening one Build chat no longer takes over another.</strong> Switching between "
            "Build sessions kept the previous session's state and could write it into the one you "
            "just opened.",
            "<strong>The token meter told the truth.</strong> It was showing a run's cumulative "
            "billed input as if it were context occupancy, which pinned the bar full and red on "
            "perfectly healthy runs. It now shows how full the context window actually is.",
            "<strong>Claude Sonnet 5 and Fable 5 report their real context window.</strong> Both have "
            "1M-token windows; the model table listed every Claude at 200K, so the meter divided by a "
            "number five times too small.",
            "<strong>The model picker no longer swallows your next click.</strong> Opening the picker "
            "and then clicking the message box now closes the picker and puts the cursor in the box.",
            "<strong>A build that produced nothing stops saying \"working\".</strong> It used to sit "
            "on the spinner forever with no further output.",
            "<strong>Long turns shrink their own context.</strong> Older tool output is condensed "
            "during a turn instead of running the conversation into the model's limit mid-build.",
            "<strong>Activity labels say what is happening.</strong> Steps read as the edit or command "
            "they actually are rather than \"using bash\".",
        ),
        "changed": _entries(
            "<strong>Claude Code decides its own compaction point.</strong> Harvis no longer pins a "
            "compaction window on the Claude lane — the CLI's per-model default is the recommended "
            "setting, and overriding it was capping a 1M-token model at 200K for no reason.",
            "<strong>Run and preview a page from the Build tab.</strong> Code written in Harvis now "
            "runs in Harvis, served from the session's own sandbox.",
            "<strong>Web search repairs its own query.</strong> A search that comes back with nothing "
            "useful is rewritten and retried instead of giving up after one attempt.",
            "<strong>Light mode is readable.</strong> Logos, marks and low-contrast text across the "
            "Engines and Integrations pages were drawn for a dark sidebar and stayed dark on white.",
            "<strong>The signup toggle works.</strong> Settings → General's \"Enable New Sign Ups\" "
            "was posting to a route that did not exist, so turning signup off did nothing.",
        ),
    },
}


def register_changelog_routes(router: APIRouter, get_current_user: Callable) -> None:
    """Unauthenticated by design — OWUI's client fetches this without a token,
    and release notes are not privileged. ``get_current_user`` is accepted only
    to match the house registration signature."""

    @router.get("/api/changelog")
    async def owui_changelog():
        return CHANGELOG
