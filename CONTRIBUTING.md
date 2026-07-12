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
  for this repo; see `project_summary.md`.
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
uv run mypy src/hackrfpy            # type check (advisory for now)
```

CI runs the same suite across Windows, Linux, and macOS on Python 3.11–3.13.
Windows is the primary target platform, so process-lifecycle changes must pass
there specifically.

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
when no device is detected. Parser fixtures live in `tests/fixtures/` and are
frozen from real hardware output via `tests/collect_real_data.py`. If you add a
parser, add a real-output fixture rather than a hand-written one where possible.

## Commit and PR conventions

- Keep PRs focused; one logical change per PR is easiest to review.
- Reference the issue the PR closes (`Closes #123`).
- Describe what you tested, and whether it was tested against real hardware or
  stubs only.
- New public methods need a README entry in the Method Reference and, ideally, a
  runnable example under `examples/`.

## License

By contributing, you agree that your contributions are licensed under the
project's **GPL-2.0-or-later** license.
