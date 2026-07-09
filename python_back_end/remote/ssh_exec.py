"""SSH execution engine (Execution Core Phase 4, lane 5).

This is the ONLY module in the codebase that opens an SSH connection, and it
does so exclusively through the **system ``ssh`` binary** invoked with an argv
LIST (``asyncio.create_subprocess_exec`` — never ``shell=True``, never string
concatenation). The security posture:

  * ``StrictHostKeyChecking=yes`` against a **pinned per-user known_hosts file**.
    An unknown or CHANGED host key is a HARD FAIL — ssh exits non-zero and we
    surface the error. There is no accept-new, no StrictHostKeyChecking=no.
  * ``BatchMode=yes`` — never prompt (no interactive password / passphrase). A
    profile that would need a prompt fails fast instead of hanging.
  * host / port / username come ONLY from a validated stored profile (the caller
    runs them through ``remote/validation.py``). The ssh OPTIONS are terminated
    with ``--`` before ``user@host`` and the remote command, so a hostile value
    can never be reinterpreted as an ssh flag.
  * The remote command is passed as a SINGLE argv element. ssh hands it to the
    remote login shell — that is the expected SSH contract; we do NOT wrap it in
    a local shell, so no local shell ever parses it.

State: per-user known_hosts lives at ``<HARVIS_SSH_STATE_DIR>/<user_id>/known_hosts``
(dir 0700, file 0600). Stored-secret private keys are decrypted to a 0600 temp
file only for the duration of one connection and deleted in a ``finally``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import stat
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


async def _read_capped(stream, cap: int) -> bytes:
    """Read at most cap+1 bytes from a stream then stop. Stopping applies pipe
    backpressure to ssh (it blocks writing more), so a runaway/hostile remote host
    can never make us buffer unbounded output. A returned length of cap+1 signals
    'there was more' (truncation)."""
    if stream is None:
        return b""
    buf = b""
    while len(buf) <= cap:
        chunk = await stream.read(cap + 1 - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def host_ssrf_block_reason(host: str) -> Optional[str]:
    """Reject SSH probe/exec against loopback + link-local targets (incl. the cloud
    metadata IP 169.254.169.254) — never a legitimate remote device and a classic
    SSRF pivot. RFC-1918 PRIVATE ranges are ALLOWED on purpose: registering a LAN
    device (GPU box, printer Pi, NAS) is the whole point of the SSH lane."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None  # unresolvable — ssh-keyscan will just fail; not an SSRF concern
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            return (f"{host} resolves to a blocked address ({ip}); loopback/link-local "
                    "targets are not allowed")
    return None

# Root for per-user known_hosts + (optional) key material. Overridable so the
# container can point it at a writable named volume (compose sets /data/ssh_state).
STATE_DIR = os.getenv("HARVIS_SSH_STATE_DIR", "/app/ssh_state")
# Directory that may hold `key_file`-auth private keys (operator-provisioned).
KEYS_DIR = os.getenv("HARVIS_SSH_KEYS_DIR", os.path.join(STATE_DIR, "keys"))

_OUTPUT_CAP_BYTES = int(os.getenv("HARVIS_SSH_OUTPUT_CAP", "65536"))
_CONNECT_TIMEOUT_S = int(os.getenv("HARVIS_SSH_CONNECT_TIMEOUT_S", "10"))
_KEYSCAN_TIMEOUT_S = int(os.getenv("HARVIS_SSH_KEYSCAN_TIMEOUT_S", "10"))

VALID_AUTH_METHODS = {"agent", "key_file", "stored_secret", "manual"}


# ─── known_hosts / state paths ────────────────────────────────────────────────


