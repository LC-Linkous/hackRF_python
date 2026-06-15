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
