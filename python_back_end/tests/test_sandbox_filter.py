"""The sandbox's seccomp filter: the program itself (run through a small BPF interpreter,
so every rule is checked on both CPU architectures) and what a real job can and cannot do.
"""

import os
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandbox_runner import child, jobs  # noqa: E402

OWN = 4242
OTHER = 7  # stands in for the server, or any pid that is not the job's


def program(arch, confine=True):
    return child._filter(*child.ARCHES[arch], OWN, confine)


def verdict(raw, arch, name_or_nr, *args, audit=None, nr_bits=0):
    """Run `raw` over a seccomp_data and say what the kernel would do."""
    audit_id, _x32, col = child.ARCHES[arch]
    nr = child.SYSCALLS[name_or_nr][col] if isinstance(name_or_nr, str) else name_or_nr
    data = struct.pack("=iIQ6Q", nr | nr_bits, audit or audit_id, 0, *[a & (2**64 - 1) for a in (list(args) + [0] * 6)[:6]])
    acc, pc = 0, 0
    while True:
        code, jt, jf, k = struct.unpack("=HBBI", raw[pc * 8:pc * 8 + 8])
        pc += 1
        if code == child.LD_ABS:
            acc = struct.unpack("=I", data[k:k + 4])[0]
        elif code == child.JEQ:
            pc += jt if acc == k else jf
        elif code == child.JSET:
            pc += jt if acc & k else jf
        elif code == child.RET:
            if k == child.ALLOW_RET:
                return "allow"
            return ("errno", k & 0xFFFF)
        else:
            raise AssertionError(f"unexpected opcode {code:#x}")


def hi(value):
    """A pid argument whose unused upper half holds junk the kernel will ignore."""
    return (0xDEADBEEF << 32) | (value & 0xFFFFFFFF)


EPERM, ENOSYS = ("errno", 1), ("errno", 38)
archs = pytest.mark.parametrize("arch", sorted(child.ARCHES))


@archs
def test_filter_jumps_stay_inside_the_program(arch):
    raw = program(arch)
    count = len(raw) // 8
    assert len(raw) % 8 == 0 and 0 < count < 120
    for i in range(count):
        code, jt, jf, _k = struct.unpack("=HBBI", raw[i * 8:i * 8 + 8])
        if code in (child.JEQ, child.JSET):
            assert i + 1 + jt < count and i + 1 + jf < count
    assert struct.unpack("=HBBI", raw[-8:])[3] == child.ALLOW_RET


@archs
def test_every_syscall_number_is_distinct_within_an_architecture(arch):
    col = child.ARCHES[arch][2]
    nrs = [pair[col] for pair in child.SYSCALLS.values()]
    assert len(nrs) == len(set(nrs))


@archs
def test_ordinary_calls_pass_and_a_foreign_architecture_does_not(arch):
    raw = program(arch)
    assert verdict(raw, arch, 0) == "allow" and verdict(raw, arch, 202) == "allow"
    assert verdict(raw, arch, 0, audit=0x40000003) == EPERM  # i386
    if child.ARCHES[arch][1]:
        assert verdict(raw, arch, 0, nr_bits=child.X32_BIT) == EPERM


@archs
@pytest.mark.parametrize("name", child.DENIED)
def test_denied_calls_fail_with_eperm_whatever_the_arguments(arch, name):
    raw = program(arch)
    assert verdict(raw, arch, name) == EPERM
    assert verdict(raw, arch, name, OWN, 0, OWN) == EPERM


