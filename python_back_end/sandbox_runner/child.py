"""Hardening shim every sandboxed child goes through before it runs anything.

Started as ``python3 -I child.py <mode> ...`` so the limits are in place before
the first line of model-written code (or LibreOffice) executes. The server cannot
do this in preexec_fn: it is multi-threaded, and fork-then-run-Python in a
threaded parent can deadlock.

    child.py run  <script> <as_bytes> <cpu_s> <fsize_bytes> <nofile>
    child.py exec <as_bytes> <cpu_s> <fsize_bytes> <nofile> -- <argv...>

What it applies, none of it reversible by the code that runs afterwards:
- RLIMIT_AS / CPU / FSIZE / NOFILE (soft == hard). An as_bytes of 0 means no cap.
- PR_SET_NO_NEW_PRIVS, then a seccomp filter that makes socket() fail for every
  family except AF_UNIX. The container sits on an internal network, but backend
  and document-worker share it, so without this a script could still open
  http://backend:8000. Wrong CPU architecture or the x32 ABI are refused too,
  otherwise they would be a way round the filter.
- run mode only: setsid() and setpgid() fail, so the script cannot leave the process
  group the server kills on timeout.
- run mode only: PR_SET_DUMPABLE 0, so a sibling job running as the same uid
  cannot read this process through /proc/<pid>/mem.
- Every job runs as the server's uid, so a signal or a ptrace could otherwise reach the
  server or the init process. The filter therefore also refuses, with EPERM:
    ptrace, process_vm_readv/writev, process_madvise, kcmp, pidfd_open/send_signal/getfd,
    tkill, rt_sigqueueinfo, rt_tgsigqueueinfo, the mount family, unshare, setns, bpf,
    perf_event_open, userfaultfd, keyctl/add_key/request_key and io_uring;
    clone with any namespace flag; clone3 (ENOSYS, so glibc falls back to clone, whose
    flags the filter can read);
    kill() unless the target is 0, the job's own pid or minus its pid (its process group);
    tgkill() unless the thread group is the job's own pid;
    prlimit64() unless the target is 0 or the job's own pid;
    fcntl(F_SETOWN / F_SETOWN_EX) and ioctl(FIOSETOWN / SIOCSPGRP): they name the process
    the kernel signals (SIGIO, or any signal F_SETSIG picks, SIGKILL included) when a pipe
    or socket becomes ready, and the kernel's only check is the uid, which is the server's.
    That is kill() done by the kernel, so it is closed the same way.
  kill() has no "any process in my tree" form: a pid cannot be told from a server thread's
  id in a filter, and a server thread id is a valid kill() target on Linux. So a script that
  signals a child it started (Popen.terminate, Pool teardown) gets PermissionError, and the
  server kills the whole group when the job ends. The pid arguments are compared as their
  low 32 bits only, which is all the kernel reads: the filter must not trust the upper half
  of the register, which a script controls.
Exit status 97 means a limit could not be installed; the server reports that as
"sandbox hardening failed" and never runs the code unconfined.
"""
import ctypes
import os
import platform
import resource
import runpy
import struct
import sys
import traceback

HARDEN_FAILED = 97

AF_UNIX = 1
ENOSYS = 38
EPERM_RET = 0x00050000 | 1  # SECCOMP_RET_ERRNO | EPERM
ENOSYS_RET = 0x00050000 | ENOSYS
ALLOW_RET = 0x7FFF0000      # SECCOMP_RET_ALLOW
X32_BIT = 0x40000000
# CLONE_NEWNS | NEWCGROUP | NEWUTS | NEWIPC | NEWUSER | NEWPID | NEWNET
CLONE_NS_FLAGS = 0x00020000 | 0x02000000 | 0x04000000 | 0x08000000 | 0x10000000 | 0x20000000 | 0x40000000

