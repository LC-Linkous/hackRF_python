#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_receiver.py'
#   PersistentReceiver: one long-lived hackrf_transfer drained in segments,
#   amortizing the per-capture startup cost. Verifies exact-count reads from
#   a SINGLE process launch, the blocks()/callback() access patterns, the
#   read-size tunability, and clean close.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

import numpy as np



def _streaming_device(stub_device, nbytes=200_000):
    # a stub hackrf_transfer that streams a long continuous int8 ramp
    payload = list((bytes(range(256)) * (nbytes // 256 + 1))[:nbytes])
    return stub_device(transfer=dict(emit_bytes=payload, idle=False))


def test_receiver_exact_counts_single_process(stub_device):
    h = _streaming_device(stub_device)
    launches = {"n": 0}
    orig = h._stream
    def counting(*a, **k):
        launches["n"] += 1
        return orig(*a, **k)
    h._stream = counting

    with h.open_receiver(100e6, 8e6) as rx:
        a = rx.read(1000)
        b = rx.read(1000)
        c = rx.read(3000)
    assert len(a) == 1000
    assert len(b) == 1000
    assert len(c) == 3000
    assert a.dtype == np.complex64
    # THE point: all reads came from ONE process launch
    assert launches["n"] == 1


def test_receiver_blocks_iteration(stub_device):
    h = _streaming_device(stub_device)
    with h.open_receiver(100e6, 8e6) as rx:
        got = 0
        for blk in rx.blocks():
            got += len(blk)
            if got >= 5000:
                break
    assert got >= 5000


def test_receiver_callback_max_samples(stub_device):
    h = _streaming_device(stub_device)
    fired = {"n": 0}
    with h.open_receiver(100e6, 8e6) as rx:
        total = rx.callback(
            lambda iq, t: fired.__setitem__("n", fired["n"] + 1),
            max_samples=4000)
    assert fired["n"] >= 1
    assert total >= 4000


def test_receiver_callback_stops_on_false(stub_device):
    h = _streaming_device(stub_device)
    calls = {"n": 0}
    def cb(iq, t):
        calls["n"] += 1
        return False
    with h.open_receiver(100e6, 8e6) as rx:
        rx.callback(cb)
    assert calls["n"] == 1


def test_receiver_read_size_tunable(stub_device):
    h = _streaming_device(stub_device)
    rx = h.open_receiver(100e6, 8e6, read_samples=4096)
    assert rx.read_samples == 4096
    rx.close()


def test_receiver_close_is_clean(stub_device):
    h = _streaming_device(stub_device)
    rx = h.open_receiver(100e6, 8e6)
    rx.read(100)
    rx.close()
    assert rx._closed is True
    assert rx._gen is None
    # double close is safe
    rx.close()


def test_receiver_records_params_for_calibration(stub_device):
    # gains should land in last_params so relative_power_db can read them
    h = _streaming_device(stub_device)
    with h.open_receiver(100e6, 8e6, lna=16, vga=20) as rx:
        rx.read(100)
        assert h.last_params is not None
        # capture() records under 'lna'/'vga'; relative_power_db reads both
        assert h.last_params["lna"] == 16
        assert h.last_params["vga"] == 20
        # and the calibration helper can read them back
        assert h.relative_power_db(-6.0) == -6.0 - 36.0


# ---- atexit backstop contract ----------------------------------------------
def test_receiver_satisfies_the_live_backstop(stub_device):
    # REGRESSION: PersistentReceiver registers itself in core._LIVE, whose atexit
    # hook does `if h.is_alive(): h.stop()`. is_alive() was missing entirely, so
    # the AttributeError was swallowed by the hook's bare `except Exception` and
    # an orphaned receiver was NEVER reaped on interpreter shutdown.
    from hackrfpy.core import _LIVE, _stop_all_live
    h = _streaming_device(stub_device)
    recv = h.open_receiver(433.92e6, 8e6)
    recv.read(16)                                  # opens the stream
    assert recv.is_alive()
    assert recv in set(_LIVE)                      # registered on the backstop
    _stop_all_live()                               # what atexit runs
    assert not recv.is_alive(), "backstop did not reap the live receiver"


def test_read_after_close_raises_typed_error(stub_device):
    # Previously fell through _ensure_open with self._gen None and blew up on
    # `for chunk in None` -> raw TypeError. Now a typed, actionable error.
    from hackrfpy.exceptions import HackRFDeviceError
    import pytest
    h = _streaming_device(stub_device)
    recv = h.open_receiver(433.92e6, 8e6)
    recv.read(16)
    recv.close()
    with pytest.raises(HackRFDeviceError, match="closed"):
        recv.read(16)


# ---------------------------------------------------------------------------
# Odd-length chunks must not swap I and Q.
#
# A pipe is free to return fewer bytes than read1() asked for, so a raw chunk
# can end in the middle of an I/Q pair. decode_iq drops an odd trailing byte;
# if blocks() handed it such a chunk directly, that one dropped byte would
# swap I and Q for every sample afterwards -- a capture whose power stats look
# healthy while the phase is garbage. capture()'s own stream path carries the
# odd byte forward; blocks() did not. These pin the carry on blocks(), and that
# read() and blocks() share one carry so they can be mixed.
# ---------------------------------------------------------------------------

def _odd_chunk_receiver(stub_device, chunks):
    """A PersistentReceiver whose raw stream is exactly `chunks`."""
    h = _streaming_device(stub_device, nbytes=16)
    rx = h.open_receiver(100e6, 8e6)
    rx._gen = iter(chunks)            # bypass the child; feed raw bytes directly
    rx._ensure_open = lambda: rx._gen
    return rx


def test_blocks_carries_odd_byte_instead_of_swapping_iq(stub_device):
    # ramp: I = 0,2,4,..  Q = 1,3,5,..  so a correct decode has I even, Q odd
    n = 1000
    raw = bytes(i % 256 for i in range(2 * n))
    # split into deliberately odd-sized chunks (7, 13, 1, 3, ...)
    sizes = [7, 13, 1, 3, 101, 9]
    chunks, pos = [], 0
    while pos < len(raw):
        for s in sizes:
            chunks.append(raw[pos:pos + s])
            pos += s
            if pos >= len(raw):
                break
    chunks = [c for c in chunks if c]
    assert any(len(c) % 2 for c in chunks), "test needs odd chunks"

    rx = _odd_chunk_receiver(stub_device, chunks)
    got = np.concatenate(list(rx.blocks()))
    assert len(got) == n
    # decode_iq divides by 128 -> undo to compare against the raw ramp
    i = np.rint(got.real * 128).astype(int) % 256
    q = np.rint(got.imag * 128).astype(int) % 256
    expect = np.arange(2 * n) % 256
    # int8 wraps at 128, so compare modulo 256 on the signed values
    assert np.array_equal(i % 256, expect[0::2])
    assert np.array_equal(q % 256, expect[1::2])
    assert rx.total_samples == n


def test_blocks_and_read_share_one_carry(stub_device):
    n = 64
    raw = bytes(i % 256 for i in range(2 * n))
    # first chunk odd, so blocks() leaves one byte in the carry; then read()
    # must pick it up and stay pair-aligned.
    chunks = [raw[:5], raw[5:40], raw[40:]]
    rx = _odd_chunk_receiver(stub_device, chunks)
    gen = rx.blocks()
    first = next(gen)                  # consumes raw[:5] -> 2 samples, 1 byte carried
    assert len(first) == 2
    assert rx._carry == raw[4:5]
    rest = rx.read(n - 2)
    got = np.concatenate([first, rest])
    assert len(got) == n
    i = np.rint(got.real * 128).astype(int) % 256
    assert np.array_equal(i, (np.arange(2 * n) % 256)[0::2])


def test_blocks_through_a_real_pipe_with_odd_writes(stub_device):
    """Same contract, but the odd boundaries come from an actual child process
    writing and flushing odd-sized pieces into the stdout pipe -- the path a
    downstream IQSource adapter (sdr_dsp's HackRFCapture) streams through.
    On the pre-fix code this swapped I and Q from the first odd piece on."""
    n = 200_000
    raw = bytes(i % 256 for i in range(2 * n))
    h = stub_device(transfer=dict(emit_bytes=raw, idle=False,
                                  emit_chunk_sizes=[7, 65537, 3, 131071, 1]))
    got = []
    with h.open_receiver(100e6, 8e6) as rx:
        for blk in rx.blocks():
            got.append(blk)
            if sum(len(g) for g in got) >= n:
                break
    x = np.concatenate(got)[:n]
    i = np.rint(x.real * 128).astype(int) % 256
    q = np.rint(x.imag * 128).astype(int) % 256
    expect = np.arange(2 * n) % 256
    assert np.array_equal(i, expect[0::2])
    assert np.array_equal(q, expect[1::2])
