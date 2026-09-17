#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'examples/collect_sample_data.py'
#
#   Collect REAL, usable example datasets from a connected HackRF One and
#   write them into a sample library (examples/sample_data/) with SigMF
#   metadata, so anyone who clones the repo has actual recordings to load,
#   inspect, and feed into downstream processing -- without owning a board.
#
#   This is DIFFERENT from tests/collect_real_data.py:
#     - collect_real_data.py freezes TINY verbatim slices as PARSER TEST
#       FIXTURES (16 bytes of IQ, a few sweep rows).
#     - this script collects SAMPLE DATASETS: real captures big enough to
#       be useful, with SigMF sidecars, organized as a sample library.
#
#   SAFETY: strictly READ-ONLY. Receive and sweep only. Never transmits,
#   never writes firmware. Stays in RX mode throughout.
#
#   Sizes are kept small by default so the samples can live in the repo
#   (a 0.5 s capture at 2 Msps is ~2 MB of int8 I/Q). Use --seconds /
#   --sample-rate to collect larger local datasets.
#
#   Usage:
#       uv run python examples/collect_sample_data.py
#       uv run python examples/collect_sample_data.py --tools-dir "C:\hackrf-tools-windows"
#       uv run python examples/collect_sample_data.py --band fm --band ism433
#       uv run python examples/collect_sample_data.py --seconds 1.0 --sample-rate 4e6
#
#   (Use `uv run` so the project environment with numpy is used.)
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

import argparse
import datetime
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(_HERE, "..", "src"), os.path.join(_HERE, "src")):
    if os.path.isdir(os.path.join(cand, "hackrfpy")):
        sys.path.insert(0, os.path.abspath(cand))
        break

from hackrfpy import HackRF, load_iq            # noqa: E402
from hackrfpy.exceptions import HackRFError     # noqa: E402

try:
    import numpy as np                          # noqa: E402
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: numpy not available -- run through uv so the project env is "
        "used:\n    uv run python examples/collect_sample_data.py [args]\n")
    sys.exit(1)

OUT_DIR = os.path.join(_HERE, "sample_data")

# Named band presets: an IQ capture at `center`, and (optionally) a sweep over
# (sweep_min, sweep_max). All legal to RECEIVE; FM is the universal default.
BANDS = {
    "fm": {
        "center": 98_000_000, "sweep": (88_000_000, 108_000_000),
        "desc": "FM broadcast band"},
    "airband": {
        "center": 124_000_000, "sweep": (118_000_000, 137_000_000),
        "desc": "VHF airband (AM voice)"},
    "ism433": {
        "center": 433_920_000, "sweep": (433_000_000, 435_000_000),
        "desc": "433 MHz ISM"},
    "ism915": {
        "center": 915_000_000, "sweep": (902_000_000, 928_000_000),
        "desc": "915 MHz ISM (US)"},
    "noaa": {
        "center": 137_500_000, "sweep": (137_000_000, 138_000_000),
        "desc": "NOAA weather satellite downlink"},
}


def _validate_capture(iq, expected_n):
    # Catch the failure modes of a bad collection run BEFORE the data goes
    # into the sample library: short reads, a dead/disconnected front end
    # (pure noise-floor silence), a stuck DC rail, and gain-induced clipping.
    # Returns (ok, [reasons]).
    reasons = []
    if len(iq) < 0.9 * expected_n:
        reasons.append(f"short read ({len(iq)}/{expected_n} samples)")
    if len(iq):
        mag = np.abs(iq)
        power_db = 10 * np.log10(float(np.mean(mag ** 2)) + 1e-20)
        if power_db < -70:
            reasons.append(f"suspiciously quiet ({power_db:.1f} dBFS -- "
                           "dead antenna / wrong gain?)")
        peak = float(mag.max())
        if peak < 0.1:
            reasons.append(f"low ADC utilization (peak {peak:.3f} < 0.1, "
                           f"~{int(peak*128)} of 127 int8 codes -- raise "
                           "LNA/VGA; see examples/calibrate.py)")
        clip = float(np.mean(mag > 0.99))
        if clip > 0.01:
            reasons.append(f"clipping ({clip*100:.1f}% of samples -- "
                           "reduce gain)")
        dc = float(abs(np.mean(iq)))
        if dc > 0.1:
            reasons.append(f"large DC offset ({dc:.3f})")
    else:
        reasons.append("empty capture")
    return (not reasons), reasons


def _signal_summary(iq):
    # A quick, honest description of what was captured: mean power and whether
    # there's evident signal vs noise floor. Not DSP -- just a sanity readout.
    if len(iq) == 0:
        return "empty"
    power = float(np.mean(np.abs(iq) ** 2))
    peak = float(np.max(np.abs(iq)))
    db = 10 * np.log10(power + 1e-12)
    return f"mean {db:.1f} dBFS, peak |amp| {peak:.3f}"


