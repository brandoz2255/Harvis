"""The visual report is served on the app's own origin, so it carries a policy that lets
its own inline script talk to /api/research and nothing else load or send."""
import asyncio
import importlib

research_router = importlib.import_module("deep_research.router")


def test_report_carries_a_policy_that_blocks_outside_scripts_and_sends(monkeypatch):
    monkeypatch.setattr(research_router, "_assert_owns_disk", lambda sid, owner: {})
    monkeypatch.setattr(research_router._handler, "get_report_html", lambda sid: "<html></html>")

    resp = asyncio.run(research_router.research_report("abc-123", {"id": 7}))

    csp = resp.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "connect-src 'self'" in csp
    assert "object-src 'none'" in csp and "base-uri 'none'" in csp
    assert "form-action 'none'" in csp
    assert "frame-ancestors 'self'" in csp
    script_src = next(p for p in csp.split(";") if p.strip().startswith("script-src"))
    assert "http" not in script_src and "*" not in script_src
    assert resp.headers["x-content-type-options"] == "nosniff"
