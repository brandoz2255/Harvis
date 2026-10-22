"""Run one piece of untrusted Python in a throwaway directory and return its files."""
import base64
import binascii
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = os.path.join(HERE, "child.py")
HARDEN_FAILED = 97

MAX_TIMEOUT = 120
DEFAULT_TIMEOUT = 60
STREAM_CAP = 64 * 1024
OUTPUT_CAP = 25 * 1024 * 1024
JOB_DISK_CAP = 160 * 1024 * 1024
MIN_FREE_BYTES = 48 * 1024 * 1024  # the job directory is capped, but a job can write elsewhere in /tmp
AS_LIMIT = 1536 * 1024 * 1024
NOFILE = 256
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$")
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"


class JobError(Exception):
    """A request the runner refuses; the message is safe to show the caller."""


def child_env(tmp):
    return {
        "PATH": SAFE_PATH, "HOME": tmp, "TMPDIR": os.path.join(tmp, "tmp"),
        "MPLBACKEND": "Agg", "MPLCONFIGDIR": os.path.join(tmp, "mpl"),
        "OUTPUT_DIR": os.path.join(tmp, "out"), "INPUT_DIR": os.path.join(tmp, "in"),
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "LANG": "C.UTF-8", "PYTHONHASHSEED": "0",
    }


def tree_bytes(root):
    total = 0
    for base, _dirs, names in os.walk(root, followlinks=False):
        for n in names:
            try:
                total += os.lstat(os.path.join(base, n)).st_size
            except OSError:
                pass
    return total


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def wipe(path):
    """Delete a path whatever its mode, without following symlinks."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            for base, dirs, _names in os.walk(path, followlinks=False):
                os.chmod(base, 0o700)
                for d in dirs:
                    full = os.path.join(base, d)
                    if not os.path.islink(full):
                        os.chmod(full, 0o700)
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except OSError:
        pass


def sweep_dir(root):
    """Empty `root`. Every job runs as the server's uid, so anything a job left in
    the shared /tmp (marker files, dropped scripts, a full disk) would reach the next one."""
    for entry in os.listdir(root):
        wipe(os.path.join(root, entry))


def prepare_job_dir(tmp):
    for sub in ("out", "in", "tmp", "mpl"):
        os.mkdir(os.path.join(tmp, sub))


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def supervise(cmd, cwd, env, timeout, tmp, stdout_path, stderr_path):
    """Run cmd as its own process group; kill the group on timeout or disk blow-up.

    Returns (returncode, reason) where reason is None, 'timeout' or 'disk'.
    """
    with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=so, stderr=se,
                                start_new_session=True, close_fds=True)
        deadline, reason = time.monotonic() + timeout, None
        try:
            while True:
                try:
                    proc.wait(timeout=0.4)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() >= deadline:
                    reason = "timeout"
                elif tree_bytes(tmp) > JOB_DISK_CAP or free_bytes(tmp) < MIN_FREE_BYTES:
                    reason = "disk"
                if reason:
                    kill_group(proc)
                    proc.wait()
                    break
        finally:
            kill_group(proc)  # also reaps anything the script left running
    return proc.returncode, reason


def read_capped(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read(STREAM_CAP + 1)
    except OSError:
        return ""
    text = data[:STREAM_CAP].decode("utf-8", "replace")
    return text + "\n[truncated]" if len(data) > STREAM_CAP else text


def scrub(text, tmp):
    """Tracebacks name the job's temp directory; the caller has no use for it."""
    return text.replace(tmp, ".")


def write_inputs(files, indir):
    if files is not None and not isinstance(files, list):
        raise JobError("files must be a list of {name, b64} objects")
    for item in files or []:
        if not isinstance(item, dict):
            raise JobError("files must be a list of {name, b64} objects")
        name = str(item.get("name") or "")
        if not NAME_OK.match(name) or ".." in name:
            raise JobError("input file name is not allowed")
        try:
            data = base64.b64decode(str(item.get("b64") or ""), validate=True)
        except (binascii.Error, ValueError):
            raise JobError("input file is not valid base64") from None
        try:
            with open(os.path.join(indir, name), "xb") as fh:
                fh.write(data)
        except FileExistsError:
            raise JobError(f"input file {name} is listed twice") from None


def collect_outputs(outdir):
    """Regular files directly under out/. Symlinks and sub-directories are skipped."""
    found, total = [], 0
    for entry in sorted(os.scandir(outdir), key=lambda e: e.name):
        st = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode):
            continue
        total += st.st_size
        if total > OUTPUT_CAP:
            raise JobError("the script produced more than 25 MB of output")
        with open(entry.path, "rb") as fh:
            found.append({"name": entry.name, "b64": base64.b64encode(fh.read()).decode()})
    return found


def run_python(code, timeout=DEFAULT_TIMEOUT, files=None):
    if not isinstance(code, str) or not code.strip():
        raise JobError("code is required")
    try:
        timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    except (TypeError, ValueError, OverflowError):
        timeout = DEFAULT_TIMEOUT
    tmp = tempfile.mkdtemp(prefix="job-")
    try:
        prepare_job_dir(tmp)
        script = os.path.join(tmp, "script.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(code)
        write_inputs(files, os.path.join(tmp, "in"))
        cmd = [sys.executable, "-I", CHILD, "run", script, str(AS_LIMIT), str(timeout + 5),
               str(OUTPUT_CAP), str(NOFILE)]
        rc, reason = supervise(cmd, tmp, child_env(tmp), timeout, tmp,
                               os.path.join(tmp, "stdout.txt"), os.path.join(tmp, "stderr.txt"))
        stdout = scrub(read_capped(os.path.join(tmp, "stdout.txt")), tmp)
        stderr = scrub(read_capped(os.path.join(tmp, "stderr.txt")), tmp)
        if rc == HARDEN_FAILED:
            return {"ok": False, "returncode": rc, "stdout": "", "stderr": "",
                    "error": "sandbox hardening failed; the code was not run", "files": []}
        out = {"ok": rc == 0, "returncode": rc, "stdout": stdout, "stderr": stderr, "files": []}
        if reason == "timeout":
            out.update(ok=False, error=f"timed out after {timeout} seconds")
        elif reason == "disk":
            out.update(ok=False, error="the script wrote too much data")
        else:
            try:
                out["files"] = collect_outputs(os.path.join(tmp, "out"))
            except JobError as exc:
                out.update(ok=False, error=str(exc))
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
