#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/device_explorer.py'
#   The "first thing you run": detect the board, identify it, report
#   firmware + capabilities + any device warnings. Read-only. This is the
#   HackRF analog of a serial-port autodetect -- it confirms the device is
#   present and usable before you build anything on top of it.
##--------------------------------------------------------------------\
import sys
from hackrfpy import HackRF


def main():
    h = HackRF()

    print("=" * 52)
    print(" hackrfpy device explorer")
    print("=" * 52)

    det = h.detect()
    if not det["found"]:
        print(f"\n  No HackRF detected: {det['problem']}")
        print("  Check the USB cable, and on Windows the WinUSB driver (Zadig).")
        return 1

    print(f"\n  boards found : {det['count']}")
    print(f"  hackrf-tools : {det['tools_version']}")
    print(f"  libhackrf    : {det['libhackrf_version']}")

    for b in det["boards"]:
        tag = "HackRF" if b["is_hackrf"] else "UNCONFIRMED"
        print(f"\n  [{b['index']}] {tag}")
        print(f"      serial   : {b['serial']}")
        print(f"      name     : {b['name']}")
        print(f"      firmware : {b['firmware']}"
              + ("   (stale: <2021)" if b["firmware_stale"] else ""))

    if det["multiple"]:
        print("\n  ! multiple boards -- target one with HackRF(serial=...)")
    for w in det.get("warnings", []):
        print(f"  ! device warning: {w}")

    # capability flags derived from firmware/tools version
    feats = h.features()
    print("\n  capabilities:")
    for k in ("stdout_streaming", "sweep_num_sweeps", "bias_tee"):
        print(f"      {k:18}: {'yes' if feats[k] else 'no'}")

    print(f"\n  ready: {'YES' if det['ready'] else 'no'}")
    print("=" * 52)
    return 0 if det["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
