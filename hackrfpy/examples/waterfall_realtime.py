#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/waterfall_realtime.py'
#   Live spectrum waterfall from hackrf_sweep. Needs the [plotting] extra.
#
#   Demonstrates consuming the sweep generator as frames arrive, with a
#   clean shutdown that reaps hackrf_sweep on Ctrl-C (sweep_stream).
#
#   Robust to real hackrf_sweep behavior: segments arrive OUT OF ORDER and a
#   sweep pass can be partial at the flush boundary, so every spectrum line is
#   conformed to a fixed width before being stacked into the image (a naive
#   np.array(history) crashes on the resulting ragged rows).
##--------------------------------------------------------------------\
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import colors
from hackrfpy import HackRF

# ---- what to watch -------------------------------------------------------
F_MIN, F_MAX = 2.40e9, 2.50e9      # 2.4 GHz ISM (Wi-Fi / BT / microwave leak)
ROWS = 160                          # waterfall history depth (time axis)
DB_FLOOR, DB_CEIL = -90, -20        # fixed color scale (dBFS); stable colors

# ---- aesthetic: a signals-monitor identity, not a default plot -----------
# Palette drawn from spectrum-monitor / oscilloscope vernacular: near-black
# instrument background, phosphor-cyan accents, signal mapped through a
# perceptually-uniform heat map (turbo) so weak-to-strong reads intuitively.
BG      = "#0a0e14"   # instrument black-blue
PANEL   = "#0d1320"
GRID    = "#1c2738"
ACCENT  = "#36e0c8"   # phosphor cyan
TEXT    = "#9fb3c8"   # cool grey-blue
TEXTDIM = "#52617a"
CMAP    = "turbo"     # perceptually uniform, high dynamic range

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": PANEL,
    "savefig.facecolor": BG,
    "font.family": "monospace",         # telemetry feel
    "text.color": TEXT,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT,
    "xtick.color": TEXTDIM,
    "ytick.color": TEXTDIM,
    "axes.linewidth": 0.8,
})

h = HackRF()

fig, ax = plt.subplots(figsize=(11, 6))
try:
    fig.canvas.manager.set_window_title("hackrfpy :: live spectrum waterfall")
except Exception:
    pass

img = None
cbar = None
width = None                 # locked to the first COMPLETE sweep's bin count
history = []

# assemble all rows sharing a timestamp into one spectrum line
sweep_bins = {}
last_time = None
sweeps_seen = 0


def assemble_line():
    # concatenate segments low->high (real hackrf_sweep emits them out of
    # order, so sort by hz_low) into one spectrum row
    return np.concatenate([sweep_bins[k] for k in sorted(sweep_bins)])


def conform(line, w):
    # make a line exactly w wide: truncate if long, edge-pad if short. Real
    # sweeps occasionally yield a partial pass at the flush boundary; this
    # keeps the image rectangular instead of crashing np.array on ragged rows.
    if len(line) == w:
        return line
    if len(line) > w:
        return line[:w]
    return np.pad(line, (0, w - len(line)), mode="edge")


def style_axes():
    band = f"{F_MIN/1e6:.0f}\u2013{F_MAX/1e6:.0f} MHz"
    ax.set_title(f"LIVE SPECTRUM  \u2014  {band}",
                 color=ACCENT, fontsize=13, fontweight="bold",
                 loc="left", pad=12, family="monospace")
    ax.set_xlabel("frequency (MHz)", fontsize=9)
    ax.set_ylabel("time  (newest at top)", fontsize=9)
    # frequency ticks across the band
    xt = np.linspace(0, width - 1, 6)
    xl = [f"{(F_MIN + (F_MAX - F_MIN) * (t / max(width - 1, 1)))/1e6:.0f}"
          for t in xt]
    ax.set_xticks(xt)
    ax.set_xticklabels(xl)
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(GRID)


def flush_line():
    global history, img, cbar, width
    line = assemble_line()
    sweep_bins.clear()

    if width is None:
        # lock the image width to the first complete sweep we see
        width = len(line)

    history.append(conform(line, width))
    history = history[-ROWS:]
    arr = np.array(history)              # now guaranteed rectangular
    arr = arr[::-1]                      # newest row on top

    if img is None:
        img = ax.imshow(arr, aspect="auto", cmap=CMAP,
                        norm=colors.Normalize(vmin=DB_FLOOR, vmax=DB_CEIL),
                        interpolation="nearest", origin="upper",
                        extent=[0, width, 0, len(arr)])
        cbar = fig.colorbar(img, ax=ax, pad=0.01, fraction=0.046)
        cbar.set_label("power (dBFS)", color=TEXT, fontsize=9)
        cbar.ax.yaxis.set_tick_params(color=TEXTDIM)
        cbar.outline.set_edgecolor(GRID)
        plt.setp(plt.getp(cbar.ax, "yticklabels"), color=TEXTDIM)
        style_axes()
        fig.tight_layout()
    else:
        img.set_data(arr)
        img.set_extent([0, width, 0, len(arr)])

    plt.pause(0.001)


print(f"[*] live waterfall {F_MIN/1e6:.0f}-{F_MAX/1e6:.0f} MHz "
      f"-- close the window or Ctrl-C to stop")

# sweep_stream guarantees hackrf_sweep is reaped on exit, including the
# KeyboardInterrupt that ends a live waterfall. Without the context manager a
# Ctrl-C could orphan the child sweep process.
try:
    with h.sweep_stream(F_MIN, F_MAX) as rows:
        for row in rows:
            if last_time is not None and row["time"] != last_time and sweep_bins:
                sweeps_seen += 1
                flush_line()
            sweep_bins[row["hz_low"]] = np.array(row["db"])
            last_time = row["time"]
except KeyboardInterrupt:
    pass    # context manager has already reaped the child on the way out

print("[*] stopped")