# name -> (x86_64, aarch64) syscall numbers
SYSCALLS = {
    "socket": (41, 198), "setsid": (112, 157), "setpgid": (109, 154),
    "kill": (62, 129), "tkill": (200, 130), "tgkill": (234, 131),
    "rt_sigqueueinfo": (129, 138), "rt_tgsigqueueinfo": (297, 240),
    "ptrace": (101, 117), "process_vm_readv": (310, 270), "process_vm_writev": (311, 271),
    "process_madvise": (440, 440), "kcmp": (312, 272),
    "pidfd_open": (434, 434), "pidfd_send_signal": (424, 424), "pidfd_getfd": (438, 438),
    "prlimit64": (302, 261), "fcntl": (72, 25), "ioctl": (16, 29), "clone": (56, 220), "clone3": (435, 435),
    "perf_event_open": (298, 241), "bpf": (321, 280), "userfaultfd": (323, 282),
    "keyctl": (250, 219), "add_key": (248, 217), "request_key": (249, 218),
    "mount": (165, 40), "umount2": (166, 39), "pivot_root": (155, 41), "move_mount": (429, 429),
    "open_tree": (428, 428), "fsopen": (430, 430), "fsconfig": (431, 431), "fsmount": (432, 432),
    "fspick": (433, 433), "mount_setattr": (442, 442), "unshare": (272, 97), "setns": (308, 268),
    "io_uring_setup": (425, 425), "io_uring_enter": (426, 426), "io_uring_register": (427, 427),
}
# Refused outright with EPERM; no document script has a use for any of them.
DENIED = (
    "ptrace", "process_vm_readv", "process_vm_writev", "process_madvise", "kcmp",
    "pidfd_open", "pidfd_send_signal", "pidfd_getfd", "tkill", "rt_sigqueueinfo", "rt_tgsigqueueinfo",
    "perf_event_open", "bpf", "userfaultfd", "keyctl", "add_key", "request_key",
    "mount", "umount2", "pivot_root", "move_mount", "open_tree", "fsopen", "fsconfig", "fsmount",
    "fspick", "mount_setattr", "unshare", "setns", "io_uring_setup", "io_uring_enter", "io_uring_register",
)
# audit arch, whether the x32 ABI exists, column in SYSCALLS
ARCHES = {
    "x86_64": (0xC000003E, True, 0),
    "aarch64": (0xC00000B7, False, 1),
}

LD_ABS, JEQ, JSET, RET = 0x20, 0x15, 0x45, 0x06
ARG0_LOW = 16  # seccomp_data.args[0], low 32 bits on a little-endian machine
ARG1_LOW = 24  # args[1]
F_SETOWN, F_SETOWN_EX = 8, 15
FIOSETOWN, SIOCSPGRP = 0x8901, 0x8902  # same value on x86_64 and aarch64


def _filter(arch_id, x32, col, own_pid, confine_group):
    """Classic BPF over seccomp_data: nr @0, arch @4, args[0] @16 and args[1] @24 (low words only).

    Every argument tested is a C int or unsigned long read as a 32-bit word. The kernel
    truncates pid_t, int and clone flags the same way, so the upper half of the register
    never matters and is deliberately not looked at.
    """
    nr = {name: pair[col] for name, pair in SYSCALLS.items()}
    neg_pid = (-own_pid) & 0xFFFFFFFF
    prog = [("ld", 4), ("jeq", arch_id, None, "deny"), ("ld", 0)]
    if x32:
        prog.append(("jset", X32_BIT, "deny", None))
    for name in DENIED + (("setsid", "setpgid") if confine_group else ()):
        prog.append(("jeq", nr[name], "deny", None))
    prog += [("jeq", nr["clone3"], "enosys", None),
             ("jeq", nr["clone"], "clone_chk", None),
             ("jeq", nr["kill"], "kill_chk", None),
             ("jeq", nr["tgkill"], "own_chk", None),
             ("jeq", nr["prlimit64"], "prlimit_chk", None),
             ("jeq", nr["fcntl"], "fcntl_chk", None),
             ("jeq", nr["ioctl"], "ioctl_chk", None),
             ("jeq", nr["socket"], "sock_chk", None),
             ("ret", ALLOW_RET),
             ("label", "clone_chk"), ("ld", ARG0_LOW), ("jset", CLONE_NS_FLAGS, "deny", "allow"),
             ("label", "kill_chk"), ("ld", ARG0_LOW), ("jeq", 0, "allow", None),
             ("jeq", neg_pid, "allow", "own_chk"),
             ("label", "prlimit_chk"), ("ld", ARG0_LOW), ("jeq", 0, "allow", None),
             ("label", "own_chk"), ("ld", ARG0_LOW), ("jeq", own_pid, "allow", "deny"),
             ("label", "sock_chk"), ("ld", ARG0_LOW), ("jeq", AF_UNIX, "allow", "deny"),
             ("label", "fcntl_chk"), ("ld", ARG1_LOW), ("jeq", F_SETOWN, "deny", None),
             ("jeq", F_SETOWN_EX, "deny", "allow"),
             ("label", "ioctl_chk"), ("ld", ARG1_LOW), ("jeq", FIOSETOWN, "deny", None),
             ("jeq", SIOCSPGRP, "deny", "allow"),
             ("label", "enosys"), ("ret", ENOSYS_RET),
             ("label", "deny"), ("ret", EPERM_RET),
             ("label", "allow"), ("ret", ALLOW_RET)]
    return _assemble(prog)


