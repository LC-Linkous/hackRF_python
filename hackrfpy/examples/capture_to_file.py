#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/capture_to_file.py'
#   Bounded capture to a file (+ SigMF sidecar), then read it back the
#   intended way: load_iq for the samples, read_sigmf_meta for the
#   recording parameters. Neither needs a device or a HackRF() instance,
#   so any downstream consumer can use them standalone.
#   Built ON TOP of the library; not required by it.
##--------------------------------------------------------------------\
import numpy as np
from hackrfpy import HackRF, load_iq, read_sigmf_meta

h = HackRF(verbose=True)
h.capture(433.92e6, 8e6, num_samples=2_000_000, out="capture.iq", lna=24, vga=20)

# samples: int8 file -> normalized complex64, no manual decode step
iq = load_iq("capture.iq")
# bounded/offset reads also work for big files:
#   first_second = load_iq("capture.iq", count=8_000_000)
#   tail         = load_iq("capture.iq", offset_samples=1_000_000)

# parameters: recover them from the sidecar instead of hard-coding
meta = read_sigmf_meta("capture.iq")
fs = meta["global"]["core:sample_rate"]
fc = meta["captures"][0]["core:frequency"]

power_db = 10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-12)
print(f"captured {len(iq)} samples @ {fs/1e6:g} Msps, fc={fc/1e6:.3f} MHz, "
      f"mean power {power_db:.1f} dBFS")
