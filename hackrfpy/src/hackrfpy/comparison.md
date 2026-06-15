# comparison.md — hackrfpy vs other Python HackRF libraries

An honest look at where this library sits among the Python options for the
HackRF One. The goal is **not** to claim it's the best at everything — each of
these makes a different, defensible tradeoff. The goal is to identify the niche
hackrfpy fills and be clear about what it gives up to fill it.

## The one decision that separates them

Every Python HackRF library makes a single architectural choice that determines
almost everything else: **bind `libhackrf` (the C library) or wrap the
`hackrf-tools` binaries (the command-line programs).**

* **libhackrf binders** (`python_hackrf`, `pyhackrf2`, `pyhackrf`, the various
  `py-hackrf-ctypes` / `pylibhackrf` projects) call the C library's functions
  directly — through ctypes, Cython, or a C extension. They get low-level
  control and real-time sample callbacks, at the cost of a compiler/headers
  dependency and a callback-based programming model.
* **hackrfpy wraps the binaries.** It runs `hackrf_info`, `hackrf_transfer`,
  `hackrf_sweep`, etc. as subprocesses and manages their I/O and lifecycle. It
  gives up real-time callback control and adds subprocess overhead, and in
  exchange gets a dependency-free install, full tool coverage, and a place to
  put a validation/safety layer.

Almost every difference below traces back to this one fork.

## The landscape

| Library | Approach | Install | TX | Sweep | Device mgmt (clock/spiflash/etc.) | Maintained |
|---|---|---|---|---|---|---|
| **hackrfpy** (this) | wraps **binaries** | `pip` + binaries on system; no compiler | yes (gated) | yes | **all 8 tools** | active |
| **python_hackrf** | Cython → libhackrf | `pip` + compiler + libhackrf headers/libusb | yes | yes | info, sweep, operacake, transfer only | active, most complete binder |
| **pyhackrf2** | Python → libhackrf (ctypes) | `pip` + libusb/libhackrf | yes | yes | minimal | moderate |
| **pyhackrf** (dressel/4thel00z) | ctypes → libhackrf | `pip` + libusb/fftw | partial | via callback | minimal | stale |
| **py-hackrf-ctypes / pylibhackrf** | ctypes / C ext → libhackrf | manual build | varies | via callback | minimal | stale/experimental |

(Approaches verified against each project's own PyPI/GitHub description; feature
columns reflect what each documents, not exhaustive testing.)

## What the libhackrf binders do well (and where hackrfpy now stands)

Being honest about the architectural tradeoff, and what has and hasn't been narrowed:

* **Real-time sample callbacks.** *Gap narrowed.* The binders expose libhackrf's
  callback model — register a function that fires as buffers arrive. hackrfpy
  now offers the same *ergonomics* via `capture_callback(freq, rate, on_block)`:
  your function is called with each decoded `complex64` block as it streams, and
  returns `False` to stop. The mechanism differs (it rides the subprocess stream
  rather than a libhackrf USB-thread callback), so it is not zero-copy — but the
  measured block-delivery latency is low: on a laptop at 20 Msps, median ~0.04 ms
  between blocks with ~0.5 ms jitter (`examples/benchmark.py`). So *when data is
  flowing*, the "latency floor is the pipe" concern is sub-millisecond; the real
  constraint at top rates is throughput (above), not per-block latency.
* **Lower overhead at high rates.** *Gap narrowed; measured, with an honest
  ceiling.* The decode path was optimized to construct `complex64` directly
  (≈3× faster; benchmarked at ~190–390 MB/s depending on machine, i.e. 5–10× the
  40 MB/s the device produces at 20 Msps — so **decode is not the bottleneck**).
  The remaining cost is the subprocess + kernel pipe. Measured on a laptop with a
  shared USB bus (`examples/benchmark.py`): a 20 Msps capture received **100% of
  samples with no bulk loss** and only a single startup-transient shortfall over
  120M samples, but the consumer drained the pipe at a **steady-state ~14 Msps**,
  so the capture ran slower than real-time (the pipe back-pressures and
  `hackrf_transfer` blocks rather than dropping). The practical reading: for
  *capture-to-file or batch* work you lose nothing; for a *live real-time*
  consumer at the very top of the rate range, the pipe drain is a real ceiling a
  binder avoids. There is also a fixed ~1–2 s per-capture **startup cost**
  (process launch + USB setup + device settle) the in-process binders don't pay.
  These numbers are machine-specific — run the benchmark on your own setup.
* **Fine-grained mid-stream control.** *Genuine remaining gap.* `hackrf_transfer`
  takes one frequency and runs until stopped; it cannot retune mid-stream, so
  hackrfpy cannot either — that is the binary's limit, not a missing feature.
  What hackrfpy adds is `scan_frequencies([...], rate, n)` to make sequential
  multi-frequency capture a single clean call, but each retune is still a fresh
  process with a short re-open gap. **True gapless retuning needs the C library**
  — if that's your requirement, use a binder.
* **Android.** `python_hackrf` documents an Android build path. hackrfpy targets
  desktop OSes. Unchanged.

