#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/_commands/sweep.py'
#
#   SweepMixin: spectrum sweep via hackrf_sweep. hackrf_sweep emits CSV to
#   stdout continuously until stopped, so this is the streaming/generator case
#   -- the analog of a continuous-acquisition loop. Each CSV row is:
#     date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, ...
#   We yield parsed rows so the caller can plot/store/decode as they arrive.
#
#   Author(s): <you>
##--------------------------------------------------------------------\

from .. import constants as C


class SweepMixin:
    def sweep(self, f_min_hz, f_max_hz, *, bin_width=None, lna=16, vga=20,
              amp=False, one_shot=False, num_sweeps=None, print_cmd=False):
        # GENERATOR yielding parsed rows (dicts). Validate the band edges with
        # the same hard-range logic, snap gains. hackrf_sweep takes the range
        # in MHz as f_min:f_max.
        f_min_hz = self._check_hard_range("f_min", f_min_hz,
                                          C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
        f_max_hz = self._check_hard_range("f_max", f_max_hz,
                                          C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
        if f_min_hz >= f_max_hz:
            from ..exceptions import HackRFValueError
            raise HackRFValueError("f_min must be < f_max")
        lna = self._snap_gain("lna_gain", lna, C.LNA_GAIN)
        vga = self._snap_gain("vga_gain", vga, C.VGA_GAIN)
        self._record_params(f_min=f_min_hz, f_max=f_max_hz, lna=lna, vga=vga,
                            amp=amp, bin_width=bin_width, mode="rx")
        self.print_message(f"[*] mode: {self.mode}")

        lo = int(f_min_hz // 1_000_000)
        hi = int(f_max_hz // 1_000_000)
        # hackrf_sweep takes integer MHz edges, so sub-MHz precision is lost.
        # Warn rather than silently shift the band the user asked for.
        if f_min_hz % 1_000_000 or f_max_hz % 1_000_000:
            self.warn(
                f"sweep edges snapped to MHz: "
                f"{f_min_hz/1e6:g}:{f_max_hz/1e6:g} -> {lo}:{hi} MHz "
                f"(hackrf_sweep takes integer MHz)")
        argv = ["sweep", "-f", f"{lo}:{hi}", "-l", lna, "-g", vga,
                "-a", 1 if amp else 0]
        if bin_width is not None:
            argv += ["-w", int(bin_width)]
        if one_shot:
            argv += ["-1"]
        if num_sweeps is not None:
            argv += ["-N", int(num_sweeps)]

        if print_cmd:
            self._run(argv, mode="blocking", print_cmd=True)
            return

        def _gen():
            # Explicitly close the inner stream generator on the way out.
            # Relying on GC to do it is not deterministic, and an unclosed
            # inner generator leaves hackrf_sweep running ORPHANED after the
            # caller breaks out of the loop.
            inner = self._run(argv, mode="stream", text=True)
            try:
                for line in inner:
                    row = self.parse_sweep_line(line)
                    if row is not None:
                        yield row
            finally:
                inner.close()
        return _gen()

    def sweep_collect(self, f_min_hz, f_max_hz, num_sweeps=1, **k):
        # Convenience: collect a bounded number of sweeps into a list.
        k.pop("num_sweeps", None)
        return list(self.sweep(f_min_hz, f_max_hz, num_sweeps=num_sweeps, **k))

    def sweep_stream(self, f_min_hz, f_max_hz, **k):
        # Context manager around the sweep generator so the underlying
        # hackrf_sweep is ALWAYS reaped on exit -- including KeyboardInterrupt
        # out of a live consumer loop (e.g. a waterfall). Without this, a
        # caller that breaks out or Ctrl-C's relies on GC to close the
        # generator, which can orphan the child:
        #     with h.sweep_stream(88e6, 108e6) as rows:
        #         for row in rows: ...
        from .._stream_ctx import StreamCtx
        gen = self.sweep(f_min_hz, f_max_hz, **k)
        return StreamCtx(gen)

    @staticmethod
    def parse_sweep_line(line):
        # Returns {date,time,hz_low,hz_high,bin_width,num_samples,db:[...]} or
        # None for blank/garbled lines.
        line = line.strip()
        if not line:
            return None
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            return None
        try:
            return {
                "date": parts[0],
                "time": parts[1],
                "hz_low": int(parts[2]),
                "hz_high": int(parts[3]),
                "bin_width": float(parts[4]),
                "num_samples": int(parts[5]),
                "db": [float(x) for x in parts[6:]],
            }
        except ValueError:
            return None
