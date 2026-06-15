# hackrfpy

A self-contained CLI and scriptable Python wrapper for the **HackRF One**, built directly on the `hackrf-tools` command-line binaries (`hackrf_info`, `hackrf_transfer`, `hackrf_sweep`, ...). No `libhackrf` bindings, no native compilation, no ABI matching — if the standard HackRF tools run on your machine, this runs.

## Why this exists

Most HackRF Python libraries are `libhackrf` bindings: they need the native library present and compiled against, and the older ctypes wrappers exist largely because handling libusb callbacks from Python becomes unusable at high sample rates. `hackrfpy` takes the other road — it drives the compiled `hackrf-tools` binaries as subprocesses, so:

* **No build pain.** `shutil.which` finds the tools; there is nothing to compile and no header/library version to match.
* **No high-rate callback cliff.** `hackrf_transfer` (C) writes the IQ file itself; samples never pass through Python at line rate. For live work you tap a decimated stream, not the full 20 Msps.
* **Full device coverage.** `clock`, `spiflash`, `operacake`, `cpldjtag`, and `debug` are wrapped (with guardrails), not dropped.
* **Metadata-first.** Every capture can write a `.sigmf-meta` sidecar so recordings are self-describing.

The library is class-first: the CLI is a thin shell over a `HackRF` class you can `import` and script directly.

## Requirements

* The **HackRF host tools** (`hackrf-tools` from Great Scott Gadgets) on your PATH.
* Python ≥ 3.11, `numpy`.

The examples additionally need `matplotlib` (and `PyQt5` on Linux) — these are **not** required by the library.

## Install (uv)

```bash
pip install uv
cd hackrfpy
uv build
pip install dist/hackrfpy-0.1.0-py3-none-any.whl

# library + example plotting deps
pip install "hackrfpy[plotting]"
# development / tests
pip install -e ".[test]"
```

## Structure

```
hackrfpy/
├── pyproject.toml
├── README.md
├── src/
│   └── hackrfpy/
│       ├── __init__.py
│       ├── cli.py            # argparse shell; thin dispatch to the class
│       ├── core.py           # HackRF class: mode machine, validation, _run
│       ├── constants.py      # the operating envelope (single source of truth)
│       ├── exceptions.py     # typed errors (API raises, CLI pretty-prints)
│       ├── presets.py        # band presets (+ user TOML overlay)
│       ├── sigmf.py          # .sigmf-meta sidecar writer
│       ├── py.typed
│       └── _commands/
│           ├── info.py       # InfoMixin     -> hackrf_info
│           ├── capture.py    # CaptureMixin  -> hackrf_transfer -r
│           ├── transmit.py   # TransmitMixin -> hackrf_transfer -t
│           ├── sweep.py      # SweepMixin    -> hackrf_sweep
│           └── device.py     # DeviceMixin   -> clock/spiflash/operacake/doctor
├── examples/                 # built ON TOP of the library, not imported by it
└── tests/                    # mirror the mixins + parsing + hardware (self-skip)
```

`from hackrfpy import HackRF` exposes the full class. The per-command methods live in the `_commands/` mixins and are composed onto `HackRF` in `core.py`, which holds shared state, the mode machine, the validation layer, and the single device-I/O choke point `_run`.

## The operating-mode gate

The device starts in **RX mode**. Transmitting requires an explicit switch to **TX mode**, which is the deliberate confirmation and prints a one-time safety banner. There is no per-call flag and no transmit-by-typo.

```bash
hrf mode           # print current mode
hrf mode tx        # arm TX (prints the safety banner); persists across calls
hrf tx signal.iq -f 433.92M -s 8M
hrf mode rx        # disarm
```

In a script the mode is object state:

```python
from hackrfpy import HackRF
h = HackRF(verbose=True)
h.set_mode("tx")                 # banner; required before transmit()
h.transmit(433.92e6, 8e6, "signal.iq", txvga=20)
```

TX uses the **full device range** (1 MHz – 6 GHz) and frequency is never policed. The gain ceiling in `constants.py` only guards against an order-of-magnitude fat-finger; lower it to cap output on a given bench.

## The validation envelope

All limits live in `constants.py` so there is one place to edit as hardware/firmware evolves, and the tests import the same numbers so they never drift.

* **Hard ranges** (frequency 1 MHz–6 GHz, sample rate 2–20 Msps): rejected by default (catches 60 GHz-for-6 GHz typos). `--force` (CLI) / `allow_out_of_spec=True` (API) downgrades a reject to a warning. TX frequency is never policed.
* **Stepped gains** (LNA 0–40/8 dB, VGA 0–62/2 dB, TX VGA 0–47/1 dB): snapped **down** to the device's real step with a printed notice — the honest "what you'll actually get" value.
* **Baseband filter**: auto-derived (~0.75 × sample rate, snapped to a supported bandwidth) when unset; an explicit value is snapped and warns if it exceeds the sample rate.

