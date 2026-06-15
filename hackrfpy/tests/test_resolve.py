#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_resolve.py'
#   Binary resolution, especially the Windows-extension path that the
#   documented tools_dir workflow depends on. Pure / no device.
##--------------------------------------------------------------------\

import os

import pytest

from hackrfpy import HackRF
from hackrfpy.exceptions import HackRFDeviceError


def test_resolve_bare_name_in_tools_dir(tmp_path):
    p = tmp_path / "hackrf_transfer"
    p.write_text("stub")
    p.chmod(0o755)
    h = HackRF(tools_dir=str(tmp_path))
    assert h.resolve("transfer") == str(p)


def test_resolve_finds_exe_extension_on_windows(tmp_path, monkeypatch):
    # Simulate a real Windows install: only hackrf_transfer.exe exists, and
    # os.name reports 'nt'. resolve() must find it via the PATHEXT extensions.
    exe = tmp_path / "hackrf_transfer.exe"
    exe.write_text("stub")
    exe.chmod(0o755)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("PATHEXT", ".EXE;.BAT;.CMD")
    h = HackRF(tools_dir=str(tmp_path))
    assert h.resolve("transfer").endswith("hackrf_transfer.exe")


def test_resolve_bat_extension_on_windows(tmp_path, monkeypatch):
    bat = tmp_path / "hackrf_info.bat"
    bat.write_text("stub")
    bat.chmod(0o755)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("PATHEXT", ".EXE;.BAT;.CMD")
    h = HackRF(tools_dir=str(tmp_path))
    assert h.resolve("info").endswith("hackrf_info.bat")


def test_resolve_missing_raises(tmp_path, monkeypatch):
    # nothing in tools_dir and nothing on PATH -> actionable error
    monkeypatch.setattr("shutil.which", lambda name: None)
    h = HackRF(tools_dir=str(tmp_path))
    with pytest.raises(HackRFDeviceError, match="not found"):
        h.resolve("transfer")
