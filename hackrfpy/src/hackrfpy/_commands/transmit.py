#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/_commands/transmit.py'
#
#   TransmitMixin: transmit via hackrf_transfer -t. Gated entirely by operating
#   mode -- transmit() raises HackRFModeError unless the device is in TX mode.
#   Switching to TX mode (set_mode/`hrf mode tx`) is the deliberate, one-time
#   confirmation and prints the safety banner. Frequency uses the full device
#   range and is never policed; the gain ceiling in constants.py guards against
#   an order-of-magnitude fat-finger only.
#
#   Author(s): <you>
##--------------------------------------------------------------------\

from __future__ import annotations

import os
from typing import Any

from .. import constants as C
from .._host import HostOps
from ..exceptions import HackRFEnvironmentError


class TransmitMixin(HostOps):
    def transmit(self, freq: float, sample_rate: float, source: str, *,
                 txvga: int = 20, amp: bool = False, bias_tee: bool = False,
                 baseband_bw: float | None = None, repeat: bool = False,
                 num_samples: int | None = None, duration: float | None = None,
                 max_duration: float | None = None,
                 print_cmd: bool = False) -> Any:
        # source: path to an int8 I/Q file to transmit.
        # max_duration: hard ceiling (seconds) enforced even for open-ended
        #   repeat transmits. A transmitter that runs until .stop() is a
        #   regulatory + hardware risk if the controlling script dies; this
        #   gives every transmit an optional dead-man bound.
        self.require_mode(C.MODE_TX)          # the gate
        # Fail fast on a bad path BEFORE spawning hackrf_transfer, so a typo'd
        # source raises a clean, catchable error instead of a generic non-zero
        # exit from the tool. Skipped for print_cmd (a dry run is a pure command
        # preview and may reference a file you haven't generated yet).
        if not print_cmd and not os.path.isfile(source):
            raise HackRFEnvironmentError(f"transmit source not found: {source!r}")
        freq, sample_rate, txvga, amp = self.validate_tx(
            freq, sample_rate, txvga, amp)
        bw = self._auto_baseband(sample_rate, baseband_bw)
        self._record_params(freq=freq, sample_rate=sample_rate, txvga=txvga,
                            amp=amp, baseband_bw=bw, mode="tx")
        self.print_message(f"[*] mode: {self.mode}  (TX)")

        argv = ["transfer", "-t", source,
                "-f", int(freq), "-s", int(sample_rate),
                "-x", txvga, "-a", 1 if amp else 0, "-b", int(bw)]
        if bias_tee:
            argv += ["-p", 1]
        if repeat:
            argv += ["-R"]
        if num_samples is not None:
            argv += ["-n", int(num_samples)]

        # An explicit duration, or a max_duration ceiling on an otherwise
        # open-ended repeat, both run as TIMED so the child is reaped on time.
        effective_timed = duration if duration is not None else (
            max_duration if repeat and num_samples is None else None)
        if effective_timed is not None:
            return self._run(argv, mode="timed", duration=effective_timed,
                             print_cmd=print_cmd)
        if num_samples is not None or not repeat:
            # bounded by file length or -n; runs to completion
            return self._run(argv, mode="blocking", print_cmd=print_cmd)
        # repeat with no bound and no max_duration -> open-ended handle
        if print_cmd:
            self._run(argv, mode="blocking", print_cmd=True)
            return None
        self.warn("open-ended repeat transmit with no max_duration; "
                  "caller must .stop() the returned handle.")
        return self._run(argv, mode="handle", kind="tx")

    # ---- aliases ----
    def tx(self, *a: Any, **k: Any) -> Any:
        return self.transmit(*a, **k)

    def transmit_file(self, freq: float, sample_rate: float, source: str,
                      **k: Any) -> Any:
        return self.transmit(freq, sample_rate, source, **k)

    def transmit_cw(self, freq: float, sample_rate: float, *,
                    amplitude: int = 127, txvga: int = 20, amp: bool = False,
                    bias_tee: bool = False, baseband_bw: float | None = None,
                    duration: float | None = None,
                    max_duration: float | None = None,
                    print_cmd: bool = False) -> Any:
        # Constant-wave / signal-source test mode: hackrf_transfer -c <amp>.
        # Transmits a fixed signal at `amplitude` (0-127) instead of a file.
        # TX-gated like any transmit. Useful for antenna/range testing. Open-
        # ended unless duration/max_duration bounds it (the dead-man applies).
        self.require_mode(C.MODE_TX)
        freq, sample_rate, txvga, amp = self.validate_tx(
            freq, sample_rate, txvga, amp)
        bw = self._auto_baseband(sample_rate, baseband_bw)
        amplitude = max(0, min(int(amplitude), 127))
        self._record_params(freq=freq, sample_rate=sample_rate, txvga=txvga,
                            amp=amp, baseband_bw=bw, mode="tx", cw=amplitude)
        self.print_message(f"[*] mode: {self.mode}  (TX, CW source)")

        argv = ["transfer", "-c", amplitude,
                "-f", int(freq), "-s", int(sample_rate),
                "-x", txvga, "-a", 1 if amp else 0, "-b", int(bw)]
        if bias_tee:
            argv += ["-p", 1]

        timed = duration if duration is not None else max_duration
        if timed is not None:
            return self._run(argv, mode="timed", duration=timed,
                             print_cmd=print_cmd)
        if print_cmd:
            self._run(argv, mode="blocking", print_cmd=True)
            return None
        self.warn("open-ended CW transmit with no duration/max_duration; "
                  "caller must .stop() the returned handle.")
        return self._run(argv, mode="handle", kind="tx")
