<!-- Thanks for contributing to hackrfpy. Keep PRs focused: one logical change. -->

## Summary

<!-- What does this change and why? Link the issue it closes. -->
Closes #

## Type of change

- [ ] Bug fix
- [ ] New command / feature
- [ ] Docs / examples
- [ ] Test / CI / tooling
- [ ] Refactor (no behavior change)

## How it was tested

- [ ] `uv run pytest -m "not hardware"` passes locally
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] Tested against **real hardware** (describe below)
- [ ] Tested with **stubs only** (no board)

<!-- If real hardware: which board, firmware, and hackrf-tools version? -->

## Checklist for new/changed commands

- [ ] Binary invocation goes through `_run(argv, mode=...)` (no direct subprocess)
- [ ] Added a command-construction test asserting the exact `hackrf_*` argv via `print_cmd`
- [ ] Added a validation-error test asserting **nothing runs** on bad input
- [ ] Any new envelope limits live in `constants.py`, not hard-coded in the method
- [ ] Process-lifecycle changes covered with the cross-platform stub factory (`tests/conftest.py`)
- [ ] README Method Reference updated; example added under `examples/` if it's a public method

## Notes for reviewers

<!-- Anything tricky, follow-ups intentionally left out, etc. -->
