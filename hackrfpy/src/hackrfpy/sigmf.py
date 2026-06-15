#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/sigmf.py'
#
#   Minimal SigMF metadata writer. Writes a '<capture>.sigmf-meta' sidecar so
#   recordings are self-describing instead of headerless int8 blobs. Follows
#   the SigMF core namespace; HackRF native format is interleaved signed 8-bit
#   I/Q -> datatype "ci8".
#
#   Author(s): <you>
##--------------------------------------------------------------------\

import json
import os
from datetime import datetime, timezone


def write_sigmf_meta(data_path, freq, sample_rate, *, lna=None, vga=None,
                     amp=None, datatype="ci8", extra=None):
    # Sidecar path: foo.iq -> foo.sigmf-meta
    base, _ = os.path.splitext(data_path)
    meta_path = base + ".sigmf-meta"

    hw = "HackRF One"
    annotations_gains = {}
    if lna is not None:
        annotations_gains["hackrf:lna_gain_db"] = lna
    if vga is not None:
        annotations_gains["hackrf:vga_gain_db"] = vga
    if amp is not None:
        annotations_gains["hackrf:amp_enabled"] = bool(amp)

    meta = {
        "global": {
            "core:datatype": datatype,
            "core:sample_rate": float(sample_rate),
            "core:hw": hw,
            "core:version": "1.0.0",
            "core:recorder": "hackrfpy",
            **annotations_gains,
        },
        "captures": [
            {
                "core:sample_start": 0,
                "core:frequency": float(freq),
                "core:datetime": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "annotations": [],
    }
    if extra:
        meta["global"].update(extra)

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    return meta_path


def read_sigmf_meta(path: str) -> dict:
    """Read a .sigmf-meta sidecar back into a dict.

    Accepts either the meta path itself or the data path (foo.iq is mapped
    to foo.sigmf-meta). The reader half of write_sigmf_meta so consuming
    code can recover frequency / sample rate / gains without re-parsing.
    """
    if not path.endswith(".sigmf-meta"):
        base, _ = os.path.splitext(path)
        path = base + ".sigmf-meta"
    with open(path) as f:
        return json.load(f)
