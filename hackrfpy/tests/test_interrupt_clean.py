#! /usr/bin/python3

##--------------------------------------------------------------------\\
#   hackrfpy  'tests/test_interrupt_clean.py'
#   The CLEAN-interrupt contract, distinguished from "the child died".
#   stop()'s whole point is that hackrf_transfer flushes + closes on the
#   interrupt signal so a capture file is never truncated; the older
#   lifecycle tests proved the child EXITS, but their stub treated the
#   interrupt and the terminate() escalation identically, so a broken
#   CTRL_BREAK path could hide behind a working escalation.
#
#   These tests assert, on BOTH platforms (no Windows skips -- Windows is
#   the target platform, and on Windows the signal must also traverse the
#   .bat -> python launcher layer, exactly like the real .bat-wrapped
#   tools):
#     1. the interrupt SIGNAL ITSELF arrives (SIGINT on POSIX, SIGBREAK
#        from CTRL_BREAK_EVENT on Windows) -- the stub records the signal
#        NAME it caught, and the escalation would record a different one
#        (or none: TerminateProcess runs no handler)
#     2. output written by the child's handler AFTER the interrupt is
#        drained into stop()'s result -- the no-truncation contract
#     3. a child that ignores the interrupt is still reaped via the
#        grace-timeout terminate() escalation, reported as unclean
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\\

import os
import sys
import time


_EXPECTED_INTERRUPT = "SIGBREAK" if sys.platform == "win32" else "SIGINT"


def _wait_for_output(proc, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in b"".join(proc._out_chunks):
            return True
        time.sleep(0.05)
    return False


# ---- 1. the clean signal itself is delivered -------------------------------
def test_stop_delivers_interrupt_signal_not_escalation(stub_device, tmp_path):
    marker = str(tmp_path / "sig")
    h = stub_device(transfer=dict(
        stdout_lines=["started"], idle=True, marker=marker))
    proc = h._run(["transfer", "-r", "x.iq"], mode="handle")
    assert _wait_for_output(proc, b"started")
    out, err, rc = proc.stop()
    assert os.path.exists(marker), "no signal reached the child at all"
    with open(marker) as f:
        caught = f.read().strip()
    # SIGTERM here would mean the child only died via the terminate()
    # escalation; empty would mean a pre-signal-name stub. Both are failures
    # of the CLEAN path this test exists to pin.
    assert caught == _EXPECTED_INTERRUPT, (
        f"child caught {caught!r}, expected {_EXPECTED_INTERRUPT!r} -- the "
        f"clean interrupt path is not the one that ended the child")
    assert rc == 0                       # handler exit, not a kill status


# ---- 2. the post-interrupt flush survives into the result ------------------
def test_interrupt_flush_is_drained_not_truncated(stub_device):
    sentinel = "FINAL_FLUSH_8f3a"
    h = stub_device(transfer=dict(
        stdout_lines=["started"], idle=True, tail_on_interrupt=sentinel))
    proc = h._run(["transfer", "-r", "x.iq"], mode="handle")
    assert _wait_for_output(proc, b"started")
    out, err, rc = proc.stop()
    # the sentinel is written by the child's signal handler AFTER stop()
    # fires the interrupt; finding it in the drained result proves the
    # interrupt -> handler -> flush -> drain chain end to end
    assert sentinel.encode() in out, (
        "output written during interrupt handling was lost -- this is the "
        "truncated-capture failure mode stop() exists to prevent")
    assert rc == 0


# ---- 3. a deaf child is still reaped, and reported as unclean --------------
def test_stop_escalates_on_ignored_interrupt(stub_device, tmp_path):
    marker = str(tmp_path / "sig")
    h = stub_device(transfer=dict(
        stdout_lines=["started"], idle=True, marker=marker,
        ignore_interrupt=True))
    proc = h._run(["transfer", "-r", "x.iq"], mode="handle")
    assert _wait_for_output(proc, b"started")
    t0 = time.monotonic()
    out, err, rc = proc.stop(grace=0.5)
    assert time.monotonic() - t0 < 10.0      # bounded by grace + terminate
    assert not proc.is_alive()
    # no handler ran (SIG_IGN), so no marker content and a non-zero status:
    # the caller can tell this reap was NOT the clean flush path
    assert not os.path.exists(marker) or not open(marker).read().strip()
    assert rc != 0
