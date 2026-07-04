"""Pure host-profile validators for the SSH scaffold (Phase 7).

Stdlib-only on purpose: these functions are the security boundary for any value
that could one day reach an SSH command line or config, so they must be
unit-testable without FastAPI/asyncpg installed and importable from anywhere
(tests, the router, a future CLI lane).

Every validator returns ``(ok: bool, reason: str)`` — reason is "" on success
and a short human-readable message on failure (safe to surface in a 400).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Tuple

# Characters that must never appear in a host string. If any of these survive
# into a shell-adjacent context (ssh CLI, scp, rsync, ProxyCommand) they enable
# injection, so we reject them outright rather than trying to escape them.
SHELL_METACHARACTERS = set(";|&$`<>(){}[]!\\\"'*?~#^,")

# RFC 1123 hostname: dot-separated labels of alnum + hyphen, no leading/trailing
# hyphen per label, each label 1-63 chars. (Overall 253-char cap checked separately.)
_HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

# POSIX-ish login name: starts with a letter or underscore, then letters,
# digits, underscore, dot, or hyphen; 1-32 chars total.
_USERNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]{0,31}$")

# Profile display name: 1-64 printable chars, no control characters. Kept
# permissive — it is display-only and never reaches a command line.
_MAX_NAME_LEN = 64

MAX_HOSTNAME_LEN = 253


def validate_host_string(host: object) -> Tuple[bool, str]:
    """Validate a target host: a sane hostname (RFC 1123) or a literal IPv4/IPv6.

    Pure function — no I/O, no DNS lookups. Rejects anything containing shell
    metacharacters, whitespace, control characters, or an embedded scheme /
    userinfo / port (those belong in their own fields, not the host string).
    """
    if not isinstance(host, str):
        return False, "host must be a string"
    if not host or not host.strip():
        return False, "host must not be empty"
    if host != host.strip():
        return False, "host must not have leading or trailing whitespace"
    if len(host) > MAX_HOSTNAME_LEN:
        return False, f"host exceeds {MAX_HOSTNAME_LEN} characters"
    if any(ch.isspace() for ch in host):
        return False, "host must not contain whitespace"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in host):
        return False, "host must not contain control characters"
    if any(ch in SHELL_METACHARACTERS for ch in host):
        return False, "host contains forbidden characters"
    if "://" in host or "@" in host:
        return False, "host must be a bare hostname or IP (no scheme, user, or port)"
    if host.startswith("-"):
        return False, "host must not start with '-' (option-injection guard)"

    # Literal IP address (IPv4 or IPv6)?
    try:
        ipaddress.ip_address(host)
        return True, ""
    except ValueError:
        pass

    # Otherwise require an RFC 1123 hostname. A colon here is neither a valid
    # bare IPv6 literal nor a hostname character (ports go in the port field).
    if ":" in host:
        return False, "host contains ':' but is not a valid IPv6 address"
    candidate = host[:-1] if host.endswith(".") else host  # allow FQDN trailing dot
    labels = candidate.split(".")
    if not labels or any(not _HOSTNAME_LABEL_RE.match(label) for label in labels):
        return False, "host is not a valid hostname or IP address"
    return True, ""


def validate_port(port: object) -> Tuple[bool, str]:
    """Validate a TCP port: an int in 1..65535 (bools are rejected)."""
    if isinstance(port, bool) or not isinstance(port, int):
        return False, "port must be an integer"
    if not 1 <= port <= 65535:
        return False, "port must be between 1 and 65535"
    return True, ""


def validate_username(username: object) -> Tuple[bool, str]:
    """Validate a remote login name (POSIX-ish, 1-32 chars, no metacharacters)."""
    if not isinstance(username, str):
        return False, "username must be a string"
    if not username:
        return False, "username must not be empty"
    if not _USERNAME_RE.match(username):
        return False, "username must match [A-Za-z_][A-Za-z0-9._-]{0,31}"
    return True, ""


def validate_profile_name(name: object) -> Tuple[bool, str]:
    """Validate a profile display name: 1-64 chars, printable, no control chars."""
    if not isinstance(name, str):
        return False, "name must be a string"
    stripped = name.strip()
    if not stripped:
        return False, "name must not be empty"
    if len(stripped) > _MAX_NAME_LEN:
        return False, f"name exceeds {_MAX_NAME_LEN} characters"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in stripped):
        return False, "name must not contain control characters"
    return True, ""
