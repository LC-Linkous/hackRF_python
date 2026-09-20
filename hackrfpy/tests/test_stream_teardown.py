#! /usr/bin/python3

##--------------------------------------------------------------------\\
#   hackrfpy  'tests/test_stream_teardown.py'
#   The frozen-writer leak: a stream consumer that breaks out stops
#   reading the pipe; at capture rates the 64 KB pipe fills in
#   milliseconds and the child blocks inside write(). Signal handlers
#   that only set an exit flag can never reach it from a blocked write,
#   and the old teardown ended at an unreaped terminate() -- so on real
#   hardware, hackrf_transfer stayed frozen, HOLDING THE USB CLAIM, and
#   every later open in the process failed "Resource busy" (found on the
#   Linux verification run: a wall of 7 failures starting immediately
#   after the two stream-breakout tests). Teardown now gives the clean
#   interrupt a window, then closes the read end to unblock the writer,
#   then completes the terminate->kill ladder.
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\\

import time


def test_breakout_reaps_flooding_writer(stub_device):
    # a deaf, flooding child: blocked in write() once we stop reading,
    # immune to the flag-setting signals -- the hardware failure mode
    h = stub_device(transfer=dict(stdout_flood=8_000_000,
                                  ignore_interrupt=True))
    gen = h._run(["transfer", "-r", "-"], mode="stream")
    next(gen)                       # stream is live; now abandon it
    t0 = time.monotonic()
    gen.close()                     # GeneratorExit -> teardown under test
    took = time.monotonic() - t0
    assert took < 6.0, f"teardown took {took:.1f}s -- ladder not bounded"


def test_breakout_then_immediate_reopen_works(stub_device):
    # the user-visible contract: after abandoning one stream, the next
    # device operation must not find a leaked child in the way
    h = stub_device(transfer=dict(stdout_flood=8_000_000,
                                  ignore_interrupt=True))
    gen = h._run(["transfer", "-r", "-"], mode="stream")
    next(gen)
    gen.close()
    gen2 = h._run(["transfer", "-r", "-"], mode="stream")
    assert next(gen2)               # second stream delivers data
    gen2.close()


def test_breakout_clean_child_still_gets_interrupt_window(stub_device,
                                                          tmp_path):
    # the fix must NOT cost well-behaved children their clean exit: the
    # SIGINT handler (marker write) runs before the pipe is closed
    marker = str(tmp_path / "sig")
    h = stub_device(transfer=dict(emit_bytes=[0, 64] * 4096, idle=True,
                                  marker=marker))
    gen = h._run(["transfer", "-r", "-"], mode="stream")
    next(gen)
    gen.close()
    import os
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not os.path.exists(marker):
        time.sleep(0.05)
    assert os.path.exists(marker), "clean interrupt window was lost"
