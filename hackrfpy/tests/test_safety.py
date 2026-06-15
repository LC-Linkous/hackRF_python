#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_safety.py'
#   The safety envelope that must hold WITHOUT hardware: brick-guards on
#   firmware ops, the non-verbose warn channel, typed frequency parsing,
#   and the TX gain ceiling. These guard the worst outcomes (bricked board,
#   silent out-of-spec operation, illegal transmit), so they are pinned
#   explicitly rather than left to integration coverage.
##--------------------------------------------------------------------\

import sys

import pytest

from hackrfpy import HackRF, parse_freq, constants as C
from hackrfpy.exceptions import HackRFValueError


# ---- brick-guards: the only operations that can permanently kill a board ----
def test_spiflash_write_requires_confirm():
    h = HackRF()
    # must refuse BEFORE touching any subprocess / resolving a binary
    with pytest.raises(HackRFValueError, match="BRICK"):
        h.spiflash_write("firmware.bin")


def test_cpldjtag_requires_confirm():
    h = HackRF()
    with pytest.raises(HackRFValueError, match="brick"):
        h.cpldjtag("firmware.xsvf")


def test_spiflash_write_confirm_passes_guard(monkeypatch):
    # With confirm=True the guard is cleared and it proceeds to _run; stub _run
    # so we don't need a binary. Proves confirm is the ONLY thing gating it.
    h = HackRF()
    called = {}

    def fake_run(argv, **k):
        called["argv"] = argv
        return ("", "", 0)

    monkeypatch.setattr(h, "_run", fake_run)
    h.spiflash_write("firmware.bin", confirm=True)
    assert called["argv"][0] == "spiflash"
    assert "-w" in called["argv"]


# ---- warn channel: safety warnings must fire regardless of verbose ----------
def test_snap_gain_warns_on_stderr_when_not_verbose(capsys):
    h = HackRF(verbose=False)
    snapped = h._snap_gain("lna", 7, C.LNA_GAIN)   # 7 -> 0, a silent 7 dB loss
    assert snapped == 0
    err = capsys.readouterr().err
    assert "lna" in err and "-> 0" in err          # user was told, on stderr


def test_sub_recommended_sample_rate_warns_not_silent(capsys):
    h = HackRF(verbose=False)
    h._check_hard_range("sample_rate", 4e6, C.SR_MIN, C.SR_MAX, C.SR_WARN_BELOW)
    assert "below the recommended" in capsys.readouterr().err


def test_forced_out_of_spec_warns_on_stderr(capsys):
    h = HackRF()
    h.allow_out_of_spec = True
    h._check_hard_range("frequency", 60e9, C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
    out, err = capsys.readouterr()
    assert "forced out-of-spec" in err
    assert out == ""                               # never pollutes stdout


# ---- typed frequency parsing ------------------------------------------------
@pytest.mark.parametrize("text,hz", [
    ("433.92M", 433_920_000),
    ("88M", 88_000_000),
    ("1.09G", 1_090_000_000),
    ("2.5k", 2_500),
    ("100", 100),
    (" 8M ", 8_000_000),
    ("1e6", 1_000_000),
    ("433.92MHz", 433_920_000),    # trailing Hz tolerated
    ("137mhz", 137_000_000),
])
def test_parse_freq_units(text, hz):
    assert parse_freq(text) == hz


def test_parse_freq_bad_input_is_typed():
    # a bad value must raise the LIBRARY's typed error so the CLI handler
    # catches it and prints a clean line, not a bare ValueError traceback
    with pytest.raises(HackRFValueError):
        parse_freq("not-a-freq")


# ---- TX ceiling: order-of-magnitude fat-finger rejects ----------------------
def test_tx_ceiling_rejects_before_snap():
    h = HackRF()
    with pytest.raises(HackRFValueError, match="ceiling"):
        # 470 instead of 47 -> must reject, not silently clamp to device max
        h.validate_tx(433.92e6, 8e6, 470, False)


def test_tx_at_ceiling_is_allowed():
    h = HackRF()
    freq, sr, txvga, amp = h.validate_tx(433.92e6, 8e6, C.TX_VGA_CEILING_DB,
                                         False)
    assert txvga == C.TX_VGA_CEILING_DB


# ---- newly-wrapped tool flags: construction tests ---------------------------
def test_sweep_to_file_text_and_binary(tmp_path, monkeypatch):
    h = HackRF(tools_dir=str(tmp_path))
    # stub resolve so no real binary needed
    monkeypatch.setattr(h, "resolve", lambda key: "/x/hackrf_sweep")
    seen = {}
    monkeypatch.setattr(h, "_run",
                        lambda argv, **k: seen.setdefault("argv", argv))
    h.sweep_to_file(2400e6, 2490e6, "s.csv")
    assert seen["argv"][-2:] == ["-r", "s.csv"]
    assert "-B" not in seen["argv"] and "-I" not in seen["argv"]
    seen.clear()
    h.sweep_to_file(2400e6, 2490e6, "s.bin", binary=True)
    assert "-B" in seen["argv"]
    seen.clear()
    h.sweep_to_file(2400e6, 2490e6, "s.bin", inverse_fft=True)
    assert "-I" in seen["argv"] and "-B" not in seen["argv"]   # -I wins


def test_transmit_cw_requires_tx_mode():
    from hackrfpy.exceptions import HackRFModeError
    h = HackRF()
    assert h.mode == C.MODE_RX
    with pytest.raises(HackRFModeError):
        h.transmit_cw(433.92e6, 8e6, amplitude=100)


def test_transmit_cw_builds_c_flag(monkeypatch):
    h = HackRF()
    h.set_mode(C.MODE_TX)
    seen = {}
    monkeypatch.setattr(h, "_run",
                        lambda argv, **k: seen.update(argv=argv) or ("", "", 0))
    h.transmit_cw(433.92e6, 8e6, amplitude=200, duration=1.0)   # 200 clamps
    assert seen["argv"][0] == "transfer"
    assert seen["argv"][1] == "-c"
    assert seen["argv"][2] == 127                                # clamped 0-127