def _assemble(prog):
    """Resolve labels; a jump target of None means the next instruction. Jumps only go forward."""
    pos, at = {}, 0
    for ins in prog:
        if ins[0] == "label":
            pos[ins[1]] = at
        else:
            at += 1
    out, at = b"", 0
    for ins in prog:
        if ins[0] == "label":
            continue
        kind = ins[0]
        if kind == "ld":
            raw = struct.pack("=HBBI", LD_ABS, 0, 0, ins[1])
        elif kind == "ret":
            raw = struct.pack("=HBBI", RET, 0, 0, ins[1])
        else:
            jt, jf = (0 if t is None else pos[t] - at - 1 for t in ins[2:4])
            if not (0 <= jt <= 255 and 0 <= jf <= 255):
                raise ValueError("seccomp jump out of range")
            raw = struct.pack("=HBBI", JEQ if kind == "jeq" else JSET, jt, jf, ins[1])
        out += raw
        at += 1
    return out


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    return libc


def install_filter(libc, confine_group):
    spec = ARCHES.get(platform.machine())
    if spec is None or sys.byteorder != "little":
        raise OSError(f"no seccomp filter for {platform.machine()}")
    pid = os.getpid()
    if os.getpgrp() != pid:  # the kill rules assume the server made this process a group leader
        raise OSError("not a process group leader")
    raw = _filter(*spec, pid, confine_group)
    buf = ctypes.create_string_buffer(raw, len(raw))

    class Fprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    prog = Fprog(len(raw) // 8, ctypes.cast(buf, ctypes.c_void_p))
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "no_new_privs")
    if libc.prctl(22, 2, ctypes.addressof(prog), 0, 0) != 0:  # PR_SET_SECCOMP, MODE_FILTER
        raise OSError(ctypes.get_errno(), "seccomp")


def apply_limits(as_bytes, cpu_s, fsize, nofile):
    for res, val in ((resource.RLIMIT_AS, as_bytes), (resource.RLIMIT_CPU, cpu_s),
                     (resource.RLIMIT_FSIZE, fsize), (resource.RLIMIT_NOFILE, nofile)):
        if val > 0:
            resource.setrlimit(res, (val, val))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main(argv):
    mode = argv[1]
    try:
        libc = _libc()
        if mode == "run":
            script = argv[2]
            apply_limits(*(int(x) for x in argv[3:7]))
            install_filter(libc, confine_group=True)
            if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
                raise OSError(ctypes.get_errno(), "dumpable")
        else:
            split = argv.index("--")
            apply_limits(*(int(x) for x in argv[2:6]))
            install_filter(libc, confine_group=False)
            cmd = argv[split + 1:]
    except Exception as exc:  # noqa: BLE001 - any failure here must stop the job
        sys.stderr.write(f"sandbox hardening failed: {type(exc).__name__}\n")
        sys.exit(HARDEN_FAILED)
    if mode == "run":
        sys.argv = [script]
        try:
            runpy.run_path(script, run_name="__main__")
        except Exception as exc:  # noqa: BLE001 - the caller needs the script's own traceback
            tb = exc.__traceback__
            while tb is not None and tb.tb_frame.f_code.co_filename != script:
                tb = tb.tb_next  # drop this shim's and runpy's frames
            traceback.print_exception(type(exc), exc, tb or exc.__traceback__)
            sys.exit(1)
    else:
        os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main(sys.argv)
