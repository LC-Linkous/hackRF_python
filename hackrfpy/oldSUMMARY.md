# hackrfpy — bug-fix pass summary (2026-06-10)

All changes verified against the test suite: **19 passed, 2 hardware-skipped**
(no board attached), including 6 new regression tests in
`tests/test_bugfixes.py` that pin each fix. End-to-end CLI behavior was
exercised with hackrf-tools 2023.01.1 installed (dry-run paths only).

---

## Bugs fixed

### 1. `hrf rx --preset` was unusable (cli.py)
`-f` was hard-required by argparse for `rx`, so `hrf rx --preset ads-b ...`
(the README example) died with "the following arguments are required: -f"
before the preset logic ever ran.
**Fix:** `rx` now uses `_add_common_rf(sp, freq_required=False)`; after
preset resolution, `main()` raises `HackRFValueError` ("rx needs a frequency:
pass -f/--frequency or --preset") if neither supplied one.
**Verified:** `hrf rx --preset ads-b -n 4000000 -o adsb.iq --print-cmd` →
`hackrf_transfer -r adsb.iq -f 1090000000 -s 8000000 ...`

### 2. Ctrl-C was swallowed by `_run`, breaking segmented capture (core.py)
`_run` caught `KeyboardInterrupt`, SIGINT'd the child, and **returned
normally**. The `except KeyboardInterrupt` in `_capture_segmented` was
therefore unreachable: Ctrl-C ended the current segment and the loop happily
started the next file.
**Fix:** `_run` still shuts the child down cleanly (SIGINT → bounded wait →
terminate, factored into `_sigint_and_reap`) but now **re-raises**
`KeyboardInterrupt`. The segmented loop's handler now actually fires and
prints "segmented capture stopped by user"; the CLI's top-level handler still
exits 130 for single captures.

### 3. Latent pipe-fill deadlock in `handle`, `timed`, and `stream` modes (core.py)
stdout/stderr were PIPEs nobody drained while the child ran. hackrf_transfer
prints a stats line to stderr every second, so a long-enough run fills the
64 KB pipe buffer and the child blocks on write — the capture silently
stalls. Exactly the long-running use cases those modes exist for.
**Fix, per mode:**
- **handle:** `_Process` now drains stdout/stderr continuously in daemon
  threads; `result()` joins them and returns the accumulated bytes.
- **timed:** the poll-sleep loop is replaced with
  `proc.communicate(timeout=duration)`, which drains while waiting, then
  SIGINT + reap on expiry.
- **stream:** a daemon thread drains stderr into a capped (~64 KB) tail
  buffer.

### 4. `--print-cmd` returned inconsistent fakes (core.py + mixins)
`_run(print_cmd=True)` returned `("", "", 0)` regardless of mode, so a
dry-run of an open-ended capture handed back a tuple where the caller expects
a `_Process`, and `capture(to_stdout=True, print_cmd=True)` built a generator
that iterated a 3-tuple and fed strings to `decode_iq`.
**Fix:** dry runs uniformly print the resolved command and return **None**.
`capture` (live + open-ended paths), `transmit` (unbounded-repeat path), and
`info()` were updated to short-circuit before building generators/handles.
`sweep` already did this correctly.

### 5. Live-stream I/Q desync hazard (capture.py)
The `to_stdout` generator decoded each chunk independently; `decode_iq` drops
an odd trailing byte. That's safe at EOF only — mid-stream it swaps I and Q
for every sample after the split. You were protected only by
`BufferedReader.read(n)` happening to return exact even-sized chunks, an
implicit invariant one refactor away from breaking.
**Fix:** the generator now carries an odd remainder byte into the next chunk
(`tail` buffer). Pinned by a regression test that feeds deliberately
odd-split chunks and checks sample continuity.

### 6. Silent failure in stream mode (core.py) — found during the fix
`hrf sweep` with no board attached: hackrf_sweep printed its error to the
(unread) stderr pipe, exited non-zero, and the generator yielded nothing —
indistinguishable from a successful empty sweep.
**Fix:** when the stream child reaches EOF on its own with a non-zero exit
code, `_stream` now raises `HackRFDeviceError` with the stderr tail. A caller
breaking out early (GeneratorExit) still cleans up without raising.

### 7. `hrf mode tx` re-printed the "one-time" banner every invocation (cli.py)
The CLI built a fresh `HackRF()` (default rx) before `set_mode("tx")`, so the
banner fired even when the persisted mode was already tx.
**Fix:** new public `HackRF.restore_mode(value)` rehydrates persisted state
with validation but without the switch ceremony; the CLI uses it both in
`_make_device` (replacing the `h._mode = ...` private-attribute poke) and
before `set_mode` in the `mode` handler. Banner now fires only on a real
rx → tx transition. Verified: first `hrf mode tx` prints it, second doesn't.

---

## New functionality (the "last mile" for data-out)

- **`load_iq(path, count=None, offset_samples=0)`** — module-level in
  `core.py` (plus an instance alias). The file twin of `decode_iq`: reads a
  HackRF int8 recording straight into a normalized `complex64` numpy array
  via `np.fromfile` (no whole-file Python bytes copy), with bounded/offset
  reads for big captures. Importable as `from hackrfpy import load_iq` — no
  device or `HackRF()` needed to consume a recording.
- **`read_sigmf_meta(path)`** in `sigmf.py` — the reader half of the sidecar
  writer. Accepts either `foo.sigmf-meta` or `foo.iq` and returns the dict,
  so consuming code can recover frequency/sample-rate/gains.

## Files I had to reconstruct (diff against your originals!)

- **`src/hackrfpy/__init__.py`** and **`_commands/__init__.py`** were not in
  the upload. I wrote a minimal `__init__.py` exporting `HackRF`, `load_iq`,
  `constants`, the SigMF helpers, and the exceptions. If yours differs, merge
  the new `load_iq` / `read_sigmf_meta` exports into it.
- **`tests/fixtures/`** (`sample.iq`, `sweep_sample.csv`, `hackrf_info.txt`)
  were reconstructed to match the assertions in `test_parsing.py`. If you
  have real frozen captures, prefer yours — especially a real multi-board
  `hackrf_info` dump, which the current fixture set doesn't cover.

## Behavior notes / things I deliberately did NOT change

- **The rx/tx mode gate blocks `capture` while persisted mode is tx** (e2e
  confirmed: exit 3 with a clear message). That's your design; just be aware
  the gate is symmetric, not tx-only.
- **Segments are still not gapless** — each segment is a fresh process spawn
  and retune. I added a verbose notice in `_capture_segmented` rather than
  re-architecting; gapless would require a single child plus in-Python file
  rotation on the `-r -` stream.
- **Windows is still not really supported**: `send_signal(SIGINT)` semantics
  there mean `stop()`/timed mode would hard-kill mid-write. Needs
  `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` if you ever want it.
- **No `-d <serial>` device selection yet** — still single-board only.
- **`py.typed` ships with no annotations** — either annotate the public
  surface or drop the marker.
- **`doctor` checks tool presence but not version** — flag-surface skew
  across hackrf-tools releases (`-r -`, `sweep -N`) is the main fragility of
  the subprocess approach.

## Test results

```
tests/test_bugfixes.py    6 passed   (new — pins fixes 1, 4, 5, 7 + load_iq)
tests/test_cli_dryrun.py  1 passed
tests/test_hardware.py    2 skipped  (no HackRF detected — as designed)
tests/test_parsing.py     5 passed
tests/test_validation.py  7 passed
```

---

# Second pass (same day): remaining gaps closed

Verified: **26 passed, 2 hardware-skipped**, stable across 3 consecutive runs.

## Fixed / added

1. **`hrf sweep` now actually emits CSV** (cli.py). It previously printed
   `400000000-405000000: 5 bins` summaries and discarded the dB values. The
   output now matches hackrf_sweep's own shape and round-trips through
   `parse_sweep_line` (verified end-to-end), so it pipes cleanly.
2. **Segmented capture now has a per-segment disk guard** (capture.py).
   The branch previously skipped `estimate_capture` entirely — the
   run-indefinitely mode was the only one that could fill the disk. Each
   loop iteration now checks the next segment fits within the headroom and
   raises `HackRFEnvironmentError` otherwise.
3. **Device-free lifecycle tests** (`tests/test_lifecycle.py`, 6 tests).
   Stub bash binaries via `tools_dir` now exercise `_run`'s stream / timed /
   handle modes: CSV streaming, error surfacing, early break-out, scheduled
   stop of a chatty child, pipe draining past 256 KB, and serial injection.
4. **`-d <serial>` device selection.** `HackRF(serial=...)` /
   `--serial` on rx, tx, and sweep. Injected at the `_run` choke point for
   the tools that support it (`constants.TOOLS_WITH_SERIAL`); hackrf_info
   and hackrf_cpldjtag are deliberately excluded.
5. **Examples model the intended consumption path.**
   `capture_to_file.py` now uses `load_iq` + `read_sigmf_meta` instead of
   hand-rolled `open().read()` + `decode_iq`.
6. **Version is single-sourced** from pyproject via `importlib.metadata`
   in both `cli.py --version` and `__init__.__version__`.
7. **`hrf doctor` exits non-zero when problems are found**, so it's usable
   as a real preflight: `hrf doctor && hrf rx ...`.
8. **doctor checks the hackrf-tools version**: pre-2021 releases (which may
   lack `-r -` streaming and `sweep -N`) are flagged as a problem, and the
   version is included in the report and printout.
9. **Multi-board `hackrf_info` fixture + parsing test** added.
10. **Best-effort Windows interrupt path** (core.py): children are started
    with `CREATE_NEW_PROCESS_GROUP` and stopped with `CTRL_BREAK_EVENT` on
    Windows, SIGINT elsewhere, via one `_interrupt()` helper used by every
    shutdown site. **Untested on Windows** — exercised on POSIX only.
11. **Annotations added to the public consumption helpers** (`load_iq`,
    `read_sigmf_meta`) — gradual typing; py.typed coverage is still partial.
12. **README updated** for `--serial`, doctor exit codes, and the
    `load_iq`/`read_sigmf_meta` consumption path.

## Bugs the new tests caught while being written (both fixed)

- **Orphaned child on generator break-out — a real pre-existing bug.**
  `sweep()` and `capture(to_stdout=True)` wrap `_stream` in an outer
  generator; closing the *outer* generator (breaking out of the loop) never
  deterministically closed the inner one, so hackrf_sweep / hackrf_transfer
  kept running orphaned after the caller broke out. Reproduced with a stub
  (child still alive 1 s after `gen.close()`), fixed by explicitly
  `close()`ing the inner generator in a `finally` in both wrappers, and
  pinned by `test_stream_early_break_reaps_child`.
- **Race in the new stream error path**: a fast-failing child could exit
  before the stderr drain thread had read its message, producing
  `"hackrf_sweep exited 1: "` with no detail. The drain thread is now
  joined before the error is composed, and the full tail (not just the last
  chunk) is included.

## Still open (smaller now)

- Windows path is untested (flagged above).
- py.typed coverage is partial — the class methods are still unannotated.
- Gapless segmented capture would require single-process file rotation on
  the `-r -` stream; current behavior (short gap, now documented and
  notified) is unchanged.
