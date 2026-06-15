#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/_commands/capture.py'
#
#   CaptureMixin: receive via hackrf_transfer -r. Exercises all consumption
#   modes and the IQ-path choice:
#       - num_samples  -> bounded (default), mode="blocking"
#       - duration     -> timed, mode="timed"
#       - neither      -> open-ended handle, mode="handle" (.stop() to end)
#       - to_stdout    -> '-r -' streamed + decoded in-Python (live path)
#       - segment_secs -> rolling files (capture lifecycle the CLI binary lacks)
#
#   Mixin only; assumes _run, validate_rx, estimate_capture, decode_iq,
#   _auto_baseband, require_mode, print_message on the host class.
#
#   Author(s): <you>
##--------------------------------------------------------------------\

import os

from .. import constants as C
from ..sigmf import write_sigmf_meta


class CaptureMixin:
    def capture(self, freq, sample_rate, *, out="capture.iq",
                num_samples=None, duration=None,
                lna=16, vga=20, amp=False, bias_tee=False,
                baseband_bw=None, to_stdout=False, sigmf=True,
                segment_secs=None, print_cmd=False):
        self.require_mode(C.MODE_RX)
        freq, sample_rate, lna, vga = self.validate_rx(freq, sample_rate, lna, vga)
        bw = self._auto_baseband(sample_rate, baseband_bw)
        self._record_params(freq=freq, sample_rate=sample_rate, lna=lna,
                            vga=vga, amp=amp, baseband_bw=bw, mode="rx")
        self.print_message(f"[*] mode: {self.mode}")

        # segmented capture is its own lifecycle path
        if segment_secs:
            return self._capture_segmented(
                freq, sample_rate, out, segment_secs, lna, vga, amp,
                bias_tee, bw, sigmf, print_cmd)

        target = "-" if to_stdout else out
        argv = self._rx_argv(freq, sample_rate, target, lna, vga, amp,
                             bias_tee, bw, num_samples)

        if to_stdout:
            if print_cmd:
                self._run(argv, mode="blocking", print_cmd=True)
                return None
            # live path: stream raw IQ chunks, decode to complex64 as we go.
            # An odd-length chunk would split an I/Q pair; dropping the byte
            # would swap I/Q for everything after, so carry it forward.
            # The inner stream generator is closed EXPLICITLY on the way out;
            # leaving it to GC can orphan a receiving hackrf_transfer after
            # the caller breaks out of the loop.
            def _gen():
                tail = b""
                inner = self._run(argv, mode="stream")
                try:
                    for chunk in inner:
                        buf = tail + chunk
                        cut = len(buf) - (len(buf) % 2)
                        buf, tail = buf[:cut], buf[cut:]
                        if buf:
                            yield self.decode_iq(buf)
                finally:
                    inner.close()
            return _gen()

        # file path: estimate + guard disk before committing
        if not print_cmd:
            est = self.estimate_capture(sample_rate, num_samples, duration,
                                        os.path.dirname(out) or ".")
            self.print_message(
                f"[*] ~{(est['total_bytes'] or 0)/1e6:.1f} MB, "
                f"{est['bytes_per_sec']/1e6:.1f} MB/s")

        if duration is not None:
            res = self._run(argv, mode="timed", duration=duration,
                            print_cmd=print_cmd)
        elif num_samples is not None:
            res = self._run(argv, mode="blocking", print_cmd=print_cmd)
        else:
            # open-ended: hand back a controller; caller .stop()s it
            if print_cmd:
                self._run(argv, mode="blocking", print_cmd=True)
                return None
            return self._run(argv, mode="handle")

        if sigmf and not print_cmd:
            write_sigmf_meta(out, freq, sample_rate, lna=lna, vga=vga,
                             amp=amp, datatype="ci8")
        return res

    # ---- aliases ----
    def rx(self, *a, **k):
        return self.capture(*a, **k)

    def capture_samples(self, freq, sample_rate, num_samples, **k):
        return self.capture(freq, sample_rate, num_samples=num_samples, **k)

    def capture_seconds(self, freq, sample_rate, duration, **k):
        return self.capture(freq, sample_rate, duration=duration, **k)

    # ---- in-memory + context-managed entry points ----
    def capture_array(self, freq, sample_rate, num_samples, *,
                      return_params=False, **k):
        # Scripting entry point: return EXACTLY num_samples complex64 samples
        # in RAM, no file. Built on the stdout-stream path so it shares the
        # odd-byte carry + clean-reap logic. The stream is closed as soon as
        # we have enough, which interrupts hackrf_transfer promptly.
        #
        # return_params=True -> (iq, params) where params is the snapped
        # last_params dict; default False keeps the bare-ndarray return so the
        # common case is unchanged.
        import numpy as np
        if num_samples is None or num_samples <= 0:
            from ..exceptions import HackRFValueError
            raise HackRFValueError("capture_array needs a positive num_samples")
        k.pop("to_stdout", None)
        k.pop("out", None)
        gen = self.capture(freq, sample_rate, to_stdout=True, **k)
        if gen is None:                       # print_cmd dry run
            return None
        blocks, have = [], 0
        try:
            for block in gen:
                blocks.append(block)
                have += len(block)
                if have >= num_samples:
                    break
        finally:
            gen.close()                       # reap the child deterministically
        iq = (np.empty(0, dtype=np.complex64) if not blocks
              else np.concatenate(blocks)[:num_samples])
        if return_params:
            return iq, self.last_params
        return iq

    def capture_stream(self, freq, sample_rate, **k):
        # Context manager wrapping the live stdout stream so the receiving
        # hackrf_transfer is ALWAYS reaped on exit, even on exception:
        #     with h.capture_stream(433.92e6, 8e6) as blocks:
        #         for iq in blocks: ...
        from .._stream_ctx import StreamCtx
        k.pop("to_stdout", None)
        gen = self.capture(freq, sample_rate, to_stdout=True, **k)
        return StreamCtx(gen)

    # ---- internals ----
    def _rx_argv(self, freq, sample_rate, target, lna, vga, amp, bias_tee,
                 bw, num_samples):
        argv = ["transfer", "-r", target,
                "-f", int(freq), "-s", int(sample_rate),
                "-l", lna, "-g", vga,
                "-a", 1 if amp else 0,
                "-b", int(bw)]
        if bias_tee:
            argv += ["-p", 1]
        if num_samples is not None:
            argv += ["-n", int(num_samples)]
        return argv

    def _capture_segmented(self, freq, sample_rate, out, segment_secs, lna,
                           vga, amp, bias_tee, bw, sigmf, print_cmd):
        # Rolling files out_000.iq, out_001.iq, ... each `segment_secs` long.
        # Each segment is a bounded blocking capture, so files are whole.
        base, ext = os.path.splitext(out)
        ext = ext or ".iq"
        n_per = int(sample_rate * segment_secs)
        idx = 0
        results = []
        self.print_message(f"[*] segmented capture: {segment_secs}s per file")
        # Honest note: each segment is a fresh hackrf_transfer spawn (device
        # open + retune), so there is a short GAP (~hundreds of ms) of missing
        # samples between files. Segments are whole, not gapless.
        self.print_message("[!] note: segments are not gapless "
                           "(short re-open gap between files)")
        try:
            while True:
                # Disk guard PER SEGMENT: this is the run-indefinitely mode,
                # so check before each file rather than once up front. Raises
                # HackRFEnvironmentError when the next segment wouldn't fit
                # within the headroom, instead of filling the disk.
                if not print_cmd:
                    self.estimate_capture(sample_rate, num_samples=n_per,
                                          path=os.path.dirname(out) or ".")
                seg = f"{base}_{idx:03d}{ext}"
                argv = self._rx_argv(freq, sample_rate, seg, lna, vga, amp,
                                     bias_tee, bw, n_per)
                res = self._run(argv, mode="blocking", print_cmd=print_cmd)
                if sigmf and not print_cmd:
                    write_sigmf_meta(seg, freq, sample_rate, lna=lna, vga=vga,
                                     amp=amp, datatype="ci8")
                results.append(seg)
                idx += 1
                if print_cmd:
                    break  # one example command is enough for dry-run
        except KeyboardInterrupt:
            # reachable now that _run re-raises after stopping the child
            self.print_message("[*] segmented capture stopped by user")
        return results