The API raises typed exceptions (`HackRFValueError`, `HackRFModeError`, `HackRFDeviceError`, `HackRFEnvironmentError`); the CLI catches them and prints a clean message with a distinct exit code.

## Quick CLI usage

```bash
hrf doctor                                  # preflight: tools, board, disk, mode
                                            # (exits non-zero on problems, so
                                            #  `hrf doctor && hrf rx ...` works)
hrf info                                    # parsed device + firmware info

# receive 1M samples at 433.92 MHz, 8 Msps, to capture.iq (+ .sigmf-meta)
hrf rx -f 433.92M -s 8M -n 1000000 -o capture.iq

# receive for 5 seconds
hrf rx -f 88.5M -s 10M -d 5 -o fm.iq

# rolling 10-second segment files
hrf rx -f 915M -s 8M --segment 10 -o ism.iq

# a band preset (frequency + sample rate filled in for you)
hrf rx --preset ads-b -n 4000000 -o adsb.iq

# spectrum sweep 400–500 MHz, CSV to stdout
hrf sweep --f-min 400M --f-max 500M -1

# see the exact hackrf_* command without running it
hrf rx -f 433.92M -s 8M -n 1000000 --print-cmd

hrf presets                                 # list bands

# multi-board setups: pick a device by serial (rx / tx / sweep)
hrf rx -f 433.92M --serial 0000aabbccdd -n 1000000 -o capture.iq
```

## Scriptable usage

The CLI shell can be driven from a script (argv as a list), or you can skip it and call the class directly.

```python
from hackrfpy.cli import HackRFCLI
app = HackRFCLI(["rx", "-f", "433.92M", "-s", "8M", "-n", "1000000"])
app.main(app.getArgs())
```

```python
from hackrfpy import HackRF, load_iq, read_sigmf_meta
import numpy as np

h = HackRF(verbose=True)          # HackRF(serial="...") for multi-board

# consume an existing recording -- no device needed
iq = load_iq("capture.iq")                  # complex64, normalized
meta = read_sigmf_meta("capture.iq")        # freq / rate / gains

# bounded capture to file (+ SigMF sidecar)
h.capture(433.92e6, 8e6, num_samples=2_000_000, out="capture.iq")

# live, decoded IQ blocks (the '-r -' path): a generator of complex64 arrays
for block in h.capture(433.92e6, 8e6, to_stdout=True):
    power = 10 * np.log10(np.mean(np.abs(block) ** 2) + 1e-12)
    # ...process as it arrives...
    break

# open-ended capture you stop yourself
proc = h.capture(100e6, 10e6, out="open.iq")   # returns a controller
# ... later ...
proc.stop()

# sweep is a generator of parsed rows
for row in h.sweep(400e6, 500e6, num_sweeps=1):
    print(row["hz_low"], row["hz_high"], len(row["db"]))
```

## Running tests

```bash
pip install -e ".[test]"
python -m pytest                 # all
python -m pytest -m "not hardware"   # device-free only
python -m pytest -m hardware         # requires a connected HackRF
```

Hardware tests self-skip when no board is detected. Parsing tests run against frozen captures in `tests/fixtures/` so they never need a device.

## Command map

| CLI command | hackrf-tools binary | class method |
|-------------|---------------------|--------------|
| `info`      | `hackrf_info`       | `HackRF.info()` |
| `rx`        | `hackrf_transfer -r`| `HackRF.capture()` |
| `tx`        | `hackrf_transfer -t`| `HackRF.transmit()` |
| `sweep`     | `hackrf_sweep`      | `HackRF.sweep()` |
| `doctor`    | (multiple)          | `HackRF.doctor()` |
| `mode`      | —                   | `HackRF.set_mode()` |
| —           | `hackrf_clock`      | `HackRF.clock()` |
| —           | `hackrf_spiflash`   | `HackRF.spiflash_*()` |
| —           | `hackrf_operacake`  | `HackRF.operacake()` |
| —           | `hackrf_cpldjtag`   | `HackRF.cpldjtag()` |
| —           | `hackrf_debug`      | `HackRF.debug()` |

## Safety

* **TX is regulated.** You are responsible for operating within your license, power limits, and local law. The mode gate prevents accidental transmit; it does not make transmitting legal in your context.
* **`spiflash_write` / `cpldjtag` can brick the board.** Both refuse unless you pass `confirm=True`, and only with a verified image and stable power.

This software is AS-IS and UNOFFICIAL; it is not affiliated with or endorsed by Great Scott Gadgets.
