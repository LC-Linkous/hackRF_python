#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_features.py'
#   Device-free coverage for the scripting-facing additions: in-memory
#   capture, the stream context manager, capability probing, preflight's
#   core-vs-optional split, sweep MHz-edge warning, and the TX dead-man cap.
#   Cross-platform stubs (conftest.stub_device) stand in for hackrf_* so
#   these run on Windows too.
##--------------------------------------------------------------------\

import time

import numpy as np
import pytest

from hackrfpy import HackRF, constants as C
from hackrfpy.exceptions import HackRFDeviceError, HackRFValueError


# 100 I/Q pairs (200 int8 bytes) emitted, then idle+trap so the early-close
# reap is clean and fast.
_IQ_200 = list(b"\x01\x02" * 100)


# ---- capture_array: exactly-N samples in RAM, child reaped -----------------
def test_capture_array_returns_exact_sample_count(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    iq = h.capture_array(433.92e6, 8e6, num_samples=40)
    assert isinstance(iq, np.ndarray)
    assert iq.dtype == np.complex64
    assert len(iq) == 40


def test_capture_array_rejects_nonpositive():
    h = HackRF()
    with pytest.raises(HackRFValueError):
        h.capture_array(433.92e6, 8e6, num_samples=0)


# ---- capture_stream: context manager reaps on exception --------------------
def test_capture_stream_reaps_on_exception(stub_device, tmp_path):
    marker = str(tmp_path / "stopped")
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True, marker=marker))
    with pytest.raises(RuntimeError):
        with h.capture_stream(433.92e6, 8e6) as blocks:
            for _ in blocks:
                raise RuntimeError("caller blew up mid-stream")
    import os
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not os.path.exists(marker):
        time.sleep(0.05)
    assert os.path.exists(marker), "child not reaped when context body raised"


# ---- from_device: fail-fast capability probe -------------------------------
def test_from_device_probes_and_warns_on_old_firmware(stub_device, capsys):
    h = stub_device(info=dict(stdout_lines=[
        "hackrf_info version: 2019.12.1",
        "libhackrf version: 2019.12.1 (0.5)",
        "Found HackRF", "Index: 0",
        "Serial number: 000000000000000000000000deadbeef"]))
    dev = HackRF.from_device(tools_dir=h.tools_dir)
    assert dev._probed["boards"]
    assert "predates 2021" in capsys.readouterr().err


def test_from_device_raises_when_no_board(stub_device):
    h = stub_device(info=dict(stdout_lines=["hackrf_info version: 2024.02.1"]))
    with pytest.raises(HackRFDeviceError):
        HackRF.from_device(tools_dir=h.tools_dir)


# ---- preflight: optional tools missing is NOT a problem --------------------
def test_preflight_optional_tools_not_flagged(stub_device, capsys):
    h = stub_device(
        info=dict(stdout_lines=[
            "hackrf_info version: 2024.02.1", "Found HackRF", "Index: 0",
            "Serial number: 00000000000000000000000012344f3f"]),
        transfer=dict(exit_code=0),
        sweep=dict(exit_code=0))
    report = h.preflight(capture_path=h._tmp_path)
    capsys.readouterr()
    missing_core = [p for p in report["problems"] if "core binary" in p]
    assert not missing_core, report["problems"]
    assert report["tools"]["hackrf_operacake"] is None
    assert not any("operacake" in p for p in report["problems"])


def test_core_tools_are_subset_of_tools():
    assert set(C.CORE_TOOLS).issubset(set(C.TOOLS))


# ---- sweep: sub-MHz edges warn ---------------------------------------------
def test_sweep_warns_on_sub_mhz_edges(capsys, monkeypatch):
    h = HackRF()
    def empty_stream(*a, **k):
        if False:
            yield
    monkeypatch.setattr(h, "_run", empty_stream)
    gen = h.sweep(433_920_000, 434_500_000)
    list(gen)
    assert "snapped to MHz" in capsys.readouterr().err


# ---- tx: max_duration converts an open-ended repeat into a timed run -------
def test_tx_max_duration_forces_timed(monkeypatch):
    h = HackRF()
    h.set_mode(C.MODE_TX)
    seen = {}
    monkeypatch.setattr(h, "_run",
                        lambda argv, **k: seen.update(k) or ("", "", 0))
    h.transmit(433.92e6, 8e6, "sig.iq", repeat=True, max_duration=5.0)
    assert seen.get("mode") == "timed"
    assert seen.get("duration") == 5.0
