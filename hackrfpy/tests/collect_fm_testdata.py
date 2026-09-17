#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/collect_fm_testdata.py'
#
#   REPEATABLE FM test-data generator: finds candidate stations,
#   calibrates gain, VERIFIES each candidate's 19 kHz pilot on a short
#   probe, records the first verified station, and validates the result.
#   If every stage fails, FALLS BACK to a deterministic synthetic FM
#   recording in the identical on-disk format, so downstream work is
#   never blocked by RF conditions, time of day, weather, or a missing
#   board.
#
#   Pipeline (hardware path):
#     1. DISCOVER   sweep 88-108 MHz, take the TOP-N hottest bins as
#                   candidate stations (skipped when --station is given)
#     2. CALIBRATE  probe captures, walking LNA/VGA until peak amplitude
#                   lands in [0.25, 0.70]
#     3. VERIFY     for each candidate: short probe, refine to the true
#                   100 kHz channel, measure the pilot AT the offset;
#                   first candidate with pilot SNR >= 6 dB wins. Station
#                   strength varies with propagation and weather, so no
#                   single sweep argmax is ever trusted with the full
#                   recording.
#     4. RECORD     the verified station at a +300 kHz offset from
#                   center, clear of the DC/LO spike
#     5. VALIDATE   length, ADC utilization, clipping, pilot
#
#   Sample-rate handling: the HackRF's baseband filter bottoms out at
#   1.75 MHz, so rates under 8 Msps admit aliases (the library warns
#   about exactly this). ALL hardware captures here therefore run at an
#   integer multiple of the output rate that is >= 8 Msps, then decimate
#   in software (windowed-sinc FIR) down to --sample-rate. The output
#   files are unchanged: 2 Msps int8 + SigMF by default.
#
#   Fallback (--fallback auto|always|never, default auto): synthesizes
#   broadcast-style FM at the same rate/offset -- 19 kHz pilot, 1 kHz
#   L+R tone, 75 kHz deviation, seeded noise -- quantized to int8 and
#   written with a SigMF sidecar plus a report.json marked
#   "mode": "synthetic". Deterministic: identical bytes on every run.
#
#   Every run's report.json logs the candidates tried and their pilot
#   SNRs, so collections at different times of day stay comparable.
#
#   Output: tests/fm_testdata/  (iq + .sigmf-meta + .report.json)
#   Exit codes: 0 = usable data written (hardware OR synthetic),
#               1 = nothing written (only possible with --fallback never)
#
#   SAFETY: strictly READ-ONLY. Never transmits, never writes firmware.
#
#   Usage:
#       uv run python tests/collect_fm_testdata.py
#       uv run python tests/collect_fm_testdata.py --station 97.3M
#       uv run python tests/collect_fm_testdata.py --fallback always
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\

import argparse
import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(_HERE, "..", "src"), os.path.join(_HERE, "src")):
    if os.path.isdir(os.path.join(cand, "hackrfpy")):
        sys.path.insert(0, os.path.abspath(cand))
        break

from hackrfpy import HackRF, parse_freq, write_sigmf_meta   # noqa: E402
from hackrfpy.exceptions import HackRFError                  # noqa: E402

try:
    import numpy as np                                       # noqa: E402
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: numpy not available -- run through uv:\n"
        "    uv run python tests/collect_fm_testdata.py [args]\n")
    sys.exit(1)

OUT_DIR = os.path.join(_HERE, "fm_testdata")
STATION_OFFSET = 300_000.0        # station sits here, clear of the DC spike
PEAK_LO, PEAK_HI = 0.25, 0.70     # ADC utilization target window
UTIL_FLOOR = 0.10                 # below this = unusable quantization
LNA_STEP, LNA_MAX = 8, 40
VGA_STEP, VGA_MAX = 8, 40
PILOT_HZ = 19_000.0
PILOT_OK_DB = 6.0
HW_RATE_FLOOR = 8_000_000         # capture at >= this; decimate to output
N_CANDIDATES = 4                  # stations to try before giving up


# ---- rate handling ----------------------------------------------------------

def hw_plan(out_rate):
    # Smallest integer multiple of the output rate that clears the aliasing
    # floor; HackRF takes any rate in 2-20 Msps. factor 1 = no decimation.
    if out_rate >= HW_RATE_FLOOR:
        return out_rate, 1
    factor = int(np.ceil(HW_RATE_FLOOR / out_rate))
    hw = out_rate * factor
    if hw > 20e6:                                  # can't clear the floor
        return out_rate, 1
    return hw, factor


