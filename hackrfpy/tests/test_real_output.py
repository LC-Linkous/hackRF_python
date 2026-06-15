#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_real_output.py'
#   Regression tests against ACTUAL hackrf_info output from a real HackRF
#   One (git-built tools, 2024 firmware). These pin the parser against the
#   formatting quirks real hardware produces -- a git tools version with no
#   year, a value on an indented continuation line, and trailing free-text
#   USB warnings -- none of which the original synthetic fixtures had.
#   Serial / part ID anonymized.
##--------------------------------------------------------------------\

import os

from hackrfpy import HackRF
from hackrfpy._commands.info import InfoMixin

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _real_text():
    return open(os.path.join(FIXTURES, "hackrf_info_real.txt")).read()


# ---- parse_info against real output ----------------------------------------
def test_real_info_parses_one_board():
    parsed = InfoMixin.parse_info(_real_text())
    assert len(parsed["boards"]) == 1
    b = parsed["boards"][0]
    assert b["serial_number"].endswith("89abcdef")
    assert b["board_id_number"] == "2 (HackRF One)"
    assert b["firmware_version"] == "2024.02.1 (API:1.08)"
    assert b["hardware_revision"] == "older than r6"


def test_real_info_continuation_line_captured():
    # "Hardware supported by installed firmware:" has its value on the NEXT
    # indented line, not after the colon. The original parser dropped it.
    parsed = InfoMixin.parse_info(_real_text())
    b = parsed["boards"][0]
    assert b["hardware_supported_by_installed_firmware"] == "HackRF One"


def test_real_info_usb_warnings_collected():
    # Trailing no-colon warning lines must be collected, not silently dropped.
    parsed = InfoMixin.parse_info(_real_text())
    assert any("same USB bus" in w for w in parsed["warnings"])
    assert any("high sample rates" in w for w in parsed["warnings"])


def test_real_info_git_tools_version():
    parsed = InfoMixin.parse_info(_real_text())
    assert parsed["library"]["hackrf_info_version"] == "git-b1dbb47"
    assert "0.10.0" in parsed["library"]["libhackrf_version"]


# ---- detect() against real output ------------------------------------------
def test_detect_real_output(stub_device):
    h = stub_device(info=dict(stdout_lines=_real_text().splitlines()))
    det = h.detect()
    assert det["found"] and det["ready"]
    assert det["count"] == 1
    assert det["multiple"] is False
    b = det["boards"][0]
    assert b["is_hackrf"] is True
    assert b["firmware"] == "2024.02.1 (API:1.08)"
    assert b["firmware_stale"] is False
    assert det["tools_version"] == "git-b1dbb47"


# ---- features() with a git tools version + real firmware -------------------
def test_features_git_tools_modern_firmware():
    # The real failure: git-b1dbb47 has no year. features() must use the
    # FIRMWARE year (2024) and recognize the git build as modern, not fall
    # through to a lucky "unknown -> assume modern".
    h = HackRF()
    f = h.features("git-b1dbb47", "2024.02.1 (API:1.08)")
    assert f["version_known"] is True          # not "unknown"
    assert f["is_git_build"] is True
    assert f["stdout_streaming"] is True
    assert f["sweep_num_sweeps"] is True
    assert f["firmware_version"].startswith("2024")


def test_detect_surfaces_usb_warnings(stub_device):
    h = stub_device(info=dict(stdout_lines=_real_text().splitlines()))
    det = h.detect()
    assert any("USB bus" in w for w in det["warnings"])


# ---- real IQ bytes: decode proves out on TRUE hardware samples -------------
def test_real_iq_decodes_nonzero():
    # sample_real.iq is a slice from the MIDDLE of a real 100 MHz capture (not
    # the settling-transient head), so it must be real nonzero signal --
    # proving decode_iq/load_iq work on true device bytes. The exact length
    # depends on --iq-fixture-bytes at collection time, so assert structure +
    # nonzero rather than a hardcoded count.
    import numpy as np
    from hackrfpy import load_iq
    path = os.path.join(FIXTURES, "sample_real.iq")
    if not os.path.exists(path):
        import pytest
        pytest.skip("sample_real.iq fixture not collected")
    raw_len = os.path.getsize(path)
    iq = load_iq(path)
    assert iq.dtype == np.complex64
    assert len(iq) == raw_len // 2             # 2 int8 bytes -> 1 complex
    assert len(iq) > 0
    assert not np.all(iq == 0), "real capture slice should not be all-zero"


# ---- real sweep output: structure + the OUT-OF-ORDER segment behavior ------
def _real_sweep_lines():
    return open(os.path.join(FIXTURES, "sweep_sample_real.csv")).read().splitlines()


def test_real_sweep_parses_four_rows():
    from hackrfpy._commands.sweep import SweepMixin
    rows = [SweepMixin.parse_sweep_line(l) for l in _real_sweep_lines()]
    good = [r for r in rows if r]
    assert len(good) == 4
    # the garbage line is rejected
    assert rows[-1] is None
    # real output: 5 dB bins, 20 FFT samples, 1 MHz bin width
    assert all(len(r["db"]) == 5 for r in good)
    assert all(r["num_samples"] == 20 for r in good)
    assert all(r["bin_width"] == 1_000_000.0 for r in good)


def test_real_sweep_segments_are_out_of_order():
    # REAL hackrf_sweep interleaves frequency segments -- it does NOT emit
    # them low-to-high. This pins that behavior so no one writes consumer code
    # assuming sorted order. Observed: 88, 98, 93, 103 (MHz).
    from hackrfpy._commands.sweep import SweepMixin
    good = [r for r in (SweepMixin.parse_sweep_line(l)
                        for l in _real_sweep_lines()) if r]
    lows = [r["hz_low"] for r in good]
    assert lows != sorted(lows), "real sweep rows were in order this time, " \
        "but the parser/consumers must not RELY on order"
    # all rows share one timestamp -> they belong to a single sweep pass
    assert len(set(r["time"] for r in good)) == 1


def test_real_sweep_reassembles_correctly_when_sorted():
    # The safe way to reconstruct a spectrum line: key by hz_low, sort. This
    # is what waterfall_realtime.py does, and it survives the out-of-order rows.
    import numpy as np
    from hackrfpy._commands.sweep import SweepMixin
    good = [r for r in (SweepMixin.parse_sweep_line(l)
                        for l in _real_sweep_lines()) if r]
    bins = {r["hz_low"]: np.array(r["db"]) for r in good}
    ordered_freqs = sorted(bins)
    assert [f // 1_000_000 for f in ordered_freqs] == [88, 93, 98, 103]
    line = np.concatenate([bins[k] for k in ordered_freqs])
    assert len(line) == 20      # 4 segments x 5 bins
