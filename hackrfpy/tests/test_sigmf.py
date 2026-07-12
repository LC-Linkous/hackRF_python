#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_sigmf.py'
#   SigMF sidecar writer/reader. Pins the core namespace shape and the
#   core:extensions declaration for hackrf:* keys (strict SigMF validators
#   reject a file that uses a non-core namespace without declaring it). No
#   device needed.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

import json

from hackrfpy import write_sigmf_meta, read_sigmf_meta


def test_core_fields_written(tmp_path):
    meta_path = write_sigmf_meta(str(tmp_path / "cap.iq"), 433.92e6, 8e6)
    meta = json.load(open(meta_path))
    g = meta["global"]
    assert g["core:datatype"] == "ci8"
    assert g["core:sample_rate"] == 8e6
    assert meta["captures"][0]["core:frequency"] == 433.92e6


def test_extensions_declared_when_gains_present(tmp_path):
    # hackrf:* keys require a core:extensions declaration to be spec-valid.
    meta_path = write_sigmf_meta(str(tmp_path / "cap.iq"), 100e6, 8e6,
                                 lna=24, vga=20, amp=True)
    g = json.load(open(meta_path))["global"]
    assert g["hackrf:lna_gain_db"] == 24
    exts = g.get("core:extensions")
    assert isinstance(exts, list) and len(exts) == 1
    assert exts[0]["name"] == "hackrf"
    assert exts[0]["optional"] is True
    assert "version" in exts[0]


def test_extensions_absent_when_no_gains(tmp_path):
    # No hackrf:* keys -> no extension declaration (nothing to declare).
    meta_path = write_sigmf_meta(str(tmp_path / "cap.iq"), 100e6, 8e6)
    g = json.load(open(meta_path))["global"]
    assert "core:extensions" not in g
    assert not any(k.startswith("hackrf:") for k in g)


def test_roundtrip_via_data_path(tmp_path):
    # read_sigmf_meta accepts the data path and maps it to the sidecar.
    data_path = str(tmp_path / "cap.iq")
    write_sigmf_meta(data_path, 915e6, 10e6, lna=16)
    meta = read_sigmf_meta(data_path)
    assert meta["global"]["hackrf:lna_gain_db"] == 16
    assert meta["captures"][0]["core:frequency"] == 915e6
