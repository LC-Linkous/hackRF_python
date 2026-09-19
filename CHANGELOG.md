# Changelog

All notable changes to hackrfpy are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Work on the current development branch. Entries move to a versioned section on
release.

### Added
- Type annotations across the entire shipped package, and `mypy` promoted to a
  blocking CI gate (`disallow_untyped_defs`). The package has always shipped a
  `py.typed` marker, which tells downstream type-checkers the inline annotations
  are real; previously only 1 of ~114 definitions was annotated, so that marker
  was a false promise. It is now enforced.
- `HostOps` protocol (`_host.py`) making the contract between `HackRF` and the
  command mixins explicit and type-checkable. The mixins call ~27 methods on
  `self` that live on the host class; that dependency was previously implicit in
  a comment. Runtime composition and MRO are unchanged.
- Continuous integration: GitHub Actions workflow running the test suite across
  Windows, Linux, and macOS on Python 3.11-3.13, plus a ruff + mypy lint job.
- CLI test suite covering argument parsing, the mode state file, preset
  resolution, `info`/`detect`/`doctor`, `rx`/`tx`/`sweep` dispatch, and the
  module-level exit-code mapping. Overall coverage raised from 73% to 86%
  (`cli.py` from 12% to ~98%).
- Community health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue templates, and a pull request template.
- `examples/channel_monitor.py`: live multi-channel power meter driven by
  `monitor_frequencies` (one continuous sweep, ASCII bar output, no plotting
  extra) -- the library's sweep-backed monitoring style previously had no
  example.
- `examples/tx_test_tone.py`: the first and only transmitting example. A
  constant-wave test tone behind the deliberate RX->TX mode switch, with a
  required and capped duration (10 s), a deliberately low default TX gain, the
  RF amp never enabled, and `--print-cmd` dry-run support.
- `tests/collect_real_FM_data.py`: records one named FM broadcast station as a
  reference dataset for comparison against a hardware receiver implementation.
  Writes the IQ + SigMF sidecar plus a machine-readable `.report.json` pinning
  down exact settings, firmware/tools versions, raw-IQ health (power, clipping,
  DC), and an FM-discriminator check for the 19 kHz stereo pilot with its SNR
  -- the definitive "this really is the station" test. Deliberately split from
  `tests/collect_real_data.py`, which freezes tiny verbatim parser fixtures.
- `tests/collect_fm_testdata.py`: repeatable FM test-data generator with a
  five-stage hardware pipeline -- discover (top-N sweep candidates), calibrate
  (walks LNA/VGA until peak amplitude lands in [0.25, 0.70]), verify (short
  probe per candidate; the 19 kHz pilot must show at the tuning offset before
  any full recording, making the script robust to time-of-day and weather
  propagation changes), record (station parked at +300 kHz, clear of the DC
  spike), validate. Falls back (`--fallback auto|always|never`) to a
  deterministic synthetic FM recording (fixed-seed; byte-identical every run)
  in the identical int8 + SigMF format, so downstream pipelines are never
  blocked by RF conditions or a missing board. Reports log every candidate
  tried with its pilot SNR, keeping runs at different times comparable.
- Per-capture validation in `examples/collect_sample_data.py`: short reads,
  dead/quiet front end, gain-induced clipping, stuck DC, and ADC utilization
  (peak amplitude < 0.1, i.e. fewer than ~13 of 127 int8 codes) are flagged.
  Validation is band-aware: bands are tagged `continuous` (fm), `bursty`
  (airband, ism433, ism915), or `scheduled` (noaa), and low utilization is a
  hard SUSPECT only for continuous bands -- on bursty bands a quiet window is
  correct data and is annotated as a noise-floor reference instead. A
  peak-to-median burst-ratio metric reports detected activity. Suspect
  captures are kept on disk but flagged on stderr, marked in the generated
  sample-data README, and the script exits 2 so a bad collection run cannot
  silently ship. (Motivated by a real 2026-09-17 run whose captures spanned
  only +/-4 of 127 int8 codes -- effectively 3-bit recordings -- while passing
  every earlier check.)
- `--hunt` / `--hunt-secs` in `examples/collect_sample_data.py`: for bursty
  bands, probe in 100 ms slices until a transmission appears (burst ratio
  >= 10 dB), then take the real capture -- so an ISM sample can be made to
  actually contain a burst (e.g. by pressing a key fob during the hunt window).
