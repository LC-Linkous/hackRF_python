#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_monitor.py'
#   monitor_frequencies: sweep-backed power-over-time monitoring. Distinct
#   from scan_frequencies (which returns IQ). Verifies frequency->segment
#   mapping, multi-pass yielding, final-pass flush, and callback mode.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\



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
    # 433 MHz sits in bin idx 2 of the 431-435 segment (1 MHz bins). The
    # reading is the max of bins 1..3: pass 1 max(-50,-52,-58) = -50, pass 2
    # max(-40,-42,-48) = -40 -- the covering bin, not the segment mean, so a
    # narrowband carrier is no longer diluted by its quiet neighbors.
    assert out[0][433e6] < out[1][433e6]      # power increased
    assert abs(out[1][433e6] - (-40.0)) < 0.1


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


# ---- regression: covering-bin power, not segment mean ----------------------
# A strong narrowband carrier in one bin of a wide segment must dominate the
# reading. The old segment-mean proxy diluted it toward the noise floor.
_HOT_BIN = [
    "2026-06-15, 12:00:00.000000, 430000000, 440000000, 1000000.00, 4, "
    "-80, -80, -80, -20, -80, -80, -80, -80, -80, -80",
    "2026-06-15, 12:00:01.000000, 430000000, 440000000, 1000000.00, 4, "
    "-80, -80, -80, -20, -80, -80, -80, -80, -80, -80",
]


def test_monitor_reads_covering_bin_not_segment_mean(stub_device):
    h = stub_device(sweep=dict(stdout_lines=_HOT_BIN))
    out = h.monitor_frequencies([433.5e6], span_hz=1e6)
    # 433.5 MHz -> bin idx 3 (the -20 dB carrier). The segment mean would
    # have read -74; the covering bin reads the carrier itself.
    assert abs(out[0][433.5e6] - (-20.0)) < 0.1


# ---- pass detection must survive real per-row timestamps -------------------
# Real hackrf_sweep timestamps each ROW individually; the stub fixtures used
# one timestamp per pass, which hid a boundary bug: flushing on timestamp
# change emitted PARTIAL updates several times per pass on real hardware
# (most watched frequencies None -- seen live as a wall of "--"). The pass
# boundary is now the sweep WRAP (a segment arriving again), which is
# timestamp-independent. These rows reproduce the hardware shape: two full
# passes over two segments, every row with a distinct timestamp.
_PER_ROW_TS_PASSES = (
    "2026-09-19, 12:00:00.100000, 88000000, 88500000, 100000.00, 8192, "
    "-71.0, -70.0, -69.0, -72.0, -71.0\n"
    "2026-09-19, 12:00:00.230000, 88500000, 89000000, 100000.00, 8192, "
    "-70.0, -20.0, -72.0, -73.0, -74.0\n"
    "2026-09-19, 12:00:00.360000, 88000000, 88500000, 100000.00, 8192, "
    "-71.5, -70.5, -69.5, -72.5, -71.5\n"
    "2026-09-19, 12:00:00.490000, 88500000, 89000000, 100000.00, 8192, "
    "-70.5, -21.0, -72.5, -73.5, -74.5\n"
)


def test_updates_are_complete_despite_per_row_timestamps(stub_device):
    h = stub_device(sweep=dict(stdout_lines=_PER_ROW_TS_PASSES.strip()
                               .split("\n")))
    seen = []
    h.monitor_frequencies([88.6e6], span_hz=0.4e6,
                          on_update=lambda u: seen.append(u))
    # two passes -> exactly two updates (wrap flush + final flush), and BOTH
    # carry a real reading for the watched frequency -- no partial updates
    assert len(seen) == 2, f"expected 2 complete updates, got {len(seen)}"
    assert seen[0][88.6e6] == -20.0       # bin 1 of pass-1 second segment
    assert seen[1][88.6e6] == -21.0       # same bin, pass 2
    assert all(u[88.6e6] is not None for u in seen)
