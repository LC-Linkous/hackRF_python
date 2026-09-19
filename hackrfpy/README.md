# hackrfpy

**An Unofficial Python CLI + Scripting Wrapper for the HackRF One that works on Windows**

[![Tests](https://github.com/LC-Linkous/hackRF_python/actions/workflows/tests.yml/badge.svg)](https://github.com/LC-Linkous/hackRF_python/actions/workflows/tests.yml)
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
- **Spectrum Sweep** — collect or stream `hackrf_sweep` output across a frequency range, plus multi-frequency power monitoring over time
- **Transmit** — file playback and constant-wave test mode, behind a deliberate TX-mode gate
- **Operating Envelope** — per-parameter range checks and gain snapping against the device's real steps
- **SigMF Recordings** — self-describing `.iq` captures with metadata sidecars
- **Error Handling** — a typed exception hierarchy and verbose output options
- **Lifecycle Safety** — clean interrupts on both platforms, an `atexit` backstop, and an OS dead-man (pdeathsig / Job Object) so even a hard-killed script cannot orphan a transmitter
- **CLI** — the `hrf` command-line shell over the full API

## Platform support

hackrfpy is developed and tested on **Windows**, and has also been verified on Debian Linux with real hardware. Running the `hackrf-tools` binaries as subprocesses — rather than binding to `libhackrf` through a C extension — is what makes that portability cheap: there is no compiler or build step on any platform, and each OS runs its own native tools. Process control is handled per-platform (`SIGINT` on POSIX, `CTRL_BREAK` on Windows), with the interrupt, flush, and dead-man paths covered by tests on every OS, no skips.

A platform is called **tested** here only after the full suite (hardware tests included) passes against a real board:

- **Windows** — the primary development platform, verified continuously against real hardware.
- **Linux** — verified 2026-09-19 on Debian 12 (`hackrf` 2022.09.1, firmware 2024.02.1): full suite, 227/227. Mechanics additionally exercised against tools 2023.01.1 on Ubuntu, so both packaged tools versions are known-good. Setup notes for Debian-family systems are in the [main repository README](https://github.com/LC-Linkous/hackRF_python#linux-setup-debian-family).

**macOS remains experimental**: the mechanics are CI-tested there, but board-attached operation is unverified. If you run it with a board, please [open an issue](https://github.com/LC-Linkous/hackRF_python/issues) — a passing hardware suite is what promotes a platform, and the bar is not a formality: the Linux verification run surfaced and fixed two real process-lifecycle bugs.

One caveat that applies everywhere: `tools_dir` must point at binaries built for the OS you are on — the Windows `.EXE` bundle will never run on Linux, and vice versa.

## Installation

```bash
pip install hackrfpy
```

The library itself depends only on `numpy`. The plotting examples need an optional extra:

```bash
pip install "hackrfpy[plotting]"
```

Python 3.11+ is required.

**You also need the `hackrf-tools` binaries**, which are *not* a pip dependency — they are installed separately at the OS level. hackrfpy locates them on your `PATH` (or via a configured `tools_dir`).

- **Windows** — *tested.* The tools are published as CI build artifacts under the [Actions tab](https://github.com/greatscottgadgets/hackrf/actions) of the HackRF repo; see the main repository README for the step-by-step.
- **Linux** — *tested.* `sudo apt install hackrf` (or your distribution's equivalent).
- **macOS** — *experimental, see [Platform support](#platform-support).* `brew install hackrf`.

Verify the tools are installed with `hackrf_info`.

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

The same operations are available from the shell via the `hrf` entry point:

```bash
hrf detect                          # is a board attached and ready?
hrf rx -f 433.92M -s 8M -n 2000000 -o capture.iq
hrf sweep --f-min 88M --f-max 108M
hrf monitor 98.1M 103.7M -d 10      # power over time on several frequencies
```

Frequencies accept unit suffixes (`433.92M`, `1.09G`), and most commands take `--print-cmd` to show the underlying `hackrf_*` invocation without running it. The full CLI reference is in the repository README.

## Transmitting

Transmit is gated behind an explicit mode switch, because an accidental transmit is the one operation that can damage equipment (or break the law)

```python
from hackrfpy import HackRF

h = HackRF()
h.set_mode("tx")                # prints the TX-mode safety banner
h.transmit(433.92e6, 8e6, "signal.iq", txvga=20)
```

A bounded constant-wave test tone is available without a source file: `h.transmit_cw(433.92e6, 2e6, duration=2)`, or `hrf tx --cw -f 433.92M -s 2M -d 2` from the CLI (the duration is mandatory there — an unbounded carrier is exactly the risk the gates exist to prevent). Behind the mode gate sit an `atexit` backstop and an OS dead-man, so even a hard-killed script cannot leave a transmitter on the air.

**Transmitting is regulated.** You are responsible for operating within the law and within your equipment's limits.

## Thread safety

A `HackRF` instance is **not** safe to share across threads: methods mutate
per-instance state (`last_params`, the persisted operating mode, logging
wiring) without locks. Instances are cheap -- the constructor touches no
hardware -- so create one per thread, or confine all hackrfpy calls to a
single worker thread.

## Examples

The [main GitHub repository](https://github.com/LC-Linkous/hackRF_python) provides runnable examples, grouped by what they demonstrate.

**Getting started / device control**

- `device_explorer.py` — detect, identify, and report board capabilities (read-only)
- `capture_to_file.py` — bounded capture to a file with a SigMF sidecar, then read it back

**Acquisition**

- `persistent_capture.py` — gapless back-to-back segments at one frequency from a single long-lived receive process (contrast with `capture(segment_secs=...)`, whose files have a short re-open gap between them)
- `power_meter.py` — live dBFS power meter at one frequency via the callback API
- `scan_then_capture.py` — sweep a band, find the strongest bin, then capture there
- `channel_monitor.py` — live power meter on several frequencies at once via `monitor_frequencies` (one continuous sweep, no plotting extra needed)

**Sweep and plotting**

- `sweep_collect.py` — one sweep across a band, saved to CSV
- `waterfall_realtime.py` — a live, continuously updating spectrum waterfall
- `waterfall_persistent.py` — a single-frequency FFT waterfall over time

**Calibration and benchmarking**

- `calibrate.py` — derive an `offset_db` and frequency-response curve for relative-power readings
- `benchmark.py` — measure decode throughput and callback latency on your hardware

**Sample data**

- `collect_sample_data.py` — collect real IQ + sweep datasets with per-capture validation (read-only; never transmits)
- `fm_demod_to_wav.py` — demodulate a captured FM broadcast IQ file to an audible mono WAV (numpy + stdlib only; file processing, never touches the device)

**Transmit**

- `tx_test_tone.py` — the one transmitting example: a bounded CW test tone behind the TX-mode gate, with `--print-cmd` dry-run

> Most plotting examples require the optional plotting dependencies:
> `pip install "hackrfpy[plotting]"`

## Documentation

Every public method carries a docstring: `help(hackrfpy.HackRF)` or `python -m pydoc hackrfpy` is the offline method reference, and a test gates the whole surface so it cannot drift. For the narrative documentation, the CLI reference, and the operating envelope:

- **Library GitHub repository**: [https://github.com/LC-Linkous/hackRF_python/](https://github.com/LC-Linkous/hackRF_python/)
- **Official HackRF documentation**: [https://hackrf.readthedocs.io/](https://hackrf.readthedocs.io/) (not associated with this library)

## Contributing

This is an unofficial community project. Contributions welcome!

- Report bugs and request features on [GitHub](https://github.com/LC-Linkous/hackRF_python)
- If you run the library on Linux or macOS, reports from real hardware are especially welcome (see [Platform support](#platform-support))
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