- The generated sample-data README now annotates each IQ file as a
  *(noise-floor reference)* or *(burst captured)*.
- `.gitignore`: `tests/fm_testdata/` (deterministic, regenerable output).
- `tests/test_interrupt_clean.py`: the clean-interrupt contract as a tested
  guarantee on BOTH platforms, replacing the "untested on Windows" caveat in
  `core.py`. The stub child now records WHICH signal it caught, so the tests
  distinguish the clean interrupt (SIGINT on POSIX; SIGBREAK from
  CTRL_BREAK_EVENT on Windows, traversing the `.bat` launcher layer like the
  real tools) from the `terminate()` escalation -- previously a broken
  CTRL_BREAK path could hide behind a working escalation. Also asserted:
  output written by the child's interrupt handler is drained into `stop()`'s
  result (the no-truncated-capture contract), and a child that ignores the
  interrupt is still reaped and reported unclean. The Windows CI leg proves
  the Windows path on the next push.
- OS dead-man for handle-mode children (closes the long-standing
  `TODO(os-deadman)` in `core.py`): the atexit backstop never runs on
  SIGKILL / TerminateProcess, so a hard-killed parent could leave a
  transmitter on the air. Now the OS itself ends the child when the parent
  dies: Linux children set `PR_SET_PDEATHSIG` to SIGINT in preexec (the
  CLEAN interrupt -- the dead-man is the flush path, with a `getppid()`
  check closing the fork-window race), and Windows children are assigned to
  a Job Object with `KILL_ON_JOB_CLOSE` (terminating the whole
  `.bat` -> python tree; the job handle lives on the `_Process`). macOS has
  no equivalent primitive; the atexit backstop remains the net there,
  documented. Gated exactly like the atexit registry: TX always, RX unless
  `backstop_rx=False`. `tests/test_deadman.py` proves it with a real
  SIGKILL of an intermediate parent on POSIX -- the child dies AND its
  interrupt handler ran -- plus the opt-out gate; the Windows Job Object
  leg proves on the next CI push.
- No-board detection reported nothing useful on Linux: `hackrf_info` there
  prints its version lines and "No HackRF boards found." to STDOUT and
  exits 1 with an empty stderr, so `detect()` raised on the exit code and
  discarded everything -- `problem` came back blank and `tools_version`
  `None`. `detect()` now parses whatever the tool printed regardless of
  exit code and reports the tool's own words, and tool errors in general
  fall back to the last stdout line when stderr is empty. Found and
  verified against the real 2023.01.1 Linux binaries (no board attached);
  regression tests pin both behaviors.
- Documentation refresh across both READMEs and CONTRIBUTING: the root
  README's claim that an OS-level dead-man was "not yet implemented" (it now
  is, and is tested), four dangling links to a `project_summary.md` that does
  not exist (scope statements are now inline), the CLI reference extended
  with `monitor`, `scan`, `sweep -o/-B/-I`, and `tx --cw`, the
  `monitor_frequencies` notes now state the covering-bin semantics, the
  package README's features/platform/transmit sections updated for the
  lifecycle-safety work, CONTRIBUTING's "mypy (advisory for now)" corrected
  to blocking, and the PR checklist extended (changelog entry, docstring
  gate, coverage gate).
- SigMF spec compliance is now tested, not trusted: the official
  `sigmf` package joined the dev dependency group, and the sidecar writer's
  output is validated with it -- including that the `hackrf` extension is
  DECLARED, not just used (a strict-validator rejection that regressed once
  pre-1.0). GNU Radio / IQEngine interop is a tested property.
- Docstrings across the entire public API: every public method on
  `HackRF` and `PersistentReceiver`, both classes, and the module-level
  functions -- 60 docstrings where `help()` previously returned nothing.
  The documentation used to live only in `#` comments, invisible to
  `help()`, IDE tooltips, and doc generators; the comments (which carry the
  rationale) remain, and the docstrings carry the contract. Includes the
  print-cmd caveat on `transmit`/`transmit_cw`: duration bounds are
  enforced parent-side, so a copied `--print-cmd` argv carries NO time
  bound. `tests/test_docstrings.py` gates the whole surface so it cannot
  drift back to undocumented.
