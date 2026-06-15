#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_lifecycle_xplat.py'
#   The lifecycle coverage from test_lifecycle.py, but using the
#   CROSS-PLATFORM stub_device factory so these run on Windows too -- the
#   platform this library targets. This is what proves the _run process
#   machinery (stream / timed / handle, pipe draining, and the
#   SIGINT/CTRL_BREAK reap) actually works before hardware is attached.
#
#   NOTE: these intentionally do NOT skip on Windows. If they fail on
#   Windows, that is a real finding about CTRL_BREAK_EVENT reaping, which
#   is the previously-uncovered (pragma: no cover) interrupt path.
##--------------------------------------------------------------------\

import os
import time

import pytest

from hackrfpy.exceptions import HackRFDeviceError


SWEEP_ROWS = [
    "2026-06-10, 12:00:00, 400000000, 405000000, 1000000.00, 8192, -70.00, -71.00",
    "2026-06-10, 12:00:00, 405000000, 410000000, 1000000.00, 8192, -72.00, -73.00",
]


# ---- stream mode -----------------------------------------------------------
def test_stream_yields_parsed_sweep_rows(stub_device):
    h = stub_device(sweep=dict(
        stderr_lines=["noise on stderr"], stdout_lines=SWEEP_ROWS))
    rows = list(h.sweep(400e6, 410e6))
    assert [r["hz_low"] for r in rows] == [400000000, 405000000]
    assert rows[1]["db"] == [-72.00, -73.00]


def test_stream_raises_on_child_failure(stub_device):
    h = stub_device(sweep=dict(
        stderr_lines=["hackrf_open() failed: (-5)"], exit_code=1))
    with pytest.raises(HackRFDeviceError, match="hackrf_open"):
        list(h.sweep(400e6, 410e6))


def test_stream_early_break_reaps_child(stub_device, tmp_path):
    marker = str(tmp_path / "stopped")
    h = stub_device(sweep=dict(
        stdout_lines=SWEEP_ROWS, idle=True, marker=marker))
    gen = h.sweep(400e6, 410e6)
    next(gen)
    gen.close()                          # GeneratorExit -> reap
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not os.path.exists(marker):
        time.sleep(0.05)
    assert os.path.exists(marker), "child not cleanly reaped on early break"


# ---- timed mode ------------------------------------------------------------
def test_timed_stops_chatty_child_on_schedule(stub_device):
    h = stub_device(transfer=dict(
        stderr_lines=["3.9 MiB / 1.000 sec"], idle=True))
    t0 = time.monotonic()
    out, err, rc = h._run(["transfer", "-r", "x.iq"], mode="timed",
                          duration=0.5)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0                 # didn't hang on a full pipe
    assert b"MiB" in err                 # stderr drained + returned
    assert rc is not None


# ---- handle mode -----------------------------------------------------------
def test_handle_drains_pipes_and_stops_cleanly(stub_device):
    # flood stderr past the pipe buffer immediately; without drain threads
    # this blocks the child (the classic deadlock)
    h = stub_device(transfer=dict(
        stderr_flood=262144, stdout_lines=["started"], idle=True))
    proc = h._run(["transfer", "-r", "x.iq"], mode="handle")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if b"started" in b"".join(proc._out_chunks):
            break
        time.sleep(0.05)
    assert proc.is_alive()
    out, err, rc = proc.stop()
    assert len(err) >= 262144
    assert b"started" in out


def test_handle_context_manager_reaps(stub_device):
    h = stub_device(transfer=dict(stdout_lines=["ready"], idle=True))
    proc = h._run(["transfer", "-r", "x.iq"], mode="handle")
    assert proc.is_alive()
    with proc as p:
        assert p.is_alive()
    assert not proc.is_alive(), "context manager did not reap child"


# ---- serial injection (no signals involved) --------------------------------
def test_serial_injected_for_supported_tools(stub_device, capsys):
    h = stub_device(transfer=dict(exit_code=0), info=dict(exit_code=0))
    h.serial = "0000aabbccdd"
    h._run(["transfer", "-r", "x.iq"], mode="blocking", print_cmd=True)
    h._run(["info"], mode="blocking", print_cmd=True)
    lines = capsys.readouterr().out.strip().splitlines()
    assert "-d 0000aabbccdd" in lines[0]
    assert lines[0].split()[1:3] == ["-d", "0000aabbccdd"]
    assert "-d" not in lines[1]           # hackrf_info doesn't take -d
