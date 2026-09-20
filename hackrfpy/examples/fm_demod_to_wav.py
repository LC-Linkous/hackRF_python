#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/fm_demod_to_wav.py'
#   The missing last mile: turn a captured IQ file into AUDIBLE audio.
#   Broadcast-FM demodulation -- channelize, discriminate, de-emphasize,
#   write a mono 16-bit WAV -- using only numpy and the stdlib.
#
#   Chain (rates for the default 8 Msps reference capture):
#     1. load IQ + SigMF sidecar (rate and center come from the sidecar)
#     2. mix the station to DC (--offset, for captures where the station
#        is parked off-center, e.g. +300 kHz from collect_fm_testdata.py)
#     3. FIR lowpass + decimate to a ~200 kHz channel (windowed sinc,
#        staged x8 then x5)
#     4. FM discriminator: phase difference of successive samples
#     5. 75 us de-emphasis (single-pole IIR; use --deemph 50 outside
#        the Americas/South Korea)
#     6. 15 kHz audio lowpass, decimate to 50 kHz, normalize, WAV
#
#   This intentionally decodes MONO (the L+R sum). The 19 kHz pilot,
#   38 kHz stereo subcarrier, and 57 kHz RDS are all present in the
#   discriminator output this script produces -- extracting them is the
#   natural next exercise, and the printed multiplex power readout shows
#   they are there.
#
#   Works on: tests/fm_reference/ captures (station at center),
#   tests/fm_testdata/ captures (--offset 300e3), or any FM capture with
#   a sidecar. SAFETY: file processing only; never touches the device.
#
#   Usage:
#     uv run python examples/fm_demod_to_wav.py tests/fm_reference/fm_98.1MHz_8Msps.iq
#     uv run python examples/fm_demod_to_wav.py \
#            tests/fm_testdata/fm_hw_103.7MHz_2Msps.iq --offset 300e3
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\
import argparse
import os
import sys
import time
import wave

import numpy as np

from hackrfpy import load_iq, parse_freq, read_sigmf_meta

AUDIO_FS_TARGET = 50_000.0        # output WAV rate (channel_fs / 4)
CHANNEL_FS_TARGET = 200_000.0     # wide enough for +/-75 kHz deviation


def lpf_decimate(x, factor, cutoff_frac=0.45):
    # Windowed-sinc FIR lowpass then downsample. cutoff_frac is relative to
    # the OUTPUT Nyquist; 0.45 leaves transition headroom.
    if factor == 1:
        return x
    ntaps = 16 * factor + 1
    m = np.arange(ntaps) - (ntaps - 1) / 2
    taps = np.sinc(2 * (cutoff_frac / factor) * m) * np.hanning(ntaps)
    taps /= taps.sum()
    return np.convolve(x, taps, mode="same")[::factor]


def staged_factors(total):
    # split a big decimation into stages (cheaper: taps scale per stage)
    stages = []
    for f in (8, 5, 4, 3, 2):
        while total % f == 0 and total > 1:
            stages.append(f)
            total //= f
    if total > 1:
        stages.append(total)
    return stages