- CLI caught up with the library, each command with tests:
  `hrf tx --cw` (a bounded CW test tone; requires `-d/--duration` because an
  unbounded carrier is exactly the orphan-transmitter risk the library
  exists to prevent; `--cw-amplitude` defaults below full scale),
  `hrf monitor` (sweep-backed multi-frequency power to stdout),
  `hrf scan` (per-frequency capture power), and `hrf sweep -o FILE` with
  `-B` / `-I` binary passthrough (which refuse the CSV stdout path, since
  that output is unparsed).
- Thread-safety documented (rescued by the roadmap-comment cleanup; it was
  recorded nowhere else): a `HackRF` instance is not safe to share across
  threads -- per-instance mutable state (`last_params`, persisted mode,
  logging wiring) and per-child drain threads. One instance per thread;
  instances are cheap. In the README and on the class.
- Coverage policy recorded in CONTRIBUTING: CI gates at
  `--cov-fail-under=82`, deliberately under the measured 85% because that
  figure counts Windows-only and hardware-only code as missed on Linux legs;
  to be revisited upward after the docstring pass.
- `hackrfpy.__version__`, resolved from installed package metadata
  (`importlib.metadata`), with a `0.0.0+unknown` fallback for uninstalled
  checkouts.
- `examples/fm_demod_to_wav.py`: the missing last mile -- demodulate a
  captured broadcast-FM IQ file to an audible mono 16-bit WAV using only
  numpy and the stdlib. Channelize (staged windowed-sinc decimation to
  200 kHz), FM-discriminate, 75 us de-emphasis (`--deemph 50` for regions
  using 50 us), 15 kHz audio lowpass to a 50 kHz WAV. Handles off-center
  stations via `--offset` (e.g. 300e3 for `collect_fm_testdata.py` output)
  and prints a multiplex readout proving the 19 kHz pilot, 38 kHz stereo
  subcarrier, and 57 kHz RDS are present in the discriminator output.
  Developed and verified against the 2026-09-17 98.1 MHz reference capture:
  the output audio shows music-shaped spectra, syllabic-band envelope
  modulation, and spectral flatness 0.09 (structured content, not noise).

### Changed
- CI platform policy: the test matrix now contains hardware-verified
  platforms only -- currently Windows (primary) and macOS -- and Linux was
  removed until it is verified against a real board, at which point it
  returns under the same standards. The coverage gate rose from 82% to an
  85% minimum on every remaining leg, and the codecov upload moved from the
  removed Linux leg to the Windows 3.12 leg. Known consequence, recorded in
  the workflow comment: the Linux `pdeathsig` dead-man path only executes on
  a Linux runner, so it is regression-untested until Linux re-enters the
  matrix.
- CONTRIBUTING policy rewrite to match: 85% minimum coverage, the
  hardware-verified-platforms rule, and a new requirement that any change
  under `src/hackrfpy/` include evidence of a full-suite run (hardware tests
  passing) on Windows with a real board -- CI cannot attach hardware, so
  that gate is enforced by review. The `needs_tools` test category (real
  binaries on PATH, no board needed) is now documented, which is why
  passed/skipped counts differ between machines.
- Second documentation pass: the root README's local-install line pinned a
  two-versions-stale wheel name (now a wildcard), its testing notes still
  described the Windows CTRL_BREAK path as untested (it now points at the
  tests that prove it), and its repo tree was missing three examples; the
  package README's platform section now records the real-binaries Linux
  verification and the Windows-EXE-on-Linux non-goal, and gained a CLI
  quick-start.
- Library diagnostics now go through the standard `logging` module instead of
  `print()`. Records are emitted on the `hackrfpy` logger: warnings at
  `WARNING`, verbose progress messages at `INFO`. A consumer can now route,
  reformat, or silence hackrfpy's output like any other library.
  - **Diagnostics no longer touch stdout.** `print_message` previously wrote to
    stdout, so `hrf sweep -v > out.csv` prepended `[*] mode: rx` into the CSV.
    stdout is now reserved for data (sweep CSV, IQ on `-r -`) and explicitly
    requested output (`--print-cmd`). Diagnostics go to stderr.
  - Console behavior is unchanged for scripts and the CLI: warnings still appear
    with no setup at all, and `verbose=True` / `-v` still prints progress. If the
    host application has configured logging, hackrfpy stays out of the way and
    simply propagates records to it.
