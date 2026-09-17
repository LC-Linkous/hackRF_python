#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/collect_real_FM_data.py'
#
#   Collect a REFERENCE recording of ONE FM broadcast station, with
#   enough validation and metadata that the capture can be compared
#   apples-to-apples against another implementation (e.g. a hardware
#   receiver or a different SDR) tuned to the same station.
#
#   This is deliberately SPLIT OUT from collect_real_data.py:
#     - collect_real_data.py    freezes tiny verbatim slices as parser
#                               test fixtures (bytes in, bytes archived).
#     - this script             records one KNOWN, VALIDATED signal --
#                               a named FM station -- and writes a
#                               machine-readable quality report next to
#                               it, so a hardware comparison has a
#                               trustworthy software-side baseline.
#
#   Validation performed on the capture (all recorded in the report):
#     - length vs. requested, mean power (dBFS), clipping fraction,
#       DC offset of the raw IQ
#     - FM discriminator + FFT: presence and SNR of the 19 kHz stereo
#       pilot, the definitive "this really is a broadcast FM station"
#       check (a pilot can't come from noise or a wrong tune)
#
#   SAFETY: strictly READ-ONLY. Never transmits, never writes firmware.
#
#   Usage:
#       uv run python tests/collect_real_FM_data.py --station 98.1e6
#       uv run python tests/collect_real_FM_data.py --station 100.9M \
#           --seconds 2.0 --sample-rate 2e6 --lna 24 --vga 20
#       uv run python tests/collect_real_FM_data.py --station 98.1M \
#           --tools-dir "C:\hackrf-tools-windows"
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\

import argparse
import datetime
import json
import os
import sys

# Allow running from the repo without installing: add src/ to the path.
_HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(_HERE, "..", "src"), os.path.join(_HERE, "src")):
    if os.path.isdir(os.path.join(cand, "hackrfpy")):
        sys.path.insert(0, os.path.abspath(cand))
        break

from hackrfpy import HackRF, load_iq, parse_freq       # noqa: E402
from hackrfpy.exceptions import HackRFError            # noqa: E402

try:
    import numpy as np                                 # noqa: E402
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: numpy not available -- run through uv so the project env is "
        "used:\n    uv run python tests/collect_real_FM_data.py [args]\n")
    sys.exit(1)

OUT_DIR = os.path.join(_HERE, "fm_reference")
PILOT_HZ = 19_000.0


def iq_metrics(iq):
    # Raw-IQ health: are we looking at a live front end at a sane level?
    mag = np.abs(iq)
    power = float(np.mean(mag.astype(np.float64) ** 2))
    return {
        "mean_power_dbfs": round(10 * np.log10(power + 1e-20), 2),
        "peak_amplitude": round(float(mag.max()) if len(iq) else 0.0, 4),
        "clip_fraction": round(float(np.mean(mag > 0.99)), 6),
        "dc_offset": round(float(abs(np.mean(iq))), 5),
    }


def pilot_metrics(iq, fs):
    # FM-demodulate (phase difference), then measure the 19 kHz stereo
    # pilot against the surrounding discriminator noise floor. A real
    # broadcast FM station shows a clear pilot; a wrong tune or a dead
    # antenna does not.
    if len(iq) < 8192:
        return {"pilot_detected": False, "reason": "capture too short"}
    demod = np.angle(iq[1:] * np.conj(iq[:-1]))
    n = len(demod)
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(demod * win)) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)

    def band_power(f_lo, f_hi):
        m = (freqs >= f_lo) & (freqs < f_hi)
        return float(spec[m].max()) if m.any() else 0.0

    pilot = band_power(PILOT_HZ - 300, PILOT_HZ + 300)
    # noise reference: flanking bands that broadcast FM leaves quiet-ish
    floor = np.median([band_power(21_000, 22_000),
                       band_power(16_000, 17_000)])
    snr_db = 10 * np.log10((pilot + 1e-20) / (floor + 1e-20))
    return {
        "pilot_detected": bool(snr_db > 6.0),
        "pilot_snr_db": round(float(snr_db), 1),
    }


