"""Secret handling must not silently orphan encrypted data or sessions."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def run(code, **settings):
    env = os.environ.copy()
    for name in ("JWT_SECRET", "API_KEY_ENCRYPTION_SECRET", "HARVIS_ALLOW_EPHEMERAL_JWT_SECRET", "HARVIS_EXPOSURE", "HARVIS_BIND_ADDR_PUBLIC", "KUBERNETES_SERVICE_HOST"):
        env.pop(name, None)
    env.update(settings)
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, text=True, capture_output=True)


def test_missing_secret_fails_closed_by_default():
    result = run("from jwt_secret import get_jwt_secret; get_jwt_secret()")
    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr


@pytest.mark.parametrize("settings", [
    {"HARVIS_EXPOSURE": "lan"},
    {"HARVIS_BIND_ADDR_PUBLIC": "0.0.0.0"},
    {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
])
def test_ephemeral_opt_in_cannot_override_shared_deployment(settings):
    result = run("from jwt_secret import get_jwt_secret; get_jwt_secret()", HARVIS_ALLOW_EPHEMERAL_JWT_SECRET="1", **settings)
    assert result.returncode != 0


def test_explicit_local_ephemeral_is_process_cached():
    result = run("from jwt_secret import get_jwt_secret; assert get_jwt_secret() == get_jwt_secret()", HARVIS_ALLOW_EPHEMERAL_JWT_SECRET="1")
    assert result.returncode == 0, result.stderr


def test_configured_secret_survives_process_restart_and_preserves_legacy_cipher():
    secret = "a-stable-high-entropy-test-secret-123456"
    encrypt = "import base64,hashlib; from cryptography.fernet import Fernet; from jwt_secret import api_key_encryption_secret; key=base64.urlsafe_b64encode(hashlib.sha256(api_key_encryption_secret().encode()).digest()); print(Fernet(key).encrypt(b'credential').decode())"
    decrypt = "import base64,hashlib,sys; from cryptography.fernet import Fernet; from jwt_secret import api_key_encryption_secret; key=base64.urlsafe_b64encode(hashlib.sha256(api_key_encryption_secret().encode()).digest()); print(Fernet(key).decrypt(sys.argv[1].encode()).decode())"
    first = run(encrypt, JWT_SECRET=secret)
    assert first.returncode == 0, first.stderr
    env = os.environ.copy()
    env.update(JWT_SECRET=secret)
    env.pop("API_KEY_ENCRYPTION_SECRET", None)
    second = subprocess.run([sys.executable, "-c", decrypt, first.stdout.strip()], cwd=BACKEND, env=env, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "credential"


def test_explicit_encryption_secret_takes_precedence():
    result = run("from jwt_secret import api_key_encryption_secret; print(api_key_encryption_secret())", JWT_SECRET="stable-signing-secret", API_KEY_ENCRYPTION_SECRET="independent-encryption-secret")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "independent-encryption-secret"


def test_separate_processes_share_configured_signing_secret():
    code = "from jwt_secret import get_jwt_secret; print(get_jwt_secret())"
    settings = {"JWT_SECRET": "stable-signing-secret-for-both-workers"}
    first, second = run(code, **settings), run(code, **settings)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout == settings["JWT_SECRET"] + "\n"
