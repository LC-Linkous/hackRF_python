#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/persistent_capture.py'
#   Collect many CONTIGUOUS segments at one frequency from a single
#   long-lived receive process, using open_receiver(). No plotting.
#
#   This is DIFFERENT from capture(segment_secs=...):
#     - capture(segment_secs=...) spawns a fresh hackrf_transfer per file,
#       so each file is whole but there is a short re-open GAP (~hundreds
#       of ms) of missing samples between files.
#     - this script drains ONE continuous stream and cuts it into files,
#       so consecutive segments are GAPLESS (back-to-back samples), at the
#       cost of re-quantizing complex64 -> int8 on write (exact for
#       samples produced by the library's own decode).
#
#   Use this when downstream processing cares about continuity across
#   file boundaries (long observations, TDOA-ish work, demod that spans
#   segments). Each file gets a SigMF sidecar.
#
#   SAFETY: read-only / receive-only.
#
#   Usage:
#     uv run python examples/persistent_capture.py --freq 100e6 --rate 2e6
#     uv run python examples/persistent_capture.py --freq 433.92e6 \
#         --rate 2e6 --segment-secs 1.0 --count 10 --out-dir segments
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\
import argparse
import os
import sys

import numpy as np

from hackrfpy import HackRF, write_sigmf_meta


def encode_iq(iq: np.ndarray) -> bytes:
    # complex64 in ~[-1, 1) -> interleaved int8 (HackRF native). Exact
    # round-trip for data that came out of decode_iq (values are k/128).
    out = np.empty(len(iq) * 2, dtype=np.int8)
    out[0::2] = np.clip(np.round(iq.real * 128.0), -128, 127)
    out[1::2] = np.clip(np.round(iq.imag * 128.0), -128, 127)
    return out.tobytes()


def main():
    p = argparse.ArgumentParser(
        description="Gapless segmented capture from one persistent receiver.")
    p.add_argument("--freq", default="100e6", help="center frequency Hz")
    p.add_argument("--rate", default="2e6", help="sample rate sps")
    p.add_argument("--segment-secs", type=float, default=1.0,
                   help="seconds of samples per file (default 1.0)")
    p.add_argument("--count", type=int, default=5,
                   help="number of segments to collect (default 5)")
    p.add_argument("--out-dir", default="segments",
                   help="output directory (default ./segments)")
    p.add_argument("--lna", type=int, default=16)
    p.add_argument("--vga", type=int, default=20)
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()
    freq, rate = float(args.freq), float(args.rate)
    n_per = int(rate * args.segment_secs)

    h = HackRF(tools_dir=args.tools_dir)
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"[*] {args.count} x {args.segment_secs}s gapless segments "
          f"@ {freq/1e6:g} MHz, {rate/1e6:g} Msps -> {args.out_dir}/")
    written = []
    with h.open_receiver(freq, rate, lna=args.lna, vga=args.vga) as rx:
        for i in range(args.count):
            iq = rx.read(n_per)
            if len(iq) < n_per:
                print(f"[!] stream ended early on segment {i}", file=sys.stderr)
                if not len(iq):
                    break
            path = os.path.join(args.out_dir, f"seg_{i:03d}.iq")
            with open(path, "wb") as f:
                f.write(encode_iq(iq))
            write_sigmf_meta(path, freq, rate, lna=rx.lna, vga=rx.vga,
                             amp=rx.amp, datatype="ci8")
            db = h.power_dbfs(iq)
            print(f"    seg_{i:03d}.iq  {len(iq)} samples  {db:6.1f} dBFS")
            written.append(path)
    print(f"[*] done: {len(written)} files, "
          f"{rx.total_samples} contiguous samples total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
