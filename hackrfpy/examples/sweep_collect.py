#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/sweep_collect.py'
#   Collect one sweep across a band and save the bin powers to CSV.
##--------------------------------------------------------------------\
import csv
from hackrfpy import HackRF

h = HackRF(verbose=True)
rows = h.sweep_collect(400e6, 500e6, num_sweeps=1)

with open("sweep.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["hz_low", "hz_high", "bin_width", "db_min", "db_max"])
    for r in rows:
        w.writerow([r["hz_low"], r["hz_high"], r["bin_width"],
                    min(r["db"]), max(r["db"])])
print(f"wrote {len(rows)} sweep segments to sweep.csv")
