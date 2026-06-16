# hackrfpy

**An Unofficial Python CLI + Scripting Wrapper for the HackRF One that works on Windows**

[![PyPI version](https://badge.fury.io/py/hackrfpy.svg)](https://badge.fury.io/py/hackrfpy)
[![Python versions](https://img.shields.io/pypi/pyversions/hackrfpy.svg)](https://pypi.org/project/hackrfpy/)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/hackrfpy.svg)](https://pypi.org/project/hackrfpy/)
[![Downloads](https://static.pepy.tech/badge/hackrfpy)](https://pepy.tech/project/hackrfpy)
[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)

A non-GUI Python wrapper and command-line tool for the HackRF One software-defined radio. This library provides programmatic control for IQ capture, spectrum sweeps, and transmit, with self-describing SigMF recordings.

Unlike libraries that bind to `libhackrf` through C extensions, hackrfpy runs the standard `hackrf-tools` command-line binaries (`hackrf_info`, `hackrf_transfer`, `hackrf_sweep`, and the device-management tools) as subprocesses. Nothing has to be compiled, which is what makes it practical to install and run on Windows. The cost is that the `hackrf-tools` binaries are a **system** dependency you install separately; see [Installation](#installation).

This repository uses official resources and documentation but is **NOT** endorsed by Great Scott Gadgets or the HackRF project. Refer to official resources and support for product information.

## Features

- **Device Discovery** — detect and identify connected HackRF boards, report firmware and identity
- **IQ Capture** — bounded, timed, streaming, or callback-style receive; decoded to normalized `complex64`
- **Spectrum Sweep** — collect or stream `hackrf_sweep` output across a frequency range
- **Transmit** — file playback and constant-wave test mode, behind a deliberate TX-mode gate
- **Operating Envelope** — per-parameter range checks and gain snapping against the device's real steps
- **SigMF Recordings** — self-describing `.iq` captures with metadata sidecars
- **Error Handling** — a typed exception hierarchy and verbose output options
- **CLI** — the `hrf` command-line shell over the full API

## Installation

```bash
pip install hackrfpy
```

The library itself depends only on `numpy`. The plotting examples need an optional extra:

```bash
pip install "hackrfpy[plotting]"
```

Python 3.11+ is required.

**You also need the `hackrf-tools` binaries**, which are *not* a pip dependency — they are installed at the OS level:

- **Linux:** `sudo apt install hackrf` (or your distribution's equivalent)
- **macOS:** `brew install hackrf`
- **Windows:** the tools are published as CI build artifacts under the [Actions tab](https://github.com/greatscottgadgets/hackrf/actions) of the HackRF repo; see the main repository README for the step-by-step.

Verify the install with `hackrf_info`.

## Quick Start

```python
from hackrfpy import HackRF

h = HackRF()
det = h.detect()
if det["ready"]:
    print(h.identify())
```

To collect a bounded IQ capture as a normalized `complex64` array:

```python
from hackrfpy import HackRF

h = HackRF()
iq = h.capture_array(433.92e6, 8e6, num_samples=1_000_000)   # 433.92 MHz, 8 Msps
print(iq.dtype, len(iq))                                      # complex64, 1000000
```

To run a single spectrum sweep:

```python
from hackrfpy import HackRF

h = HackRF()
rows = h.sweep_collect(88e6, 108e6, num_sweeps=1)   # FM broadcast band
for r in rows:
    print(r["hz_low"], r["hz_high"], min(r["db"]), max(r["db"]))
```

## Transmitting

Transmit is gated behind an explicit mode switch, because an accidental transmit is the one operation that can damage equipment or break the law:

```python
from hackrfpy import HackRF

h = HackRF()
h.set_mode("tx")                # prints the TX-mode safety banner
h.transmit(433.92e6, 8e6, "signal.iq", txvga=20)
```

**Transmitting is regulated.** You are responsible for operating within the law and within your equipment's limits.

## Examples

The [main GitHub repository](https://github.com/LC-Linkous/hackRF_python) provides runnable examples, grouped by what they demonstrate.

**Getting started / device control**

- `device_explorer.py` — detect, identify, and report board capabilities (read-only)
- `capture_to_file.py` — bounded capture to a file with a SigMF sidecar, then read it back

**Acquisition**

- `persistent_capture.py` — collect many segments at one frequency from a single long-lived process
- `power_meter.py` — live dBFS power meter at one frequency via the callback API
- `scan_then_capture.py` — sweep a band, find the strongest bin, then capture there

**Sweep and plotting**

- `sweep_collect.py` — one sweep across a band, saved to CSV
- `waterfall_realtime.py` — a live, continuously updating spectrum waterfall
- `waterfall_persistent.py` — a single-frequency FFT waterfall over time

**Calibration and benchmarking**

- `calibrate.py` — derive an `offset_db` and frequency-response curve for relative-power readings
- `benchmark.py` — measure decode throughput and callback latency on your hardware

**Sample data**

- `collect_sample_data.py` — collect real IQ + sweep datasets (read-only; never transmits)

> Most plotting examples require the optional plotting dependencies:
> `pip install "hackrfpy[plotting]"`

## Documentation

For comprehensive documentation, the full method reference, the CLI reference, and the operating envelope:

- **Library GitHub repository**: [https://github.com/LC-Linkous/hackRF_python/](https://github.com/LC-Linkous/hackRF_python/)
- **Official HackRF documentation**: [https://hackrf.readthedocs.io/](https://hackrf.readthedocs.io/) (not associated with this library)

## Contributing

This is an unofficial community project. Contributions welcome!

- Report bugs and request features on [GitHub](https://github.com/LC-Linkous/hackRF_python)
- For device information and OFFICIAL resources, see [https://hackrf.readthedocs.io/](https://hackrf.readthedocs.io/)
  - Please do **NOT** request features or report bugs to Great Scott Gadgets or the HackRF project! This is an unofficial project and they do not maintain it.

## Citing

If you use this library in your work, citation details are in the repository's `CITATION.cff`.

## License

GPL-2.0 — this package and the repo code is unofficial software with no warranty, offered AS-IS. Use at your own risk.

The licensing of this software does NOT take priority over the official releases and the decisions of Great Scott Gadgets, and does NOT apply to any of their products or firmware.

## Acknowledgments

- Great Scott Gadgets and the HackRF community, who created and maintain the device and its tools
- Official HackRF documentation and resources, especially [hackrf.readthedocs.io](https://hackrf.readthedocs.io/)
- All contributors to this library, including those who have contributed code and reached out with questions

---

**Disclaimer**: This software is unofficial and not supported by Great Scott Gadgets or the HackRF project. For official software and support, visit [hackrf.readthedocs.io](https://hackrf.readthedocs.io/). The HackRF makers do not offer tech support for this software, do not maintain it, and have no responsibility for any of the contents.