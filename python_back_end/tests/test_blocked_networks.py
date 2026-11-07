"""HARVIS_BLOCKED_NETWORKS / HARVIS_BLOCKED_DOMAINS: public places no agent fetch may reach."""

import pytest

from tools import blocked_networks as bn


@pytest.fixture(autouse=True)
def campus(monkeypatch):
    monkeypatch.setenv("HARVIS_BLOCKED_NETWORKS", "203.0.113.0/24, not-a-cidr")
    monkeypatch.setenv("HARVIS_BLOCKED_DOMAINS", ".school.example.edu")


@pytest.mark.parametrize("ip,blocked", [
    ("203.0.113.198", True), ("203.0.113.1", True), ("::ffff:203.0.113.11", True),
    ("2002:cb00:710b::1", True),  # 6to4 wrapping 203.0.113.11
    ("203.0.114.1", False), ("8.8.8.8", False), ("not an ip", False),
])
def test_ip_ranges(ip, blocked):
    assert bn.ip_blocked(ip) is blocked


@pytest.mark.parametrize("host,blocked", [
    ("school.example.edu", True), ("www.school.example.edu", True), ("MY.SCHOOL.EXAMPLE.EDU.", True),
    ("notschool.example.edu", False), ("school.example.edu.evil.com", False), ("", False),
])
def test_domains(host, blocked):
    assert bn.domain_blocked(host) is blocked


def test_nothing_is_blocked_when_unset(monkeypatch):
    monkeypatch.delenv("HARVIS_BLOCKED_NETWORKS")
    monkeypatch.delenv("HARVIS_BLOCKED_DOMAINS")
    assert not bn.ip_blocked("203.0.113.11") and not bn.domain_blocked("school.example.edu")


def test_agent_fetch_refuses_the_campus():
    from agent_reach import tools as reach

    assert reach._ip_is_public("203.0.113.11") is False
    assert reach._ip_is_public("8.8.8.8") is True
    with pytest.raises(reach.ReachBlocked):
        reach._resolve_public_ips("www.school.example.edu", 443)


def test_openclaw_web_proxy_refuses_the_campus():
    from fastapi import HTTPException
    from tools import openclaw_proxy as op

    assert "blocks" in (op._blocked_reason("203.0.113.11") or "")
    assert op._blocked_reason("8.8.8.8") is None
    for live in (False, True):
        with pytest.raises(HTTPException):
            op._validate_url("https://www.school.example.edu/", live_web=live)
