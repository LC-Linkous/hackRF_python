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
            #
            # NOTE on ordering: real hackrf_sweep does NOT emit frequency
            # segments low-to-high -- it interleaves them (observed: 88, 98,
            # 93, 103 MHz for an 88:108 sweep). All rows of ONE sweep share a
            # timestamp. Consumers that need a contiguous spectrum must group
            # by timestamp and sort segments by hz_low; do NOT assume the rows
            # arrive in frequency order.
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

    def monitor_frequencies(self, freqs_hz, *, span_hz=2_000_000, duration=None,
                            on_update=None, lna=16, vga=20, amp=False):
        # Watch POWER over time at several frequencies, backed by hackrf_sweep's
        # fast internal hardware retuning. This is DELIBERATELY a different
        # method from scan_frequencies():
        #   - scan_frequencies() returns IQ SAMPLES (complex64) per frequency,
        #     via separate hackrf_transfer captures (re-open gap between each).
        #   - monitor_frequencies() returns POWER (dB) per frequency over time,
        #     via one continuous hackrf_sweep. No IQ -- spectrum bins only.
        # Use this for "is there activity on these channels?" monitoring; use
        # scan_frequencies for "give me the samples at each frequency."
        #
        # Yields dicts: {freq_hz: power_db, ...} once per sweep pass, mapping
        # each requested frequency to the dB of the sweep bin covering it.
        # Runs until `duration` seconds elapse, on_update returns False, or the
        # caller stops iterating (the underlying sweep is reaped on exit).
        import time as _time
        lo = min(freqs_hz) - span_hz
        hi = max(freqs_hz) + span_hz
        t0 = _time.time()

        def _nearest_power(rows_by_low, f):
            # find the sweep segment whose [hz_low, hz_high) covers f, return
            # the mean dB of that segment's bins (a simple power proxy)
            for low in sorted(rows_by_low):
                r = rows_by_low[low]
                if r["hz_low"] <= f < r["hz_high"]:
                    db = r["db"]
                    return sum(db) / len(db) if db else float("-inf")
            return None

        from .._stream_ctx import StreamCtx
        results = []
        stopped = False
        with StreamCtx(self.sweep(lo, hi, lna=lna, vga=vga, amp=amp)) as gen:
            rows_by_low = {}
            last_time = None
            for row in gen:
                if last_time is not None and row["time"] != last_time and rows_by_low:
                    update = {f: _nearest_power(rows_by_low, f) for f in freqs_hz}
                    if on_update is not None:
                        if on_update(update) is False:
                            stopped = True
                            break
                    else:
                        results.append(update)
                    rows_by_low = {}
                    if duration is not None and _time.time() - t0 >= duration:
                        break
                rows_by_low[row["hz_low"]] = row
                last_time = row["time"]
            # flush the final buffered pass (stream ended before its timestamp
            # rolled over) -- unless we were explicitly stopped by on_update
            if rows_by_low and not stopped:
                update = {f: _nearest_power(rows_by_low, f) for f in freqs_hz}
                if on_update is not None:
                    on_update(update)
                else:
                    results.append(update)
        return None if on_update is not None else results

    def sweep_to_file(self, f_min_hz, f_max_hz, out, *, binary=False,
                      inverse_fft=False, bin_width=None, lna=16, vga=20,
                      amp=False, one_shot=False, num_sweeps=None,
                      print_cmd=False):
        # Write sweep output straight to a file instead of yielding parsed
        # rows. This is the home for hackrf_sweep's binary-output flags, which
        # don't fit the text-CSV generator:
        #   binary=True       -> -B  raw binary FFT-bin output
        #   inverse_fft=True  -> -I  binary inverse-FFT output (implies binary)
        # With neither, this writes the normal CSV text to the file via -r.
        # Returns the output path. The binary formats are NOT parsed by this
        # library (parse_sweep_line is text-only); you own the format on read.
        f_min_hz = self._check_hard_range("f_min", f_min_hz,
                                          C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
        f_max_hz = self._check_hard_range("f_max", f_max_hz,
                                          C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
        if f_min_hz >= f_max_hz:
            from ..exceptions import HackRFValueError
            raise HackRFValueError("f_min must be < f_max")
        lna = self._snap_gain("lna_gain", lna, C.LNA_GAIN)
        vga = self._snap_gain("vga_gain", vga, C.VGA_GAIN)
        lo = int(f_min_hz // 1_000_000)
        hi = int(f_max_hz // 1_000_000)
        argv = ["sweep", "-f", f"{lo}:{hi}", "-l", lna, "-g", vga,
                "-a", 1 if amp else 0, "-r", out]
        if bin_width is not None:
            argv += ["-w", int(bin_width)]
        if one_shot:
            argv += ["-1"]
        if num_sweeps is not None:
            argv += ["-N", int(num_sweeps)]
        if inverse_fft:
            argv += ["-I"]          # binary inverse FFT (binary output mode)
        elif binary:
            argv += ["-B"]          # raw binary output
        res = self._run(argv, mode="blocking", print_cmd=print_cmd)
        return None if print_cmd else out

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
