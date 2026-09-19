#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/core.py'
#
#   The HackRF device class. Composed from functional mixins under
#   ./_commands/ (info, capture, transmit, sweep, device). core.py holds the
#   shared state, the operating-mode machine, the validation layer, and the
#   ONE device-I/O choke point (_run) that every command funnels through.
#
#   Design mirrors a request/response wrapper, but the "response" from a
#   hackrf_* binary can be bounded (-n samples / sweep -1), timed, streamed
#   (sweep CSV), or open-ended (rx until stopped). So _run takes a `mode`
#   argument the way a serial wrapper takes a length flag.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

from __future__ import annotations

import atexit
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import weakref
from types import TracebackType
from typing import Any, Callable, Generator, Literal, Protocol

import numpy as np

from . import constants as C
from .exceptions import (
    HackRFValueError, HackRFModeError, HackRFDeviceError, HackRFEnvironmentError,
)
from ._commands.info import InfoMixin
from ._commands.capture import CaptureMixin
from ._commands.transmit import TransmitMixin
from ._commands.sweep import SweepMixin
from ._commands.device import DeviceMixin


# ---- diagnostics channel ----------------------------------------------------
# Library diagnostics go through logging, not print(), so a consumer can route,
# filter, or silence them. Two rules hold, and the tests pin both:
#
#   1. Diagnostics NEVER touch stdout. stdout is for DATA (sweep CSV, an
#      IQ stream on `-r -`) and for explicitly-requested output (a --print-cmd
#      preview). `hrf sweep -v > out.csv` must not put "[*] mode: rx" in the CSV.
#   2. Warnings fire regardless of verbose. A safety notice that only appears in
#      verbose mode is, in practice, a silent warning.
#
# No NullHandler is installed on purpose: with no handler anywhere, logging's
# last-resort handler emits WARNING+ to stderr on its own, which preserves the
# "warnings always show, zero setup required" contract for plain scripts.
log = logging.getLogger("hackrfpy")


def _ensure_console_logging() -> None:
    # The last-resort handler only emits WARNING and above, so verbose=True in a
    # plain script would otherwise print nothing at INFO. Attach a stderr handler
    # -- but ONLY if nobody has configured logging (neither our logger nor the
    # root). If the host application owns logging, stay out of its way and just
    # let records propagate.
    if log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))   # bare: no level prefix
    log.addHandler(handler)

# ---- platform interrupt plumbing -------------------------------------------
# hackrf_* tools flush + close cleanly on SIGINT. On Windows SIGINT can't be
# delivered to a child; the equivalent is CTRL_BREAK_EVENT, which requires
# the child to be in its own process group. Both paths are exercised by
# tests/test_interrupt_clean.py, which asserts the interrupt signal itself
# arrives (not the terminate() escalation) and that a handler's final flush
# survives into the drained output -- the no-truncated-capture contract.
if sys.platform == "win32":  # pragma: no cover
    _CREATION_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP
    _INTERRUPT_SIGNAL = signal.CTRL_BREAK_EVENT
else:
    _CREATION_FLAGS = 0
    _INTERRUPT_SIGNAL = signal.SIGINT


def _interrupt(proc: subprocess.Popen[Any]) -> None:
    proc.send_signal(_INTERRUPT_SIGNAL)


# ---- live-process registry + atexit backstop (Tier B) ----------------------
# Tier A is the context managers (_Process / _StreamCtx __exit__). Tier B is
# this: a registry of still-running handles that an atexit hook stops on
# interpreter shutdown, catching the "script raised/exited and forgot to
# .stop()" case that Tier A misses when the caller didn't use `with`.
#
# It does NOT survive `kill -9` / power loss (no handler runs); that needs an
# OS dead-man (Linux PR_SET_PDEATHSIG / Windows Job Object) which is platform-
# split work deferred to a later pass.
# ---- OS dead-man ------------------------------------------------------------
# The atexit backstop never runs on SIGKILL / TerminateProcess, so a hard-
# killed parent could orphan a live transmitter. The dead-man asks the OS
# itself to end the child when the parent dies, surviving any kind of parent
# death:
#   Linux   : the child sets PR_SET_PDEATHSIG to SIGINT in preexec, so the
#             kernel delivers the CLEAN interrupt (same flush path as stop())
#             the moment the parent dies. A getppid() check closes the fork-
#             window race where the parent died before prctl ran.
#   Windows : the child is assigned to a Job Object with KILL_ON_JOB_CLOSE.
#             The parent's death closes its handles; the OS then terminates
#             the whole job -- including the .bat -> python launcher tree.
#             The job handle lives on the _Process; dropping every reference
#             to a running protected handle therefore lets GC close the job
#             and reap the child, which is the dead-man philosophy applied
#             to a leaked handle.
#   macOS   : no equivalent primitive; the atexit backstop remains the only
#             net there.
# Scope: handle-mode spawns, gated exactly like the atexit registry below
# (TX always, RX unless backstop_rx=False). Exercised by
# tests/test_deadman.py, including a real parent hard-kill.
#
# TX handles are ALWAYS registered (an orphaned transmitter is a regulatory /
# interference problem). RX handles are registered by default but can opt out
# (an orphaned receiver only wastes disk, and fire-and-forget is occasionally
# wanted).
if sys.platform == "win32":
    def _deadman_preexec() -> Any:
        return None                      # Windows path uses the Job Object

    def _deadman_attach(proc: subprocess.Popen[Any]) -> Any:
        import ctypes
        from ctypes import wintypes

        class _BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimits),
                        ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        _KILL_ON_JOB_CLOSE = 0x2000
        _EXTENDED_LIMIT_CLASS = 9
        try:
            k32 = ctypes.windll.kernel32
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return None
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(
                    job, _EXTENDED_LIMIT_CLASS, ctypes.byref(info),
                    ctypes.sizeof(info)):
                k32.CloseHandle(job)
                return None
            if not k32.AssignProcessToJobObject(
                    job, wintypes.HANDLE(int(proc._handle))):  # type: ignore[attr-defined]
                k32.CloseHandle(job)
                return None
            return job
        except OSError:
            return None                  # best-effort: never block a spawn
