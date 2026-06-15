#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_compat.py'
#   Device-compatibility + lifecycle-safety additions: the atexit/registry
#   backstop, handle-mode context manager, parameter readback, the
#   return_params tuple, and the version feature-probe. Cross-platform
#   stubs (conftest.stub_device) so the process-lifecycle ones run on
#   Windows too.
##--------------------------------------------------------------------\

import time
import weakref

import numpy as np
import pytest

from hackrfpy import HackRF, constants as C
import hackrfpy.core as core

_IQ_200 = list(b"\x01\x02" * 100)


# ---- feature probe (pure, no device) ---------------------------------------
def test_features_modern_version():
    f = HackRF().features("2024.02.1")
    assert f["stdout_streaming"] and f["sweep_num_sweeps"]
    assert f["version_known"]


def test_features_old_version_flags_no_streaming():
    f = HackRF().features("2019.01.1")
    assert f["stdout_streaming"] is False
    assert f["sweep_num_sweeps"] is False
    assert f["bias_tee"] is True


def test_features_unknown_version_is_optimistic_but_marked():
    f = HackRF().features("not-a-version")
    assert f["version_known"] is False
    assert f["stdout_streaming"] is True


# ---- parameter readback ----------------------------------------------------
def test_last_params_records_snapped_values(monkeypatch):
    h = HackRF()
    monkeypatch.setattr(h, "_run", lambda *a, **k: ("", "", 0))
    monkeypatch.setattr(h, "estimate_capture", lambda *a, **k: {
        "total_bytes": 0, "bytes_per_sec": 1, "seconds": 0, "free_bytes": 1})
    h.capture(433.92e6, 8e6, num_samples=1000, lna=30, vga=20)
    assert h.last_params["lna"] == 24
    assert h.last_params["freq"] == 433_920_000
    assert h.last_params["mode"] == "rx"
    assert h.last_params["baseband_bw"] in C.BASEBAND_FILTER_BW_HZ


def test_sweep_records_params(monkeypatch):
    h = HackRF()
    def empty(*a, **k):
        if False:
            yield
    monkeypatch.setattr(h, "_run", empty)
    list(h.sweep(400e6, 410e6, lna=30))
    assert h.last_params["lna"] == 24
    assert h.last_params["f_min"] == 400e6


def test_capture_array_return_params_tuple(stub_device):
    h = stub_device(transfer=dict(emit_bytes=_IQ_200, idle=True))
    iq, params = h.capture_array(433.92e6, 8e6, num_samples=40,
                                 lna=30, return_params=True)
    assert len(iq) == 40
    assert params["lna"] == 24
    iq2 = h.capture_array(433.92e6, 8e6, num_samples=10)
    assert isinstance(iq2, np.ndarray)


# ---- handle-mode context manager (Tier A) ----------------------------------
def test_handle_context_manager_reaps(stub_device):
    h = stub_device(transfer=dict(stdout_lines=["ready"], idle=True))
    proc = h._run(["transfer", "-r", "x.iq"], mode="handle")
    assert proc.is_alive()
    with proc as p:
        assert p.is_alive()
    assert not proc.is_alive(), "handle context manager did not reap child"


# ---- atexit / registry backstop (Tier B) -----------------------------------
def test_tx_handle_registered_rx_optout(stub_device, monkeypatch):
    monkeypatch.setattr(core, "_LIVE", weakref.WeakSet())
    h = stub_device(transfer=dict(idle=True))
    before = len(core._LIVE)
    tx = h._run(["transfer", "-t", "x.iq"], mode="handle", kind="tx")
    assert len(core._LIVE) == before + 1
    tx.stop()
    assert tx not in core._LIVE

    h.backstop_rx = False
    rx = h._run(["transfer", "-r", "x.iq"], mode="handle", kind="rx")
    assert rx not in core._LIVE
    rx.stop()


def test_atexit_hook_stops_live_handle(stub_device, monkeypatch):
    monkeypatch.setattr(core, "_LIVE", weakref.WeakSet())
    h = stub_device(transfer=dict(idle=True))
    proc = h._run(["transfer", "-t", "x.iq"], mode="handle", kind="tx")
    assert proc.is_alive()
    core._stop_all_live()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and proc.is_alive():
        time.sleep(0.05)
    assert not proc.is_alive(), "atexit backstop did not stop the handle"


# ---- preflight / doctor alias ----------------------------------------------
def test_preflight_and_doctor_alias_agree(stub_device):
    info_lines = ["hackrf_info version: 2024.02.1", "Found HackRF", "Index: 0",
                  "Serial number: 0000000000000000000000000000abcd"]
    h = stub_device(info=dict(stdout_lines=info_lines),
                    transfer=dict(exit_code=0), sweep=dict(exit_code=0))
    r1 = h.preflight(capture_path=h._tmp_path)
    r2 = h.doctor(capture_path=h._tmp_path)
    assert r1["features"]["stdout_streaming"] is True
    assert r1["tools"].keys() == r2["tools"].keys()
    assert "features" in r1
