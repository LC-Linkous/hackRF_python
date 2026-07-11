# Changelog

All notable changes to hackrfpy are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Work on the current development branch. Entries move to a versioned section on
release.

### Added
- Continuous integration: GitHub Actions workflow running the test suite across
  Windows, Linux, and macOS on Python 3.11-3.13, plus a ruff + mypy lint job.
- CLI test suite covering argument parsing, the mode state file, preset
  resolution, `info`/`detect`/`doctor`, `rx`/`tx`/`sweep` dispatch, and the
  module-level exit-code mapping. Overall coverage raised from 73% to 86%
  (`cli.py` from 12% to ~98%).
- Community health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue templates, and a pull request template.

### Changed
- Packaging classifiers: removed the contradictory `Operating System ::
  OS Independent` (the library shells out to the Windows `hackrf-tools`
  binaries and Linux/macOS operation is unverified), leaving `Operating System
  :: Microsoft :: Windows`. Development status raised from `3 - Alpha` to
  `5 - Production/Stable` to match the 1.0.0 release.

### Fixed
- `CITATION.cff` version and release date corrected to `1.0.0` / `2026-06-16`,
  aligning the citation metadata with `pyproject.toml` and the tagged release.

<!--
Roadmap for this branch (append entries above as each lands):
  - Fix: cap the _Process stdout/stderr drain buffers (unbounded growth on
    long-lived RX/TX handles).
  - Fix: validate the transmit source file exists before arming TX mode.
  - Fix: declare the `hackrf` namespace in SigMF `core:extensions`.
  - Changed: route library diagnostics through the `logging` module instead of
    print(); `warn`/`print_message` become thin wrappers. NOTE breaking-ish:
    library users who set verbose=True must configure a logging handler to see
    info-level messages (the CLI configures this automatically).
  - Added: type annotations across the public API; mypy promoted to a CI gate
    (makes the shipped py.typed marker accurate).
  - Docs: note that a single HackRF instance is not safe to share across
    threads (deferred pending broader testing).
-->

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