@archs
def test_kill_reaches_only_the_job_and_its_group(arch):
    raw = program(arch)
    sig = 9
    for ok in (0, OWN, -OWN, hi(OWN), hi(-OWN), -OWN & 0xFFFFFFFF, -OWN & 0xFFFFFFFFFFFFFFFF, hi(0)):
        assert verdict(raw, arch, "kill", ok, sig) == "allow", hex(ok)
    for bad in (1, OTHER, OWN + 1, OWN - 1, -1 & 0xFFFFFFFF, -1 & 0xFFFFFFFFFFFFFFFF, -OTHER & 0xFFFFFFFF,
                -(OWN + 1) & 0xFFFFFFFF, hi(1), hi(OTHER), hi(-1), 0x1_0000_0000 + 1):
        assert verdict(raw, arch, "kill", bad, sig) == EPERM, hex(bad)


@archs
def test_tgkill_and_prlimit_accept_only_the_job(arch):
    raw = program(arch)
    assert verdict(raw, arch, "tgkill", OWN, OWN) == "allow"
    assert verdict(raw, arch, "tgkill", hi(OWN), 99) == "allow"
    for bad in (0, 1, OTHER, OWN + 1, -OWN & 0xFFFFFFFF, hi(OTHER)):
        assert verdict(raw, arch, "tgkill", bad, OWN) == EPERM, hex(bad)
    for ok in (0, OWN, hi(0), hi(OWN)):
        assert verdict(raw, arch, "prlimit64", ok) == "allow", hex(ok)
    for bad in (1, OTHER, OWN + 1, -1 & 0xFFFFFFFF):
        assert verdict(raw, arch, "prlimit64", bad) == EPERM, hex(bad)


@archs
def test_file_owner_calls_that_make_the_kernel_signal_are_refused(arch):
    raw = program(arch)
    for cmd in (8, 15):  # F_SETOWN, F_SETOWN_EX
        for a0 in (0, 3, hi(3)):
            assert verdict(raw, arch, "fcntl", a0, cmd, OTHER) == EPERM, (cmd, a0)
            assert verdict(raw, arch, "fcntl", a0, hi(cmd), OTHER) == EPERM  # upper half is ignored
    for cmd in (0x8901, 0x8902):  # FIOSETOWN, SIOCSPGRP
        assert verdict(raw, arch, "ioctl", 3, cmd, 0) == EPERM and verdict(raw, arch, "ioctl", 3, hi(cmd), 0) == EPERM
    # everything else a document library does with descriptors stays open: F_DUPFD(0), F_GETFD(1),
    # F_SETFD(2), F_GETFL(3), F_SETFL(4), F_GETLK(5), F_SETLK(6), F_GETOWN(9), F_SETSIG(10),
    # F_DUPFD_CLOEXEC(1030), F_SETPIPE_SZ(1031)
    for cmd in (0, 1, 2, 3, 4, 5, 6, 9, 10, 1030, 1031):
        assert verdict(raw, arch, "fcntl", 3, cmd, OTHER) == "allow", cmd
    for cmd in (0x5401, 0x541B, 0x5421, 0x5452, 0x8913):  # TCGETS, FIONREAD, FIONBIO, FIOASYNC, SIOCGIFFLAGS
        assert verdict(raw, arch, "ioctl", 3, cmd, 0) == "allow", hex(cmd)
    assert verdict(raw, arch, "fcntl", 8, 3) == "allow"  # the fd number is args[0], not the command


@archs
def test_clone_is_refused_only_with_namespace_flags(arch):
    raw = program(arch)
    sigchld = 17
    assert verdict(raw, arch, "clone", 0x01200000 | sigchld) == "allow"   # fork
    assert verdict(raw, arch, "clone", 0x003D0F00) == "allow"             # pthread_create
    for flag in (0x10000000, 0x40000000, 0x20000000, 0x00020000, 0x04000000, 0x08000000, 0x02000000):
        assert verdict(raw, arch, "clone", 0x01200000 | sigchld | flag) == EPERM, hex(flag)
    assert verdict(raw, arch, "clone3", 0) == ENOSYS


