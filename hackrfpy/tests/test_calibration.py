#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_calibration.py'
#   Level-1 relative calibration helpers: power in dBFS, gain chain, and
#   gain-normalized relative power (with optional offset + freq correction).
#   Pure math, no hardware.
##--------------------------------------------------------------------\

import numpy as np

from hackrfpy import HackRF
from hackrfpy import constants as C


def test_power_dbfs_known_amplitude():
    h = HackRF()
    # amplitude 1.0 -> power 1.0 -> 0 dBFS (full scale)
    iq = np.ones(100, dtype=np.complex64)
    assert abs(h.power_dbfs(iq) - 0.0) < 1e-6
    # amplitude 0.5 -> power 0.25 -> ~ -6.02 dBFS
    iq = np.full(100, 0.5 + 0j, dtype=np.complex64)
    assert abs(h.power_dbfs(iq) - (-6.0206)) < 1e-3


def test_power_dbfs_empty_is_neg_inf():
    h = HackRF()
    assert h.power_dbfs(np.array([], dtype=np.complex64)) == float("-inf")


def test_gain_db_sums_chain():
    h = HackRF()
    assert h.gain_db(16, 20, False) == 36.0
    assert h.gain_db(16, 20, True) == 36.0 + C.AMP_DB
    assert h.gain_db(0, 0, False) == 0.0


def test_relative_power_normalizes_gain():
    # the core property: the SAME physical signal reads the same relative
    # value regardless of gain. Higher gain -> higher dBFS by exactly the gain
    # delta, which normalization removes.
    h = HackRF()
    r_low = h.relative_power_db(-60.0, lna=0, vga=0, amp=False)
    r_high = h.relative_power_db(-60.0 + 36.0, lna=16, vga=20, amp=False)
    assert abs(r_low - r_high) < 1e-9


def test_relative_power_offset_applies():
    h = HackRF()
    base = h.relative_power_db(-6.0, lna=0, vga=0, amp=False)
    with_offset = h.relative_power_db(-6.0, lna=0, vga=0, amp=False,
                                      offset_db=-10.0)
    assert abs((with_offset - base) - (-10.0)) < 1e-9


def test_relative_power_freq_correction_applies():
    h = HackRF()
    curve = lambda f: 3.0 if f > 2e9 else 0.0       # noqa: E731
    base = h.relative_power_db(-6.0, lna=0, vga=0, amp=False)
    corrected = h.relative_power_db(-6.0, lna=0, vga=0, amp=False,
                                    freq_hz=2.4e9, freq_correction=curve)
    assert abs((base - corrected) - 3.0) < 1e-9


def test_relative_power_reads_from_last_params():
    # if gains aren't passed, they come from last_params (set by a capture)
    h = HackRF()
    h.last_params = {"lna_gain": 16, "vga_gain": 20, "amp": False}
    r = h.relative_power_db(-6.0)
    assert abs(r - (-6.0 - 36.0)) < 1e-9


def test_relative_power_accepts_iq_block():
    # passing a complex64 block measures its power then normalizes
    h = HackRF()
    iq = np.full(100, 0.5 + 0j, dtype=np.complex64)   # -6.02 dBFS
    r = h.relative_power_db(iq, lna=0, vga=0, amp=False)
    assert abs(r - (-6.0206)) < 1e-3
