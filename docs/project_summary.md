# hackrfpy — project split summary


AI summary for some scratch notes. it's a bit gross and incomplete

This project is the control/transport layer over the `hackrf-tools` binaries —
move bytes, manage the device, validate the operating envelope, and hand back
raw samples. Anything that *interprets* the samples is project two.

## Feature split

| Feature | This project (transport/control) | Project two (DSP/visualization) | Notes |
|---|:---:|:---:|---|
| Device info / enumeration (`info`, multi-board) | ✅ | | Parses `hackrf_info`; serial selection via `-d`. |
| Environment preflight (`preflight`, `doctor` alias) | ✅ | | Tools-on-PATH, board presence, disk, version. |
| Tool version + feature probe (`features()`) | ✅ | | Maps tools version → capability flags. |
| Operating-mode machine + TX gate | ✅ | | RX default; TX requires deliberate switch + banner. |
| Validation envelope (freq/rate/gain hard ranges) | ✅ | | Reject-by-default; `--force` downgrades. |
| Gain snapping + readback (`last_params`) | ✅ | | Snapped values published per call. |
| File capture (`hackrf_transfer -r`) | ✅ | | Bounded / timed / open-ended. |
| In-memory capture (`capture_array`) | ✅ | | Returns `complex64` ndarray, no file. |
| Live stream (`capture_stream`, stdout `-r -`) | ✅ | | Yields decoded blocks; context-managed. |
| Segmented / rolling capture | ✅ | | Whole files; documented re-open gap. |
| IQ decode (`decode_iq`, `load_iq`) | ✅ | | int8 interleaved → normalized `complex64`. **The seam.** |
| Transmit (`hackrf_transfer -t`) | ✅ | | TX-gated; gain ceiling; bias-tee. |
| TX dead-man (`max_duration`) + atexit backstop | ✅ | | Best-effort; see OS-deadman TODO. |
| Sweep (`hackrf_sweep`, parsed CSV rows) | ✅ | | Yields parsed dict rows. |
| SigMF sidecar write/read | ✅ | | Records actual (snapped) params. |
| Band presets | ✅ | | User-convenience freq/rate; not a TX gate. |
| Device mgmt (clock, operacake, spiflash, cpld, debug) | ✅ | | Firmware ops brick-guarded (`confirm=True`). |
| CLI (`hrf`) | ✅ | | Thin shell over the API. |
| Resampling / decimation | | ✅ | Consumes `complex64`. |
| Filtering (FIR/IIR, channelization) | | ✅ | |
| Demodulation (FM/AM/PSK/etc.) | | ✅ | |
| FFT / spectrogram / PSD | | ✅ | |
| Waterfall / real-time plotting | | ✅ | `examples/waterfall_realtime.py` previews the *input* only. |
| Signal detection / classification | | ✅ | |
| Recording playback + analysis UI | | ✅ | May reuse `load_iq` + SigMF reader from here. |

## Examples (this repo) are previews, not the product

`examples/` shows how project two will *consume* this library (e.g. a waterfall
fed by `capture_stream`), but the DSP/plotting math in them is a stand-in. The
real signal work lives in project two.

## Deferred / known gaps (this project)

- **OS-level dead-man** for hard-kill (`kill -9`, power loss): not implemented.
  Linux `PR_SET_PDEATHSIG` is Linux-only; Windows needs a Job Object with
  kill-on-close. Deferred as deliberate platform-split work.
  Marker: `TODO(os-deadman)` in `core.py`.
- **Windows lifecycle test coverage**: the stub-binary lifecycle tests are bash
  scripts and skip on Windows — the platform this library targets. Worth a set
  of `.bat`/Python stubs so `_run`'s lifecycle is proven on Windows.
- **Capability-driven validation**: `features()` exists but the validation
  envelope still uses static `constants.py` ranges rather than adjusting to the
  probed board/firmware. Closing that loop is a candidate enhancement.
