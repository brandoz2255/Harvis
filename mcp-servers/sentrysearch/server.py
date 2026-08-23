"""SentrySearch MCP stub — video footage search scaffold only.

Enable the compose profile ``sentrysearch`` only after an explicit product yes
for local video search. This process refuses to pretend a full embed pipeline
is ready: it prints status on stdio and idles / exits cleanly.
"""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    video_dir = os.getenv("SENTRYSEARCH_VIDEO_DIR", "/data/videos")
    backend = os.getenv("SENTRYSEARCH_EMBED_BACKEND", "local")
    real = (os.getenv("HARVIS_SENTRYSEARCH_REAL") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    status = {
        "service": "sentrysearch-mcp",
        "ready": False,
        "reason": (
            "Scaffold only — implement MCP tools after product confirms video search. "
            "Do not use upstream OpenClaw Gemini skill path."
            if not real
            else "HARVIS_SENTRYSEARCH_REAL set but no real server wired yet"
        ),
        "video_dir": video_dir,
        "embed_backend": backend,
        "not": "security/CVE/OSINT search",
    }
    print(json.dumps(status), flush=True)
    # Stay up for compose health when profile is enabled, without claiming tools.
    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
