#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/conftest.py'
#   Shared pytest fixtures + the hardware-marker self-skip + the
#   CROSS-PLATFORM stub-binary factory (so lifecycle/handle/stream tests
#   run on Windows, not just where bash exists).
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

import os
import shutil
import stat
import subprocess
import sys

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _hackrf_present():
    if shutil.which("hackrf_info") is None:
        return False
    try:
        out = subprocess.run(["hackrf_info"], capture_output=True, text=True,
                             timeout=5).stdout
    except Exception:
        return False
    return "Serial number" in out or "Found HackRF" in out


def pytest_collection_modifyitems(config, items):
    if _hackrf_present():
        return
    skip = pytest.mark.skip(reason="no HackRF detected")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fixtures_dir():
    return FIXTURES


# =====================================================================
# Cross-platform stub binaries
# =====================================================================
# The old per-file stubs were bash scripts, so every lifecycle/handle/
# stream test skipped on Windows -- the platform this library targets and
# the code (_run's lifecycle, the SIGINT / CTRL_BREAK reap) most worth
# proving before hardware. This factory renders a stub as a PYTHON script
# plus a platform launcher resolve()/Popen can execute:
#   POSIX  : shebang'd executable file `<name>`        (chmod +x)
#   Windows: `<name>.bat` -> `python <name>.py`        (.bat on PATHEXT)
# Behavior is declarative so the same spec runs identically on both OSes.

_STUB_TEMPLATE = '''\
import os, signal, sys, time

MARKER = {marker!r}
STDOUT_LINES = {stdout_lines!r}
STDERR_LINES = {stderr_lines!r}
STDERR_FLOOD = {stderr_flood!r}
IDLE = {idle!r}
EXIT_CODE = {exit_code!r}
EMIT_BYTES = {emit_bytes!r}
TAIL_ON_INTERRUPT = {tail_on_interrupt!r}
IGNORE_INTERRUPT = {ignore_interrupt!r}
BUSY_FAILS = {busy_fails!r}
STDOUT_FLOOD = {stdout_flood!r}

if BUSY_FAILS:
    # simulate hackrf_open()'s stale-claim race: fail with the Resource
    # busy signature the first N invocations, then behave normally. State
    # lives in a counter file next to the stub so it survives respawns.
    _cf = __file__ + ".busycount"
    try:
        _n = int(open(_cf).read())
    except (OSError, ValueError):
        _n = 0
    if _n < BUSY_FAILS:
        open(_cf, "w").write(str(_n + 1))
        sys.stderr.write("hackrf_open() failed: Resource busy (-1000)\\n")
        sys.stderr.flush()
        sys.exit(1)

def _on_signal(signum, frame):
    # record WHICH signal arrived, so tests can distinguish the clean
    # interrupt (SIGINT / SIGBREAK from CTRL_BREAK_EVENT) from the
    # terminate() escalation -- "the child died" is not "the child was
    # interrupted cleanly"
    if MARKER:
        try:
            with open(MARKER, "w") as fh:
                fh.write(signal.Signals(signum).name)
        except (OSError, ValueError):
            try:
                open(MARKER, "w").close()
            except OSError:
                pass
    if TAIL_ON_INTERRUPT:
        # the hackrf_transfer contract: flush buffered output BEFORE dying,
        # so the capture file is never truncated mid-sample-pair
        sys.stdout.write(TAIL_ON_INTERRUPT + "\\n")
        sys.stdout.flush()
    sys.exit(0)

if IGNORE_INTERRUPT:
    # deaf child: exercises the stop() grace-timeout -> terminate() path
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
else:
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

for line in STDERR_LINES:
    sys.stderr.write(line + "\\n")
sys.stderr.flush()

if STDERR_FLOOD:
    sys.stderr.buffer.write(b"\\x00" * STDERR_FLOOD)
    sys.stderr.flush()

if EMIT_BYTES:
    sys.stdout.buffer.write(bytes(EMIT_BYTES))
    sys.stdout.buffer.flush()

for line in STDOUT_LINES:
    sys.stdout.write(line + "\\n")
sys.stdout.flush()

if STDOUT_FLOOD:
    # keep writing far past pipe capacity so a consumer that stops reading
    # leaves this child BLOCKED inside write() -- the frozen-writer state
    # that held the USB claim on real hardware
    _w = 0
    while _w < STDOUT_FLOOD:
        sys.stdout.buffer.write(b"\\x2a" * 4096)
        _w += 4096
    sys.stdout.buffer.flush()

if IDLE:
    _idle_until = time.monotonic() + 30.0    # safety ceiling: never leak a
    while time.monotonic() < _idle_until:    # stub child on CI, even one
        if STDERR_LINES:                     # that ignores interrupts
            sys.stderr.write(STDERR_LINES[-1] + "\\n")
            sys.stderr.flush()
        time.sleep(0.02)

sys.exit(EXIT_CODE)
'''


def _write_stub(tools_dir, name, *, stdout_lines=(), stderr_lines=(),
                stderr_flood=0, idle=False, exit_code=0, marker=None,
                emit_bytes=None, tail_on_interrupt=None,
                ignore_interrupt=False, busy_fails=0, stdout_flood=0):
    py_path = os.path.join(tools_dir, name + ".py")
    body = _STUB_TEMPLATE.format(
        marker=marker, stdout_lines=list(stdout_lines),
        stderr_lines=list(stderr_lines), stderr_flood=stderr_flood,
        idle=idle, exit_code=exit_code,
        emit_bytes=list(emit_bytes) if emit_bytes else None,
        tail_on_interrupt=tail_on_interrupt,
        ignore_interrupt=ignore_interrupt, busy_fails=busy_fails,
        stdout_flood=stdout_flood)
    with open(py_path, "w") as f:
        f.write(body)

    if os.name == "nt":
        launcher = os.path.join(tools_dir, name + ".bat")
        with open(launcher, "w") as f:
            f.write(f'@echo off\r\n"{sys.executable}" "{py_path}" %*\r\n')
        return launcher
    launcher = os.path.join(tools_dir, name)
    with open(launcher, "w") as f:
        f.write(f"#!{sys.executable}\n")
        f.write(body)
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR
             | stat.S_IXGRP | stat.S_IXOTH)
    return launcher


@pytest.fixture
def stub_device(tmp_path):
    """Factory: HackRF whose tools_dir holds cross-platform stub binaries.
        h = stub_device(transfer=dict(stdout_lines=[...], idle=True,
                                      marker=str(tmp_path/'stopped')))
    Keyword is the TOOLS key; value is the stub spec (see _write_stub).
    """
    from hackrfpy import HackRF
    from hackrfpy import constants as C

    def factory(**specs):
        for key, spec in specs.items():
            name = C.TOOLS[key]
            _write_stub(str(tmp_path), name, **spec)
        h = HackRF(tools_dir=str(tmp_path))
        h._tmp_path = str(tmp_path)
        return h
    return factory
