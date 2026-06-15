#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/conftest.py'
#   Shared pytest fixtures + the hardware-marker self-skip + the
#   CROSS-PLATFORM stub-binary factory (so lifecycle/handle/stream tests
#   run on Windows, not just where bash exists).
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

def _on_signal(signum, frame):
    if MARKER:
        try:
            open(MARKER, "w").close()
        except OSError:
            pass
    sys.exit(0)

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

if IDLE:
    while True:
        if STDERR_LINES:
            sys.stderr.write(STDERR_LINES[-1] + "\\n")
            sys.stderr.flush()
        time.sleep(0.02)

sys.exit(EXIT_CODE)
'''


def _write_stub(tools_dir, name, *, stdout_lines=(), stderr_lines=(),
                stderr_flood=0, idle=False, exit_code=0, marker=None,
                emit_bytes=None):
    py_path = os.path.join(tools_dir, name + ".py")
    body = _STUB_TEMPLATE.format(
        marker=marker, stdout_lines=list(stdout_lines),
        stderr_lines=list(stderr_lines), stderr_flood=stderr_flood,
        idle=idle, exit_code=exit_code,
        emit_bytes=list(emit_bytes) if emit_bytes else None)
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
