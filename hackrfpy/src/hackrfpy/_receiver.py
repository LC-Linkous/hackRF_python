#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'src/hackrfpy/_receiver.py'
#   Persistent fixed-frequency receiver. Opens ONE long-lived
#   hackrf_transfer stream and serves decoded complex64 segments on demand,
#   so you don't pay the ~1-2 s process spin-up for every capture. This is
#   the data-collection answer to the per-capture startup cost measured by
#   examples/benchmark.py.
#
#   ARCHITECTURAL HONESTY: hackrf_transfer cannot retune mid-stream, so this
#   is FIXED-FREQUENCY by design. It is "start once, drain over time at one
#   frequency", NOT "one process I can retune". For multiple frequencies use
#   scan_frequencies (separate captures) or monitor_frequencies (sweep). True
#   gapless retuning needs the C library.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\



from __future__ import annotations

from types import TracebackType
from typing import Any, Callable, Generator, Iterator, Literal

import numpy as np

from ._host import HostOps
from .exceptions import HackRFDeviceError


class PersistentReceiver:
    # A long-lived RX stream at one frequency. Created via
    # HackRF.open_receiver(...); use as a context manager so the child is
    # always reaped:
    #
    #   with h.open_receiver(100e6, 8e6) as rx:
    #       a = rx.read(1_000_000)        # exactly 1e6 complex64 samples
    #       b = rx.read(1_000_000)        # again, NO new process spin-up
    #       for block in rx.blocks():     # or iterate raw decoded blocks
    #           ...
    #
    # The underlying hackrf_transfer is launched once on __enter__ (or first
    # use) and runs continuously until close()/__exit__.
    def __init__(self, hackrf: HostOps, freq: float, sample_rate: float, *,
                 lna: int = 16, vga: int = 20, amp: bool = False,
                 baseband_bw: float | None = None,
                 read_samples: int = 131072) -> None:
        self._h = hackrf
        self.freq = freq
        self.sample_rate = sample_rate
        self.lna = lna
        self.vga = vga
        self.amp = amp
        self.baseband_bw = baseband_bw
        self.read_samples = read_samples
        self._gen: Generator[bytes, None, None] | None = None   # raw-bytes stream
        self._carry = b""           # leftover bytes between reads (odd splits)
        self._closed = False
        self.total_samples = 0      # cumulative samples served

    # ---- lifecycle ---------------------------------------------------------
    def _ensure_open(self) -> Generator[bytes, None, None]:
        if self._closed:
            raise HackRFDeviceError(
                "receiver is closed; construct a new PersistentReceiver "
                "(via HackRF.open_receiver) to start a new stream.")
        if self._gen is not None:
            return self._gen
        h = self._h
        # validate + snap exactly like capture() does, and record params so
        # relative_power_db() etc. can read the gains back. validate_rx returns
        # (freq, sample_rate, lna, vga); amp passes through untouched on RX.
        freq, sample_rate, lna, vga = h.validate_rx(
            self.freq, self.sample_rate, self.lna, self.vga)
        amp = bool(self.amp)
        bw = h._auto_baseband(sample_rate, self.baseband_bw)
        self.freq, self.sample_rate = freq, sample_rate
        self.lna, self.vga, self.amp = lna, vga, amp
        h._record_params(freq=freq, sample_rate=sample_rate, lna=lna, vga=vga,
                         amp=amp, baseband_bw=bw, mode="rx")
        argv = ["transfer", "-r", "-", "-f", int(freq), "-s", int(sample_rate),
                "-l", lna, "-g", vga, "-a", 1 if amp else 0, "-b", int(bw)]
        # one long-lived stream; large read granularity for sustained rate
        self._gen = h._run(argv, mode="stream", read_samples=self.read_samples)
        # register on the live backstop so a dying script reaps it
        from .core import _LIVE
        try:
            _LIVE.add(self)
        except Exception:
            pass
        return self._gen

    def __enter__(self) -> PersistentReceiver:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        self.close()
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._gen is not None:
            try:
                self._gen.close()       # interrupts + reaps the child
            except Exception:
                pass
            self._gen = None
        try:
            from .core import _LIVE
            _LIVE.discard(self)
        except Exception:
            pass

    def stop(self) -> None:
        # alias so PersistentReceiver works with the _LIVE backstop, which
        # calls .stop() on whatever it holds
        self.close()

    def is_alive(self) -> bool:
        # Required by the _LIVE atexit backstop, which does `if h.is_alive():
        # h.stop()`. This was MISSING: the resulting AttributeError was swallowed
        # by the backstop's bare `except Exception`, so an orphaned persistent
        # receiver was silently never reaped on interpreter shutdown.
        return self._gen is not None and not self._closed

    # ---- data access -------------------------------------------------------
    def read(self, n_samples: int) -> np.ndarray:
        # Return EXACTLY n_samples complex64 (or fewer if the stream ends).
        # Pulls and decodes raw bytes from the persistent stream until it has
        # enough; carries any partial trailing pair between calls. No new
        # process is launched -- this is the whole point.
        gen = self._ensure_open()
        need_bytes = int(n_samples) * 2          # 2 int8 per complex sample
        buf = self._carry
        for chunk in gen:
            buf += chunk
            if len(buf) >= need_bytes:
                break
        take = buf[:need_bytes]
        self._carry = buf[need_bytes:]
        # decode, dropping any odd trailing byte (shouldn't happen since we
        # cut on an even boundary, but be safe)
        iq = self._h.decode_iq(take)
        self.total_samples += len(iq)
        return iq

    def blocks(self) -> Iterator[np.ndarray]:
        # Yield decoded complex64 blocks as they arrive (raw cadence), until
        # the stream ends or the caller stops iterating. Good for a continuous
        # consumer that doesn't need a fixed sample count per read.
        gen = self._ensure_open()
        if self._carry:
            lead = self._h.decode_iq(self._carry)
            self._carry = b""
            if len(lead):
                self.total_samples += len(lead)
                yield lead
        for chunk in gen:
            iq = self._h.decode_iq(chunk)
            self.total_samples += len(iq)
            yield iq

    def callback(self, on_block: Callable[[np.ndarray, int], Any], *,
                 max_samples: int | None = None) -> int:
        # Inverted loop over blocks(): call on_block(iq, total) per block;
        # stop on False, on max_samples, or stream end.
        for iq in self.blocks():
            cont = on_block(iq, self.total_samples)
            if cont is False:
                break
            if max_samples is not None and self.total_samples >= max_samples:
                break
        return self.total_samples