else:
    def _deadman_preexec() -> Any:
        if not sys.platform.startswith("linux"):
            return None                  # macOS: no pdeathsig primitive
        try:
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
        except OSError:
            return None
        _PR_SET_PDEATHSIG = 1

        def _preexec() -> None:
            libc.prctl(_PR_SET_PDEATHSIG, signal.SIGINT, 0, 0, 0)
            if os.getppid() == 1:        # parent died in the fork window
                os.kill(os.getpid(), signal.SIGINT)
        return _preexec

    def _deadman_attach(proc: subprocess.Popen[Any]) -> Any:
        return None                      # POSIX path is the preexec


class _Stoppable(Protocol):
    # What the atexit backstop actually needs. _Process and PersistentReceiver
    # both satisfy it; a Protocol keeps _LIVE honest about holding both without
    # forcing an inheritance relationship between them.
    def is_alive(self) -> bool: ...
    def stop(self) -> Any: ...


_LIVE: weakref.WeakSet[_Stoppable] = weakref.WeakSet()


def _register_live(proc_handle: _Stoppable) -> None:
    _LIVE.add(proc_handle)


@atexit.register
def _stop_all_live() -> None:
    for h in list(_LIVE):
        try:
            if h.is_alive():
                h.stop()
        except Exception:
            pass  # best-effort on the way down; never raise from atexit


# Upper bound on retained drained output per stream (stdout / stderr). The
# handle-mode drain and the streaming-mode stderr tail both cap here so a
# long-lived RX/TX handle can't grow memory without bound (hackrf_transfer
# prints a stats line every second for the life of the process). We keep the
# most-recent bytes -- enough for an error tail -- and drop older ones.
_DRAIN_CAP = 64 * 1024


class _Process:
    # Thin controller returned by _run(mode="handle") for "run until I stop it"
    # workflows (the wait-for-user-stop consumption mode). Wraps a Popen and
    # exposes the liveness poll so callers can build their own error checking.
    #
    # stdout/stderr are drained continuously in daemon threads. hackrf_transfer
    # prints a stats line every second; with an undrained PIPE the 64 KB buffer
    # eventually fills and the child blocks on write, silently stalling a
    # long-running capture. Draining as we go removes that failure mode.
    def __init__(self, proc: subprocess.Popen[Any], owner: HackRF,
                 kind: str = "rx") -> None:
        self._proc = proc
        self._owner = owner
        self._job: Any = None            # Windows Job Object (OS dead-man)
        self._kind = kind          # "rx" | "tx" -- for atexit messaging
        self._stopped = False
        self._out_chunks: list[bytes] = []
        self._err_chunks: list[bytes] = []
        self._threads = []
        for stream, sink in ((proc.stdout, self._out_chunks),
                             (proc.stderr, self._err_chunks)):
            if stream is None:
                continue
            t = threading.Thread(target=self._drain, args=(stream, sink),
                                 daemon=True)
            t.start()
            self._threads.append(t)

    @staticmethod
    def _drain(stream: Any, sink: list[bytes]) -> None:
        try:
            # read1(): return as soon as ANY bytes are available (at most one
            # raw read), b"" only at EOF. Plain read(65536) on a BufferedReader
            # BLOCKS until 64 KB accumulate, so a child's small writes (e.g.
            # hackrf_transfer's ~60-byte-per-second stats lines) were invisible
            # to the parent until process exit -- output was only "live" if the
            # child flooded past the buffer size.
            for chunk in iter(lambda: stream.read1(65536), b""):
                sink.append(chunk)
                # Bound retained output: drop oldest chunks once over the cap,
                # always keeping at least the latest one. Prevents unbounded
                # growth on open-ended handles (see _DRAIN_CAP).
                while sum(len(c) for c in sink) > _DRAIN_CAP and len(sink) > 1:
                    sink.pop(0)
        except (OSError, ValueError):
            pass  # pipe closed under us during shutdown

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def stop(self, grace: float = 2.0) -> tuple[bytes, bytes, int | None]:
        # SIGINT lets hackrf_transfer flush + close the file cleanly so the
        # IQ stream isn't truncated mid-sample-pair.
        if self._proc.poll() is None:
            _interrupt(self._proc)
            try:
                self._proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                # Escalation ladder, each rung bounded and REAPED: a child
                # that ignores the interrupt gets terminate(); one that
                # survives that gets kill(). stop() previously fired
                # terminate() and returned without waiting, so a hardened
                # child could outlive stop() and result() reported
                # returncode None.
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
        self._stopped = True
        _LIVE.discard(self)         # no longer needs the atexit backstop
        return self.result()

    def wait(self) -> tuple[bytes, bytes, int | None]:
        self._proc.wait()
        _LIVE.discard(self)
        return self.result()

    def result(self) -> tuple[bytes, bytes, int | None]:
        for t in self._threads:
            t.join(timeout=2.0)
        out = b"".join(self._out_chunks)
        err = b"".join(self._err_chunks)
        return out, err, self._proc.returncode

    # ---- context manager (Tier A): guaranteed reap on block exit -----------
    def __enter__(self) -> _Process:
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        if not self._stopped:
            self.stop()
        return False  # never suppress the caller's exception


