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

from .. import constants as C


class TransmitMixin:
    def transmit(self, freq, sample_rate, source, *, txvga=20, amp=False,
                 bias_tee=False, baseband_bw=None, repeat=False,
                 num_samples=None, duration=None, max_duration=None,
                 print_cmd=False):
        # source: path to an int8 I/Q file to transmit.
        # max_duration: hard ceiling (seconds) enforced even for open-ended
        #   repeat transmits. A transmitter that runs until .stop() is a
        #   regulatory + hardware risk if the controlling script dies; this
        #   gives every transmit an optional dead-man bound.
        self.require_mode(C.MODE_TX)          # the gate
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
    def tx(self, *a, **k):
        return self.transmit(*a, **k)

    def transmit_file(self, freq, sample_rate, source, **k):
        return self.transmit(freq, sample_rate, source, **k)
