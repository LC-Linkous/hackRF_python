#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_detect.py'
#   Hardware autodetection + identification. The HackRF is not a serial
#   device, so "detect" means: run hackrf_info, confirm each board is a
#   HackRF, report firmware/identity. Device-free via stub hackrf_info.
##--------------------------------------------------------------------\

import pytest

from hackrfpy import HackRF
from hackrfpy.exceptions import HackRFDeviceError


_ONE_BOARD = [
    "hackrf_info version: 2024.02.1",
    "libhackrf version: 2024.02.1 (0.9)",
    "Found HackRF", "Index: 0",
    "Serial number: 0000000000000000457863c82b4f3f",
    "Board ID Number: 2 (HackRF One)",
    "Firmware Version: 2024.02.1 (API:1.08)",
]

_TWO_BOARDS = _ONE_BOARD + [
    "Found HackRF", "Index: 1",
    "Serial number: 000000000000000088869dc38a11b2",
    "Board ID Number: 2 (HackRF One)",
    "Firmware Version: 2020.12.1 (API:1.04)",   # stale (<2021)
]


def test_detect_no_board(stub_device):
    # hackrf_info runs but reports nothing
    h = stub_device(info=dict(stdout_lines=["hackrf_info version: 2024.02.1"]))
    det = h.detect()
    assert det["found"] is False
    assert det["ready"] is False
    assert det["count"] == 0
    assert "no HackRF" in det["problem"]


def test_detect_single_board(stub_device):
    h = stub_device(info=dict(stdout_lines=_ONE_BOARD))
    det = h.detect()
    assert det["found"] and det["ready"]
    assert det["count"] == 1
    assert det["multiple"] is False
    b = det["boards"][0]
    assert b["is_hackrf"] is True
    assert b["serial"].endswith("4f3f")
    assert b["firmware_stale"] is False
    assert det["tools_version"] == "2024.02.1"


def test_detect_multiple_boards_flags_disambiguation(stub_device):
    h = stub_device(info=dict(stdout_lines=_TWO_BOARDS))
    det = h.detect()
    assert det["count"] == 2
    assert det["multiple"] is True
    # second board has stale firmware
    assert det["boards"][1]["firmware_stale"] is True


def test_detect_missing_binary_is_not_raised(tmp_path):
    # no hackrf_info anywhere -> detect() reports a problem, does NOT raise
    h = HackRF(tools_dir=str(tmp_path))
    import shutil
    # ensure resolve fails: tools_dir empty and nothing on PATH for this name
    det = h.detect()
    assert det["found"] is False
    assert det["problem"] is not None


def test_detect_non_hackrf_device(stub_device):
    # a USB device enumerates but isn't a HackRF (board id doesn't match)
    lines = [
        "hackrf_info version: 2024.02.1",
        "Found HackRF", "Index: 0",
        "Serial number: 000000000000000000000000deadbeef",
        "Board ID Number: 0 (Jellybean)",     # not a HackRF One
        "Firmware Version: 2024.02.1",
    ]
    h = stub_device(info=dict(stdout_lines=lines))
    det = h.detect()
    assert det["found"] is True
    assert det["ready"] is False              # found, but not confirmed HackRF
    assert det["boards"][0]["is_hackrf"] is False
    assert "did not identify" in det["problem"]


def test_identify_first_and_by_serial(stub_device):
    h = stub_device(info=dict(stdout_lines=_TWO_BOARDS))
    first = h.identify()
    assert first["index"] == "0"
    by_serial = h.identify("11b2")
    assert by_serial["serial"].endswith("11b2")
    assert h.identify("nonexistent") is None


def test_identify_none_when_no_board(stub_device):
    h = stub_device(info=dict(stdout_lines=["hackrf_info version: 2024.02.1"]))
    assert h.identify() is None
