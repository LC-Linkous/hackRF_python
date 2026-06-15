#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/calibrate.py'
#   Calibration WORKFLOW (Levels 2-3) on top of the library's Level-1
#   gain-normalized readings. This is an EXAMPLE, not library code, because
#   it depends on hardware you must supply: a signal of KNOWN power.
#
#   What this can and cannot do:
#     * The HackRF is NOT a calibrated instrument. There is no factory
#       per-unit characterization of absolute power.
#     * Level 1 (in the library, relative_power_db): subtracts the gain chain
#       so readings are CONSISTENT across gain settings. Relative, honest.
#     * Level 3 (here): if you feed a KNOWN power into the antenna port, you
#       can compute a single-point OFFSET that makes readings approximately
#       absolute (dBm) -- good to maybe +/-2-3 dB, NOT lab-traceable, and only
#       valid for THIS board near the reference frequency/gain.
#     * Level 2 (here, optional): sweep a flat reference to characterize the
#       front-end's frequency response, producing a correction you can feed
#       back into relative_power_db(freq_correction=...).
#
#   You need a reference source: a signal generator set to a known dBm, or a
#   characterized noise source. WITHOUT one, you cannot get absolute dBm --
#   the script will still show you gain-consistent RELATIVE readings.
#
#   SAFETY: read-only / receive-only. Never transmits.
#
#   Usage (single-point offset at a known reference):
#     uv run python examples/calibrate.py --ref-freq 100e6 --ref-dbm -30
#   Then use the printed offset:
#     h.relative_power_db(iq, offset_db=<printed offset>)
##--------------------------------------------------------------------\
import argparse
import json
import sys
import numpy as np
from hackrfpy import HackRF


def measure_dbfs(h, freq, rate, n, lna, vga, amp):
    iq = h.capture_array(freq, rate, n, lna=lna, vga=vga, amp=amp)
    return h.power_dbfs(iq)


def single_point_offset(h, args):
    # Level 3: feed a KNOWN dBm at ref-freq, measure dBFS, derive offset such
    # that  approx_dbm = relative_power_db(dbfs, ..., offset_db=offset).
    print(f"\n== single-point offset @ {args.ref_freq/1e6:g} MHz ==")
    print(f"   FEED A KNOWN {args.ref_dbm} dBm SIGNAL into the antenna port now.")
    if not args.assume_ready:
        input("   press Enter when the reference is connected and on... ")

    dbfs = measure_dbfs(h, args.ref_freq, args.rate, args.samples,
                        args.lna, args.vga, args.amp)
    # relative reading with zero offset = dbfs - gain_chain
    relative = h.relative_power_db(dbfs, lna=args.lna, vga=args.vga,
                                   amp=args.amp, offset_db=0.0)
    # we want: ref_dbm = relative + offset  ->  offset = ref_dbm - relative
    offset = args.ref_dbm - relative
    print(f"   measured: {dbfs:.2f} dBFS  (relative {relative:.2f} dB)")
    print(f"   => offset_db = {offset:.2f}")
    print(f"   sanity: relative_power_db(..., offset_db={offset:.2f}) now reads "
          f"~{args.ref_dbm} dBm at this freq/gain")
    return offset


def freq_response_curve(h, args):
    # Level 2: characterize the front-end shape. IDEALLY you sweep a FLAT
    # reference (a broadband noise source with known-flat output). Lacking
    # that, this still captures the *relative* shape vs the reference freq,
    # which removes most of the "why is 2.4 GHz lower than 100 MHz" confound.
    print(f"\n== frequency-response characterization ==")
    print("   NOTE: only meaningful with a FLAT reference source connected.")
    if not args.assume_ready:
        input("   press Enter with the flat reference on (or Ctrl-C to skip)... ")

    freqs = np.linspace(args.fr_min, args.fr_max, args.fr_points)
    table = {}
    ref = None
    for f in freqs:
        dbfs = measure_dbfs(h, float(f), args.rate, args.samples,
                            args.lna, args.vga, args.amp)
        rel = h.relative_power_db(dbfs, lna=args.lna, vga=args.vga, amp=args.amp)
        if ref is None:
            ref = rel
        # correction = how much this freq reads ABOVE the reference; subtract
        # it to flatten. Stored as freq -> correction_dB.
        table[float(f)] = rel - ref
        print(f"   {f/1e6:8.1f} MHz : {rel:7.2f} dB  (corr {table[float(f)]:+.2f})")
    return table


def main():
    p = argparse.ArgumentParser(
        description="HackRF calibration workflow (read-only). Levels 2-3 on "
                    "top of the library's Level-1 relative readings.")
    p.add_argument("--tools-dir", default=None)
    p.add_argument("--rate", type=float, default=2e6)
    p.add_argument("--samples", type=int, default=200_000)
    p.add_argument("--lna", type=int, default=16)
    p.add_argument("--vga", type=int, default=20)
    p.add_argument("--amp", action="store_true")
    # Level 3
    p.add_argument("--ref-freq", type=float, default=None,
                   help="reference frequency Hz (enables single-point offset)")
    p.add_argument("--ref-dbm", type=float, default=None,
                   help="known reference power in dBm at --ref-freq")
    # Level 2
    p.add_argument("--freq-response", action="store_true",
                   help="characterize front-end frequency response")
    p.add_argument("--fr-min", type=float, default=100e6)
    p.add_argument("--fr-max", type=float, default=1e9)
    p.add_argument("--fr-points", type=int, default=10)
    # misc
    p.add_argument("--assume-ready", action="store_true",
                   help="skip the 'press Enter' prompts (reference already on)")
    p.add_argument("--out", default="calibration.json",
                   help="where to save the derived calibration")
    args = p.parse_args()

    h = HackRF(tools_dir=args.tools_dir)
    det = h.detect()
    if not det["ready"]:
        print(f"no usable HackRF: {det['problem']}", file=sys.stderr)
        return 1
    print(f"[*] board ready: firmware {det['boards'][0].get('firmware')}")
    print("[*] REMINDER: the HackRF is not a calibrated instrument; results "
          "are approximate and specific to this board.")

    cal = {"board_serial": det["boards"][0]["serial"],
           "gain": {"lna": args.lna, "vga": args.vga, "amp": args.amp},
           "offset_db": None, "freq_correction": None}

    if args.ref_freq is not None and args.ref_dbm is not None:
        cal["offset_db"] = single_point_offset(h, args)
        cal["offset_ref_freq_hz"] = args.ref_freq
    else:
        print("\n[*] no --ref-freq/--ref-dbm given: skipping absolute offset "
              "(readings stay RELATIVE, gain-consistent).")

    if args.freq_response:
        try:
            cal["freq_correction"] = freq_response_curve(h, args)
        except KeyboardInterrupt:
            print("\n   (skipped frequency-response step)")

    with open(args.out, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"\n[*] saved calibration -> {args.out}")
    print("[*] use it like:")
    print("      cal = json.load(open('calibration.json'))")
    print("      db = h.relative_power_db(iq, offset_db=cal['offset_db'] or 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
