#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_hardware.py'
#   Tests that need a connected HackRF. Auto-skip when absent (see conftest).
#
#   SAFETY: every test here is READ-ONLY / receive-only. None transmit, none
#   write firmware. They run automatically whenever a board is detected, so
#   they must never do anything that could affect hardware or the spectrum.
#
#   These exist to validate the real device paths -- the things stubs and
#   frozen fixtures can't prove: that hackrf_info output matches the parser,
#   that a real capture yields the right sample count, that hackrf_sweep -N
#   actually terminates, that the reap paths stop a real child cleanly.
##--------------------------------------------------------------------\

import time

import numpy as np
import pytest

from hackrfpy import HackRF, load_iq, read_sigmf_meta

# A small, USB-friendly capture config used across tests. 2 Msps keeps data
# volume low; FM center is always legal to receive and usually has signal.
RX_FREQ = 100_000_000
RX_RATE = 2_000_000
SWEEP_LO, SWEEP_HI = 88_000_000, 108_000_000


# ---- identity / detection --------------------------------------------------
@pytest.mark.hardware
def test_info_returns_board():
    h = HackRF()
    parsed = h.info()
    assert parsed["boards"], "expected a connected board"
    b = parsed["boards"][0]
    # real device must report a serial and a HackRF board id
    assert b.get("serial_number")
    assert "hackrf" in (b.get("board_id_number", "")).lower()


@pytest.mark.hardware
def test_detect_reports_ready():
    h = HackRF()
    det = h.detect()
    assert det["found"] is True
    assert det["ready"] is True
    assert det["count"] >= 1
    assert det["boards"][0]["is_hackrf"] is True
    # firmware should be reported (string like "2024.02.1 (API:1.08)")
    assert det["boards"][0]["firmware"]


@pytest.mark.hardware
def test_identify_matches_detect():
    h = HackRF()
    board = h.identify()
    assert board is not None
    assert board["is_hackrf"] is True
    # identify by the real serial substring should find the same board
    serial = board["serial"]
    again = h.identify(serial[-8:])
    assert again is not None
    assert again["serial"] == serial


@pytest.mark.hardware
def test_from_device_probes_ok():
    # fail-fast constructor: should succeed with a board present
    h = HackRF.from_device()
    assert h is not None


@pytest.mark.hardware
def test_features_reports_capabilities():
    h = HackRF()
    feats = h.features()
    # a real modern board/tools should support streaming + sweep -N
    assert feats["stdout_streaming"] is True
    assert feats["sweep_num_sweeps"] is True


# ---- doctor / preflight ----------------------------------------------------
@pytest.mark.hardware
def test_doctor_finds_tools():
    h = HackRF()
    report = h.doctor()
    assert report["tools"].get("hackrf_info")
    assert not report["problems"], report["problems"]


@pytest.mark.hardware
def test_preflight_clean_with_board():
    h = HackRF()
    report = h.preflight()
    # core tools present, board detected -> no problems
    assert not report["problems"], report["problems"]
    assert report["features"]["stdout_streaming"] is True


# ---- receive: the real capture path ---------------------------------------
@pytest.mark.hardware
def test_capture_array_returns_exact_count():
    h = HackRF()
    n = 100_000
    iq = h.capture_array(RX_FREQ, RX_RATE, n)
    assert iq.dtype == np.complex64
    assert len(iq) == n                      # EXACTLY the requested count
    # real samples should not be all-zero (we're receiving something)
    assert not np.all(iq == 0)
    # int8 full-scale normalized to ~[-1,1)
    assert np.max(np.abs(iq)) <= 1.5


@pytest.mark.hardware
def test_capture_to_file_with_sigmf(tmp_path):
    h = HackRF()
    out = str(tmp_path / "cap.iq")
    h.capture(RX_FREQ, RX_RATE, num_samples=50_000, out=out, sigmf=True)
    iq = load_iq(out)
    assert len(iq) == 50_000
    meta = read_sigmf_meta(out)
    assert meta["captures"][0]["core:frequency"] == RX_FREQ
    assert meta["global"]["core:sample_rate"] == RX_RATE


@pytest.mark.hardware
def test_capture_callback_fires_on_real_stream():
    h = HackRF()
    blocks = {"n": 0, "samples": 0}

    def on_block(iq, total):
        blocks["n"] += 1
        blocks["samples"] += len(iq)

    total = h.capture_callback(RX_FREQ, RX_RATE, on_block=on_block,
                               max_samples=200_000)
    assert blocks["n"] > 0                   # callback actually fired
    assert total >= 200_000


@pytest.mark.hardware
def test_capture_stream_context_reaps():
    # the stream context manager must yield real blocks and stop cleanly
    h = HackRF()
    got = 0
    with h.capture_stream(RX_FREQ, RX_RATE) as blocks:
        for iq in blocks:
            got += len(iq)
            if got >= 200_000:
                break                        # early exit must reap the child
    assert got >= 200_000


@pytest.mark.hardware
def test_scan_frequencies_real():
    h = HackRF()
    freqs = [100_000_000, 433_920_000]
    out = h.scan_frequencies(freqs, RX_RATE, num_samples=20_000)
    assert set(out.keys()) == set(freqs)
    assert all(len(v) == 20_000 for v in out.values())


# ---- sweep: the termination + ordering behavior ---------------------------
@pytest.mark.hardware
def test_sweep_collect_terminates():
    # the big one: a bounded sweep (-N) must actually TERMINATE, not hang.
    h = HackRF()
    t0 = time.time()
    rows = h.sweep_collect(SWEEP_LO, SWEEP_HI, num_sweeps=1)
    elapsed = time.time() - t0
    assert rows, "sweep returned no rows"
    assert elapsed < 30, "sweep did not terminate promptly"
    # each row has the expected structure
    r = rows[0]
    assert "hz_low" in r and "hz_high" in r and "db" in r
    assert isinstance(r["db"], list) and len(r["db"]) >= 1


@pytest.mark.hardware
def test_sweep_rows_share_timestamp_per_pass():
    # rows of one sweep pass share a timestamp (the waterfall relies on this)
    h = HackRF()
    rows = h.sweep_collect(SWEEP_LO, SWEEP_HI, num_sweeps=1)
    times = set(r["time"] for r in rows)
    # one pass -> ideally one timestamp; allow a little slack for boundary
    assert len(times) <= 2


@pytest.mark.hardware
def test_sweep_to_file_writes(tmp_path):
    h = HackRF()
    out = str(tmp_path / "sweep.csv")
    h.sweep_to_file(SWEEP_LO, SWEEP_HI, out, num_sweeps=1)
    import os
    assert os.path.getsize(out) > 0


# ---- read-only device management -------------------------------------------
@pytest.mark.hardware
def test_operacake_list_runs():
    # no Opera Cake attached is fine -- it just must run without error
    h = HackRF()
    out = h.operacake_list()
    text = out[0] if isinstance(out, tuple) else str(out)
    assert isinstance(text, str)
