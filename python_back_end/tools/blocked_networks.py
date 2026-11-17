"""Public networks and domains nothing Harvis fetches may reach (HARVIS_BLOCKED_NETWORKS,
HARVIS_BLOCKED_DOMAINS), e.g. a campus's own address block and domain.

The private-address checks in each fetch path stop the LAN; a school or workplace
often sits on public addresses those checks let through. Every path that turns an
agent's URL into a request (agent_reach, the OpenClaw web proxy) also asks here.
The box proxy (box-egress) and the Kubernetes browser policy read the same settings.

Read on every call, so a changed .env needs only a restart, not a code path.
"""

from __future__ import annotations

import ipaddress
import logging
import os

logger = logging.getLogger(__name__)


def _items(var: str) -> list[str]:
    return [x.strip() for x in (os.getenv(var) or "").split(",") if x.strip()]


def networks() -> list:
    out = []
    for raw in _items("HARVIS_BLOCKED_NETWORKS"):
        try:
            out.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            logger.error("HARVIS_BLOCKED_NETWORKS: %r is not a CIDR range; ignored", raw)
    return out


def ip_blocked(ip: str) -> bool:
    """True when ``ip`` (or the IPv4 inside an IPv6 mapped/6to4 form) is in a blocked range."""
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0].strip("[]"))
    except ValueError:
        return False
    cands = [addr]
    for attr in ("ipv4_mapped", "sixtofour"):
        inner = getattr(addr, attr, None)
        if inner is not None:
            cands.append(inner)
    return any(a.version == n.version and a in n for a in cands for n in networks())


def domain_blocked(host: str) -> bool:
    """True when ``host`` is a blocked domain or under one (``.school.example.edu`` and
    ``school.example.edu`` both block the domain and every subdomain)."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False
    for d in _items("HARVIS_BLOCKED_DOMAINS"):
        d = d.lower().lstrip(".").rstrip(".")
        if d and (h == d or h.endswith("." + d)):
            return True
    return False