def decimate(iq, factor):
    if factor == 1:
        return iq
    ntaps = 16 * factor + 1
    m = np.arange(ntaps) - (ntaps - 1) / 2
    cutoff = 0.45 / factor                          # of hw Nyquist
    taps = np.sinc(2 * cutoff * m) * np.hanning(ntaps)
    taps /= taps.sum()
    return np.convolve(iq, taps, mode="same")[::factor].astype(np.complex64)


# ---- shared analysis --------------------------------------------------------

def peak_amp(iq):
    return float(np.abs(iq).max()) if len(iq) else 0.0


def iq_metrics(iq):
    mag = np.abs(iq)
    p = float(np.mean(mag.astype(np.float64) ** 2)) if len(iq) else 0.0
    return {"mean_power_dbfs": round(10 * np.log10(p + 1e-20), 2),
            "peak_amplitude": round(peak_amp(iq), 4),
            "clip_fraction": round(float(np.mean(mag > 0.99)), 6) if len(iq) else 1.0,
            "dc_offset": round(float(abs(np.mean(iq))), 5) if len(iq) else 0.0}


def pilot_snr_db(iq, fs, offset_hz):
    # Shift the station (at offset_hz from center) to DC, decimate to
    # ~250 kHz, FM-discriminate, measure the pilot over the flanking floor.
    if len(iq) < 65536:
        return -99.0
    t = np.arange(len(iq)) / fs
    shifted = iq * np.exp(-2j * np.pi * offset_hz * t)
    d = max(1, int(fs // 250_000))
    lp = decimate(shifted, d) if d > 1 else shifted
    fsd = fs / d
    demod = np.angle(lp[1:] * np.conj(lp[:-1]))
    spec = np.abs(np.fft.rfft(demod * np.hanning(len(demod)))) ** 2
    fr = np.fft.rfftfreq(len(demod), 1.0 / fsd)

    def band(lo, hi):
        m = (fr >= lo) & (fr < hi)
        return float(spec[m].max()) if m.any() else 0.0

    pilot = band(PILOT_HZ - 300, PILOT_HZ + 300)
    floor = np.median([band(16_000, 17_000), band(21_000, 22_000)])
    return round(10 * np.log10((pilot + 1e-20) / (floor + 1e-20)), 1)


def validate(iq, expected_n, fs, offset_hz):
    m = iq_metrics(iq)
    reasons = []
    if len(iq) < 0.9 * expected_n:
        reasons.append(f"short read ({len(iq)}/{expected_n})")
    if m["peak_amplitude"] < UTIL_FLOOR:
        reasons.append(f"low ADC utilization (peak {m['peak_amplitude']:.3f} "
                       f"< {UTIL_FLOOR} -- raise LNA/VGA)")
    if m["clip_fraction"] > 0.01:
        reasons.append(f"clipping ({m['clip_fraction']*100:.1f}%)")
    snr = pilot_snr_db(iq, fs, offset_hz)
    if snr < PILOT_OK_DB:
        reasons.append(f"no 19 kHz pilot at offset (SNR {snr} dB)")
    m["pilot_snr_db"] = snr
    return (not reasons), reasons, m


def encode_iq(iq):
    out = np.empty(len(iq) * 2, dtype=np.int8)
    out[0::2] = np.clip(np.round(iq.real * 128.0), -128, 127)
    out[1::2] = np.clip(np.round(iq.imag * 128.0), -128, 127)
    return out.tobytes()


def write_set(stem, iq, center_hz, fs, report):
    os.makedirs(OUT_DIR, exist_ok=True)
    iq_path = os.path.join(OUT_DIR, stem + ".iq")
    with open(iq_path, "wb") as f:
        f.write(encode_iq(iq))
    write_sigmf_meta(iq_path, center_hz, fs,
                     lna=report.get("lna_gain_db", 0),
                     vga=report.get("vga_gain_db", 0),
                     amp=False, datatype="ci8")
    report_path = os.path.join(OUT_DIR, stem + ".report.json")
    with open(report_path, "w", newline="\n") as f:
        json.dump(report, f, indent=2)
    print(f"  wrote {os.path.basename(iq_path)} "
          f"({os.path.getsize(iq_path)/1e6:.1f} MB) + sidecar + report")
    return iq_path


# ---- hardware path ----------------------------------------------------------

def discover_candidates(h, hw_rate):
    print(f"== 1/5 discover: sweeping 88-108 MHz (top {N_CANDIDATES}) ==")
    rows = h.sweep_collect(88e6, 108e6, num_sweeps=3, lna=24, vga=24)
    bins = {}                                   # bin center -> best dB seen
    for r in rows:
        for i, db in enumerate(r["db"]):
            hz = r["hz_low"] + (i + 0.5) * r["bin_width"]
            if 88e6 <= hz <= 108e6:
                bins[hz] = max(bins.get(hz, -999.0), db)
    ranked = sorted(bins.items(), key=lambda kv: -kv[1])[:N_CANDIDATES]
    for hz, db in ranked:
        print(f"  candidate bin {hz/1e6:6.1f} MHz  {db:6.1f} dB")
    return [hz for hz, _ in ranked]


def refine_channel(h, coarse_hz, hw_rate, factor, lna, vga):
    # One probe: find the strongest carrier near the coarse bin and snap it
    # to the broadcast 100 kHz raster. Runs at the alias-safe hw rate.
    probe = h.capture_array(coarse_hz, hw_rate, int(hw_rate * 0.05),
                            lna=lna, vga=vga)
    nfft = 8192
    acc = np.zeros(nfft)
    for k in range(len(probe) // nfft):
        acc += np.abs(np.fft.fftshift(
            np.fft.fft(probe[k*nfft:(k+1)*nfft] * np.hanning(nfft)))) ** 2
    c = nfft // 2
    acc[c-4:c+5] = 0                                  # ignore DC spike
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1.0 / hw_rate))
    inband = np.abs(freqs) < 600e3                    # stay near the bin
    acc[~inband] = 0
    station = coarse_hz + freqs[int(np.argmax(acc))]
    return round(station / 100e3) * 100e3


def calibrate_gain(h, center, hw_rate, args):
    print("== 2/5 calibrate: walking gains toward peak "
          f"[{PEAK_LO}, {PEAK_HI}] ==")
    lna, vga = args.lna, args.vga
    pk = 0.0
    for _ in range(8):
        iq = h.capture_array(center, hw_rate, 200_000, lna=lna, vga=vga)
        pk = peak_amp(iq)
        clip = float(np.mean(np.abs(iq) > 0.99))
        print(f"  lna {lna:2d} vga {vga:2d} -> peak {pk:.3f} clip {clip*100:.2f}%")
        if clip > 0.001 or pk > PEAK_HI:
            if vga > 0:
                vga = max(0, vga - VGA_STEP)
            elif lna > 0:
                lna = max(0, lna - LNA_STEP)
            else:
                break
        elif pk < PEAK_LO:
            if vga < VGA_MAX:
                vga = min(VGA_MAX, vga + VGA_STEP)
            elif lna < LNA_MAX:
                lna = min(LNA_MAX, lna + LNA_STEP)
            else:
                break                                  # maxed out; take it
        else:
            break
    return lna, vga, pk


def verify_candidates(h, candidates, hw_rate, factor, out_rate, lna, vga, tried):
    print(f"== 3/5 verify: pilot check per candidate (need >= "
          f"{PILOT_OK_DB:g} dB) ==")
    for coarse in candidates:
        station = refine_channel(h, coarse, hw_rate, factor, lna, vga)
        center = station - STATION_OFFSET
        probe_hw = h.capture_array(center, hw_rate, int(hw_rate * 0.5),
                                   lna=lna, vga=vga)
        probe = decimate(probe_hw, factor)
        snr = pilot_snr_db(probe, out_rate, STATION_OFFSET)
        tried.append({"station_hz": station, "pilot_snr_db": snr})
        mark = "OK" if snr >= PILOT_OK_DB else "--"
        print(f"  {station/1e6:6.1f} MHz  pilot {snr:6.1f} dB  {mark}")
        if snr >= PILOT_OK_DB:
            return station
    return None


def hardware_capture(args):
    h = HackRF(tools_dir=args.tools_dir, verbose=False)
    det = h.detect()
    if not det["ready"]:
        print(f"  no usable HackRF: {det['problem']}", file=sys.stderr)
        return None
    out_rate = args.sample_rate
    hw_rate, factor = hw_plan(out_rate)
    if factor > 1:
        print(f"[*] capturing at {hw_rate/1e6:g} Msps, decimating x{factor} "
              f"to {out_rate/1e6:g} Msps (alias-safe)")
    tried = []
    if args.station:
        candidates = [parse_freq(args.station)]
    else:
        candidates = discover_candidates(h, hw_rate)
        if not candidates:
            print("  sweep found nothing", file=sys.stderr)
            return None
    lna, vga, pk = calibrate_gain(h, candidates[0] - STATION_OFFSET,
                                  hw_rate, args)
    if pk < UTIL_FLOOR:
        print(f"  calibration could not reach usable level (peak {pk:.3f})",
              file=sys.stderr)
        return None
    station = verify_candidates(h, candidates, hw_rate, factor, out_rate,
                                lna, vga, tried)
    if station is None:
        print("  no candidate showed a pilot (conditions? antenna?)",
              file=sys.stderr)
        return None
    center = station - STATION_OFFSET
    n_out = int(out_rate * args.seconds)
    print(f"== 4/5 record: {args.seconds}s, station {station/1e6:.1f} MHz "
          f"at +{STATION_OFFSET/1e3:.0f} kHz, lna {lna} vga {vga} ==")
    try:
        iq_hw = h.capture_array(center, hw_rate, int(hw_rate * args.seconds),
                                lna=lna, vga=vga)
    except HackRFError as e:
        print(f"  capture failed: {e}", file=sys.stderr)
        return None
    iq = decimate(iq_hw, factor)[:n_out]
    print("== 5/5 validate ==")
    ok, reasons, m = validate(iq, n_out, out_rate, STATION_OFFSET)
    for r in reasons:
        print(f"  [!] {r}", file=sys.stderr)
    print(f"  metrics: {m}")
    if not ok:
        return None
    report = {"mode": "hardware", "station_hz": station,
              "center_hz": center, "offset_hz": STATION_OFFSET,
              "sample_rate": out_rate, "hw_sample_rate": hw_rate,
              "decimation": factor, "samples": len(iq),
              "lna_gain_db": lna, "vga_gain_db": vga,
              "candidates_tried": tried,
              "firmware": det["boards"][0].get("firmware"),
              "tools_version": det["tools_version"],
              "collected": datetime.datetime.now().isoformat(timespec="seconds"),
              "metrics": m}
    stem = f"fm_hw_{station/1e6:g}MHz_{out_rate/1e6:g}Msps"
    return write_set(stem, iq, center, out_rate, report)


# ---- synthetic fallback -----------------------------------------------------

def synthesize(args):
    # Deterministic broadcast-style FM: pilot + L+R tone, 75 kHz deviation,
    # station at +STATION_OFFSET, fixed-seed noise floor. Same bytes every run.
    print("== synthesizing deterministic FM (fallback) ==")
    fs, secs = args.sample_rate, args.seconds
    n = int(fs * secs)
    t = np.arange(n) / fs
    audio = 0.9 * np.sin(2 * np.pi * 1_000.0 * t)          # L+R tone
    pilot = 0.09 * np.sin(2 * np.pi * PILOT_HZ * t)
    baseband = audio + pilot
    phase = 2 * np.pi * 75_000.0 * np.cumsum(baseband) / fs
    carrier = 0.5 * np.exp(1j * (2 * np.pi * STATION_OFFSET * t + phase))
    rng = np.random.default_rng(20260917)                   # fixed seed
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    iq = (carrier + 0.005 * noise).astype(np.complex64)

    ok, reasons, m = validate(iq, n, fs, STATION_OFFSET)     # same gate
    if not ok:
        print(f"  [!] synthetic failed self-check: {reasons}", file=sys.stderr)
    print(f"  metrics: {m}")
    report = {"mode": "synthetic", "station_hz": None,
              "center_hz": None, "offset_hz": STATION_OFFSET,
              "sample_rate": fs, "samples": n,
              "lna_gain_db": 0, "vga_gain_db": 0,
              "generator": "collect_fm_testdata.py deterministic v2",
              "seed": 20260917, "metrics": m}
    stem = f"fm_synth_{fs/1e6:g}Msps"
    return write_set(stem, iq, 0.0, fs, report) if ok else None


def main():
    p = argparse.ArgumentParser(
        description="Calibrated, pilot-verified FM test-data collection with "
                    "deterministic synthetic fallback (READ-ONLY).")
    p.add_argument("--station", default=None,
                   help="station frequency (e.g. 97.3M); default: "
                        "auto-discover and verify top candidates")
    p.add_argument("--seconds", type=float, default=2.0)
    p.add_argument("--sample-rate", type=parse_freq, default=2e6,
                   help="OUTPUT rate; hardware runs at >=8 Msps and "
                        "decimates (default 2M)")
    p.add_argument("--lna", type=int, default=32, help="calibration start LNA")
    p.add_argument("--vga", type=int, default=28, help="calibration start VGA")
    p.add_argument("--fallback", choices=["auto", "always", "never"],
                   default="auto")
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()

    path = None
    if args.fallback != "always":
        try:
            path = hardware_capture(args)
        except Exception as e:                       # never block the pipeline
            print(f"  hardware path error: {e}", file=sys.stderr)
    if path is None and args.fallback != "never":
        path = synthesize(args)
    if path:
        print(f"== OK: usable FM test data at {os.path.relpath(path, _HERE)} ==")
        return 0
    print("== FAILED: no usable data written ==", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
