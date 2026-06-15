#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_monitor.py'
#   monitor_frequencies: sweep-backed power-over-time monitoring. Distinct
#   from scan_frequencies (which returns IQ). Verifies frequency->segment
#   mapping, multi-pass yielding, final-pass flush, and callback mode.
##--------------------------------------------------------------------\

from hackrfpy import HackRF


# two sweep passes (two timestamps), segments covering 100 and 433 MHz
_TWO_PASS = [
    "2026-06-15, 12:00:00.000000, 98000000, 102000000, 1000000.00, 4, -70, -65, -68, -72",
    "2026-06-15, 12:00:00.000000, 431000000, 435000000, 1000000.00, 4, -55, -50, -52, -58",
    "2026-06-15, 12:00:01.000000, 98000000, 102000000, 1000000.00, 4, -71, -66, -69, -73",
    "2026-06-15, 12:00:01.000000, 431000000, 435000000, 1000000.00, 4, -45, -40, -42, -48",
]


def test_monitor_maps_freqs_to_segments(stub_device):
    h = stub_device(sweep=dict(stdout_lines=_TWO_PASS))
    out = h.monitor_frequencies([100e6, 433e6], span_hz=2e6)
    assert len(out) == 2                      # both passes (incl. final flush)
    # each pass maps both requested frequencies to a power value
    for u in out:
        assert set(u.keys()) == {100e6, 433e6}
        assert all(v is not None for v in u.values())


def test_monitor_tracks_power_change(stub_device):
    h = stub_device(sweep=dict(stdout_lines=_TWO_PASS))
    out = h.monitor_frequencies([433e6], span_hz=2e6)
    # 433 MHz segment rises from mean(-55,-50,-52,-58)=-53.75 to
    # mean(-45,-40,-42,-48)=-43.75 between passes
    assert out[0][433e6] < out[1][433e6]      # power increased
    assert abs(out[1][433e6] - (-43.75)) < 0.1


def test_monitor_callback_mode(stub_device):
    h = stub_device(sweep=dict(stdout_lines=_TWO_PASS))
    seen = []
    r = h.monitor_frequencies([100e6], on_update=lambda u: seen.append(u))
    assert r is None                          # callback mode returns nothing
    assert len(seen) == 2


def test_monitor_callback_stops_on_false(stub_device):
    h = stub_device(sweep=dict(stdout_lines=_TWO_PASS))
    calls = {"n": 0}

    def cb(u):
        calls["n"] += 1
        return False                          # stop after first pass

    h.monitor_frequencies([100e6], on_update=cb)
    assert calls["n"] == 1
