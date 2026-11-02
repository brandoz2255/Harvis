"""Exercise main's real bootstrap in isolated, independent Python processes."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]
DOTENV_SECRET = "synthetic-dotenv-signing-secret-for-startup"

# Stop immediately after the real auth module has imported, before main can
# initialize unrelated services or touch a database. The copied main.py makes
# python-dotenv discover only the temporary fixture, never the project's .env.
BOOTSTRAP = r'''
import builtins, os
original = builtins.__import__
class BootstrapComplete(Exception):
    pass
def intercept(name, *args, **kwargs):
    module = original(name, *args, **kwargs)
    if name == "auth_optimized":
        assert module.SECRET_KEY == os.environ["EXPECTED_SECRET"]
        raise BootstrapComplete
    return module
builtins.__import__ = intercept
try:
    import main
except BootstrapComplete:
    print("auth bootstrap complete")
else:
    raise AssertionError("auth bootstrap was not reached")
'''


def run_bootstrap(tmp_path, dotenv_secret=None, environment_secret=None):
    shutil.copyfile(BACKEND / "main.py", tmp_path / "main.py")
    if dotenv_secret is not None:
        (tmp_path / ".env").write_text(f"JWT_SECRET={dotenv_secret}\n")
    env = os.environ.copy()
    for key in ("JWT_SECRET", "HARVIS_ALLOW_EPHEMERAL_JWT_SECRET", "PYTHON_DOTENV_DISABLED", "PYTHONPATH"):
        env.pop(key, None)
    if environment_secret is not None:
        env["JWT_SECRET"] = environment_secret
    env["EXPECTED_SECRET"] = environment_secret or dotenv_secret or "missing"
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(BACKEND)))
    return subprocess.run([sys.executable, "-c", BOOTSTRAP], cwd=tmp_path,
                          env=env, capture_output=True, text=True, timeout=60)


def test_dotenv_secret_is_available_to_auth_on_each_restart(tmp_path):
    for _ in range(2):
        result = run_bootstrap(tmp_path, dotenv_secret=DOTENV_SECRET)
        assert result.returncode == 0, result.stderr
        assert "auth bootstrap complete" in result.stdout


def test_process_environment_takes_precedence_over_dotenv(tmp_path):
    result = run_bootstrap(tmp_path, dotenv_secret=DOTENV_SECRET,
                           environment_secret="synthetic-environment-signing-secret")
    assert result.returncode == 0, result.stderr


def test_missing_secret_still_fails_closed(tmp_path):
    result = run_bootstrap(tmp_path)
    assert result.returncode != 0
    assert "JWT_SECRET must be set" in result.stderr
