#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_metadata.py'
#   SigMF sidecar round-trips, and preset resolution/override. Device-free.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\


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


# ---- package version attribute ---------------------------------------------
def test_dunder_version_present():
    import hackrfpy
    v = hackrfpy.__version__
    assert isinstance(v, str) and v
    try:
        from importlib.metadata import version
        assert v == version("hackrfpy")
    except Exception:
        assert v.startswith("0.0.0")          # uninstalled checkout fallback


# ---- official SigMF validator (plan:#8) ------------------------------------
# The writer looked spec-correct by inspection; this makes GNU Radio /
# IQEngine interop a TESTED property instead of a trusted one. Skips only
# where the dev group is not installed.
def test_sidecar_passes_official_sigmf_validator(tmp_path):
    sigmffile = pytest.importorskip("sigmf.sigmffile",
                                    reason="sigmf dev dependency not installed")
    import numpy as np
    iq_path = str(tmp_path / "capture.iq")
    np.zeros(4096, dtype=np.int8).tofile(iq_path)
    write_sigmf_meta(iq_path, 98.1e6, 2e6, lna=32, vga=20, amp=False,
                     datatype="ci8")

    f = sigmffile.fromfile(str(tmp_path / "capture.sigmf-meta"))
    f.set_data_file(iq_path)
    f.validate()                          # raises on any spec violation
    assert f.get_global_field("core:datatype") == "ci8"
    assert f.get_global_field("core:sample_rate") == 2e6
    assert f.sample_count == 2048         # 4096 int8 bytes = 2048 ci8 pairs
    # the hackrf extension must be DECLARED, not just used (strict validators
    # reject undeclared namespaces; this regressed once pre-1.0)
    exts = f.get_global_field("core:extensions")
    assert any(e.get("name") == "hackrf" for e in exts)
