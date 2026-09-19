# Contributing to hackrfpy

Thanks for your interest in improving hackrfpy. This is an **unofficial**
community wrapper around the `hackrf-tools` binaries. It is not endorsed by
Great Scott Gadgets, and nothing here should be read as an authoritative
statement about device behavior — always defer to the
[official HackRF documentation](https://hackrf.readthedocs.io/).

This project deals with hardware that can **transmit**. Please read the safety
notes in the README before contributing anything that touches the transmit
path.

## Ways to contribute

- **Report a bug** — open an issue with the bug template. Include your OS,
  Python version, `hackrf-tools` version (`hackrf_info`), and the exact command
  or code that reproduces it.
- **Request a feature** — open an issue with the feature template. Note that
  signal processing (demod, FFT, waterfalls) is intentionally **out of scope**
  for the library API — this project is transport + control. The `examples/`
  directory may demonstrate downstream processing (`fm_demod_to_wav.py`) to
  show where the boundary sits, but the API stays at `complex64` in, files
  out.
- **Improve docs** — README fixes, clearer examples, and beginner notes are all
  welcome and don't require hardware.
- **Submit code** — see the workflow below.

## Development setup

The installable project lives in the `hackrfpy/` subdirectory (the one with
`pyproject.toml`). This project uses [uv](https://docs.astral.sh/uv/).

```bash
cd hackrfpy
uv sync                 # numpy + dev group, editable install of hackrfpy
uv run pytest           # hardware tests self-skip without a board
```

Run everything through `uv run` so the synced environment is used. A bare
`python ...` can silently create or use a second environment.

## Before you open a pull request

Run these from the `hackrfpy/` directory:

```bash
uv run pytest -m "not hardware"     # full hardware-free suite must pass
uv run ruff check .                 # lint
uv run ruff format .                # apply formatting
uv run mypy src/hackrfpy            # type check (BLOCKING in CI)
```

Also expected with a code PR:

- **A CHANGELOG entry** under `[Unreleased]` — this project's changelog is
  detailed and rationale-bearing; say what changed and why.
- **Docstrings on new public API** — `tests/test_docstrings.py` gates the
  whole public surface and will fail your PR without them.
- **Coverage** — CI gates at 85% (see the policy at the bottom of this file);
  new code arrives with its tests.
- **Hardware evidence for core changes** — any change under `src/hackrfpy/`
  requires a full-suite run on Windows with a real HackRF attached (hardware
  tests passing), reported in the PR. See the policy below.

CI runs the suite on Windows and macOS across Python 3.11–3.13. Windows is
the primary — and only hardware-verified — platform, so process-lifecycle
changes must pass there specifically. Linux is not in the CI matrix: see the
platform standard in the coverage policy below.

## Adding a command

The `HackRF` class is composed from mixins in `src/hackrfpy/_commands/`, wired
together in `core.py`. To add a command:

1. Add the method to the appropriate mixin (`capture.py`, `sweep.py`,
   `transmit.py`, `info.py`, or `device.py`).
2. Route the binary invocation through `_run(argv, mode=...)` — don't spawn
   subprocesses directly. The four modes are `blocking`, `timed`, `handle`,
   and `stream`.
3. Add a **command-construction test**: assert the exact `hackrf_*` argv on the
   happy path via `print_cmd=True`, and assert that **nothing runs** on the
   validation-error path.
4. If your change touches process lifecycle (start/stop/reap/interrupt), cover
   it with the cross-platform stub-binary factory in `tests/conftest.py` so it
   is exercised on Windows as well as POSIX.

Any value the library treats as a limit (frequency, sample rate, gain steps,
filter bandwidths) belongs in `constants.py` — the single source of truth the
tests import. Don't hard-code envelope numbers in a method.

## Tests that touch hardware

Tests that need a real board are marked `@pytest.mark.hardware` and self-skip
when no device is detected. A second, lighter category is marked with a
`needs_tools` skipif: those need the real `hackrf-tools` binaries on `PATH`
but **no board**, so they run on any machine with the tools installed — which
is why passed/skipped counts differ between machines. Parser fixtures live in
`tests/fixtures/` and are frozen from real hardware output via
`tests/collect_real_data.py`. If you add a parser, add a real-output fixture
rather than a hand-written one where possible.

## Commit and PR conventions

- Keep PRs focused; one logical change per PR is easiest to review.
- Reference the issue the PR closes (`Closes #123`).
- Describe what you tested. For changes under `src/hackrfpy/` (the core
  library), a full-suite run on Windows with a real HackRF attached — hardware
  tests passing — is **required**, and the PR should say so (paste the pytest
  tail). Docs, examples, and test-only changes are exempt. CI cannot attach a
  board, so this is the human half of the quality gate; maintainers may
  re-verify on their own hardware before merge.
- New public methods need a README entry in the Method Reference and, ideally, a
  runnable example under `examples/`.

## License

By contributing, you agree that your contributions are licensed under the
project's **GPL-2.0-or-later** license.

## Test coverage and platform policy

CI gates coverage at **85% minimum** (`--cov-fail-under=85`, applied on every
leg of the CI matrix). Coverage below the gate fails the build; new code
arrives with the tests that keep it above.

**The CI matrix contains hardware-verified platforms** — currently Windows.
A platform enters the matrix when it is verified against a real HackRF
board, and is then held to the same standards (the 85% gate and the
hardware-evidence requirement below).

**Core library changes require a passing hardware test.** CI has no board
attached, so the stub suite is necessary but not sufficient: any PR that
changes code under `src/hackrfpy/` must include evidence of a full-suite
run — hardware tests included and passing — on Windows with a real HackRF
attached. Paste the pytest tail in the PR description. Changes limited to
docs, examples, or tests are exempt. The gates that CI *can* enforce
(coverage, lint, types, docstrings) stay automated; this one is enforced by
review.