def main():
    p = argparse.ArgumentParser(
        description="Demodulate a broadcast-FM IQ capture to a mono WAV.")
    p.add_argument("iq_file", help="int8 interleaved IQ file with sidecar")
    p.add_argument("--offset", type=parse_freq, default=0.0,
                   help="station offset from capture center in Hz "
                        "(default 0; collect_fm_testdata.py files use 300e3)")
    p.add_argument("--out", default=None,
                   help="output WAV path (default: alongside the IQ file)")
    p.add_argument("--deemph", type=float, default=75.0,
                   help="de-emphasis time constant in us (75 Americas/KR, "
                        "50 most elsewhere; default 75)")
    args = p.parse_args()

    meta = read_sigmf_meta(args.iq_file)
    fs = float(meta["global"]["core:sample_rate"])
    center = float(meta["captures"][0]["core:frequency"])
    station = center + args.offset
    print(f"[*] {os.path.basename(args.iq_file)}: {fs/1e6:g} Msps, "
          f"center {center/1e6:g} MHz, station {station/1e6:g} MHz")

    t0 = time.perf_counter()
    iq = load_iq(args.iq_file)

    # 2. mix the station to DC
    if args.offset:
        t = np.arange(len(iq)) / fs
        iq = iq * np.exp(-2j * np.pi * args.offset * t)

    # 3. channelize to ~200 kHz
    chan_factor = max(1, int(round(fs / CHANNEL_FS_TARGET)))
    x = iq
    for f in staged_factors(chan_factor):
        x = lpf_decimate(x, f)
    chan_fs = fs / chan_factor
    print(f"[*] channelized: x{chan_factor} -> {chan_fs/1e3:g} kHz "
          f"({time.perf_counter()-t0:.1f}s)")

    # 4. FM discriminator, scaled to Hz of instantaneous deviation
    demod = np.angle(x[1:] * np.conj(x[:-1])) * chan_fs / (2 * np.pi)

    # multiplex readout: prove the pilot/stereo/RDS are in there
    spec = np.abs(np.fft.rfft(demod * np.hanning(len(demod)))) ** 2
    fr = np.fft.rfftfreq(len(demod), 1.0 / chan_fs)

    def band_db(lo, hi):
        m = (fr >= lo) & (fr < hi)
        return 10 * np.log10(float(spec[m].max()) + 1e-20) if m.any() else -200

    ref = band_db(300, 15_000)
    print(f"[*] multiplex (dB rel. audio peak): "
          f"pilot 19k {band_db(18_700, 19_300)-ref:+.1f}, "
          f"stereo 38k {band_db(37_000, 39_000)-ref:+.1f}, "
          f"RDS 57k {band_db(56_500, 57_500)-ref:+.1f}")

    # 5. de-emphasis: single-pole IIR  y[n] = a*x[n] + b*y[n-1], with
    # a = 1 - exp(-1/(fs*tau)), b = 1 - a. A pure-python sample loop is too
    # slow, so evaluate the same recurrence blockwise: within each block,
    #   y[n] = a * sum_{k<=n} b^(n-k) x[k]  +  y_prev * b^(n+1)
    # via one convolution against the geometric kernel, carrying y_prev
    # across block boundaries. Numerically safe because b < 1 and blocks
    # are short enough that b^n underflows to 0 harmlessly.
    tau = args.deemph * 1e-6
    a = 1.0 - np.exp(-1.0 / (chan_fs * tau))
    b = 1.0 - a
    # The geometric kernel decays fast (b < 1), so truncate it where its
    # weight drops below 1e-9 -- a few hundred taps at 200 kHz -- instead
    # of convolving against a full-block kernel, which is quadratic.
    klen = int(np.ceil(np.log(1e-9) / np.log(b))) + 1
    kernel = a * b ** np.arange(klen)
    audio = np.empty_like(demod)
    y_prev = 0.0
    block = 262144
    for start in range(0, len(demod), block):
        seg = demod[start:start + block]
        n = len(seg)
        y = np.convolve(seg, kernel)[:n]
        decay = b ** np.arange(1, min(n, klen) + 1)
        y[:len(decay)] += y_prev * decay
        audio[start:start + n] = y
        y_prev = y[-1]

    # 6. audio lowpass + decimate to WAV rate
    audio_factor = max(1, int(round(chan_fs / AUDIO_FS_TARGET)))
    for f in staged_factors(audio_factor):
        audio = lpf_decimate(audio, f, cutoff_frac=0.30)   # 15 kHz at x4 from 200k
    audio_fs = chan_fs / audio_factor
    audio -= np.mean(audio)                    # remove residual tuning DC
    peak = float(np.max(np.abs(audio))) + 1e-12
    pcm = np.clip(audio / peak * 0.9 * 32767, -32768, 32767).astype("<i2")

    out = args.out or os.path.splitext(args.iq_file)[0] + ".wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(audio_fs))
        w.writeframes(pcm.tobytes())
    print(f"[*] wrote {out}  ({len(pcm)/audio_fs:.2f}s mono @ "
          f"{audio_fs/1e3:g} kHz; {time.perf_counter()-t0:.1f}s total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