@archs
def test_sockets_and_session_calls(arch):
    raw = program(arch)
    assert verdict(raw, arch, "socket", 1) == "allow" and verdict(raw, arch, "socket", hi(1)) == "allow"
    for family in (2, 10, 16, 17, hi(2)):
        assert verdict(raw, arch, "socket", family) == EPERM
    assert verdict(raw, arch, "setsid") == EPERM and verdict(raw, arch, "setpgid", 0, 0) == EPERM
    loose = program(arch, confine=False)
    assert verdict(loose, arch, "setsid") == "allow" and verdict(loose, arch, "setpgid", 0, 0) == "allow"
    assert verdict(loose, arch, "kill", OTHER, 9) == EPERM  # signals stay confined for soffice too


# ── a real job ──────────────────────────────────────────────────────────────

PROBE = '''
import ctypes, errno, os, signal, platform
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
X = platform.machine() == "x86_64"
NR = dict(kill=62 if X else 129, tkill=200 if X else 130, tgkill=234 if X else 131, ptrace=101 if X else 117,
          pidfd_open=434, pidfd_send_signal=424, unshare=272 if X else 97, bpf=321 if X else 280,
          prlimit64=302 if X else 261)
def sc(name, *a):
    ctypes.set_errno(0)
    r = libc.syscall(NR[name], *[ctypes.c_long(x) for x in a])
    return "ok" if r >= 0 else errno.errorcode[ctypes.get_errno()]
me, parent = os.getpid(), os.getppid()
res = {
    "kill init": sc("kill", 1, 0), "kill all": sc("kill", -1, 0), "kill parent": sc("kill", parent, 0),
    "kill parent group": sc("kill", -os.getpgid(parent), 0),
    "kill junk-high parent": sc("kill", (0xDEAD << 32) | parent, 0), "kill all 64": sc("kill", -1 & (2**64 - 1), 0),
    "kill self": sc("kill", me, 0), "kill group": sc("kill", -me, 0), "kill 0": sc("kill", 0, 0),
    "tkill self": sc("tkill", me, 0), "tgkill parent": sc("tgkill", parent, parent, 0),
    "tgkill self": sc("tgkill", me, me, 0), "pidfd_open self": sc("pidfd_open", me, 0),
    "ptrace parent": sc("ptrace", 16, parent, 0, 0), "unshare user": sc("unshare", 0x10000000),
    "bpf": sc("bpf", 0, 0, 0), "prlimit parent": sc("prlimit64", parent, 9, 0, 0),
}
for k, v in res.items():
    print(k + "=" + v)
'''


def parse(stdout):
    return dict(line.split("=") for line in stdout.splitlines())


def test_a_job_cannot_signal_trace_or_limit_its_parent():
    r = jobs.run_python(PROBE)
    got = parse(r["stdout"])
    for name in ("kill init", "kill all", "kill parent", "kill parent group", "kill junk-high parent",
                 "kill all 64", "tkill self", "tgkill parent", "pidfd_open self", "ptrace parent",
                 "unshare user", "bpf", "prlimit parent"):
        assert got[name] == "EPERM", (name, got[name])
    assert [got[k] for k in ("kill self", "kill group", "kill 0", "tgkill self")] == ["ok"] * 4


def test_a_script_can_signal_itself_and_its_own_threads():
    r = jobs.run_python('''
import os, signal, threading
hits = []
signal.signal(signal.SIGUSR1, lambda *a: hits.append("usr1"))
os.kill(os.getpid(), signal.SIGUSR1)
signal.raise_signal(signal.SIGUSR1)
t = threading.Thread(target=lambda: __import__("time").sleep(0.3))
t.start()
signal.pthread_kill(t.ident, 0)
t.join()
os.killpg(os.getpgrp(), 0)
print(len(hits))
''')
    assert r["ok"] and r["stdout"] == "2\n", r


