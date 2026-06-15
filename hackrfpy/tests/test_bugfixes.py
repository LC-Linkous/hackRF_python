#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_bugfixes.py'
#   Regression tests for the 2026-06-10 bug-fix pass. Each test pins one
#   fixed behavior. No device needed (dry-run tests need hackrf-tools).
##--------------------------------------------------------------------\

import shutil

import numpy as np
import pytest

from hackrfpy import HackRF, load_iq
from hackrfpy.cli import HackRFCLI
from hackrfpy.exceptions import HackRFValueError


needs_tools = pytest.mark.skipif(
    shutil.which("hackrf_transfer") is None,
    reason="hackrf-tools not installed")


# ---- bug 1: `hrf rx --preset` used to die in argparse (-f was required) ----
@needs_tools
def test_rx_preset_supplies_frequency(capsys):
    app = HackRFCLI(["rx", "--preset", "ads-b", "-n", "4000000", "--print-cmd"])
    app.main(app.getArgs())
    out = capsys.readouterr().out
    assert "hackrf_transfer" in out
    assert "-f 1090000000" in out          # came from the preset


@needs_tools
def test_rx_without_freq_or_preset_raises():
    app = HackRFCLI(["rx", "-n", "1000", "--print-cmd"])
    with pytest.raises(HackRFValueError):
        app.main(app.getArgs())


# ---- bug 4: print_cmd dry runs now uniformly return None ----
@needs_tools
def test_print_cmd_returns_none(capsys):
    h = HackRF()
    assert h._run(["info"], mode="blocking", print_cmd=True) is None
    capsys.readouterr()
    # open-ended capture dry run must not hand back a fake handle
    assert h.capture(433.92e6, 8e6, print_cmd=True) is None
    # live-stream dry run must not build a generator over a dry-run result
    assert h.capture(433.92e6, 8e6, to_stdout=True, print_cmd=True) is None


# ---- bug 5: odd-length stream chunks must carry over, not drop a byte ----
def test_stream_decode_carries_odd_remainder(monkeypatch):
    h = HackRF()
    # 4 I/Q pairs split at an ODD boundary: dropping the dangling byte would
    # swap I and Q for everything after the split.
    pairs = bytes([1, 2, 3, 4, 5, 6, 7, 8])
    chunks = [pairs[:3], pairs[3:]]

    def fake_run(argv, mode=None, **k):
        assert mode == "stream"
        def g():                     # real generator: has .close(), like _stream
            yield from chunks
        return g()

    monkeypatch.setattr(h, "_run", fake_run)
    monkeypatch.setattr(h, "resolve", lambda key: f"/fake/{key}")
    blocks = list(h.capture(433.92e6, 8e6, to_stdout=True))
    iq = np.concatenate(blocks)
    assert len(iq) == 4
    expect = (np.array([1, 3, 5, 7]) + 1j * np.array([2, 4, 6, 8])) / 128.0
    assert np.allclose(iq, expect.astype(np.complex64))


# ---- new: load_iq is decode_iq's file twin ----
def test_load_iq_matches_decode_iq(tmp_path, fixtures_dir):
    import os
    src = os.path.join(fixtures_dir, "sample.iq")
    h = HackRF()
    via_decode = h.decode_iq(open(src, "rb").read())
    via_load = load_iq(src)
    assert np.array_equal(via_decode, via_load)
    # bounded / offset reads
    assert len(load_iq(src, count=3)) == 3
    assert load_iq(src, count=1, offset_samples=1)[0] == via_decode[1]


# ---- restore_mode: rehydrate without the banner ----
def test_restore_mode_no_banner(capsys):
    h = HackRF()
    h.restore_mode("tx")
    out = capsys.readouterr().out
    assert "TX MODE ARMED" not in out
    assert h.mode == "tx"
    with pytest.raises(HackRFValueError):
        h.restore_mode("nonsense")
