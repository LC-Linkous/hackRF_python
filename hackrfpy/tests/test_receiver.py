#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_receiver.py'
#   PersistentReceiver: one long-lived hackrf_transfer drained in segments,
#   amortizing the per-capture startup cost. Verifies exact-count reads from
#   a SINGLE process launch, the blocks()/callback() access patterns, the
#   read-size tunability, and clean close.
##--------------------------------------------------------------------\

import numpy as np

from hackrfpy import HackRF


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
