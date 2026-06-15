#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/waterfall_persistent.py'
#   Single-frequency spectrum waterfall over time, driven by a PERSISTENT
#   receiver. Needs the [plotting] extra.
#
#   This is the COMPLEMENT to waterfall_realtime.py, not a replacement:
#     - waterfall_realtime.py : SWEEP-based. x-axis = frequency across a wide
#       band; shows WHERE activity is across the spectrum.
#     - waterfall_persistent.py (this) : RECEIVER-based. Locks ONE center
#       frequency, FFTs each block; x-axis = frequency WITHIN the capture
#       bandwidth; shows how one channel evolves over time at full rate.
#
#   It uses open_receiver() so the hackrf_transfer process spins up once and
#   streams continuously -- the natural fit for a live single-frequency view.
#   Read-only / receive-only; the receiver is reaped on exit.
#
#   Usage:
#     uv run python examples/waterfall_persistent.py --freq 100e6 --rate 8e6
#     uv run python examples/waterfall_persistent.py --freq 2437e6 --rate 10e6
##--------------------------------------------------------------------\
import argparse
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import colors
from hackrfpy import HackRF

# ---- aesthetic: same signals-monitor identity as the sweep waterfall ------
BG      = "#0a0e14"
PANEL   = "#0d1320"
GRID    = "#1c2738"
ACCENT  = "#36e0c8"
TEXT    = "#9fb3c8"
TEXTDIM = "#52617a"
CMAP    = "turbo"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": PANEL, "savefig.facecolor": BG,
    "font.family": "monospace", "text.color": TEXT, "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT, "xtick.color": TEXTDIM, "ytick.color": TEXTDIM,
    "axes.linewidth": 0.8,
})


def main():
    p = argparse.ArgumentParser(description="Single-freq waterfall (persistent RX).")
    p.add_argument("--freq", default="100e6", help="center frequency Hz")
    p.add_argument("--rate", default="8e6", help="sample rate sps")
    p.add_argument("--fft", type=int, default=1024, help="FFT size (bins)")
    p.add_argument("--rows", type=int, default=400, help="time history depth")
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()
    freq, rate, nfft, rows = float(args.freq), float(args.rate), args.fft, args.rows

    h = HackRF(tools_dir=args.tools_dir)
    det = h.detect()
    if not det["ready"]:
        print(f"no usable HackRF: {det['problem']}", file=sys.stderr)
        return 1

    # color scale in dBFS-ish FFT magnitude; fixed so colors are stable
    DB_FLOOR, DB_CEIL = -90, -20
    win = np.hanning(nfft).astype(np.float32)

    def spectrum(iq):
        # Average several FFT frames across the big block for a smoother line,
        # then suppress the center DC / LO-leakage spike that every direct-
        # conversion SDR shows at 0 Hz (the bright line dead-center). We
        # replace the few central bins with their neighbors so a real signal
        # isn't hidden under the artifact.
        nframes = max(1, len(iq) // nfft)
        acc = np.zeros(nfft, dtype=np.float64)
        for k in range(nframes):
            seg = iq[k * nfft:(k + 1) * nfft]
            if len(seg) < nfft:
                break
            sp = np.fft.fftshift(np.fft.fft(seg * win))
            acc += (np.abs(sp) / nfft) ** 2
        acc /= nframes
        db = 10 * np.log10(acc + 1e-12)
        # flatten the DC spike: overwrite the center +/-2 bins with a neighbor
        c = nfft // 2
        db[c - 2:c + 3] = db[c + 3]
        return db

    fig, ax = plt.subplots(figsize=(11, 6))
    try:
        fig.canvas.manager.set_window_title(
            "hackrfpy :: persistent-RX waterfall")
    except Exception:
        pass

    history = []
    img = None
    cbar = None
    # frequency axis: center +/- rate/2, in MHz
    f_lo = (freq - rate / 2) / 1e6
    f_hi = (freq + rate / 2) / 1e6

    print(f"[*] persistent waterfall @ {freq/1e6:g} MHz, {rate/1e6:g} Msps, "
          f"{nfft}-pt FFT  (close window or Ctrl-C to stop)")

    try:
        with h.open_receiver(freq, rate) as rx:
            # Read a LARGE block per iteration so the pipe drains fast enough
            # to keep hackrf_transfer streaming (reading only nfft=1024 samples
            # per loop, with a redraw each time, stalls the device at 10 Msps).
            # Each big block becomes one averaged waterfall row.
            block_samples = 262144
            while True:
                iq = rx.read(block_samples)
                if len(iq) < nfft:
                    break
                history.append(spectrum(iq))
                history = history[-rows:]
                arr = np.array(history)[::-1]   # newest on top

                if img is None:
                    img = ax.imshow(
                        arr, aspect="auto", cmap=CMAP,
                        norm=colors.Normalize(vmin=DB_FLOOR, vmax=DB_CEIL),
                        interpolation="nearest", origin="upper",
                        extent=[f_lo, f_hi, 0, len(arr)])
                    cbar = fig.colorbar(img, ax=ax, pad=0.01, fraction=0.046)
                    cbar.set_label("magnitude (dB)", color=TEXT, fontsize=9)
                    cbar.outline.set_edgecolor(GRID)
                    plt.setp(plt.getp(cbar.ax, "yticklabels"), color=TEXTDIM)
                    ax.set_title(
                        f"SINGLE-FREQ WATERFALL  \u2014  {freq/1e6:g} MHz "
                        f"\u00b1 {rate/2e6:g} MHz",
                        color=ACCENT, fontsize=13, fontweight="bold",
                        loc="left", pad=12, family="monospace")
                    ax.set_xlabel("frequency (MHz)", fontsize=9)
                    ax.set_ylabel("time  (newest at top)", fontsize=9)
                    ax.set_yticks([])
                    for s in ax.spines.values():
                        s.set_color(GRID)
                    fig.tight_layout()
                else:
                    img.set_data(arr)
                    img.set_extent([f_lo, f_hi, 0, len(arr)])
                plt.pause(0.001)
                if not plt.fignum_exists(fig.number):
                    break
    except KeyboardInterrupt:
        pass
    print("[*] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())