"""Remote-device access (Phase 7 — SCAFFOLD, flagged OFF).

SSH connection-profile storage for future remote device + folder access. The
scaffold ships with NO working SSH I/O of any kind:

  * Every endpoint is gated on the ``HARVIS_SSH_ENABLED`` env flag — absent/0
    (the default) returns 403 "SSH access is disabled pending security review".
  * The connect/test endpoint is ADDITIONALLY stubbed: even with the flag on it
    returns 501 — no SSH client library (paramiko/asyncssh) is imported anywhere.

Credentials follow the owui_compat/engine_auth.py pattern exactly: Fernet-
encrypted via main.encrypt_api_key, write-only at the API (GET returns only a
``has_credential`` bool), decrypted only by a future, user-approved runtime.

Modules:
  validation  — pure-stdlib host/port/username validators (unit-testable, no deps)
  ssh_manager — FastAPI router: CRUD for user_ssh_hosts + stubbed test endpoint

NOTE: this package intentionally has no eager imports so ``remote.validation``
stays importable without FastAPI installed (used by the unit tests).
"""

__all__ = ["validation", "ssh_manager"]