def _user_state_dir(user_id: int) -> str:
    """<state>/<user_id>, created 0700. Never accepts a non-int user id."""
    path = os.path.join(STATE_DIR, str(int(user_id)))
    os.makedirs(path, mode=0o700, exist_ok=True)
    # makedirs honors mode only for the leaf it creates; enforce it explicitly.
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def known_hosts_path(user_id: int) -> str:
    """Absolute path to this user's pinned known_hosts file (touched 0600)."""
    path = os.path.join(_user_state_dir(user_id), "known_hosts")
    if not os.path.exists(path):
        # Create empty 0600 so ssh has a file to read even before first trust.
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def append_known_hosts(user_id: int, known_hosts_line: str) -> None:
    """Append scanned host-key line(s) to the per-user pinned known_hosts.

    De-dupes exact lines so repeated trusts don't bloat the file. Called ONLY
    from the /trust approve path after a human approves the fingerprint.
    """
    path = known_hosts_path(user_id)
    new_lines = [ln for ln in (known_hosts_line or "").splitlines() if ln.strip() and not ln.startswith("#")]
    if not new_lines:
        return
    existing: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            existing = {ln.rstrip("\n") for ln in fh}
    except FileNotFoundError:
        pass
    to_add = [ln for ln in new_lines if ln not in existing]
    if not to_add:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for ln in to_add:
            fh.write(ln + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ─── ssh argv construction (LIST, never a shell string) ───────────────────────


def build_ssh_argv(
    profile: dict,
    command: str,
    *,
    known_hosts: str,
    identity: Optional[str] = None,
    jump: Optional[dict] = None,
) -> list[str]:
    """Build the ssh argv as a list.

    host / username / port MUST be pre-validated by remote.validation. Options
    are terminated with ``--`` before ``user@host`` and the single command
    element so nothing user-derived can be read as an ssh flag.
    """
    host = str(profile["host"])
    username = str(profile["username"])
    port = int(profile["port"])

    argv: list[str] = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", f"ConnectTimeout={_CONNECT_TIMEOUT_S}",
    ]
    # IdentitiesOnly only when we hand ssh a specific key — for agent auth we
    # must NOT set it (it would stop ssh from offering the agent's identities).
    if identity:
        argv += ["-o", "IdentitiesOnly=yes"]
    argv += ["-p", str(port)]
    if jump:
        # NOTE (v0): jump hosts are NOT wired yet — jump_host_id is never persisted, so
        # this branch is unreachable in v0. When ProxyJump lands (v1), the jump hop's
        # host key is NOT covered by the destination -o UserKnownHostsFile/StrictHostKeyChecking
        # above; it must get its own pinned known_hosts (it fails closed under BatchMode
        # meanwhile, so an unknown jump key is refused, never accepted).
        juser = str(jump["username"])
        jhost = str(jump["host"])
        jport = int(jump.get("port", 22))
        argv += ["-J", f"{juser}@{jhost}:{jport}"]
    if identity:
        argv += ["-i", identity]
    argv += ["--", f"{username}@{host}", command]
    return argv


def _resolve_key_file(profile: dict) -> str:
    """Resolve a `key_file`-auth identity path, confined to KEYS_DIR.

    The profile carries a `key_path` relative to KEYS_DIR; we realpath it and
    refuse anything that escapes the keys dir (traversal guard).
    """
    rel = str(profile.get("key_path") or "").strip()
    if not rel:
        raise ValueError("auth_method 'key_file' requires a key_path")
    base = os.path.realpath(KEYS_DIR)
    candidate = os.path.realpath(os.path.join(base, rel))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise ValueError("key_path escapes the configured keys dir")
    if not os.path.isfile(candidate):
        raise ValueError("configured key file does not exist")
    return candidate


def _write_temp_key(secret: str) -> str:
    """Write a decrypted private key to a fresh 0600 temp file; caller deletes."""
    fd, path = tempfile.mkstemp(prefix="ssh_key_", dir=_ensure_tmp_dir())
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        data = secret if secret.endswith("\n") else secret + "\n"
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    return path


def _ensure_tmp_dir() -> str:
    d = os.path.join(STATE_DIR, "tmp")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


# ─── host-key probe (ssh-keyscan + ssh-keygen fingerprint) ────────────────────


