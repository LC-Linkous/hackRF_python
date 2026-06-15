#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/scan_then_capture.py'
#   Pipeline the class can express that CLI-only tools can't: sweep a band,
#   find the strongest bin, then capture at that frequency.
##--------------------------------------------------------------------\
import numpy as np
from hackrfpy import HackRF

h = HackRF(verbose=True)

# 1) one sweep over the ISM band
rows = h.sweep_collect(430e6, 440e6, num_sweeps=1)

# 2) find the peak bin across all segments
best_freq, best_db = None, -1e9
for r in rows:
    db = np.array(r["db"])
    i = int(np.argmax(db))
    if db[i] > best_db:
        best_db = float(db[i])
        span = r["hz_high"] - r["hz_low"]
        best_freq = r["hz_low"] + (i + 0.5) * span / len(db)

print(f"peak: {best_freq/1e6:.3f} MHz @ {best_db:.1f} dB")

# 3) capture there
h.capture(best_freq, 8e6, num_samples=4_000_000, out="peak.iq")