class HackRF(InfoMixin, CaptureMixin, TransmitMixin, SweepMixin, DeviceMixin):
    """Python controller for a HackRF One, driving the hackrf-tools binaries.

    The constructor touches no hardware; use from_device() for a fail-fast
    probed handle. Receive works immediately; transmitting requires the
    deliberate set_mode('tx') arming step. NOT thread-safe: one instance
    per thread (see the class comment below and the README).
    """
    # THREAD SAFETY: a HackRF instance is NOT safe to share across threads.
    # Methods mutate per-instance state without locks -- last_params readback,
    # the persisted operating-mode state, verbose/logging wiring -- and the
    # process handles it returns own per-child drain threads whose lists are
    # appended from those threads but read from the caller's. One instance
    # per thread (they are cheap: the constructor touches nothing), or confine
    # all hackrfpy calls to a single worker thread. This limitation predates
    # 1.0 and is recorded here rather than "fixed" because the right fix
    # (locking) would serialize the interesting operations anyway.
    def __init__(self, tools_dir: str | None = None, verbose: bool = False,
                 serial: str | None = None) -> None:
        # ---- feedback ----
        # via set_verbose so that HackRF(verbose=True) wires up the console
        # handler exactly like an explicit set_verbose(True) call would.
        self.verboseEnabled = False
        self.set_verbose(verbose)

        # ---- device selection (multi-board setups) ----
        # When set, `-d <serial>` is injected into every tool that supports
        # it (constants.TOOLS_WITH_SERIAL). None = let the tools pick the
        # sole attached board, exactly as before.
        self.serial = serial

        # ---- operating mode (the TX gate) ----
        # Default RX. transmit() refuses unless mode == MODE_TX. Switching to
        # TX is the deliberate confirmation; it emits a one-time safety banner.
        self._mode = C.DEFAULT_MODE

        # ---- envelope override ----
        # When True, hard-range violations warn instead of raising. CLI maps
        # this to --force. Does NOT affect TX frequency (never policed) or the
        # snap-and-notify params (always snapped).
        self.allow_out_of_spec = False

        # ---- binary resolution ----
        # tools_dir lets Windows installs point at the hackrf-tools folder when
        # they aren't on PATH.
        self.tools_dir = tools_dir

        # ---- handle-mode safety backstop (Tier B) ----
        # TX handles are ALWAYS atexit-stopped. RX handles are too by default;
        # set backstop_rx=False for deliberate fire-and-forget receivers.
        self.backstop_rx = True

        # ---- parameter readback ----
        # Populated by every validated operation with the ACTUAL values used
        # after snapping / auto-derivation, so a script can see what really
        # happened (e.g. a requested lna=30 that snapped to 24). None until the
        # first rx/tx/sweep call on this instance.
        self.last_params: dict[str, Any] | None = None
        self._probed: dict[str, Any] | None = None   # set by from_device()

    def _record_params(self, **params: Any) -> dict[str, Any]:
        # Single place the mixins call to publish post-snap values. Returns the
        # dict so callers can also use it inline if they want.
        self.last_params = params
        return params

    # =================================================================
    # Feedback
    # =================================================================
    def set_verbose(self, verbose: bool = True) -> None:
        """Enable or disable verbose progress output (INFO-level logging)."""
        self.verboseEnabled = verbose
        if verbose:
            # Make INFO actually visible in a plain script (see
            # _ensure_console_logging). No-op if the host app configured logging.
            _ensure_console_logging()
            if log.getEffectiveLevel() > logging.INFO:
                log.setLevel(logging.INFO)

    def get_verbose(self) -> bool:
        """Return whether verbose progress output is enabled."""
        return self.verboseEnabled

    def print_message(self, msg: str) -> None:
        """Emit a progress message (INFO, stderr) if verbose is enabled."""
        # Progress / status chatter. INFO, and gated on verbose so the level and
        # the flag agree. Goes to stderr (never stdout) -- see the module note.
        if self.verboseEnabled:
            log.info(msg)

    def warn(self, msg: str) -> None:
        """Emit a warning (WARNING, stderr) regardless of the verbose flag.

        Used for safety and degraded-results notices that must never be silent.
        """
        # Safety / correctness warnings the user must see REGARDLESS of verbose.
        # (A degraded-results or out-of-spec notice that only prints in verbose
        # mode is, in practice, a silent warning.) WARNING level, so it survives
        # with no logging setup at all via logging's last-resort stderr handler.
        # The "[!] " marker lives in the message so it shows under any formatter.
        log.warning(f"[!] {msg}")

    # =================================================================
    # Operating mode machine
    # =================================================================
    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        self.set_mode(value)

    def get_mode(self) -> str:
        """Return the current operating mode: "rx" or "tx"."""
        return self._mode

    def set_mode(self, value: str) -> str:
        """Switch operating mode ("rx" or "tx") and persist it.

        Switching to TX prints the one-time safety banner. Transmit methods
        refuse unless the instance is in TX mode; this switch is the deliberate
        arming step.
        """
        value = str(value).lower()
        if value not in C.MODES:
            raise HackRFValueError(
                f"mode must be one of {C.MODES}, got {value!r}")
        if value == C.MODE_TX and self._mode != C.MODE_TX:
            # the one important warn, attached to the deliberate switch
            self._tx_safety_banner()
        self._mode = value
        self.print_message(f"[*] mode -> {value}")
        return self._mode

    def restore_mode(self, value: str) -> str:
        """Rehydrate a previously persisted mode without the switch ceremony.

        No banner, no chatter: for the CLI restoring state between invocations
        (the banner already fired at the original mode switch).
        """
        # Rehydrate previously-persisted mode WITHOUT the switch ceremony
        # (no banner, no chatter). For the CLI restoring state between
        # invocations; the banner already fired at the original `mode tx`.
        value = str(value).lower()
        if value not in C.MODES:
            raise HackRFValueError(
                f"mode must be one of {C.MODES}, got {value!r}")
        self._mode = value
        return self._mode

    def require_mode(self, needed: str) -> None:
        """Raise HackRFModeError unless the instance is in the given mode."""
        if self._mode != needed:
            raise HackRFModeError(
                f"operation requires '{needed}' mode but device is in "
                f"'{self._mode}' mode. Switch first (set_mode('{needed}') or "
                f"`hrf mode {needed}`).")

    def _tx_safety_banner(self) -> None:
        # Always printed (not gated on verbose): switching to TX is a moment
        # that deserves a clear, one-time notice regardless of verbosity.
        print("=" * 64)
        print(" TX MODE ARMED -- the device can now transmit.")
        print(" Transmitting is regulated. You are responsible for operating")
        print(" within your license privileges, power limits, and local law.")
        print(f" Gain is capped at {C.TX_VGA_CEILING_DB} dB by constants.py.")
        print("=" * 64)

    # =================================================================
    # Validation layer
    # =================================================================
    def _check_hard_range(self, name: str, value: float, lo: float, hi: float,
                          warn_below: float | None = None) -> float:
        # Reject-by-default outside [lo, hi]; --force downgrades to a warning.
        # warn_below: a soft floor that only ever warns (e.g. low sample rate).
        value = float(value)
        if value < lo or value > hi:
            msg = (f"{name}={value:g} is outside the device range "
                   f"[{lo:g}, {hi:g}]")
            if self.allow_out_of_spec:
                self.warn("forced out-of-spec: " + msg)
            else:
                raise HackRFValueError(
                    msg + " (pass --force / allow_out_of_spec=True to override)")
        elif warn_below is not None and value < warn_below:
            self.warn(
                f"{name}={value:g} is below the recommended "
                f"{warn_below:g}; results may be degraded.")
        return value

    def _snap_gain(self, name: str, value: int,
                   table: tuple[int, int, int]) -> int:
        # Round DOWN to the device's real step and notify. This is the honest
        # "what you'll actually get" value, matching the silicon. A request
        # that snaps to a DIFFERENT value is surfaced via warn() (not just
        # verbose) because e.g. lna=7 -> 0 is a silent 7 dB loss otherwise.
        lo, hi, step = table
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise HackRFValueError(f"{name} must be a number, got {value!r}")
        clamped = min(max(v, lo), hi)
        snapped = lo + ((clamped - lo) // step) * step
        if snapped != v:
            self.warn(
                f"{name} {value} -> {snapped} dB "
                f"(snapped to device step <= request, range [{lo},{hi}]/{step}dB)")
        return snapped

    def _snap_baseband(self, value: float) -> float:
        # Snap an explicit baseband BW to the nearest supported value.
        opts = C.BASEBAND_FILTER_BW_HZ
        nearest = min(opts, key=lambda o: abs(o - value))
        if nearest != value:
            self.print_message(
                f"[*] baseband BW {value/1e6:g} -> {nearest/1e6:g} MHz "
                f"(nearest supported)")
        return nearest

    def _auto_baseband(self, sample_rate: float,
                       explicit: float | None = None) -> float:
        # If unset, derive ~0.75x sample rate snapped to a supported BW. If set
        # explicitly, snap it and warn when it exceeds the sample rate (a
        # likely mistake -- you can't filter wider than you sample).
        if explicit is None:
            target = sample_rate * C.BASEBAND_AUTO_FRACTION
            return self._snap_baseband(target)
        bw = self._snap_baseband(explicit)
        if bw > sample_rate:
            self.warn(
                f"baseband BW {bw/1e6:g} MHz exceeds sample rate "
                f"{sample_rate/1e6:g} Msps.")
        return bw

    def validate_rx(self, freq: float, sample_rate: float, lna: int,
                    vga: int) -> tuple[float, float, int, int]:
        """Validate and snap receive parameters; return the values actually used.

        Hard-range checks frequency and sample rate, snaps LNA/VGA to real
        device gain steps. Returns (freq, sample_rate, lna, vga).
        """
        freq = self._check_hard_range("frequency", freq,
                                      C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
        sample_rate = self._check_hard_range("sample_rate", sample_rate,
                                             C.SR_MIN, C.SR_MAX, C.SR_WARN_BELOW)
        lna = self._snap_gain("lna_gain", lna, C.LNA_GAIN)
        vga = self._snap_gain("vga_gain", vga, C.VGA_GAIN)
        return freq, sample_rate, lna, vga

    def validate_tx(self, freq: float, sample_rate: float, txvga: int,
                    amp: bool) -> tuple[float, float, int, bool]:
        """Validate and snap transmit parameters; return the values actually used.

        TX gain is capped by constants.TX_VGA_CEILING_DB. The only mode gate is
        require_mode('tx'); frequency uses the full device range.
        """
        # NOTE: TX frequency uses the full device range and is never policed by
        # --force; the only gate is being in TX mode. The gain ceiling guards
        # against an order-of-magnitude fat-finger.
        freq = self._check_hard_range("frequency", freq,
                                      C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
        sample_rate = self._check_hard_range("sample_rate", sample_rate,
                                             C.SR_MIN, C.SR_MAX, C.SR_WARN_BELOW)
        # Check the RAW request against the ceiling BEFORE snapping, so an
        # order-of-magnitude fat-finger (e.g. 470 for 47) rejects instead of
        # being silently clamped to the device max.
        if txvga > C.TX_VGA_CEILING_DB:
            raise HackRFValueError(
                f"txvga_gain {txvga} exceeds the TX ceiling "
                f"{C.TX_VGA_CEILING_DB} dB set in constants.py")
        txvga = self._snap_gain("txvga_gain", txvga, C.TXVGA_GAIN)
        if amp and not C.TX_AMP_ALLOWED:
            raise HackRFValueError("TX amplifier disabled in constants.py")
        return freq, sample_rate, txvga, amp

    # =================================================================
    # Binary resolution
    # =================================================================
    def resolve(self, key: str) -> str:
        """Return the full path of a hackrf tool by TOOLS key (e.g. 'transfer').

        Raises HackRFDeviceError with an actionable message if the tool is not
        found in tools_dir, the configured directory, or PATH.
        """
        # key is a TOOLS key ("transfer", "info", ...). Returns the full path
        # or raises HackRFDeviceError with an actionable message.
        name = C.TOOLS[key]
        if self.tools_dir:
            # On Windows the real binaries are hackrf_transfer.exe etc., so a
            # bare-name check misses them. Try the bare name first (POSIX),
            # then each executable extension from PATHEXT (Windows). This is
            # the documented Windows workflow: tools_dir -> a hackrf-tools
            # folder that isn't on PATH.
            exts = [""]
            if os.name == "nt":
                exts += [e.lower() for e in
                         os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(";")
                         if e]
            for ext in exts:
                cand = os.path.join(self.tools_dir, name + ext)
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    return cand
        path = shutil.which(name)
        if path is None:
            raise HackRFDeviceError(
                f"'{name}' not found. Install hackrf-tools (Great Scott "
                f"Gadgets) or set tools_dir / [tools].dir in config.")
        return path

    # =================================================================
    # Capability probe
    # =================================================================
    @classmethod
    def from_device(cls, *, tools_dir: str | None = None, verbose: bool = False,
                    serial: str | None = None) -> HackRF:
        """Build a HackRF and immediately probe the attached board (fail fast).

        Unlike the bare constructor (which touches nothing), this runs
        hackrf_info: it raises HackRFDeviceError if tools are missing or no board
        is present, and warns if the firmware looks stale.
        """
        # Build a HackRF and immediately probe the attached board so callers
        # get a device whose reported firmware is known up front. Unlike the
        # bare constructor (which touches nothing), this RUNS hackrf_info, so
        # it raises HackRFDeviceError if tools are missing or no board is
        # present. Use it when you want a fail-fast handle for scripting.
        h = cls(tools_dir=tools_dir, verbose=verbose, serial=serial)
        info = h.info()                      # raises if no tools / no board
        if not isinstance(info, dict):       # raw=False -> parsed dict
            # a plain assert is stripped under `python -O`, which would let a
            # str flow onward; keep the guard a real, typed error
            raise HackRFDeviceError(
                "hackrf_info output could not be parsed into a device dict")
        if not info.get("boards"):
            raise HackRFDeviceError("no HackRF board detected")
        h._probed = info
        h._warn_if_firmware_stale(info)
        return h

    def _warn_if_firmware_stale(self, info: dict[str, Any]) -> None:
        # The subprocess approach is firmware-version sensitive: '-r -' stdout
        # streaming and 'sweep -N' need reasonably modern tools. Surface a
        # warning (not a raise) so old boards still work for what they can do.
        import re as _re
        ver = (info.get("library", {}) or {}).get("hackrf_info_version", "")
        m = _re.match(r"(\d{4})", ver or "")
        if m and int(m.group(1)) < 2021:
            self.warn(
                f"hackrf-tools {ver} predates 2021; stdout streaming "
                f"(rx to_stdout / capture_array) and 'sweep -N' may be "
                f"unsupported -- consider upgrading.")

    # =================================================================
    # The device-I/O choke point
    # =================================================================
    def _run(self, argv: list[Any], *, mode: str = "blocking",
             duration: float | None = None, text: bool = False,
             check: bool = True, print_cmd: bool = False, kind: str = "rx",
             read_samples: int = 65536) -> Any:
        # argv: full command list whose [0] is a TOOLS key, e.g.
        #       ["transfer", "-r", "out.iq", ...]; resolved to a real path here.
        #
        # mode:
        #   "blocking" -> process self-terminates (-n / sweep -1). Wait, return
        #                 (stdout, stderr, returncode).
        #   "timed"    -> run `duration` s, then SIGINT, return result.
        #   "stream"   -> GENERATOR yielding raw stdout chunks/lines as they
        #                 arrive (sweep CSV, rx -r -). Caller decodes.
        #   "handle"   -> return a _Process the caller drives with .stop().
        #
        # print_cmd: if True, print the resolved command and DO NOT run it
        #            (the --print-cmd / dry-run feature). Returns None so a
        #            dry run is never mistaken for a result tuple / handle.
        resolved = [self.resolve(argv[0])] + [str(a) for a in argv[1:]]
        if self.serial and argv[0] in C.TOOLS_WITH_SERIAL:
            resolved[1:1] = ["-d", str(self.serial)]

        if print_cmd:
            print(" ".join(resolved))
            return None

        self.print_message("[*] exec: " + " ".join(resolved))

        if mode == "stream":
            return self._stream(resolved, text=text, read_samples=read_samples)
        if mode == "handle":
            # Tier C (OS dead-man): same gate as the atexit registry below.
            protected = kind == "tx" or self.backstop_rx
            preexec = _deadman_preexec() if protected else None
            proc = subprocess.Popen(resolved, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    creationflags=_CREATION_FLAGS,
                                    preexec_fn=preexec)
            handle = _Process(proc, self, kind=kind)
            if protected:
                handle._job = _deadman_attach(proc)
            # Tier B: TX always backstopped; RX backstopped unless opted out.
            if protected:
                _register_live(handle)
            return handle

        if mode == "timed" and duration is None:
            raise HackRFValueError("timed mode requires duration")

        proc = subprocess.Popen(resolved, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=text,
                                creationflags=_CREATION_FLAGS)
        try:
            if mode == "timed":
                # communicate(timeout=) drains stdout/stderr WHILE waiting, so
                # a chatty child can't fill the pipe and stall (the old poll
                # loop drained nothing until the end).
                try:
                    out, err = proc.communicate(timeout=duration)
                except subprocess.TimeoutExpired:
                    out, err = self._sigint_and_reap(proc)
            else:
                out, err = proc.communicate()
        except KeyboardInterrupt:
            # Stop the child cleanly, then RE-RAISE. Swallowing Ctrl-C here
            # made it impossible to break out of multi-_run loops (segmented
            # capture would just start the next segment).
            self._sigint_and_reap(proc)
            raise

        rc = proc.returncode
        # timed runs end via our SIGINT, so a non-zero rc there is expected.
        if check and mode != "timed" and rc not in (0, None):
            errtxt = err.decode(errors="replace") if isinstance(err, bytes) else err
            detail = errtxt.strip()
            if not detail:
                # some tools report failures on STDOUT with an empty stderr
                # (Linux hackrf_info prints "No HackRF boards found." there,
                # exit 1) -- without this fallback the error read
                # "exited 1: " with the actual reason discarded
                outtxt = out.decode(errors="replace") if isinstance(out, bytes) else (out or "")
                tail = [ln for ln in outtxt.splitlines() if ln.strip()]
                detail = tail[-1].strip() if tail else ""
            raise HackRFDeviceError(
                f"{C.TOOLS[argv[0]]} exited {rc}: {detail}")
        return out, err, rc

    @staticmethod
    def _sigint_and_reap(proc: subprocess.Popen[Any],
                         grace: float = 5.0) -> tuple[Any, Any]:
        # SIGINT (clean flush/close in hackrf_*), bounded wait, escalate.
        _interrupt(proc)
        try:
            return proc.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.terminate()
            return proc.communicate()

    def _stream(self, resolved: list[str], text: bool = False,
                read_samples: int = 65536) -> Generator[Any, None, None]:
        # Generator twin of _run. Launch, yield stdout as it arrives, clean up
        # on the caller breaking out (GeneratorExit) so we never leave a
        # transmitting/receiving process orphaned.
        #
        # read_samples sets the stdout read granularity (in I/Q samples). Bigger
        # = fewer syscalls / higher sustained throughput; smaller = lower
        # per-block latency. The default 65536 (128 KB) is a balance; the
        # persistent receiver and benchmark can raise it to push sustained rate.
        #
        # stderr is drained continuously by a daemon thread (capped tail) --
        # an undrained PIPE eventually fills and blocks the child. If the
        # child dies on its own with a non-zero code (e.g. no board found),
        # we now RAISE with the stderr tail instead of silently yielding
        # nothing and looking like an empty-but-successful run.
        proc = subprocess.Popen(resolved, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=text,
                                creationflags=_CREATION_FLAGS)
        # PIPE is always requested above, so these are never None. Typed Any
        # because the concrete class depends on `text`: BufferedReader in binary
        # mode (which is where .read1 comes from) vs TextIOWrapper in text mode.
        stdout: Any = proc.stdout
        err_tail: list[Any] = []
        err_cap = _DRAIN_CAP

        def _eat(stream: Any, sink: list[Any]) -> None:
            try:
                for data in iter(lambda: stream.read(4096), b"" if not text else ""):
                    sink.append(data)
                    while sum(len(d) for d in sink) > err_cap and len(sink) > 1:
                        sink.pop(0)
            except (OSError, ValueError):
                pass

        t = threading.Thread(target=_eat, args=(proc.stderr, err_tail),
                             daemon=True)
        t.start()
        broke_out = True
        try:
            if text:
                for line in stdout:
                    yield line
            else:
                # read1() returns whatever is available after ONE underlying
                # read, instead of blocking until the full count or EOF. With
                # plain read(n) a continuous source (hackrf_transfer -r -) that
                # has only a partial chunk buffered would block, stalling
                # low-latency consumers and making bounded capture_array hang
                # until a full 128 KB accumulated. Cap the request so we never
                # split an I/Q pair across yields.
                while True:
                    chunk = stdout.read1(C.BYTES_PER_SAMPLE * read_samples)
                    if not chunk:
                        break
                    yield chunk
            broke_out = False  # natural EOF, not a caller break
        finally:
            if proc.poll() is None:
                _interrupt(proc)
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.terminate()
        if not broke_out and proc.returncode not in (0, None):
            t.join(timeout=2.0)   # let the drain finish before reading it
            err = (b"" if not text else "").join(err_tail)
            if isinstance(err, bytes):
                err = err.decode(errors="replace")
            raise HackRFDeviceError(
                f"{os.path.basename(resolved[0])} exited "
                f"{proc.returncode}: {err.strip()}")

    # =================================================================
    # Shared helpers used by mixins
    # =================================================================
    def decode_iq(self, raw: bytes) -> np.ndarray:
        """Decode HackRF-native interleaved int8 I/Q bytes to complex64.

        Values are normalized to roughly [-1, 1); an odd trailing byte
        (truncated final pair) is dropped.
        """
        # HackRF native format -> complex64. Interleaved int8 I,Q,I,Q...
        # Guard against an odd trailing byte (truncated final pair).
        #
        # Direct construction into a preallocated complex64 array (assigning
        # the int8 I/Q slices straight into .real/.imag) is ~3x faster than
        # going via a full float32 intermediate. At 20 Msps (40 MB/s) the old
        # path left ~2.4x headroom; this leaves ~7x, which matters when other
        # Python work is competing for the GIL during a live capture.
        a = np.frombuffer(raw, dtype=np.int8)
        if a.size % 2:
            a = a[:-1]
        iq = np.empty(a.size // 2, dtype=np.complex64)
        iq.real = a[0::2]
        iq.imag = a[1::2]
        iq /= 128.0          # normalize int8 full-scale to ~[-1, 1)
        return iq

    # ---- power / relative calibration (Level 1) ----------------------------
    # These turn the device's arbitrary dBFS amplitude into something that is
    # at least CONSISTENT across gain settings (and, with a user-supplied
    # offset, approximately absolute). They are PURE math on values you give
    # them -- the library never invents reference data or claims a calibrated
    # dBm figure it cannot honestly produce. Producing the offset and any
    # frequency-correction table is a hardware+reference workflow; see
    # examples/calibrate.py.

    @staticmethod
    def power_dbfs(iq: np.ndarray) -> float:
        """Mean power of a complex64 block in dBFS (0 dBFS = |amplitude| 1.0)."""
        # Mean power of a complex64 block in dBFS (dB relative to full scale).
        # 0 dBFS == |amplitude| 1.0 (ADC full scale). Always <= 0 for real
        # captures. This is the raw, UNCALIBRATED reading.
        if len(iq) == 0:
            return float("-inf")
        power = float(np.mean((iq.real.astype(np.float64) ** 2
                               + iq.imag.astype(np.float64) ** 2)))
        return 10.0 * np.log10(power + 1e-20)

    @staticmethod
    def gain_db(lna: int = 0, vga: int = 0, amp: bool = False) -> float:
        """Total configured receive gain chain in dB (LNA + VGA + optional amp)."""
        # Total RX gain through the chain in dB: LNA (IF) + VGA (baseband) +
        # the fixed ~14 dB front-end amp if enabled. This is the quantity that
        # makes a raw dBFS reading ambiguous -- the SAME signal reads ~36 dB
        # different between min and max gain.
        return float(lna) + float(vga) + (C.AMP_DB if amp else 0.0)

    def relative_power_db(self, iq_or_dbfs: np.ndarray | float, *,
                          lna: int | None = None, vga: int | None = None,
                          amp: bool | None = None, offset_db: float = 0.0,
                          freq_hz: float | None = None,
                          freq_correction: Callable[[float], float] | None = None
                          ) -> float:
        """Gain-normalized power: dBFS minus the configured gain chain.

        Readings are consistent across gain settings but RELATIVE, not absolute
        dBm, unless offset_db from a known reference is supplied
        (see examples/calibrate.py).
        """
        # Gain-normalized power: subtract the gain chain so readings taken at
        # DIFFERENT gain settings are directly comparable. This is the Level 1
        # relative calibration -- still not absolute dBm, but consistent.
        #
        #   value = dBFS - total_gain_dB + offset_db [- freq_correction(freq)]
        #
        # iq_or_dbfs:   a complex64 block (its power is measured) OR a dBFS float
        # lna/vga/amp:  gain settings; if omitted, taken from last_params
        # offset_db:    your single-point reference offset (Level 3), if any.
        #               With a correct offset this approximates dBm; without
        #               one it is relative dB (still gain-consistent).
        # freq_hz + freq_correction: optional per-frequency correction. If you
        #               pass a callable freq_correction(freq_hz)->dB (e.g. built
        #               from a sweep of a flat source, see examples/calibrate.py),
        #               it is subtracted to flatten the front-end response
        #               (Level 2). The library ships NO built-in curve, because
        #               front-end response varies per unit.
        dbfs = (iq_or_dbfs if isinstance(iq_or_dbfs, (int, float))
                else self.power_dbfs(iq_or_dbfs))
        lp = self.last_params or {}
        if lna is None:
            lna = lp.get("lna_gain", lp.get("lna", 0))
        if vga is None:
            vga = lp.get("vga_gain", lp.get("vga", 0))
        if amp is None:
            amp = lp.get("amp", False)
        value = dbfs - self.gain_db(lna, vga, amp) + float(offset_db)
        if freq_hz is not None and freq_correction is not None:
            value -= float(freq_correction(freq_hz))
        return value

    def estimate_capture(self, sample_rate: float,
                         num_samples: int | None = None,
                         duration: float | None = None,
                         path: str = ".") -> dict[str, Any]:
        """Estimate bytes, duration, and disk fit for a planned capture.

        Returns a dict including sizes and free-disk headroom; use before long
        captures to avoid filling the drive mid-recording.
        """
        # Bytes/sec = sample_rate * 2 (int8 I + int8 Q). Returns a dict and
        # raises HackRFEnvironmentError if it would blow past free disk.
        bps = sample_rate * C.BYTES_PER_SAMPLE
        if num_samples is not None:
            total = num_samples * C.BYTES_PER_SAMPLE
            secs = num_samples / sample_rate
        elif duration is not None:
            total = int(bps * duration)
            secs = duration
        else:
            total = None  # open-ended (handle mode)
            secs = None
        free = shutil.disk_usage(path).free
        info = {"bytes_per_sec": bps, "total_bytes": total,
                "seconds": secs, "free_bytes": free}
        if total is not None and total > free * C.DEFAULT_DISK_HEADROOM:
            raise HackRFEnvironmentError(
                f"capture needs ~{total/1e9:.2f} GB but only "
                f"{free/1e9:.2f} GB free at {path}")
        return info


# =====================================================================
# Module-level helpers: consume recordings WITHOUT a device / HackRF()
# =====================================================================
def parse_freq(txt: str | float | int) -> float:
    """Parse '433.92M', '88M', '1.09G', '2.5k', '100MHz', or plain Hz -> float Hz.

    Lives at module scope (not just in the CLI) so library callers can accept
    the same human notation. Raises HackRFValueError on bad input instead of a
    bare ValueError, so the CLI's typed-exception handler catches it.
    """
    s = str(txt).strip()
    # tolerate a trailing 'Hz'/'hz' so '433.92MHz' works, not just '433.92M'
    if s[-2:].lower() == "hz":
        s = s[:-2]
    mult = 1.0
    if s and s[-1] in "kKmMgG":
        mult = {"k": 1e3, "m": 1e6, "g": 1e9}[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        raise HackRFValueError(
            f"could not parse frequency {txt!r} "
            f"(try 433.92M, 1.09G, 2.5k, or plain Hz)")


def load_iq(path: str, count: int | None = None,
            offset_samples: int = 0) -> np.ndarray:
    """Load a HackRF int8 I/Q recording into a complex64 numpy array.

    The other half of capture(): other code's entry point into a recording.
    Reads with np.fromfile (no whole-file Python bytes copy), drops a
    truncated trailing byte, and normalizes int8 full-scale to ~[-1, 1).

    count:           number of complex samples to read (None = all)
    offset_samples:  complex samples to skip from the start of the file
    """
    n_bytes = -1 if count is None else int(count) * C.BYTES_PER_SAMPLE
    a = np.fromfile(path, dtype=np.int8, count=n_bytes,
                    offset=int(offset_samples) * C.BYTES_PER_SAMPLE)
    if a.size % 2:
        a = a[:-1]
    iq = np.empty(a.size // 2, dtype=np.complex64)   # fast direct construction
    iq.real = a[0::2]
    iq.imag = a[1::2]
    iq /= 128.0
    return iq