If your work is "process every sample in real time with the lowest possible
latency, retuning on the fly," a libhackrf binder — `python_hackrf` is the most
complete and actively maintained — is still the better fit. The gap is now
narrower (callback ergonomics and fast decode), but the architectural ceiling is
real and this document won't pretend otherwise.

## What hackrfpy does that the others don't

The niche, stated plainly:

* **Dependency-free install, especially on Windows.** Because it wraps the
  binaries, there is no C compiler, no `libhackrf.h`, no `libusb` headers, no
  `PYTHON_HACKRF_CFLAGS`/`LDFLAGS` to set. The binders all require a build
  toolchain and the native headers present at install time — the exact friction
  that makes HackRF-in-Python painful on Windows. hackrfpy needs only the
  `hackrf-tools` binaries (which ship prebuilt) and pip. This is the single
  biggest practical differentiator.
* **Complete tool coverage.** hackrfpy wraps **all eight** `hackrf-tools`
  binaries, including the ones the binders explicitly skip. `python_hackrf`'s
  own docs list `hackrf_clock`, `hackrf_cpldjtag`, `hackrf_debug`, and
  `hackrf_spiflash` as "Will not be implemented." hackrfpy wraps clock, debug,
  and operacake as full argument passthroughs and provides brick-guarded
  spiflash/cpldjtag. If you need clock configuration or firmware operations from
  Python, this is currently the option.
* **A validation / safety layer.** None of the binders police your inputs — they
  pass values straight to libhackrf. hackrfpy adds a reject-by-default operating
  envelope (catch a 60 GHz typo for 6 GHz), gain snapping with honest
  notification, a sub-recommended-sample-rate warning, an explicit RX/TX mode
  gate so you can't transmit by accident, a TX gain ceiling against
  order-of-magnitude fat-fingers, and a `max_duration` dead-man for open-ended
  transmits. This is a deliberate "help you not break your hardware or the law"
  layer that a thin binding has no place to put.
* **Lifecycle safety for scripts.** Clean child reaping on `KeyboardInterrupt`,
  context managers (`capture_stream`, `sweep_stream`) that guarantee the radio
  is stopped on exit, and an `atexit` backstop so a dying script doesn't leave a
  transmitter running. These matter precisely because subprocess management is
  the risk hackrfpy takes on — so it's where the engineering went.
* **A real CLI.** `hrf` is a first-class command-line tool (`hrf detect`,
  `hrf rx`, `hrf sweep`, `hrf doctor`), not just a library. The binders are
  libraries first; `python_hackrf` has a CLI but centered on info/sweep.
* **Self-describing captures.** SigMF sidecar metadata written automatically, so
  a recording carries its frequency/rate/gains instead of being a headerless
  int8 blob.
* **Hardware-validated parsing.** The parsers are tested against frozen verbatim
  output from a real HackRF One (info, sweep, IQ), including real quirks like
  out-of-order sweep segments and continuation-line fields.

## Honest weaknesses

Where hackrfpy is genuinely behind, beyond the architectural give-ups above:

* **Younger and fewer users** than the established binders. It is validated
  against a real HackRF One (hardware-marked tests pass; parsers are pinned to
  verbatim device output), but it has far less field exposure across diverse
  setups, firmware versions, and edge cases than libraries that have been in
  wide use for years. Maturity is about breadth of real-world exposure, and
  that takes time and users.
* **Subprocess dependence on tool behavior.** It relies on the `hackrf-tools`
  stdout format and exit codes, which it parses and version-checks — but a
  future tools change could require parser updates. A binder against the stable
  C ABI is insulated from that.
* **No real-time callback path.** Restated because it's the real ceiling: if you
  outgrow "stream blocks from a subprocess," the architecture won't follow you
  into zero-latency callback territory without becoming a different library.
* **Not a DSP library.** By design — it yields `complex64` and stops. The binders
  don't do DSP either, but their callback model sits closer to where you'd build
  it.

## Who should use which

* **Use a libhackrf binder (`python_hackrf` first) if:** you need real-time
  per-buffer callbacks, minimum latency at high sample rates, mid-stream
  retuning, Android support, or you're already in a compiled-toolchain
  environment where the build dependency is free.
* **Use hackrfpy if:** you want a clean `pip` install with no compiler
  (especially on Windows), a scriptable + CLI workflow, full access to *all* the
  hackrf tools including clock/debug/firmware, a safety/validation layer that
  guards against expensive mistakes, robust script lifecycle (clean stop, no
  orphaned transmitters), and self-describing recordings — and your data path is
  "capture/sweep to file or to `complex64`," not real-time callback DSP.

## The one-line version

The other libraries are **C bindings** that give you low-level, real-time
control at the cost of a build toolchain. hackrfpy is a **binary wrapper** that
gives you a dependency-free install, complete tool coverage, and a safety layer.
It now matches the binders' callback *ergonomics* (`capture_callback`) and has a
fast decode path, so the usability gap is small; the remaining hard difference
is true gapless mid-stream retuning, which needs the C library. Different tools
for different jobs; the niche is "scriptable HackRF control that installs cleanly
on Windows and tries to keep you from breaking things."

---

*Landscape current as of mid-2026; library capabilities and maintenance status
change. Verify against each project's current PyPI/GitHub before relying on a
specific claim. Feature columns reflect each project's own documentation.*
