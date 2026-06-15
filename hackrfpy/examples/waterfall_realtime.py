#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/waterfall_realtime.py'
#   Live waterfall from hackrf_sweep. Needs the [plotting] extra.
#   Demonstrates consuming the sweep generator as frames arrive, with a
#   clean shutdown that reaps hackrf_sweep on Ctrl-C (sweep_stream).
##--------------------------------------------------------------------\
import numpy as np
import matplotlib.pyplot as plt
from hackrfpy import HackRF

F_MIN, F_MAX = 88e6, 108e6          # FM broadcast band
ROWS = 100

h = HackRF()
fig, ax = plt.subplots()
img = None

# A single hackrf_sweep pass over a wide band arrives as MANY rows (one per
# ~5 MHz tuning segment) that share a timestamp. We assemble all rows with the
# same timestamp into one spectrum line, then flush when the timestamp changes.
sweep_bins = {}
last_time = None
history = []


def flush_line():
    # concatenate the assembled segments low->high into one spectrum row
    global history, img
    line = np.concatenate([sweep_bins[k] for k in sorted(sweep_bins)])
    sweep_bins.clear()
    history.append(line)
    history = history[-ROWS:]
    arr = np.array(history)
    if img is None:
        img = ax.imshow(arr, aspect="auto", cmap="viridis")
    else:
        img.set_data(arr)
        img.set_clim(arr.min(), arr.max())
    plt.pause(0.001)


# sweep_stream guarantees hackrf_sweep is reaped on exit, including the
# KeyboardInterrupt that ends a live waterfall. Without the context manager a
# Ctrl-C could orphan the child sweep process.
try:
    with h.sweep_stream(F_MIN, F_MAX) as rows:
        for row in rows:
            if last_time is not None and row["time"] != last_time and sweep_bins:
                flush_line()
            sweep_bins[row["hz_low"]] = np.array(row["db"])
            last_time = row["time"]
except KeyboardInterrupt:
    pass    # context manager has already reaped the child on the way out