def test_signalling_a_child_fails_cleanly_and_the_job_still_ends():
    r = jobs.run_python('''
import subprocess
p = subprocess.Popen(["sleep", "300"])
try:
    p.terminate()
    print("signalled")
except PermissionError:
    print("refused")
''', timeout=10)
    assert r["ok"] and r["stdout"] == "refused\n", r
    assert not [d for d in os.listdir("/proc") if d.isdigit() and b"sleep\x00300" in _cmdline(d)]


def _cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def test_a_job_cannot_make_the_kernel_signal_a_process_for_it():
    """SIGIO delivery names its target by file owner; the target here is a forked child, and
    the signal is SIGKILL, so a hole shows as the child dying instead of the job exiting clean.
    """
    r = jobs.run_python('''
import errno, fcntl, os, socket, struct, time
pid = os.fork()
if pid == 0:
    time.sleep(3); os._exit(0)
def attempt(label, fn):
    try:
        fn(); print(label + "=ok")
    except OSError as exc:
        print(label + "=" + errno.errorcode[exc.errno])
rd, wr = os.pipe()
a, b = socket.socketpair()
attempt("F_SETOWN child", lambda: fcntl.fcntl(rd, fcntl.F_SETOWN, pid))
attempt("F_SETOWN self", lambda: fcntl.fcntl(rd, fcntl.F_SETOWN, os.getpid()))
attempt("F_SETOWN_EX child", lambda: fcntl.fcntl(rd, 15, struct.pack("iI", 1, pid)))
attempt("FIOSETOWN child", lambda: fcntl.ioctl(a.fileno(), 0x8901, struct.pack("i", pid)))
attempt("SIOCSPGRP child", lambda: fcntl.ioctl(a.fileno(), 0x8902, struct.pack("i", pid)))
attempt("F_SETSIG", lambda: fcntl.fcntl(rd, 10, 9))
attempt("F_SETFL O_ASYNC", lambda: fcntl.fcntl(rd, fcntl.F_SETFL, fcntl.fcntl(rd, fcntl.F_GETFL) | os.O_ASYNC))
os.write(wr, b"x"); b.send(b"x")
time.sleep(0.3)
done, status = os.waitpid(pid, os.WNOHANG)
print("child alive=" + str(done == 0))
''', timeout=10)
    got = parse(r["stdout"])
    for name in ("F_SETOWN child", "F_SETOWN self", "F_SETOWN_EX child", "FIOSETOWN child", "SIOCSPGRP child"):
        assert got[name] == "EPERM", (name, got)
    assert got["child alive"] == "True", got
    assert got["F_SETSIG"] == "ok" and got["F_SETFL O_ASYNC"] == "ok"  # harmless without an owner


def test_forking_and_waiting_for_a_child_still_works():
    r = jobs.run_python('''
import os, subprocess, multiprocessing
pid = os.fork()
if pid == 0:
    os._exit(7)
print("fork", os.waitpid(pid, 0)[1] >> 8)
print("run", subprocess.run(["echo", "hi"], capture_output=True, text=True).stdout.strip())
def sq(x): return x * x
with multiprocessing.get_context("fork").Pool(2) as pool:
    print("pool", pool.map(sq, range(4)))
''', timeout=20)
    assert "fork 7" in r["stdout"] and "run hi" in r["stdout"] and "pool [0, 1, 4, 9]" in r["stdout"], r


def test_document_libraries_still_produce_files():
    pytest.importorskip("openpyxl")
    r = jobs.run_python('''
import os
import openpyxl
wb = openpyxl.Workbook(); wb.active["A1"] = 1; wb.save(os.path.join(os.environ["OUTPUT_DIR"], "a.xlsx"))
''')
    assert r["ok"] and [f["name"] for f in r["files"]] == ["a.xlsx"], r


def test_the_server_makes_itself_non_dumpable():
    out = subprocess.run(
        [sys.executable, "-c",
         "import ctypes; from sandbox_runner import server; server.make_undumpable();"
         "print(ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), capture_output=True, text=True)
    assert out.stdout.strip() == "0", out