async def keyscan(host: str, port: int, *, timeout: int = _KEYSCAN_TIMEOUT_S) -> tuple[str, list[str]]:
    """Scan a host's public key(s) and compute SHA256 fingerprints.

    Returns ``(known_hosts_line, [fingerprints])`` — the raw (unhashed)
    known_hosts text for pinning, and the human-verifiable SHA256 fingerprints.
    Both are UNTRUSTED: the caller must present them for human approval and only
    persist them via the /trust path. host/port are pre-validated by the caller.
    """
    blocked = host_ssrf_block_reason(host)
    if blocked:
        raise PermissionError(blocked)
    argv = ["ssh-keyscan", "-T", str(int(timeout)), "-p", str(int(port)), host]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, _err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError("ssh-keyscan timed out")

    scan_out = (out_b or b"").decode("utf-8", errors="replace")
    lines = [ln for ln in scan_out.splitlines() if ln.strip() and not ln.startswith("#")]
    known_hosts_line = "\n".join(lines)
    if not lines:
        return "", []

    # Fingerprint each key by feeding the scanned lines to `ssh-keygen -lf`.
    fps: list[str] = []
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="keyscan_", dir=_ensure_tmp_dir())
        os.write(fd, (known_hosts_line + "\n").encode("utf-8"))
        os.close(fd)
        kg = await asyncio.create_subprocess_exec(
            "ssh-keygen", "-l", "-f", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        kg_out_b, _ = await asyncio.wait_for(kg.communicate(), timeout=10)
        for ln in (kg_out_b or b"").decode("utf-8", errors="replace").splitlines():
            # Format: "<bits> SHA256:<b64> <host> (<TYPE>)"
            for tok in ln.split():
                if tok.startswith("SHA256:") or tok.startswith("MD5:"):
                    fps.append(tok)
                    break
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return known_hosts_line, fps


# ─── run one command over ssh ─────────────────────────────────────────────────


async def run_ssh(
    profile: dict,
    command: str,
    *,
    user_id: int,
    timeout: int = 60,
) -> dict:
    """Execute one command on a trusted host over ssh.

    ``profile`` is a plain dict (host/port/username pre-validated) that also
    carries ``auth_method`` and, per method, the material to authenticate:
      * 'agent'         — rely on SSH_AUTH_SOCK from the process env (no -i).
      * 'key_file'      — profile['key_path'] resolved under KEYS_DIR, -i it.
      * 'stored_secret' — decrypt profile['credential_encrypted'] to a 0600 temp
                          file, -i it, delete in finally.
      * 'manual'        — REJECTED in v0 (BatchMode forbids interactive password).

    Returns {exit_code, stdout, stderr, truncated}. Never raises for a routine
    connection failure — a bad host key / auth error comes back as a non-zero
    exit_code with ssh's stderr, so the trace records the honest outcome.
    """
    if not command or not str(command).strip():
        return {"exit_code": -1, "stdout": "", "stderr": "empty command", "truncated": False}

    blocked = host_ssrf_block_reason(str(profile.get("host") or ""))
    if blocked:
        return {"exit_code": -1, "stdout": "", "stderr": blocked, "truncated": False}

    auth = str(profile.get("auth_method") or "agent").strip().lower()
    if auth not in VALID_AUTH_METHODS:
        return {"exit_code": -1, "stdout": "", "stderr": f"unknown auth_method '{auth}'", "truncated": False}
    if auth == "manual":
        return {
            "exit_code": -1, "stdout": "",
            "stderr": "auth_method 'manual' (interactive password) is not supported in v0 — BatchMode is enforced.",
            "truncated": False,
        }

    kh = known_hosts_path(user_id)
    env = os.environ.copy()
    identity: Optional[str] = None
    tmp_key: Optional[str] = None

    try:
        if auth == "key_file":
            identity = _resolve_key_file(profile)
        elif auth == "stored_secret":
            enc = profile.get("credential_encrypted")
            if not enc:
                return {"exit_code": -1, "stdout": "", "stderr": "profile has no stored secret", "truncated": False}
            # Decrypt ONLY here (the approved runtime); ssh_manager never decrypts.
            from main import decrypt_api_key

            secret = decrypt_api_key(enc)
            if not secret:
                return {"exit_code": -1, "stdout": "", "stderr": "failed to decrypt stored secret", "truncated": False}
            tmp_key = _write_temp_key(secret)
            identity = tmp_key
        # auth == 'agent': leave identity None, keep SSH_AUTH_SOCK in env.

        argv = build_ssh_argv(
            profile, command, known_hosts=kh, identity=identity, jump=profile.get("jump"),
        )
        logger.info("ssh.exec user=%s host=%s port=%s auth=%s", user_id, profile.get("host"), profile.get("port"), auth)

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            # Bounded read: each stream reads at most CAP+1 bytes then stops, which
            # applies backpressure to ssh (its pipe fills and it blocks) — so a hostile
            # or runaway remote host can never exhaust backend memory, unlike
            # communicate() which buffers the whole output first.
            out_b, err_b = await asyncio.wait_for(
                asyncio.gather(
                    _read_capped(proc.stdout, _OUTPUT_CAP_BYTES),
                    _read_capped(proc.stderr, _OUTPUT_CAP_BYTES),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except Exception:
                pass
            return {
                "exit_code": -1, "stdout": "",
                "stderr": f"ssh command timed out after {timeout}s", "truncated": False,
            }

        # If either stream hit the cap there was more; kill ssh so it stops streaming.
        over = len(out_b) > _OUTPUT_CAP_BYTES or len(err_b) > _OUTPUT_CAP_BYTES
        if over and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass

        exit_code = proc.returncode if proc.returncode is not None else -1
        stdout = out_b[:_OUTPUT_CAP_BYTES].decode("utf-8", errors="replace")
        stderr = err_b[:_OUTPUT_CAP_BYTES].decode("utf-8", errors="replace")
        if len(out_b) > _OUTPUT_CAP_BYTES:
            stdout += f"\n…[stdout truncated at {_OUTPUT_CAP_BYTES} bytes]"
        if len(err_b) > _OUTPUT_CAP_BYTES:
            stderr += f"\n…[stderr truncated at {_OUTPUT_CAP_BYTES} bytes]"
        return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "truncated": over}
    finally:
        if tmp_key:
            try:
                os.unlink(tmp_key)
            except OSError:
                pass
