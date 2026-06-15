#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_validation.py'
#   The validation envelope + mode machine. No device needed.
##--------------------------------------------------------------------\

import pytest

from hackrfpy import HackRF, constants as C
from hackrfpy.exceptions import HackRFValueError, HackRFModeError


def test_gain_snaps_down():
    h = HackRF()
    assert h._snap_gain("lna", 30, C.LNA_GAIN) == 24      # 8 dB steps, round down
    assert h._snap_gain("vga", 21, C.VGA_GAIN) == 20      # 2 dB steps
    assert h._snap_gain("lna", 100, C.LNA_GAIN) == 40     # clamps to max


def test_hard_range_rejects_typo():
    h = HackRF()
    # 60 GHz instead of 6 GHz -> reject by default
    with pytest.raises(HackRFValueError):
        h._check_hard_range("frequency", 60e9, C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)


def test_force_downgrades_to_warning():
    h = HackRF()
    h.allow_out_of_spec = True
    # no raise when forced
    assert h._check_hard_range("frequency", 60e9, C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)


def test_baseband_auto_and_snap():
    h = HackRF()
    bw = h._auto_baseband(8e6)               # ~0.75*8M = 6M -> supported 6M
    assert bw == 6_000_000
    assert h._auto_baseband(8e6, 5.4e6) in C.BASEBAND_FILTER_BW_HZ


def test_tx_ceiling_rejects():
    h = HackRF()
    with pytest.raises(HackRFValueError):
        h.validate_tx(433.92e6, 8e6, C.TX_VGA_CEILING_DB + 5, False)


def test_mode_gate_blocks_tx_in_rx():
    h = HackRF()
    assert h.mode == C.MODE_RX
    with pytest.raises(HackRFModeError):
        h.require_mode(C.MODE_TX)


def test_mode_switch_allows_tx(capsys):
    h = HackRF()
    h.set_mode(C.MODE_TX)                     # prints the safety banner
    out = capsys.readouterr().out
    assert "TX MODE ARMED" in out
    h.require_mode(C.MODE_TX)                 # no raise now
