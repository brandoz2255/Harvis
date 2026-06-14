"""P5.2 smoke — profiles load + ModelRouter reaches a live model via _resolve_route.

    docker cp python_back_end/tests/test_orchestration_modelrouter.py harvis-backend:/tmp/tr.py
    docker exec -e PYTHONPATH=/app harvis-backend python3 /tmp/tr.py
"""

import asyncio

from workspace.orchestration.model_router import ModelRouter
from workspace.orchestration.profiles import AGENT_PROFILES, get_profile


async def main() -> None:
    assert "orchestrator" in AGENT_PROFILES and "testing" in AGENT_PROFILES
    p = get_profile("testing")
    print("profile testing ->", p["display_name"], p["model_name"], p["approval_policy"])
    print("profile unknown ->", get_profile("nope")["display_name"], "(fallback)")

    r = ModelRouter()
    msg = await r.complete(
        model_name="gemma4:e2b",
        messages=[{"role": "user", "content": "Reply with exactly the word: PONG"}],
        timeout=120.0,
    )
    content = (msg.get("content") or "").strip()
    print("router content:", content[:80])
    print("RESULT:", "PASS" if content else "FAIL (empty completion)")
    if not content:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
