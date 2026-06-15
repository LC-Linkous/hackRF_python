#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_realtime.py'
#   The features that narrow the gap with libhackrf binders: callback-style
#   receive (capture_callback), sequential multi-frequency scanning
#   (scan_frequencies), and proof the optimized decode is bit-identical to
#   the old path. Cross-platform stubs; no device.
##--------------------------------------------------------------------\

import numpy as np
import pytest

from hackrfpy import HackRF

_IQ_200 = list(b"\x01\x02" * 100)   # 100 I/Q pairs


# ---- capture_callback: binder-style inverted loop --------------------------
def test_capture_callback_fires_per_block(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    seen = []
    total = h.capture_callback(433.92e6, 8e6,
                               on_block=lambda iq, n: seen.append((len(iq), n)),
                               max_samples=40)
    assert total >= 40
    assert seen                       # callback actually fired
    # n_so_far is the running count BEFORE each block
    assert seen[0][1] == 0


def test_capture_callback_stops_on_false(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    calls = {"n": 0}

    def cb(iq, n):
        calls["n"] += 1
        return False                  # stop after the first block

    h.capture_callback(433.92e6, 8e6, on_block=cb)
    assert calls["n"] == 1


def test_capture_callback_max_blocks(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    calls = {"n": 0}
    h.capture_callback(433.92e6, 8e6,
                       on_block=lambda iq, n: calls.__setitem__("n", calls["n"] + 1),
                       max_blocks=1)
    assert calls["n"] == 1


# ---- scan_frequencies: sequential multi-freq capture -----------------------
def test_scan_frequencies_returns_dict(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    freqs = [433.92e6, 868e6, 915e6]
    out = h.scan_frequencies(freqs, 8e6, num_samples=20)
    assert set(out.keys()) == set(freqs)
    assert all(isinstance(v, np.ndarray) and len(v) == 20 for v in out.values())


def test_scan_frequencies_on_capture_callback(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    seen = []
    out = h.scan_frequencies([100e6, 200e6], 8e6, num_samples=10,
                             on_capture=lambda f, iq: seen.append(f))
    assert out is None                # callback mode returns nothing
    assert seen == [100e6, 200e6]     # called per frequency, in order


# ---- decode optimization: bit-identical to the documented behavior ---------
def test_optimized_decode_matches_reference():
    h = HackRF()
    # reference: the straightforward int8 -> complex64 / 128 path
    for raw in [bytes([0, 0, 127, 0, 0x80, 5, 10, 0xF6]),
                bytes([10, 20, 30]),          # odd trailing byte dropped
                b"",
                bytes(range(16))]:
        a = np.frombuffer(raw, dtype=np.int8)
        if a.size % 2:
            a = a[:-1]
        ref = (a[0::2].astype(np.float32) + 1j * a[1::2].astype(np.float32)
               ).astype(np.complex64) / 128.0
        got = h.decode_iq(raw)
        assert np.array_equal(got, ref), f"decode mismatch on {list(raw)}"
        assert got.dtype == np.complex64