- Packaging classifiers: removed the contradictory `Operating System ::
  OS Independent` (the library shells out to the Windows `hackrf-tools`
  binaries and Linux/macOS operation is unverified), leaving `Operating System
  :: Microsoft :: Windows`. Development status raised from `3 - Alpha` to
  `5 - Production/Stable` to match the 1.0.0 release.
- Ruff configuration added (`line-length = 100`, `select = ["E", "F", "W"]`), and
  the codebase made lint-clean so the CI lint job is meaningful.
- `examples/persistent_capture.py` rewritten to match its name and the README's
  description: a gapless segment collector draining ONE long-lived
  `open_receiver()` stream into back-to-back `seg_NNN.iq` files with SigMF
  sidecars (contrast with `capture(segment_secs=...)`, whose per-file process
  re-open leaves a short gap between files). The file had been a near-duplicate
  of `waterfall_persistent.py` whose own header pointed at the wrong filename.
- `examples/waterfall_persistent.py` absorbed the improvements stranded in that
  duplicate: frame-averaged spectra, DC/LO-leakage spike suppression, and
  large-block reads so the pipe drains fast enough to keep `hackrf_transfer`
  streaming at 10 Msps.
- `hackrfpy/README.md` examples list corrected (`persistent_capture.py` entry
  now matches the code) and extended with the new examples, including a new
  Transmit section.
- `examples/collect_sample_data.py` defaults: collects three bands (fm,
  ism433, ism915) instead of one, and exposes `--lna` / `--vga` with defaults
  raised to 32 / 28 (the old library defaults of 16 / 20 produced the 3-bit
  captures described above).
- `tests/collect_real_FM_data.py` defaults: gains raised to LNA 32 / VGA 28,
  and default sample rate raised from 2 Msps to 8 Msps -- the HackRF's
  baseband filter bottoms out at 1.75 MHz, so rates under 8 Msps admit
  aliases; a reference recording deserves the alias-free version at the price
  of larger files.
- `tests/collect_fm_testdata.py` captures at an integer multiple of the
  requested output rate that clears 8 Msps and decimates in software
  (windowed-sinc FIR) back down, so output files are unchanged (2 Msps int8 +
  SigMF by default) while discovery and demodulation run alias-free. Offline
  verification: an interferer 1.7 MHz off-channel, which a direct 2 Msps
  capture folds onto the demod region, is suppressed ~45 dB while the pilot
  survives at ~72 dB SNR.

### Fixed
- The `atexit` backstop never reaped an orphaned `PersistentReceiver`.
  `PersistentReceiver` registers itself in the live-handle registry, whose
  shutdown hook calls `if h.is_alive(): h.stop()` -- but `is_alive()` did not
  exist on the class, so the resulting `AttributeError` was swallowed by the
  hook's bare `except Exception` and the receiver was silently left running.
  Found by the typing pass; `is_alive()` added and pinned with a regression test.
- Reading from a closed `PersistentReceiver` raised a bare
  `TypeError: 'NoneType' object is not iterable` instead of a typed error; it now
  raises `HackRFDeviceError` with an actionable message.
- `sweep_stream(..., print_cmd=True)` would hand `StreamCtx` a `None` and crash;
  it now raises `HackRFValueError` pointing at `sweep(..., print_cmd=True)`.
- Unbounded memory growth on long-lived RX/TX handles: `_Process` drained child
  stdout/stderr into lists that were never trimmed, so an open-ended capture or
  repeat transmit retained every per-second stats line for the life of the
  process. Both drain paths now share a 64 KB cap (`_DRAIN_CAP`).
- `transmit()` now verifies the source file exists *before* arming TX and
  spawning `hackrf_transfer`, raising `HackRFEnvironmentError` instead of
  failing with a generic non-zero exit from the tool. The TX-mode gate is still
  checked first, and `print_cmd` dry runs skip the check.
- SigMF sidecars now declare the `hackrf` namespace in `core:extensions`.
  Previously the `hackrf:*` gain keys were written without declaring the
  extension, which strict SigMF validators reject.
