# hackRF_python

[![PyPI version](https://badge.fury.io/py/hackrfpy.svg)](https://badge.fury.io/py/hackrfpy)
[![Python versions](https://img.shields.io/pypi/pyversions/hackrfpy.svg)](https://pypi.org/project/hackrfpy/)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/hackrfpy.svg)](https://pypi.org/project/hackrfpy/)
[![Downloads](https://static.pepy.tech/badge/hackrfpy)](https://pepy.tech/project/hackrfpy)
[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)



## An UNOFFICIAL Python CLI + scripting wrapper for the HackRF One

A non-GUI Python wrapper and command-line tool for the [HackRF One](https://greatscottgadgets.com/hackrf/one/) software-defined radio.

This repository uses official resources and documentation but is **NOT** endorsed by Great Scott Gadgets or the HackRF project. See the [references](#references) section for further reading. See the [official HackRF documentation](https://hackrf.readthedocs.io/) and the [GitHub project](https://github.com/greatscottgadgets/hackrf) for official documentation of device behavior.

This is a library designed to work on Windows. Historically, that has been difficult, but there have been improvements the last few years. There still exists a gap with some functional needs and installer streamlining. Unlike libraries that bind to `libhackrf` through C extensions, this library interfaces directly with the standard `hackrf-tools` command-line binaries (`hackrf_info`, `hackrf_transfer`, `hackrf_sweep`, and the device-management tools). There are no compiled bindings to build, which is what makes it practical to install and run on Windows. The cost of that choice is that the host `hackrf-tools` binaries must be installed and reachable; see [Requirements](#requirements).

This README documents the library's methods, the operating envelope it enforces, and the exact `hackrf-tools` invocation each method builds, with runnable examples in the `examples/` directory. While the library does argument validation, it is **not exhaustive**, and the device and binaries do their own checks. It is strongly advised to read the official documentation before scripting your HackRF, especially before transmitting. **Transmitting into the wrong load, band, or power level can damage your device, connected equipment, or violate radio regulations.**

The primary GitHub: [https://github.com/LC-Linkous/hackRF_python](https://github.com/LC-Linkous/hackRF_python)


## Table of Contents

* [The HackRF One Device](#the-hackrf-one-device)
* [How This Library Works (Architecture)](#how-this-library-works-architecture)
* [Library Usage](#library-usage)
    * [Local Install Using UV](#local-install-using-uv)
    * [Installing hackrf-tools](#installing-hackrf-tools)
* [Requirements](#requirements)
* [Structure](#structure)
* [The Operating Envelope](#the-operating-envelope)
* [Operating Modes and the TX Gate](#operating-modes-and-the-tx-gate)
* [Running Tests](#running-tests)
* [Error Handling](#error-handling)
* [Example Implementations](#example-implementations)
    * [Preflight: Checking Your Environment](#preflight-checking-your-environment)
    * [Detecting and Identifying Hardware](#detecting-and-identifying-hardware)
    * [Device Info](#device-info)
    * [Bounded Capture to a File](#bounded-capture-to-a-file)
    * [In-Memory Capture (no file)](#in-memory-capture-no-file)
    * [Live Streaming with Clean Shutdown](#live-streaming-with-clean-shutdown)
    * [Spectrum Sweep](#spectrum-sweep)
    * [Scan-then-Capture Pipeline](#scan-then-capture-pipeline)
    * [Transmitting](#transmitting)
    * [Reading Recordings Back](#reading-recordings-back)
    * [Sample Data (no board required)](#sample-data-no-board-required)
    * [Runnable Examples](#runnable-examples)
* [Method Reference](#method-reference)
    * [Receive / Capture](#receive--capture)
    * [Sweep](#sweep)
    * [Transmit](#transmit)
    * [Info and Preflight](#info-and-preflight)
    * [Device Management (advanced)](#device-management-advanced)
    * [Decoding and File Helpers](#decoding-and-file-helpers)
    * [Power and Relative Calibration](#power-and-relative-calibration)
    * [Mode, Validation, and Feedback](#mode-validation-and-feedback)
* [Device Capability Coverage](#device-capability-coverage)
* [CLI Reference](#cli-reference)
* [Library Development](#library-development)
* [Notes for Beginners](#notes-for-beginners)
    * [Vocab Check](#vocab-check)
    * [What an SDR Is (and Isn't)](#what-an-sdr-is-and-isnt)
    * [Some General HackRF Notes](#some-general-hackrf-notes)
* [FAQs](#faqs)
* [References](#references)
* [Licensing](#licensing)


## The HackRF One Device

The [HackRF One](https://greatscottgadgets.com/hackrf/one/) is a wide-band, half-duplex software-defined radio from Great Scott Gadgets. It tunes from 1 MHz to 6 GHz and samples at up to 20 Msps (2 Msps floor). It is **half-duplex**  (it receives or transmits, but never both at once) and **8-bit**: samples are quantized to signed 8-bit I and Q, interleaved. That interleaved int8 I/Q is the native format this library reads and writes, on both the receive and transmit paths.

Because there is one radio and it can't do both directions at once, the library carries an explicit operating mode (RX or TX), with a deliberate gate before transmit — see [Operating Modes and the TX Gate](#operating-modes-and-the-tx-gate).

Official documentation is at [hackrf.readthedocs.io](https://hackrf.readthedocs.io/); the firmware and tools source is at [github.com/greatscottgadgets/hackrf](https://github.com/greatscottgadgets/hackrf). Those track firmware and tooling more closely than this repo will — read them before driving the hardware experimentally.


## How This Library Works (Architecture)

**The library does not talk to the HackRF directly. It runs the `hackrf-tools` binaries as subprocesses and manages their input, output, and lifecycle.** When you call `h.capture(...)`, the library builds a `hackrf_transfer` command line, launches it, and — depending on how you asked for the data — waits for it, times it, streams its stdout, or hands you a controllable process handle.

Wrapping the binaries instead of binding the C library shapes everything downstream:

* **No compiled dependencies.** This is the largest change from previous versions of this tool and other Python libraries. There is no `libhackrf` to link, no build step, and no wheel that has to match your platform's C toolchain. The tradeoff is that the binaries for the SDR are a *system* dependency you install separately, but it is what lets this library run on Windows without managing multiple installs.
* **The library manages the hackrf-tools child processes.** It handles draining stdout/stderr without deadlocking, stopping hackrf_transfer cleanly so recordings aren't truncated mid-sample-pair, reaping children when a consumer exits early, and shutting down the transmitter if the script dies. Tests cover these paths.
* **Everything funnels through one method.** Every binary invocation goes through `_run(argv, mode=...)`. The `mode` selects the lifecycle: `blocking` (run to completion), `timed` (run N seconds then stop), `handle` (return a controllable process), or `stream` (yield output as it arrives). Centralizing this is what makes the lifecycle testable.
* **The library yields `complex64`; it does not interpret samples.** Decoding interleaved int8 to normalized `complex64` is the boundary. Filtering, demodulation, FFTs, waterfalls — deliberately *not* here. See [project_summary.md](project_summary.md) for the split between this project (transport + control) and the planned signal-processing project.


## Library Usage

This is a development repository. The installable package lives in the `hackrfpy/` subdirectory (the one with `pyproject.toml`).

Several usage examples are in the [Example Implementations](#example-implementations) section; runnable versions live in the `examples/` directory.


### Local Install Using UV

This project is set up for [uv](https://docs.astral.sh/uv/) with a `src/` layout and PEP 735 dependency groups.

```bash
# install uv (if not already)
pip install uv

# navigate to the package directory (the one with pyproject.toml)
cd hackrfpy

# create the venv, install numpy + the dev group, and editable-install
# hackrfpy. Writes uv.lock + .python-version.
uv sync

# add plotting deps (matplotlib) when running the examples
uv sync --extra plotting
```

To build a distributable wheel:

```bash
# produces dist/ in the package directory
uv build
pip install dist/hackrfpy-0.1.0-py3-none-any.whl
```

You can use another package manager if you prefer; the package metadata is all in `pyproject.toml`. Manual install equivalents:

```bash
pip install "hackrfpy[plotting]"   # library + example plotting deps
pip install -e .                   # editable, library only
```


### Installing hackrf-tools


### Installing hackrf-tools

This library is requires the  `hackrf-tools` binaries on the host. They are **not** a pip dependency; they are installed at the OS level. This package cannot install them.

Only the command line tools are required. (`hackrf_info`, `hackrf_transfer`, `hackrf_sweep`, and the device-management utilities). 

* **Linux:** `sudo apt install hackrf` (Debian/Ubuntu) or your distribution's equivalent. This installs the tools and the udev rules; you may need to be in the `plugdev` group for non-root USB access.
* **macOS:** `brew install hackrf`.
* **Windows:** Great Scott Gadgets publishes the tools as CI build artifacts for some workflow runs. You do **not** need GNU Radio, SoapySDR, or a full SDR distribution. If you have radioconda installed, then you have the binaries, and GNU Radio and a full conda environment you don't need for this library. Download the prebuilt `hackrf-tools` from the [Great Scott Gadgets releases](https://github.com/greatscottgadgets/hackrf/releases) (or via a package manager that provides them). 

    1. Open the [Actions tab](https://github.com/greatscottgadgets/hackrf/actions) of the HackRF repo.
    2. Click a recent successful workflow run (one with a green check).
    3. Under **Artifacts** on the run page (files at the bottom of the page, link at the top), download the Windows build — a zipped folder of the binaries.
    4. Unzip it, then either add the folder to your `PATH` or pass it as `HackRF(tools_dir=r"C:\path\to\hackrf-tools")`. The library resolves `hackrf_transfer.exe` etc. by extension, so a bare-name `PATH` entry is not required.

Verify the install before scripting:

```bash
hackrf_info
```

If that prints a board (or at least runs), the binaries are reachable. If it is not on your `PATH`, use `tools_dir` (Python) or `[tools].dir` in config.


## Requirements

The library itself depends only on **numpy**. It shells out to the `hackrf-tools` binaries (`hackrf_info`, `hackrf_transfer`, `hackrf_sweep`, and the device-management tools), which are a **system dependency**, not a pip one. There is no serial port and no `pyserial` involved — the HackRF presents as a USB device the binaries talk to.

The plotting examples additionally need matplotlib, grouped under the optional `[plotting]` extra:

```bash
pip install nvnapython              # (illustrative) library only
pip install "hackrfpy[plotting]"    # library + example plotting deps
```

matplotlib draws the example figures using a native GUI backend (TkAgg on Windows and most platforms, which ships with Python — no extra install). If a live window doesn't appear, your matplotlib may have selected a non-interactive backend; set one explicitly with the `MPLBACKEND=TkAgg` environment variable before running.

Python 3.11+ is required (the library uses `tomllib` and modern typing). The examples default to common ISM/broadcast bands but take frequency arguments for other ranges.


## Structure

The public API is `from hackrfpy import HackRF`. Per-command methods live in mixin modules under `_commands/` and are composed onto the `HackRF` class in `core.py`, which holds shared state, binary resolution, the validation envelope, the `_run` process machinery, and IQ decoding. `constants.py` holds the operating envelope (frequency range, sample-rate range, gain tables, baseband filter set, the tool table) — a single source of truth that both the validation code and the test suite import, so they cannot drift apart.

```
hackRF_python/                  repo root (this README, CITATION, etc.)
├── README.md
├── project_summary.md          this-project vs next-project split
├── hackrfpy/                   the installable package + its dev tree
│   ├── pyproject.toml
│   ├── README.md               package README (dev/install quickref)
│   ├── src/
│   │   └── hackrfpy/
│   │       ├── __init__.py
│   │       ├── core.py         HackRF class: _run, validation, decode, modes
│   │       ├── constants.py    the operating envelope (single source of truth)
│   │       ├── exceptions.py   typed exception hierarchy
│   │       ├── presets.py      band presets (user convenience)
│   │       ├── sigmf.py        SigMF sidecar write/read
│   │       ├── cli.py          the `hrf` command-line shell
│   │       ├── _stream_ctx.py  context manager for live streams
│   │       ├── py.typed
│   │       └── _commands/
│   │           ├── capture.py    CaptureMixin (hackrf_transfer -r)
│   │           ├── transmit.py   TransmitMixin (hackrf_transfer -t)
│   │           ├── sweep.py      SweepMixin (hackrf_sweep)
│   │           ├── info.py       InfoMixin (hackrf_info)
│   │           └── device.py     DeviceMixin (clock/spiflash/operacake/…, preflight)
│   ├── examples/
│   │   ├── capture_to_file.py
│   │   ├── scan_then_capture.py
│   │   ├── sweep_collect.py
│   │   ├── waterfall_realtime.py
│   │   ├── waterfall_persistent.py  single-freq FFT waterfall (persistent RX)
│   │   ├── device_explorer.py       detect + identify + capabilities (read-only)
│   │   ├── power_meter.py           live dBFS meter via capture_callback
│   │   ├── persistent_capture.py    multi-segment capture, one process
│   │   ├── benchmark.py             measure decode/throughput/latency
│   │   ├── calibrate.py             calibration workflow (Levels 2-3)
│   │   ├── collect_sample_data.py   real sample-data collector (read-only)
│   │   └── sample_data/             committed real recordings + SigMF + README
│   └── tests/
│       ├── conftest.py           cross-platform stub-binary factory
│       ├── fixtures/             frozen hackrf_info / sweep / iq samples
│       └── test_*.py
```


## The Operating Envelope

Everything the library treats as a "limit" lives in `constants.py`, so there is exactly one place to edit as firmware evolves, and the tests import the same numbers they validate against. These describe the **library's checking envelope**, not live device state — editing them changes what the library accepts, not anything on the board.

| Parameter | Value | Behavior |
|---|---|---|
| Frequency | 1 MHz – 6 GHz | **Reject-by-default** outside this. A 60 GHz value is almost always a typo for 6 GHz, which is exactly what reject-by-default catches. `--force` / `allow_out_of_spec` downgrades the reject to a warning. |
| Sample rate | 2 – 20 Msps | Reject outside. **Warn** below 8 Msps (the commonly recommended floor) without rejecting. |
| LNA (IF) gain | 0–40 dB, 8 dB steps | Snapped **down** to the real device step. A request that snaps to a different value is reported (e.g. `lna=30 → 24`). |
| VGA (baseband RX) gain | 0–62 dB, 2 dB steps | Snapped down, reported. |
| TX VGA gain | 0–47 dB, 1 dB steps | Snapped down. A value over the ceiling (default 47) is **rejected** as a likely order-of-magnitude typo. |
| Front-end amp | ~14 dB, on/off | Boolean only. |
| Baseband filter BW | discrete MAX2837 set | Auto-derived as ~0.75 × sample rate, snapped to the nearest supported value; explicit values are snapped too. |

"Snap-and-notify, round down" is a deliberate honesty choice: the silicon rounds to a step regardless, so the library tells you the value you will actually get rather than pretending your exact request was honored. Gain snapping and other safety notices are printed to **stderr** regardless of the verbose setting, so they are never silently swallowed.


## Operating Modes and the TX Gate

The HackRF is half-duplex, so the library carries an explicit mode: `rx` (default) or `tx`. Receiving, capturing, and sweeping require RX mode; transmitting requires TX mode. Switching to TX is a **deliberate, one-time action** that prints a safety banner — it is not something you can do by accident in the middle of a capture call.

```python
h = HackRF()
h.set_mode("tx")     # prints the TX-mode safety banner
h.require_mode("tx") # now passes; transmit() is allowed
```

The mode persists across CLI invocations (stored in a small state file), so `hrf mode tx` once, then subsequent `hrf tx ...` calls honor it. The gate exists because an accidental transmit is the one operation that can damage equipment or break the law; making it explicit is the point. Frequency is never policed on transmit (you may legitimately transmit anywhere in range); the gain ceiling guards only against a fat-finger.


## Running Tests

This is primarily for development. The suite uses [pytest](https://docs.pytest.org/) and must be run from the `hackrfpy` project directory (the one with `pyproject.toml`), since the `hardware` marker and pytest config live there.

```bash
# full suite (hardware tests self-skip with no device connected)
uv run pytest

# hardware-free only (explicitly skip device tests)
uv run pytest -m "not hardware"

# hardware only (requires a connected HackRF One)
uv run pytest -m hardware

# with coverage
uv run pytest --cov=hackrfpy --cov-report=term-missing
```

> **Note:** this is a configured uv project, so `uv run pytest` uses the synced venv and editable install. **Run *scripts* the same way** — `uv run python tests/collect_real_data.py ...`, not bare `python ...`. Bare `python` can pick up a different activated `.venv` (for example one at the repo root, outside the `hackrfpy/` project dir) that doesn't have the project's dependencies installed, producing a confusing `ModuleNotFoundError: No module named 'numpy'` even though numpy is declared. If you see uv warn that `VIRTUAL_ENV ... does not match the project environment`, that's the mismatch — prefer `uv run` so the right environment is always used.

The suite is split into hardware-free tests and tests marked `@pytest.mark.hardware`, which auto-skip when no board is detected. Hardware detection is intentionally **not cached**, so you can plug/unplug between runs.

**A note on cross-platform coverage:** the process-lifecycle tests (the riskiest code) use **cross-platform stub binaries**, not bash scripts, so they run on Windows — the platform this library targets. Stubs are generated by a factory in `conftest.py` that writes a small Python program plus a launcher (`.bat` on Windows, a shebang'd file on POSIX). This matters because the Windows interrupt path (`CTRL_BREAK_EVENT`, used to stop a running `hackrf_transfer`) is otherwise untested on the exact platform where it must work. Run `pytest tests/test_lifecycle_xplat.py` on Windows to prove the reap/stop machinery before attaching hardware.

**Hardware-validated parsing.** The parsers (`parse_info`, `parse_sweep_line`, IQ decode) are tested against frozen *verbatim output from a real HackRF One* — see `tests/fixtures/*_real.*` and `tests/test_real_output.py`. Collecting that real output surfaced behaviors no synthetic fixture had: a git-style tools version with no year, a field whose value sits on an indented continuation line, trailing free-text USB warnings, and **out-of-order sweep segments**. The hardware-marked tests (`test_hardware.py`) pass against a connected board. You can regenerate the real fixtures yourself with `tests/collect_real_data.py` (read-only).


## Error Handling

The library raises a **typed exception hierarchy** (rather than returning sentinel values), so importing scripts get real, catchable exceptions and the CLI maps them to clean stderr messages and exit codes.

| Exception | Exit code | Raised when |
|---|---|---|
| `HackRFError` | 1 | Base class — catch this to catch everything the library raises. |
| `HackRFValueError` | 2 | A parameter is outside the operating envelope (freq/rate/gain) and `--force` was not given; also bad presets, bad parse input. |
| `HackRFModeError` | 3 | An operation was attempted in the wrong mode (e.g. transmit while in RX). |
| `HackRFDeviceError` | 4 | A `hackrf_*` binary is missing, no board found, or a subprocess exited non-zero. |
| `HackRFEnvironmentError` | 5 | The host can't support the request (insufficient disk for a capture, permissions). |

Two feedback toggles control how chatty the library is:

* `set_verbose(True/False)` (or `HackRF(verbose=True)`) — prints status/diagnostic messages (which mode it's in, capture size estimates, what a method did).
* `allow_out_of_spec` (or `--force` on the CLI) — downgrades a reject-by-default range error to a stderr warning instead of an exception. Use with care; it exists for the rare legitimate out-of-spec case, not as a way to silence validation.

Safety and correctness warnings (gain snapping, sub-recommended sample rate, forced out-of-spec, MHz edge truncation on sweep) print to **stderr unconditionally** — they are never gated behind `verbose`, because a safety warning you can't see is not a warning.

Validation is not exhaustive, and the binaries and device do their own checks, so always consult the official documentation for valid ranges.


## Example Implementations

Runnable versions of these are in the `examples/` directory; the snippets here are illustrative. All examples are single files you can copy out.

### Preflight: Checking Your Environment

Before anything else, confirm the tools are reachable and (optionally) a board is present. `preflight()` (also available as the familiar alias `doctor()`) checks the binaries, board enumeration, free disk, the tools version, and derived feature flags.

```python
from hackrfpy import HackRF

h = HackRF()
report = h.preflight()          # prints a readable report, returns a dict
if report["problems"]:
    print("not ready:", report["problems"])
```

On the CLI:

```bash
hrf doctor
```

### Detecting and Identifying Hardware

The HackRF is not a serial device, so there are no COM ports to scan. `detect()` is the equivalent: it runs `hackrf_info`, confirms each enumerated board is actually a HackRF, and reports identity and firmware. It never raises for "no board" — that's a normal result you inspect.

```python
from hackrfpy import HackRF

h = HackRF()
det = h.detect()
if not det["ready"]:
    print("no usable HackRF:", det["problem"])
else:
    for b in det["boards"]:
        print(f"[{b['index']}] {b['name']}  fw={b['firmware']}  sn={b['serial']}")
    if det["multiple"]:
        print("multiple boards — pass serial=... to target one")

# "what am I about to talk to?"
board = h.identify()                 # first board, or identify("<serial>")
```

On the CLI (exits non-zero if no usable board, so it chains: `hrf detect && hrf rx ...`):

```bash
hrf detect
```

### Device Info

```python
from hackrfpy import HackRF

h = HackRF()
info = h.info()                 # parsed dict by default
for board in info["boards"]:
    print(board.get("serial_number"), board.get("firmware_version"))

raw_text = h.info(raw=True)     # the verbatim hackrf_info output
```

### Bounded Capture to a File

A fixed number of samples to an `.iq` file, with a SigMF metadata sidecar written alongside so the recording is self-describing.

```python
from hackrfpy import HackRF

h = HackRF(verbose=True)
h.capture(433.92e6, 8e6, num_samples=2_000_000,
          out="capture.iq", lna=24, vga=20)
```

This writes `capture.iq` (interleaved int8 I/Q) and `capture.sigmf-meta` (frequency, sample rate, gains, timestamp). The actual *snapped* gains are recorded, not the requested ones.

### In-Memory Capture (no file)

For scripting, get samples straight back as a normalized `complex64` array — no file round-trip. This is the entry point downstream signal-processing code will lean on.

```python
from hackrfpy import HackRF

h = HackRF()
iq = h.capture_array(433.92e6, 8e6, num_samples=1_000_000)
print(iq.dtype, len(iq))        # complex64, 1000000

# want the actual parameters used (after snapping)?
iq, params = h.capture_array(433.92e6, 8e6, num_samples=1_000_000,
                             lna=30, return_params=True)
print(params["lna"])            # 24 (snapped from 30)
```

### Live Streaming with Clean Shutdown

Stream decoded blocks as they arrive, with a context manager that **guarantees** the receiving `hackrf_transfer` is reaped on exit — including a Ctrl-C out of the loop.

```python
from hackrfpy import HackRF

h = HackRF()
with h.capture_stream(433.92e6, 8e6) as blocks:
    for iq in blocks:           # each iq is a complex64 block
        process(iq)             # break or Ctrl-C is safe; child is reaped
```

### Spectrum Sweep

`hackrf_sweep` emits CSV rows continuously; the library yields them parsed.

```python
from hackrfpy import HackRF

h = HackRF()
rows = h.sweep_collect(400e6, 500e6, num_sweeps=1)   # bounded -> list
for r in rows:
    print(r["hz_low"], r["hz_high"], min(r["db"]), max(r["db"]))
```

For a live, indefinite sweep (e.g. a waterfall), use `sweep_stream` so the child is reaped on exit:

```python
with h.sweep_stream(88e6, 108e6) as rows:
    for row in rows:
        update_display(row)
```

### Scan-then-Capture Pipeline

A pipeline the class can express that CLI-only tools cannot: sweep a band, find the strongest bin, capture there.

```python
import numpy as np
from hackrfpy import HackRF

h = HackRF(verbose=True)
rows = h.sweep_collect(430e6, 440e6, num_sweeps=1)

best_freq, best_db = None, -1e9
for r in rows:
    db = np.array(r["db"]); i = int(np.argmax(db))
    if db[i] > best_db:
        best_db = float(db[i])
        span = r["hz_high"] - r["hz_low"]
        best_freq = r["hz_low"] + (i + 0.5) * span / len(db)

h.capture(best_freq, 8e6, num_samples=4_000_000, out="peak.iq")
```

### Transmitting

Transmit requires TX mode — the deliberate gate. The source is an int8 I/Q file.

```python
from hackrfpy import HackRF

h = HackRF()
h.set_mode("tx")                # prints the safety banner
h.transmit(433.92e6, 8e6, "signal.iq", txvga=20)

# open-ended repeat with a hard time cap (dead-man), in case the script dies:
h.transmit(433.92e6, 8e6, "beacon.iq", repeat=True, max_duration=30.0)
```

`max_duration` is best-effort: it stops the child on schedule from within the process. It does not survive a hard kill of the parent (`kill -9` / power loss); that needs an OS-level dead-man not yet implemented (see [project_summary.md](project_summary.md)).

### Reading Recordings Back

The decode and metadata helpers work standalone — no device, no `HackRF()` instance — so any consumer can use them.

```python
from hackrfpy import load_iq, read_sigmf_meta

iq = load_iq("capture.iq")                      # int8 file -> complex64
first_second = load_iq("capture.iq", count=8_000_000)
tail = load_iq("capture.iq", offset_samples=1_000_000)

meta = read_sigmf_meta("capture.iq")            # accepts the .iq or .sigmf-meta path
fs = meta["global"]["core:sample_rate"]
fc = meta["captures"][0]["core:frequency"]
```

### Sample Data (no board required)

The repo ships **real recordings** under `examples/sample_data/` so you can try
the library — and downstream signal processing — without owning a HackRF. Each
`.iq` is interleaved int8 I/Q with a `.sigmf-meta` sidecar, plus sweep CSVs and a
provenance README noting the firmware/tools that produced them.

```python
from hackrfpy import load_iq, read_sigmf_meta
iq = load_iq("examples/sample_data/fm_2Msps.iq")
meta = read_sigmf_meta("examples/sample_data/fm_2Msps.iq")
```

To collect your own (read-only; never transmits), use the sample collector. It
preflights for a board, then captures real IQ + sweep data per band with SigMF
metadata:

```bash
uv run python examples/collect_sample_data.py --band fm --band ism433
```

Defaults are kept small (0.5 s at 2 Msps) so they can live in the repo; use
`--seconds` / `--sample-rate` for larger local datasets. This is distinct from
`tests/collect_real_data.py`, which freezes tiny verbatim slices as *parser test
fixtures* rather than usable sample datasets.

### Runnable Examples

The `examples/` directory has end-to-end scripts you can run against a board (all read-only except where noted):

| Script | What it shows |
|---|---|
| `device_explorer.py` | The "first thing you run": `detect` + `identify` + `features`, reporting board, firmware, capabilities, and any device warnings. |
| `capture_to_file.py` | Bounded capture to a file with a SigMF sidecar, then read it back. |
| `power_meter.py` | Live dBFS power meter at one frequency via `capture_callback` — the callback API on a real stream, with the gain-normalized relative reading. |
| `scan_then_capture.py` | Sweep a band, find the strongest bin, then capture there — a pipeline the class expresses that CLI tools can't. |
| `sweep_collect.py` | One sweep across a band saved to CSV. |
| `waterfall_realtime.py` | Live spectrum waterfall (needs the `[plotting]` extra). |
| `waterfall_persistent.py` | Single-frequency FFT waterfall over time, driven by a persistent receiver — the complement to the sweep waterfall (one channel evolving vs. a wide band). Needs the `[plotting]` extra. |
| `persistent_capture.py` | Collect many segments at one frequency from a single long-lived process (amortizes startup). |
| `benchmark.py` | Measure decode throughput, sustained-rate drop behavior, and callback latency on your hardware. |
| `calibrate.py` | Calibration workflow (Levels 2–3): derive an absolute-ish `offset_db` from a known reference and/or a frequency-response curve, saved to `calibration.json`. |
| `collect_sample_data.py` | Collect real sample datasets into `examples/sample_data/`. |

Run any of them through uv so the project environment is used, e.g. `uv run python examples/device_explorer.py`.


## Method Reference

The `HackRF` class is composed from mixins. Methods build a `hackrf-tools` command and run it through `_run` in one of four lifecycle modes (`blocking`, `timed`, `handle`, `stream`). Pass `print_cmd=True` to most methods to print the exact command that *would* run, without running it — useful for debugging and for learning the underlying tool invocation.

### Receive / Capture

#### `capture`
* **Builds:** `hackrf_transfer -r <file|-> -f <hz> -s <sps> -l <lna> -g <vga> -a <0|1> -b <bw> [-p 1] [-n <n>]`
* **Signature:** `capture(freq, sample_rate, *, out="capture.iq", num_samples=None, duration=None, lna=16, vga=20, amp=False, bias_tee=False, baseband_bw=None, to_stdout=False, sigmf=True, segment_secs=None, print_cmd=False)`
* **Consumption mode is chosen by argument:**
    * `num_samples` → bounded, runs to completion (`blocking`)
    * `duration` → timed, stops after N seconds (`timed`)
    * neither → open-ended; returns a controllable process handle (`handle`) you `.stop()`
    * `to_stdout=True` → streams `-r -` and decodes to `complex64` in Python (`stream`)
    * `segment_secs` → rolling files `out_000.iq`, `out_001.iq`, … (each a whole bounded capture; there is a short re-open gap between segments — they are not gapless)
* **Aliases:** `rx`, `capture_samples`, `capture_seconds`
* **Notes:** writes a SigMF sidecar by default (`sigmf=True`) for file captures; records snapped gains. Requires RX mode.

#### `capture_array`
* **Signature:** `capture_array(freq, sample_rate, num_samples, *, return_params=False, **kwargs)`
* **Returns:** exactly `num_samples` as a `complex64` ndarray (or `(iq, params)` if `return_params=True`).
* **Notes:** built on the `to_stdout` stream path; closes the child as soon as enough samples arrive. The scripting/DSP entry point.

#### `capture_stream`
* **Signature:** `capture_stream(freq, sample_rate, **kwargs)`
* **Returns:** a context manager yielding decoded `complex64` blocks; reaps `hackrf_transfer` on exit.

#### `capture_callback`
* **Signature:** `capture_callback(freq, sample_rate, on_block, *, max_samples=None, max_blocks=None, **kwargs)`
* **Returns:** total samples delivered.
* **Notes:** callback-style receive — `on_block(iq, n_so_far)` fires with each decoded `complex64` block as it streams; return `False` to stop. This is the ergonomic analog of libhackrf's RX callback (the loop is inverted so calling code resembles the C-binding libraries), riding the same subprocess stream as `capture_stream`. The child is always reaped on exit. Stops on `False`, on `max_samples`/`max_blocks`, or when the source ends.

#### `scan_frequencies`
* **Signature:** `scan_frequencies(freqs, sample_rate, num_samples, *, on_capture=None, **kwargs)`
* **Returns:** `{freq: complex64}` dict, or `None` if `on_capture` is given.
* **Notes:** sequentially captures `num_samples` at each frequency, retuning between them. Makes multi-frequency capture one call. **Not gapless** — each retune is a fresh `hackrf_transfer` with a short re-open (the binary can't retune mid-stream); pass `on_capture(freq, iq)` to process-and-discard instead of holding every array.

#### `open_receiver`
* **Signature:** `open_receiver(freq, sample_rate, *, lna=16, vga=20, amp=False, baseband_bw=None, read_samples=131072)`
* **Returns:** a `PersistentReceiver` (use as a context manager).
* **Notes:** opens **one long-lived** `hackrf_transfer` you drain in segments, so you pay the ~startup cost **once** instead of per capture — the efficient path for collecting many segments over time. **Fixed-frequency by design** (the binary can't retune mid-stream); for multiple frequencies use `scan_frequencies` or `monitor_frequencies`. The receiver offers `read(n)` (exactly *n* `complex64`), `blocks()` (iterate raw decoded blocks), and `callback(on_block, max_samples=)`. The child is reaped on `__exit__` and registered on the atexit backstop. `read_samples` tunes the stdout read granularity (larger = higher sustained throughput).

```python
with h.open_receiver(100e6, 8e6) as rx:
    a = rx.read(1_000_000)      # exact count
    b = rx.read(1_000_000)      # again, NO new process spin-up
    for block in rx.blocks():   # or iterate decoded blocks
        ...
```

### Sweep

#### `sweep`
* **Builds:** `hackrf_sweep -f <lo:hi MHz> -l <lna> -g <vga> -a <0|1> [-w <bin_hz>] [-1] [-N <n>]`
* **Signature:** `sweep(f_min_hz, f_max_hz, *, bin_width=None, lna=16, vga=20, amp=False, one_shot=False, num_sweeps=None, print_cmd=False)`
* **Returns:** a generator of parsed rows: `{date, time, hz_low, hz_high, bin_width, num_samples, db: [...]}`. `None` for blank/garbled lines (filtered out).
* **Notes:** band edges are taken in integer MHz; sub-MHz edges are snapped and a warning is printed. A single sweep over a wide band arrives as multiple rows sharing one timestamp. **Real `hackrf_sweep` does not emit segments in frequency order** — it interleaves them (e.g. 88, 98, 93, 103 MHz). To reconstruct a contiguous spectrum, group rows by timestamp and sort segments by `hz_low`; never assume the rows arrive low-to-high.

#### `sweep_collect`
* **Signature:** `sweep_collect(f_min_hz, f_max_hz, num_sweeps=1, **kwargs)`
* **Returns:** a list (bounded — relies on `-N` terminating the sweep).

#### `monitor_frequencies`
* **Signature:** `monitor_frequencies(freqs_hz, *, span_hz=2_000_000, duration=None, on_update=None, lna=16, vga=20, amp=False)`
* **Returns:** a list of `{freq_hz: power_db}` dicts (one per sweep pass), or `None` if `on_update` is given.
* **Notes:** watch **power over time** at several frequencies, backed by `hackrf_sweep`'s fast internal retuning. Deliberately separate from `scan_frequencies`: that one returns **IQ samples** (per-frequency captures); this returns **power** (spectrum bins) and never yields IQ. Use it for "is there activity on these channels?" monitoring. `on_update(update)` returning `False` stops it.

#### `sweep_stream`
* **Signature:** `sweep_stream(f_min_hz, f_max_hz, **kwargs)`
* **Returns:** a context manager around the sweep generator; reaps `hackrf_sweep` on exit. Use for live/indefinite consumers.

#### `sweep_to_file`
* **Builds:** `hackrf_sweep -f <lo:hi> -l -g -a -r <out> [-w] [-1] [-N] [-B|-I]`
* **Signature:** `sweep_to_file(f_min_hz, f_max_hz, out, *, binary=False, inverse_fft=False, bin_width=None, lna=16, vga=20, amp=False, one_shot=False, num_sweeps=None, print_cmd=False)`
* **Returns:** the output path.
* **Notes:** writes sweep output straight to a file. `binary=True` selects raw binary FFT output (`-B`); `inverse_fft=True` selects binary inverse-FFT output (`-I`). With neither, it writes the normal CSV text. The binary formats are **not** parsed by this library (`parse_sweep_line` is text-only) — you own the format on read.

### Transmit

#### `transmit`
* **Builds:** `hackrf_transfer -t <file> -f <hz> -s <sps> -x <txvga> -a <0|1> -b <bw> [-p 1] [-R] [-n <n>]`
* **Signature:** `transmit(freq, sample_rate, source, *, txvga=20, amp=False, bias_tee=False, baseband_bw=None, repeat=False, num_samples=None, duration=None, max_duration=None, print_cmd=False)`
* **Aliases:** `tx`, `transmit_file`
* **Notes:** **requires TX mode** (the gate). `max_duration` caps even an open-ended `repeat`. Frequency is not policed; the TX VGA ceiling guards against a fat-finger.

#### `transmit_cw`
* **Builds:** `hackrf_transfer -c <amplitude> -f <hz> -s <sps> -x <txvga> -a <0|1> -b <bw> [-p 1]`
* **Signature:** `transmit_cw(freq, sample_rate, *, amplitude=127, txvga=20, amp=False, bias_tee=False, baseband_bw=None, duration=None, max_duration=None, print_cmd=False)`
* **Notes:** constant-wave / signal-source test mode — transmits a fixed signal at `amplitude` (0–127, clamped) instead of a file. **Requires TX mode.** Useful for antenna and range testing. Open-ended unless bounded by `duration`/`max_duration` (the dead-man applies).

### Info and Preflight

#### `info`
* **Builds:** `hackrf_info`
* **Signature:** `info(raw=False, print_cmd=False)`
* **Returns:** a parsed dict (`{library: {...}, boards: [...]}`) by default, or verbatim text if `raw=True`. Alias: `get_info`.

#### `detect`
* **Builds:** `hackrf_info` (then interprets it)
* **Signature:** `detect()`
* **Returns:** an autodetection/identification report dict: `found` (a board enumerated), `ready` (≥1 confirmed HackRF with usable tooling), `count`, `boards` (each with `index`, `serial`, `name`, `firmware`, `is_hackrf`, `firmware_stale`), `tools_version`, `libhackrf_version`, `multiple` (more than one board → disambiguate with `serial=`), and `problem`.
* **Notes:** the HackRF is **not** a serial device — there are no COM ports to scan — so "detection" means running `hackrf_info`, confirming each board identifies as a HackRF, and reporting firmware/identity. **Never raises for "no board"** (that's a normal result you inspect); only raises if `hackrf_info` can't run at all. This is the analog of a serial-port autodetect for a non-serial device.

#### `identify`
* **Signature:** `identify(serial=None)`
* **Returns:** the identity dict for one board — the one matching `serial` (substring match), or the first detected board if `serial=None`; `None` if not found. Convenience for "what am I about to talk to?" before a capture/transmit.

#### `preflight`
* **Signature:** `preflight(capture_path=".")` — alias `doctor`
* **Returns:** a report dict (`tools`, `boards`, `mode`, `tool_version`, `features`, `disk_free_bytes`, `problems`) and prints a readable summary. Only the **core** tools (info, transfer, sweep) count as problems when missing; the device-management extras are optional.

#### `features`
* **Signature:** `features(tool_version=None)`
* **Returns:** capability flags derived from the tools version (`stdout_streaming`, `sweep_num_sweeps`, `bias_tee`). Probes the device if no version is passed. Lets callers gate behavior on tool capability instead of re-deriving it per call.

#### `from_device` (classmethod)
* **Signature:** `HackRF.from_device(*, tools_dir=None, verbose=False, serial=None)`
* **Returns:** a `HackRF` that has already probed the board (raises if tools missing or no board), warning on firmware too old for streaming/`-N`. Use for a fail-fast handle.

### Device Management (advanced)

These wrap the less-common tools. The firmware-writing operations are **brick-guarded** — they refuse unless `confirm=True` is passed explicitly, because a bad image or interrupted write can permanently disable the board.

The goal here is **full scripting access**: even where the library doesn't model every flag of a tool, the wrapping method forwards arbitrary arguments so nothing on the device is unreachable from Python.

#### Opera Cake antenna switch — `operacake`

* **Builds:** `hackrf_operacake <args...>`
* **Signatures:** `operacake(*args, print_cmd=False)`, `operacake_list()`
* **Full passthrough.** Every Opera Cake capability is reachable by forwarding the tool's own flags. Opera Cake is an antenna-switching add-on with three switching modes — manual, frequency-based, and time-based.

```python
h = HackRF()
h.operacake_list()                        # -l : list connected Opera Cake boards
h.operacake("-m", "manual", "-a", "0", "-b", "1")   # manual: A0->port0, B0->port1
h.operacake("-m", "frequency",
            "-f", "0:100:500",            # auto-route port 0 for 100-500 MHz
            "-f", "1:500:1000")           # auto-route port 1 for 500-1000 MHz
h.operacake("-m", "time", "-t", "0:10", "-t", "1:10", "-w", "1000")  # time mode
h.operacake("-g")                         # -g : GPIO self-test
```

Modes (`-m manual|frequency|time`), port assignment (`-a`/`-b`), frequency routing (`-f port:min:max`), time dwell (`-t port:dwell`, `-w dwell`), board address (`-o`), and the GPIO test (`-g`) are all reachable. See `hackrf_operacake -h` for the authoritative flag set.

#### Clock configuration — `clock`

* **Builds:** `hackrf_clock <args...>`
* **Signature:** `clock(*args, print_cmd=False)`
* **Full passthrough.** Reads and writes the HackRF's clock input/output configuration (the reference clock used to synchronize multiple devices or lock to an external source).

```python
h = HackRF()
h.clock("-r", "3")       # read settings for clock 3 (CLKOUT); -r needs a clock num
h.clock("-a")            # read settings for ALL clocks
h.clock("-i")            # get CLKIN status
h.clock("-o", "1")       # enable CLKOUT
```

Note that `-r` requires a clock number (e.g. `-r 3`); calling `clock("-r")` alone prints the tool's usage rather than reading anything. Refer to `hackrf_clock -h` for the full set on your tools version (it has varied across releases — newer builds add HackRF Pro P1/P2 connector signal selection).

#### Debug register access — `debug`

* **Builds:** `hackrf_debug <args...>`
* **Signature:** `debug(*args, print_cmd=False)`
* **Full passthrough.** Low-level read/write of the radio's chip registers (MAX2837, Si5351C, RFFC5071) for debugging and advanced configuration. **This is a sharp tool** — writing registers can put the radio in an undefined state. Read access is harmless; write access is your responsibility.

```python
h = HackRF()
h.debug("--si5351c", "-n", "0", "-r")     # read Si5351C register 0
h.debug("--max2837", "-r")                # dump MAX2837 registers
h.debug("--rffc5071", "-r")               # dump RFFC5071 registers
```

#### SPI flash and CPLD — `spiflash_*`, `cpldjtag`

These read and (dangerously) write the device's firmware storage. The write paths are brick-guarded.

| Method | Builds | Guard |
|---|---|---|
| `spiflash_read(out, length=None)` | `hackrf_spiflash -r <out> [-l <n>]` | — (read is safe) |
| `spiflash_reset()` | `hackrf_spiflash -R` | — |
| `spiflash_write(firmware, confirm=False)` | `hackrf_spiflash -w <firmware>` | **`confirm=True` required** (can BRICK) |
| `cpldjtag(firmware, confirm=False)` | `hackrf_cpldjtag -x <firmware>` | **`confirm=True` required** (can BRICK) |

```python
h.spiflash_read("backup.bin")                       # dump current firmware
h.spiflash_write("new_firmware.bin", confirm=True)  # flash (guarded)
```

The `confirm=True` requirement exists because flashing firmware is the single most dangerous operation in the library: a bad image, an interrupted write, or unstable power can leave the board unbootable. The guard fires *before* any subprocess runs, so a forgotten `confirm` costs you nothing.

### Decoding and File Helpers

| Function / method | Purpose |
|---|---|
| `decode_iq(raw)` | bytes of interleaved int8 → normalized `complex64`. Drops a dangling odd byte rather than crashing. |
| `load_iq(path, count=None, offset_samples=0)` | file → `complex64`; the file twin of `decode_iq`, with bounded/offset reads. Module-level, no device needed. |
| `write_sigmf_meta(...)` / `read_sigmf_meta(path)` | write/read the `.sigmf-meta` sidecar. The reader accepts the `.iq` or `.sigmf-meta` path. |
| `parse_info(text)` (staticmethod) | `hackrf_info` text → dict. |
| `parse_sweep_line(line)` (staticmethod) | one `hackrf_sweep` CSV row → dict, or `None`. |
| `parse_freq(txt)` | `"433.92M"`, `"1.09G"`, `"2.5k"`, `"100MHz"`, or plain Hz → float Hz. Module-level. |

### Power and Relative Calibration

The HackRF is **not a calibrated instrument** — its raw dBFS amplitude is relative to ADC full scale, not power at the antenna, and it depends on the gain you set. These helpers (Level 1) make readings *consistent*; turning them into approximate dBm (Levels 2–3) is a hardware-and-reference workflow shown in `examples/calibrate.py`.

| Method | Purpose |
|---|---|
| `power_dbfs(iq)` | mean power of a `complex64` block in dBFS (≤ 0; raw, uncalibrated). |
| `gain_db(lna, vga, amp)` | total RX gain through the chain in dB. The quantity that makes a raw dBFS reading ambiguous. |
| `relative_power_db(iq_or_dbfs, *, lna=, vga=, amp=, offset_db=0, freq_hz=, freq_correction=)` | gain-normalized power: subtracts the gain chain so readings at *different gains are comparable*. Gains default from `last_params`. Pass `offset_db` (from a calibration run) to approximate dBm, and a `freq_correction(freq)→dB` callable to flatten the front-end response. |

The key property: the **same physical signal reads the same `relative_power_db` value regardless of gain**, where raw dBFS would shift by the gain delta. The library does only pure math here — it never invents reference data or claims a dBm it can't back up. To derive `offset_db` (feed a known power) or a `freq_correction` curve (sweep a flat source), run `examples/calibrate.py`; it saves a `calibration.json` you feed back in.

### Mode, Validation, and Feedback

| Method | Purpose |
|---|---|
| `set_mode(value)` / `get_mode()` / `require_mode(needed)` / `restore_mode(value)` | the RX/TX mode machine and gate. `set_mode("tx")` prints the safety banner; `restore_mode` rehydrates state without it. |
| `validate_rx(...)` / `validate_tx(...)` | apply the envelope (range checks + gain snapping); return the actual values used. |
| `estimate_capture(...)` | predict capture size/time and check free disk before committing. |
| `resolve(key)` | locate a `hackrf-tools` binary (handles Windows `.exe`/`.bat`/`.cmd` in `tools_dir`). |
| `set_verbose` / `get_verbose` / `print_message` / `warn` | feedback. `warn` always goes to stderr; `print_message` is verbose-gated. |
| `last_params` (attribute) | the snapped parameters from the most recent rx/tx/sweep call. |


## Device Capability Coverage

Great Scott Gadgets ships **eight** `hackrf-tools` binaries. This library wraps **all eight** — there is no device-interfacing tool it can't reach. (For comparison, some popular wrappers omit clock, cpldjtag, debug, and spiflash.)

| Binary | Wrapped by | Coverage |
|---|---|---|
| `hackrf_info` | `info`, `get_info`, `detect`, `identify`, `from_device` | Full — parsed + raw, plus autodetect/identify. |
| `hackrf_transfer` (RX) | `capture`, `capture_array`, `capture_stream`, `rx`, … | Full. |
| `hackrf_transfer` (TX) | `transmit`, `tx`, `transmit_file`, `transmit_cw` | Full, including CW signal-source mode (`-c`). |
| `hackrf_sweep` | `sweep`, `sweep_collect`, `sweep_stream`, `sweep_to_file` | Full — text generator plus binary/inverse-FFT file output (`-B`/`-I`). |
| `hackrf_clock` | `clock(*args)` | Passthrough — any `hackrf_clock` argument. |
| `hackrf_operacake` | `operacake(*args)`, `operacake_list` | Passthrough — any Opera Cake argument. |
| `hackrf_spiflash` | `spiflash_read`, `spiflash_write`, `spiflash_reset` | Read / write / reset; write is brick-guarded. |
| `hackrf_cpldjtag` | `cpldjtag` | Wrapped; brick-guarded. |
| `hackrf_debug` | `debug(*args)` | Passthrough — any register/debug argument. |

### Passthrough commands (full tool access)

`clock`, `operacake`, and `debug` accept arbitrary arguments and forward them verbatim, so the **entire** capability of those tools is reachable even though the library doesn't model each flag individually. Each has its own documented subsection under [Device Management](#device-management-advanced) with worked examples. In short:

```python
h = HackRF()
h.operacake_list()                       # hackrf_operacake -l
h.operacake("-m", "frequency", "-f", "0:100:500")
h.clock("-r")                            # hackrf_clock -r
h.debug("--si5351c", "-n", "0", "-r")    # read a register
```

### Binary and test-signal modes (now wrapped)

The handful of flags that don't fit the main capture/sweep paths each have a dedicated method, so they're first-class rather than escape-hatch-only:

* `hackrf_sweep -B` / `-I` (binary / inverse-FFT output) → **`sweep_to_file(..., binary=True)`** / **`sweep_to_file(..., inverse_fft=True)`**. The text generator (`sweep`) stays CSV; the file method owns the binary formats. (The library does not *parse* the binary output — you own that on read.)
* `hackrf_transfer -c` (constant-wave signal source) → **`transmit_cw(freq, sample_rate, amplitude=...)`**, TX-gated like any transmit.

### Genuinely not wrapped

What remains unexposed is minor and listed here so the boundary is explicit, not accidental:

* `hackrf_transfer -H` (hardware sync / wait-for-trigger) — a multi-device synchronization feature outside the single-device model here.
* The exact flag set of `clock`/`operacake`/`debug` is version-dependent; the library forwards whatever you pass but doesn't validate it against your tools version.

If you need `-H` before it's wrapped, drop to the internal runner — `h._run(["transfer", "-t", "f.iq", "-H", ...], mode="handle", kind="tx")` — accepting that you're then responsible for the invocation. Wrapping it properly (a typed parameter + a construction test) is a small, welcome addition.


## CLI Reference

The `hrf` entry point (installed by `pip`/`uv`) is a thin shell over the API.

```bash
hrf --help
hrf info                          # device + firmware info
hrf detect                        # autodetect + identify connected HackRF(s)
hrf doctor                        # environment preflight
hrf mode [rx|tx]                  # get or set the persisted mode
hrf presets                       # list band presets

# receive
hrf rx -f 433.92M -s 8M -n 2000000 -o capture.iq
hrf rx --preset ads-b -n 4000000  # a preset can supply the frequency

# sweep (CSV to stdout)
hrf sweep --f-min 88M --f-max 108M

# transmit (TX mode required)
hrf mode tx
hrf tx signal.iq -f 433.92M -s 8M -x 20
```

Most commands accept `--print-cmd` to print the underlying `hackrf_*` command without running it, `--force` to downgrade range rejects to warnings, `--serial` to select a board, and `-v/--verbose`. Frequencies accept unit suffixes (`433.92M`, `1.09G`).


## Library Development

The package layout, the `plotting` optional-dependency, the `dev` group, and the `hardware` pytest marker are all defined in `pyproject.toml`. To work on the library, from the `hackrfpy` project directory:

```bash
uv sync                 # installs numpy + dev group, editable-installs hackrfpy
uv run pytest           # hardware tests self-skip without a device
```

Per-command methods live in mixin modules under `src/hackrfpy/_commands/` and are composed onto the `HackRF` class in `core.py`. Adding a command usually means: add a method to the appropriate mixin, then add a command-construction test (assert the exact `hackrf_*` argv on the happy path via `print_cmd`, and assert nothing runs on the validation-error path). Process-lifecycle changes should be exercised with the cross-platform stub factory in `tests/conftest.py` so they are covered on Windows as well as POSIX.

See [project_summary.md](project_summary.md) for the boundary between this project (transport + control) and the planned signal-processing/visualization project.


## Notes for Beginners

This is a brief section for anyone who jumped in a little ahead of the reading. It is strongly suggested to *read the official documentation* before driving the hardware, especially before transmitting.

### Vocab Check

* **I/Q** — the two components (in-phase and quadrature) of a complex sample. The HackRF delivers them interleaved as signed 8-bit values. "int8 I/Q" is the native format; this library normalizes it to `complex64` for you.
* **Sample rate (Msps)** — millions of complex samples per second. It sets the instantaneous bandwidth you can see (roughly equal to the sample rate).
* **LNA / VGA gain** — two stages of receive gain (IF and baseband). They step in fixed increments; the library snaps your request down to a real step.
* **Bias tee** — a switch that puts DC on the antenna port to power an external amplifier. Off by default; don't enable it unless you know your antenna setup wants it.
* **SigMF** — a simple open format for recording the *metadata* of an I/Q capture (frequency, rate, gains) alongside the raw samples, so a headerless int8 blob becomes self-describing.

### What an SDR Is (and Isn't)

A software-defined radio moves the radio's "knobs" — tuning, filtering, demodulation — into software. The HackRF is a *wide-band, half-duplex, 8-bit* SDR: it covers an enormous frequency range but sees one band at a time, can't receive and transmit simultaneously, and quantizes coarsely (8-bit). That makes it a superb tool for exploration, capture, and experimentation, and a poor choice when you need high dynamic range or full-duplex operation. It is not a spectrum analyzer (though `hackrf_sweep` approximates one), and it is not a vector network analyzer.

### Some General HackRF Notes

* It is **half-duplex**. You cannot receive and transmit at once. The library's mode gate reflects this.
* **Transmitting is regulated.** You are responsible for operating within the law and within your equipment's limits. The TX gate and gain ceiling are guardrails, not permission.
* An interrupted capture can leave a partially written file; the library stops children with a clean interrupt (not a hard kill) specifically so recordings aren't truncated mid-sample-pair.
* Tool version matters. Stdout streaming (`-r -`) and bounded sweeps (`sweep -N`) need reasonably modern `hackrf-tools`; `preflight`/`features` will warn on versions too old.
* On Windows, point `tools_dir` at your `hackrf-tools` folder if the binaries aren't on `PATH` — the library resolves the `.exe` names for you.


## FAQs

### How should I be using this?

For scripting and automating HackRF capture, sweep, and transmit from Python when you don't need a GUI, and as a cleaner CLI (`hrf`) over the raw `hackrf-tools`. It is especially useful for capture pipelines (sweep → find signal → capture), batch recording with self-describing SigMF metadata, and feeding samples into downstream processing.

### Does this replace the official hackrf-tools?

No — it *wraps* them. You still install `hackrf-tools`; this library orchestrates them and gives you a Python API and a friendlier CLI on top.

### Why wrap the binaries instead of using libhackrf bindings?

Portability, especially on Windows. No C extension to compile means no toolchain matching, no build failures, and an install that just works once the binaries are present. The trade-off is the system dependency on `hackrf-tools` and a dependence on their stdout/exit behavior, which the library probes and version-checks.

### Will there be signal processing (demod, FFTs, waterfalls)?

Not in this library. That is the planned second project. This one stops at delivering `complex64`; see [project_summary.md](project_summary.md) for the split.

### How often is this updated?

As development continues and as behavior is confirmed on hardware. This repository tracks the working version.


## References

* HackRF official documentation: [https://hackrf.readthedocs.io/](https://hackrf.readthedocs.io/)
* HackRF firmware + tools source (Great Scott Gadgets): [https://github.com/greatscottgadgets/hackrf](https://github.com/greatscottgadgets/hackrf)
* HackRF One product page: [https://greatscottgadgets.com/hackrf/one/](https://greatscottgadgets.com/hackrf/one/)
* `hackrf_transfer`, `hackrf_sweep`, `hackrf_info` man pages / `--help` output (your installed version is the authoritative reference)
* SigMF specification: [https://github.com/sigmf/SigMF](https://github.com/sigmf/SigMF)
* This project's sibling libraries (same author, same structural approach):
    * [tinySA_python](https://github.com/LC-Linkous/tinySA_python)
    * [nanoVNA_python](https://github.com/LC-Linkous/nanoVNA_python)


## Licensing

This project is licensed under the GNU General Public License v2.0 or later. See the [LICENSE](LICENSE) file for details.

The **code in this repository** is released under GPL-2.0-or-later. This licensing does NOT take priority over the official HackRF releases or the decisions of Great Scott Gadgets, and does NOT apply to their products or firmware.

This software is released **AS-IS** — there may be bugs, especially under active development. It is **UNOFFICIAL**: Great Scott Gadgets does not support, maintain, or bear responsibility for it. You are responsible for operating your hardware safely and legally, particularly when transmitting.
