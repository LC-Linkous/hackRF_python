#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_parsing.py'
#   Parsing logic against frozen real-ish captures. Runs without a device.
##--------------------------------------------------------------------\

import os
import numpy as np

from hackrfpy import HackRF
from hackrfpy.core import HackRF as _H
from hackrfpy._commands.sweep import SweepMixin
from hackrfpy._commands.info import InfoMixin


def test_decode_iq_roundtrip(fixtures_dir):
    raw = open(os.path.join(fixtures_dir, "sample.iq"), "rb").read()
    h = HackRF()
    iq = h.decode_iq(raw)
    assert iq.dtype == np.complex64
    assert len(iq) == 8                      # 16 int8 -> 8 complex
    # first sample was (0,0)
    assert iq[0] == 0
    # second sample I=127,Q=0  -> ~ +1.0 real
    assert abs(iq[1].real - 127 / 128.0) < 1e-6
    assert iq[1].imag == 0


def test_decode_iq_odd_trailing_byte():
    # a truncated final pair (odd byte count) must be dropped, not crash
    h = HackRF()
    raw = bytes([10, 20, 30])   # 1.5 pairs
    iq = h.decode_iq(raw)
    assert len(iq) == 1


def test_sweep_line_parse(fixtures_dir):
    lines = open(os.path.join(fixtures_dir, "sweep_sample.csv")).read().splitlines()
    rows = [SweepMixin.parse_sweep_line(l) for l in lines]
    rows = [r for r in rows if r]
    assert len(rows) == 2
    assert rows[0]["hz_low"] == 433000000
    assert rows[0]["hz_high"] == 433500000
    assert len(rows[0]["db"]) == 5
    assert rows[0]["db"][0] == -71.23


def test_sweep_line_parse_garbage():
    assert SweepMixin.parse_sweep_line("") is None
    assert SweepMixin.parse_sweep_line("not,enough") is None


def test_info_parse(fixtures_dir):
    text = open(os.path.join(fixtures_dir, "hackrf_info.txt")).read()
    parsed = InfoMixin.parse_info(text)
    assert parsed["boards"], "expected at least one board"
    b = parsed["boards"][0]
    assert "serial_number" in b
    assert b["serial_number"].endswith("4f3f")


def test_info_parse_multi_board(fixtures_dir):
    # two boards attached: each "Found HackRF" block becomes its own entry
    text = open(os.path.join(fixtures_dir, "hackrf_info_multi.txt")).read()
    parsed = InfoMixin.parse_info(text)
    assert len(parsed["boards"]) == 2
    assert parsed["boards"][0]["serial_number"].endswith("4f3f")
    assert parsed["boards"][1]["serial_number"].endswith("11b2")
    assert parsed["boards"][1]["index"] == "1"
    assert parsed["library"]["hackrf_info_version"] == "2024.02.1"
