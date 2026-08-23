"""Credential adapter for MCP server environments.

Every MCP server is configured the same way — a launcher command plus a set of
environment variables — and most of the ones worth connecting (GitHub, Slack,
Notion, Higgsfield) carry an API key in that environment. `mcp_servers.env` is
plain JSONB, so the connections wizard refused to collect secret fields at all
("credential storage pending review") and every secret-bearing server was
therefore unusable: it saved fine and failed at spawn with no key.

This module is the missing layer. It seals secret values with the same Fernet
cipher every other Harvis credential already uses (`main.encrypt_api_key`,
derived from JWT_SECRET), stores them inline in the existing `env` column under
a marked wrapper, and unseals them at exactly one place — the moment the runtime
builds the sandbox container's environment. It is transport- and
vendor-agnostic on purpose: any server that reads an env var works, with no
per-vendor code.

Two rules hold the design together:

* **Sealed at rest, everywhere but the spawn.** `McpServerConfig.env` carries
  the sealed shape unchanged through the registry, so a config that is read and
  written back can never downgrade a secret to plaintext. Only
  `runtime._spawn_container` calls `unseal_env`.
* **A saved secret never travels back to a browser.** The API read path calls
  `mask_env`, and a re-save that omits a key keeps the stored one
  (`merge_env`), so editing a connection does not require retyping every token.
"""

from __future__ import annotations

import logging
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)

# Marker key of the sealed wrapper. Long and namespaced so it can never collide
# with a real environment value a server might legitimately want.
SEALED = "__harvis_enc__"

MASK = "••••••••"


def is_sealed(value) -> bool:
    return isinstance(value, Mapping) and SEALED in value


def seal(value: str) -> dict:
    """Wrap a plaintext secret for storage. Never logs the value."""
    from main import encrypt_api_key  # lazy: plugins must import without main

    return {SEALED: encrypt_api_key(str(value))}


def unseal(value) -> str:
    """Plaintext for a sealed wrapper; the value itself when it is already plain.

    Returns "" for a wrapper that cannot be decrypted — a rotated JWT_SECRET
    invalidates every stored credential, and handing the server an empty
    variable fails loudly at the vendor instead of silently half-working.
    """
    if not is_sealed(value):
        return "" if value is None else str(value)
    from main import decrypt_api_key

    plain = decrypt_api_key(str(value.get(SEALED) or ""))
    if not plain:
        logger.warning("mcp: a stored credential could not be decrypted (key rotated?)")
    return plain


def seal_env(plain: Mapping[str, str]) -> dict:
    """Seal every value in a credentials payload. Blank values are dropped."""
    out: dict = {}
    for k, v in (plain or {}).items():
        if v is None or str(v).strip() == "":
            continue
        out[str(k)] = v if is_sealed(v) else seal(str(v))
    return out


def unseal_env(env: Mapping) -> dict:
    """Plaintext environment for the sandbox container. The ONLY read path."""
    return {str(k): unseal(v) for k, v in (env or {}).items()}


def mask_env(env: Mapping) -> dict:
    """What the API returns: sealed values become a fixed mask, never a length."""
    return {str(k): (MASK if is_sealed(v) else v) for k, v in (env or {}).items()}


def sealed_keys(env: Mapping) -> list[str]:
    """Names of the variables that hold a stored secret, for UI status."""
    return sorted(str(k) for k, v in (env or {}).items() if is_sealed(v))


def merge_env(
    existing: Mapping,
    *,
    env: Mapping | None = None,
    credentials: Mapping | None = None,
    drop: Iterable[str] | None = None,
) -> dict:
    """Build the env to store from a save request.

    ``env`` is plain, non-secret configuration and replaces what was there.
    ``credentials`` is sealed on the way in. A credential the client omits — or
    sends back as the mask — keeps its stored value, which is what lets the user
    edit a connection's command without retyping its token. ``drop`` removes a
    stored credential outright.
    """
    merged: dict = {}

    # Carry forward only the sealed entries; plain config is fully replaced by
    # `env` so removing a variable in the UI actually removes it.
    for k, v in (existing or {}).items():
        if is_sealed(v):
            merged[str(k)] = v

    for k, v in (env or {}).items():
        merged[str(k)] = v

    for k, v in (credentials or {}).items():
        key = str(k)
        if v is None or str(v).strip() == "" or str(v) == MASK:
            continue  # untouched field — keep whatever is stored
        merged[key] = seal(str(v))

    for k in drop or ():
        merged.pop(str(k), None)

    return merged
