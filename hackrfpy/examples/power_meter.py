#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/power_meter.py'
#   Live signal-strength meter at one frequency, using capture_callback.
#   Demonstrates the callback API (the binder-style inverted loop) on a real
#   stream: register a function, get each decoded complex64 block as it
#   arrives, print a rolling power reading. Read-only / receive-only.
#
#   Usage:
#     uv run python examples/power_meter.py --freq 100e6
#     uv run python examples/power_meter.py --freq 433.92e6 --rate 2e6
##--------------------------------------------------------------------\
import argparse
import sys
import numpy as np
from hackrfpy import HackRF


def main():
    p = argparse.ArgumentParser(description="Live power meter (read-only).")
    p.add_argument("--freq", default="100e6", help="center frequency Hz")
    p.add_argument("--rate", default="2e6", help="sample rate sps")
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()
    freq, rate = float(args.freq), float(args.rate)

    h = HackRF(tools_dir=args.tools_dir)
    det = h.detect()
    if not det["ready"]:
        print(f"no usable HackRF: {det['problem']}", file=sys.stderr)
        return 1

    print(f"[*] power meter @ {freq/1e6:g} MHz  (Ctrl-C to stop)\n")

    # bar-graph scale in dBFS: roughly noise floor (-90) to full-scale (0)
    LO, HI, WIDTH = -90.0, 0.0, 40

    def on_block(iq, total):
        if len(iq) == 0:
            return
        # raw dBFS, plus the gain-normalized relative reading (Level 1): the
        # relative value is comparable across gain settings; pass offset_db
        # from a calibration run (see examples/calibrate.py) to approximate dBm.
        db = h.power_dbfs(iq)
        rel = h.relative_power_db(db, lna=16, vga=20, amp=False)
        frac = max(0.0, min(1.0, (db - LO) / (HI - LO)))
        bar = "#" * int(frac * WIDTH)
        sys.stdout.write(f"\r  {db:7.1f} dBFS  (rel {rel:7.1f} dB)  "
                         f"|{bar:<{WIDTH}}|")
        sys.stdout.flush()

    try:
        # callback fires per block; we never reach a sample cap, so it runs
        # until Ctrl-C, and the context manager inside reaps the child.
        h.capture_callback(freq, rate, on_block=on_block)
    except KeyboardInterrupt:
        pass
    print("\n[*] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
