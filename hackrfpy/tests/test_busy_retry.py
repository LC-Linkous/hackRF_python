#! /usr/bin/python3

##--------------------------------------------------------------------\\
#   hackrfpy  'tests/test_busy_retry.py'
#   Device-busy retry: hackrf_open() reports "Resource busy (-1000)"
#   when the PREVIOUS child's USB claim has not been released yet. On
#   Linux the kernel takes a beat after a tool exits, so rapid back-to-
#   back operations lose the race -- found on the first real-hardware
#   Linux run (7 test failures, all this one error, all in tests that
#   reopen the device immediately after another process used it).
#   The library absorbs it with bounded, backed-off retries in every
#   acquisition mode; these tests pin that with a stub that fails busy
#   N times and then behaves.
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\\

import os

import pytest

from hackrfpy.exceptions import HackRFDeviceError


def _fast(h):
    h.busy_backoff = 0.01           # keep test wall time negligible
    return h


def _spawn_count(h, tool="hackrf_operacake"):
    # the counter sits next to the EXECUTED file: the extensionless launcher
    # on POSIX, the .py on Windows (the .bat re-invokes it)
    for suffix in ("", ".py"):
        cf = os.path.join(h._tmp_path, tool + suffix + ".busycount")
        if os.path.exists(cf):
            return int(open(cf).read())
    return 0


# ---- blocking mode ----------------------------------------------------------
def test_blocking_retries_through_busy(stub_device):
    h = _fast(stub_device(operacake=dict(stdout_lines=["OK boards: none"],
                                         busy_fails=2)))
    out, err, rc = h.operacake("-l")
    assert rc == 0 and "OK boards" in out
    assert _spawn_count(h) == 2         # two busy failures were absorbed


def test_blocking_raises_when_retries_exhausted(stub_device):
    h = _fast(stub_device(operacake=dict(stdout_lines=["never seen"],
                                         busy_fails=99)))
    with pytest.raises(HackRFDeviceError, match="Resource busy"):
        h.operacake("-l")
    assert _spawn_count(h) == h.busy_retries + 1   # initial try + retries


def test_busy_retries_zero_fails_immediately(stub_device):
    h = _fast(stub_device(operacake=dict(busy_fails=1)))
    h.busy_retries = 0
    with pytest.raises(HackRFDeviceError, match="Resource busy"):
        h.operacake("-l")
    assert _spawn_count(h) == 1


# ---- stream mode (sweep, monitor, and the persistent receiver ride on it) --
_SWEEP_ROW = ("2026-06-18, 12:00:00.000000, 88000000, 88500000, 100000.00, "
              "8192, -71.2, -70.1, -69.9, -72.4, -71.8")


def test_stream_retries_before_first_row(stub_device):
    h = _fast(stub_device(sweep=dict(stdout_lines=[_SWEEP_ROW],
                                     busy_fails=1)))
    rows = h.sweep_collect(88e6, 89e6, num_sweeps=1)
    assert rows and rows[0]["hz_low"] == 88000000


def test_receiver_open_retries_through_busy(stub_device):
    h = _fast(stub_device(transfer=dict(emit_bytes=[0, 64] * 65536,
                                        busy_fails=1)))
    with h.open_receiver(100e6, 2e6) as rx:
        iq = rx.read(1024)
    assert len(iq) == 1024
