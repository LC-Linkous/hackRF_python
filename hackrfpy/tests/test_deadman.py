#! /usr/bin/python3

##--------------------------------------------------------------------\\
#   hackrfpy  'tests/test_deadman.py'
#   The OS dead-man: a HARD-killed parent (SIGKILL / TerminateProcess --
#   the deaths the atexit backstop cannot see) must not orphan a
#   handle-mode child. Each test spawns a real intermediate parent
#   process that starts a protected stub handle, hard-kills that parent,
#   and asserts the OS ends the child:
#     Linux   : PR_SET_PDEATHSIG delivers SIGINT -- the CLEAN interrupt,
#               so the child's handler runs and the marker records
#               "SIGINT": the dead-man IS the flush path.
#     Windows : the Job Object's KILL_ON_JOB_CLOSE terminates the child
#               tree when the parent's handles close. TerminateProcess
#               runs no handler, so death itself is the assertion.
#     macOS   : skipped -- no OS primitive; the atexit backstop remains
#               the only net there (documented in core.py).
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\\

import os
import signal
import subprocess
import sys
import time

import pytest

from conftest import _write_stub


_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))


def _pid_alive(pid):
    if sys.platform == "win32":
        import ctypes
        _PQLI = 0x1000                   # PROCESS_QUERY_LIMITED_INFORMATION
        _STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(_PQLI, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_dead(pid, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


_PARENT_TEMPLATE = """\
import sys, time
sys.path.insert(0, {src!r})
from hackrfpy import HackRF
h = HackRF(tools_dir={tools!r})
p = h._run(["transfer", "-r", "x.iq"], mode="handle", kind={kind!r})
# wait until the stub says "started": its signal handlers are installed
# BEFORE its stdout lines, so seeing this means an interrupt from here on
# runs the handler -- without this wait, a fast parent-kill can land during
# the stub's interpreter startup and die handler-less (a test race, not a
# dead-man failure). Live small-write draining is what makes this wait
# possible (the read1() drain fix).
deadline = time.monotonic() + 10.0
while time.monotonic() < deadline:
    if b"started" in b"".join(p._out_chunks):
        break
    time.sleep(0.05)
print(p._proc.pid, flush=True)
time.sleep(120)                          # murdered long before this returns
"""


def _spawn_parent_with_child(tmp_path, marker, kind="tx"):
    _write_stub(str(tmp_path), "hackrf_transfer",
                stdout_lines=["started"], idle=True, marker=marker)
    script = tmp_path / "parent.py"
    script.write_text(_PARENT_TEMPLATE.format(
        src=_SRC, tools=str(tmp_path), kind=kind))
    parent = subprocess.Popen([sys.executable, str(script)],
                              stdout=subprocess.PIPE, text=True)
    line = parent.stdout.readline().strip()
    assert line.isdigit(), f"parent never reported a child pid: {line!r}"
    return parent, int(line)


@pytest.mark.skipif(sys.platform == "darwin",
                    reason="no OS dead-man primitive on macOS; atexit "
                           "backstop only (see core.py)")
def test_hard_killed_parent_cannot_orphan_child(tmp_path):
    marker = str(tmp_path / "sig")
    parent, child_pid = _spawn_parent_with_child(tmp_path, marker, kind="tx")
    assert _pid_alive(child_pid)
    # the death atexit cannot see: no cleanup code in the parent runs
    parent.kill()
    parent.wait(timeout=10)
    assert _wait_dead(child_pid), (
        "child survived a hard-killed parent -- the OS dead-man did not "
        "fire; an orphaned transmitter would still be on the air")
    if sys.platform.startswith("linux"):
        # pdeathsig delivers the CLEAN interrupt: the handler ran and
        # recorded it, so even the dead-man path flushes output
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not os.path.exists(marker):
            time.sleep(0.05)
        assert os.path.exists(marker)
        assert open(marker).read().strip() == "SIGINT"


@pytest.mark.skipif(sys.platform == "darwin",
                    reason="no OS dead-man primitive on macOS")
def test_rx_opt_out_is_not_deadman_protected(tmp_path):
    # backstop_rx=False is the documented fire-and-forget escape hatch; the
    # dead-man honors the same gate, so an opted-out RX child SURVIVES its
    # parent. (Only RX can opt out; TX is always protected.)
    _write_stub(str(tmp_path), "hackrf_transfer",
                stdout_lines=["started"], idle=True)
    script = tmp_path / "parent.py"
    script.write_text(_PARENT_TEMPLATE.format(
        src=_SRC, tools=str(tmp_path), kind="rx").replace(
        "p = h._run(", "h.backstop_rx = False\np = h._run("))
    parent = subprocess.Popen([sys.executable, str(script)],
                              stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline().strip())
    parent.kill()
    parent.wait(timeout=10)
    time.sleep(1.5)                       # give a wrong dead-man time to fire
    try:
        assert _pid_alive(child_pid), (
            "opted-out RX child was reaped -- the dead-man ignored the "
            "backstop_rx gate")
    finally:
        # we deliberately orphaned it; clean up (idle ceiling would also end
        # it within 30 s, but be a good citizen on CI)
        if _pid_alive(child_pid):
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(child_pid), "/F"],
                               capture_output=True)
            else:
                os.kill(child_pid, signal.SIGKILL)