- Removed unreachable dead code in `core.py` (an orphaned `return load_iq(...)`
  after a `return`, referencing three undefined names).
- The test suite no longer writes a stray `capture.sigmf-meta` into the working
  directory on every run.
- `CITATION.cff` version and release date corrected to `1.0.0` / `2026-06-16`,
  aligning the citation metadata with `pyproject.toml` and the tagged release.
- Removed a stray `hackrfpy/capture.sigmf-meta` at the package root, left over
  from a July test run at 433.92 MHz.
- `examples/fm_demod_to_wav.py` de-emphasis was accidentally quadratic: each
  64 K block was convolved against a full-block-length geometric kernel
  (~5e10 multiply-adds for a 2 s / 8 Msps capture), stalling the script after
  the multiplex readout. The kernel is now truncated where its weight falls
  below 1e-9 (a few hundred taps at 200 kHz); a 2 s reference file demodulates
  in ~3 s end to end, with output identical to within 1 LSB. Stage timings are
  now printed so a future stall is self-locating.
- `sweep()` / `sweep_to_file()` silently truncated the TOP of the requested
  band: both MHz edges were floored, so `sweep(433.9e6, 434.1e6)` ran
  `433:434` and never covered 434.0-434.1 MHz even while warning about the
  snap. Edges now snap OUTWARD (floor the low edge, ceil the high edge) so
  the swept range always contains the requested band; the warning text says
  so.
- `monitor_frequencies()` reported the MEAN dB of the whole covering sweep
  segment as the power "at" a frequency, diluting a narrowband carrier
  toward the noise floor (a -20 dB carrier in one bin of a 10-bin segment
  read as -74). It now reads the bin covering the frequency (max of that
  bin +/-1 for tuning slop). Behavior change for `examples/channel_monitor.py`
  and any monitor consumer: readings of narrowband signals rise to their
  true level.
- Handle-mode output was not visible to the parent until process exit unless
  the child flooded: the drain thread read pipes with `BufferedReader.read(N)`,
  which blocks until N bytes (64 KB) accumulate, so small periodic writes --
  e.g. hackrf_transfer's ~60-byte-per-second stats lines -- sat invisible for
  what would be ~18 minutes of real capture. Now `read1()`: bytes appear in
  the drain as soon as the child writes them. Found by the new clean-interrupt
  tests; also cut the test suite's wall time roughly in half by removing the
  same latency from every stubbed lifecycle test. (Found by the new
  clean-interrupt tests.)
- `_Process.stop()`'s escalation fired `terminate()` and returned without
  reaping: a child that ignored the interrupt could outlive `stop()`, and
  `result()` reported `returncode None`. The escalation is now a bounded,
  reaped ladder (interrupt -> terminate -> kill), so `stop()` always returns
  with the child dead and a real exit status. (Found by the new
  clean-interrupt tests.)
- `from_device()` guarded its parsed-info invariant with a bare `assert`,
  which `python -O` strips, letting raw text flow onward; it now raises
  `HackRFDeviceError`.

## [1.0.0] - 2026-06-16

Initial public release.

### Added
- Python wrapper and non-GUI command-line tool (`hrf`) for the HackRF One,
  driving the `hackrf-tools` binaries directly (no libhackrf bindings).
- Receive: bounded and streaming capture, with decode to `complex64` and
  self-describing SigMF (`.sigmf-meta`) sidecars.
- Spectrum sweep with streaming CSV parsing.
- Transmit: file playback and constant-wave source, guarded by an explicit
  operating-mode gate (transmit refuses unless the instance is switched to TX
  mode, which emits a one-time safety banner) and a TX gain ceiling.
- Device management passthroughs (clock, Opera Cake, SPI flash, debug) and
  preflight `info` / `detect` / `doctor` helpers.
- Cross-platform process lifecycle handling with best-effort clean interrupt
  (SIGINT on POSIX, CTRL_BREAK on Windows) and an atexit backstop for live
  RX/TX handles.
- Validation layer with hard-range checks, gain snapping to real device steps,
  and a parameter readback (`last_params`) reflecting the values actually used.

[Unreleased]: https://github.com/LC-Linkous/hackRF_python/compare/V1.0.0...HEAD
[1.0.0]: https://github.com/LC-Linkous/hackRF_python/releases/tag/V1.0.0