def collect_band(h, name, args, suspects):
    band = BANDS[name]
    os.makedirs(OUT_DIR, exist_ok=True)
    n = int(args.sample_rate * args.seconds)
    results = []

    # ---- IQ capture (with SigMF sidecar via capture()) ----
    iq_path = os.path.join(OUT_DIR, f"{name}_{int(args.sample_rate/1e6)}Msps.iq")
    print(f"\n== {name}: IQ capture @ {band['center']/1e6:g} MHz "
          f"({args.seconds}s, {args.sample_rate/1e6:g} Msps) ==")
    try:
        h.capture(band["center"], args.sample_rate, num_samples=n,
                  out=iq_path, sigmf=True, lna=args.lna, vga=args.vga)
        iq = load_iq(iq_path)
        size_mb = os.path.getsize(iq_path) / 1e6
        print(f"  wrote {os.path.basename(iq_path)} "
              f"({size_mb:.1f} MB, {len(iq)} samples) -- {_signal_summary(iq)}")
        print(f"  + {os.path.basename(iq_path).rsplit('.',1)[0]}.sigmf-meta")
        ok, reasons = _validate_capture(iq, n)
        if not ok:
            print("  [!] SUSPECT capture -- " + "; ".join(reasons),
                  file=sys.stderr)
            print("  [!] kept on disk, but re-run this band before shipping "
                  "it in the sample library", file=sys.stderr)
        results.append(iq_path)
        if not ok:
            suspects.append(iq_path)
    except HackRFError as e:
        print(f"  IQ capture failed: {e}", file=sys.stderr)

    # ---- sweep dataset (CSV) ----
    if not args.no_sweep and band.get("sweep"):
        lo, hi = band["sweep"]
        sweep_path = os.path.join(OUT_DIR, f"{name}_sweep.csv")
        print(f"  sweep {lo/1e6:g}-{hi/1e6:g} MHz ...")
        try:
            rows = h.sweep_collect(lo, hi, num_sweeps=args.sweep_count)
            with open(sweep_path, "w", newline="\n") as f:
                f.write("date,time,hz_low,hz_high,bin_width,num_samples,db...\n")
                for r in rows:
                    f.write(", ".join(
                        [r["date"], r["time"], str(r["hz_low"]),
                         str(r["hz_high"]), f"{r['bin_width']:.2f}",
                         str(r["num_samples"])]
                        + [f"{d:.2f}" for d in r["db"]]) + "\n")
            print(f"  wrote {os.path.basename(sweep_path)} ({len(rows)} rows)")
            results.append(sweep_path)
        except HackRFError as e:
            print(f"  sweep failed: {e}", file=sys.stderr)

    return results


def write_readme(collected, args, det, suspects=()):
    # A README for the sample library so the data is self-documenting.
    path = os.path.join(OUT_DIR, "README.md")
    with open(path, "w", newline="\n") as f:
        f.write("# hackrfpy sample data\n\n")
        f.write("Real recordings from a HackRF One, for trying the library "
                "and downstream processing without owning a board.\n\n")
        f.write(f"- collected: "
                f"{datetime.datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"- device firmware: {det['boards'][0].get('firmware')}\n")
        f.write(f"- tools: {det['tools_version']}\n")
        f.write(f"- sample rate: {args.sample_rate/1e6:g} Msps, "
                f"{args.seconds}s per IQ capture\n\n")
        f.write("Each `.iq` is interleaved int8 I/Q (HackRF native) with a "
                "`.sigmf-meta` sidecar describing frequency, rate, and gains. "
                "Load with:\n\n")
        f.write("```python\nfrom hackrfpy import load_iq, read_sigmf_meta\n"
                "iq = load_iq('fm_2Msps.iq')\n"
                "meta = read_sigmf_meta('fm_2Msps.iq')\n```\n\n")
        f.write("## Files\n\n")
        for p in collected:
            flag = "  **(SUSPECT -- failed validation; re-collect)**" \
                if p in suspects else ""
            f.write(f"- `{os.path.basename(p)}`{flag}\n")
    print(f"\n  wrote {os.path.relpath(path, _HERE)}")


def main():
    p = argparse.ArgumentParser(
        description="Collect real sample datasets from a HackRF (READ-ONLY).")
    p.add_argument("--tools-dir", default=None)
    p.add_argument("--band", action="append", choices=list(BANDS),
                   help="band(s) to collect; repeatable. "
                        "Default: fm, ism433, ism915")
    p.add_argument("--seconds", type=float, default=0.5,
                   help="capture duration per band (default 0.5s)")
    p.add_argument("--sample-rate", type=float, default=2e6,
                   help="sample rate in sps (default 2e6, small + USB-friendly)")
    p.add_argument("--sweep-count", type=int, default=1,
                   help="sweeps per band dataset (default 1)")
    p.add_argument("--lna", type=int, default=32,
                   help="LNA gain dB (default 32; the old library default of "
                        "16 produced ~3-bit captures on 2026-09-17)")
    p.add_argument("--vga", type=int, default=28,
                   help="VGA gain dB (default 28)")
    p.add_argument("--no-sweep", action="store_true",
                   help="IQ captures only, skip sweep datasets")
    args = p.parse_args()
    bands = args.band or ["fm", "ism433", "ism915"]

    h = HackRF(tools_dir=args.tools_dir, verbose=False)
    print("== confirming a real board before collecting ==")
    det = h.detect()
    if not det["ready"]:
        print(f"  NO USABLE HACKRF: {det['problem']}", file=sys.stderr)
        return 1
    print(f"  ready: firmware {det['boards'][0].get('firmware')}")
    for w in det.get("warnings", []):
        print(f"  ! {w}")

    collected = []
    suspects = []
    try:
        for name in bands:
            collected += collect_band(h, name, args, suspects)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
    if collected:
        write_readme(collected, args, det, suspects)
        total = sum(os.path.getsize(p) for p in collected
                    if p.endswith(".iq")) / 1e6
        print(f"\n== done: {len(collected)} files, ~{total:.1f} MB of IQ "
              f"in {os.path.relpath(OUT_DIR, _HERE)} ==")
    if suspects:
        print(f"== {len(suspects)} capture(s) FAILED validation -- see "
              "warnings above; re-run those bands ==", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
