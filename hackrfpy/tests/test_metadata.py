#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_metadata.py'
#   SigMF sidecar round-trips, and preset resolution/override. Device-free.
##--------------------------------------------------------------------\

import json
import os

import pytest

from hackrfpy.sigmf import write_sigmf_meta, read_sigmf_meta
from hackrfpy import presets as P
from hackrfpy.exceptions import HackRFValueError


# ---- SigMF: write then read back recovers the capture parameters -----------
def test_sigmf_roundtrip(tmp_path):
    data = tmp_path / "capture.iq"
    data.write_bytes(b"\x00\x01\x02\x03")
    meta_path = write_sigmf_meta(str(data), 433.92e6, 8e6,
                                 lna=24, vga=20, amp=True)
    assert meta_path.endswith(".sigmf-meta")
    # read back via the DATA path (twin maps foo.iq -> foo.sigmf-meta)
    meta = read_sigmf_meta(str(data))
    g = meta["global"]
    assert g["core:datatype"] == "ci8"
    assert g["core:sample_rate"] == 8e6
    assert g["hackrf:lna_gain_db"] == 24
    assert g["hackrf:amp_enabled"] is True
    cap = meta["captures"][0]
    assert cap["core:frequency"] == 433.92e6
    assert "core:datetime" in cap


def test_sigmf_omits_unset_gains(tmp_path):
    data = tmp_path / "c.iq"
    data.write_bytes(b"\x00\x01")
    write_sigmf_meta(str(data), 100e6, 2e6)         # no lna/vga/amp
    meta = read_sigmf_meta(str(data))
    assert "hackrf:lna_gain_db" not in meta["global"]
    assert "hackrf:amp_enabled" not in meta["global"]


def test_sigmf_extra_merges(tmp_path):
    data = tmp_path / "c.iq"
    data.write_bytes(b"\x00\x01")
    write_sigmf_meta(str(data), 100e6, 2e6, extra={"core:description": "test"})
    meta = read_sigmf_meta(str(data))
    assert meta["global"]["core:description"] == "test"


# ---- presets ---------------------------------------------------------------
def test_builtin_presets_present():
    pre = P.load_presets()
    assert "ads-b" in pre
    assert pre["ads-b"]["center"] == 1_090_000_000


def test_get_preset_unknown_raises():
    with pytest.raises(HackRFValueError, match="unknown preset"):
        P.get_preset("does-not-exist")


def test_user_toml_overrides_builtin(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "hackrfpy"
    cfg_dir.mkdir()
    (cfg_dir / "presets.toml").write_text(
        '[presets.ads-b]\ncenter = 1100000000\nsample_rate = 4000000\n'
        'desc = "overridden"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    pre = P.load_presets()
    assert pre["ads-b"]["center"] == 1_100_000_000   # user wins
    assert pre["ads-b"]["desc"] == "overridden"
