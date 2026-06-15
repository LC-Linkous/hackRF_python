#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_hardware.py'
#   Tests that need a connected HackRF. Auto-skip when absent (see conftest).
##--------------------------------------------------------------------\

import pytest
from hackrfpy import HackRF


@pytest.mark.hardware
def test_info_returns_board():
    h = HackRF()
    parsed = h.info()
    assert parsed["boards"], "expected a connected board"


@pytest.mark.hardware
def test_doctor_finds_tools():
    h = HackRF()
    report = h.doctor()
    assert report["tools"].get("hackrf_info")
    assert not report["problems"], report["problems"]