def main():
    p = argparse.ArgumentParser(
        description="Record + validate one FM station as a reference "
                    "dataset (READ-ONLY).")
    p.add_argument("--station", required=True,
                   help="station center frequency (e.g. 98.1e6 or 98.1M)")
    p.add_argument("--seconds", type=float, default=2.0,
                   help="capture duration (default 2.0 s)")
    p.add_argument("--sample-rate", default="8e6",
                   help="sample rate sps (default 8e6: HackRF's baseband "
                        "filter bottoms out at 1.75 MHz, so rates under "
                        "8 Msps admit aliases; larger files are the price "
                        "of a trustworthy reference)")
    p.add_argument("--lna", type=int, default=32)
    p.add_argument("--vga", type=int, default=28)
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()
    freq = parse_freq(args.station)
    fs = parse_freq(args.sample_rate)
    n = int(fs * args.seconds)

    h = HackRF(tools_dir=args.tools_dir, verbose=False)
    print("== confirming a real board before collecting ==")
    det = h.detect()
    if not det["ready"]:
        print(f"  NO USABLE HACKRF: {det['problem']}", file=sys.stderr)
        return 1
    print(f"  ready: firmware {det['boards'][0].get('firmware')}")

    os.makedirs(OUT_DIR, exist_ok=True)
    stem = f"fm_{freq/1e6:g}MHz_{fs/1e6:g}Msps"
    iq_path = os.path.join(OUT_DIR, stem + ".iq")

    print(f"== capturing {args.seconds}s of {freq/1e6:g} MHz "
          f"@ {fs/1e6:g} Msps ==")
    try:
        h.capture(freq, fs, num_samples=n, out=iq_path,
                  lna=args.lna, vga=args.vga, sigmf=True)
    except HackRFError as e:
        print(f"  capture failed: {e}", file=sys.stderr)
        return 1

    iq = load_iq(iq_path)
    report = {
        "station_hz": freq,
        "sample_rate": fs,
        "requested_samples": n,
        "captured_samples": len(iq),
        "lna_gain_db": h.last_params.get("lna_gain", h.last_params.get("lna")),
        "vga_gain_db": h.last_params.get("vga_gain", h.last_params.get("vga")),
        "firmware": det["boards"][0].get("firmware"),
        "tools_version": det["tools_version"],
        "collected": datetime.datetime.now().isoformat(timespec="seconds"),
        "iq": iq_metrics(iq),
        "fm": pilot_metrics(iq, fs),
    }
    report_path = os.path.join(OUT_DIR, stem + ".report.json")
    with open(report_path, "w", newline="\n") as f:
        json.dump(report, f, indent=2)

    print(f"  wrote {os.path.basename(iq_path)} "
          f"({os.path.getsize(iq_path)/1e6:.1f} MB) + .sigmf-meta")
    print(f"  wrote {os.path.basename(report_path)}")
    print(f"  IQ    : {report['iq']}")
    print(f"  pilot : {report['fm']}")

    ok = (len(iq) >= 0.9 * n
          and report["iq"]["mean_power_dbfs"] > -70
          and report["iq"]["peak_amplitude"] >= 0.1
          and report["iq"]["clip_fraction"] < 0.01
          and report["fm"].get("pilot_detected", False))
    if report["iq"]["peak_amplitude"] < 0.1:
        print("  [!] low ADC utilization -- raise --lna/--vga (or use "
              "tests/collect_fm_testdata.py, which auto-calibrates)",
              file=sys.stderr)
    if ok:
        print("== PASS: capture looks like a real FM station ==")
        return 0
    print("== SUSPECT: capture failed one or more checks -- verify the "
          "station frequency, antenna, and gains, then re-run ==",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
