#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/_host.py'
#
#   The contract between the HackRF class and the command mixins under
#   ./_commands/. Each mixin calls methods on `self` that live on the HOST
#   class (core.py), not on the mixin -- _run, validate_rx, warn, and so on.
#   Until now that contract existed only as a comment at the top of each
#   mixin; HostOps makes it explicit and type-checkable.
#
#   Mixins inherit HostOps, so a type checker knows what `self` provides. At
#   runtime a Protocol subclass is an ordinary class (no abstract enforcement,
#   no metaclass conflict), so the HackRF(InfoMixin, CaptureMixin, ...)
#   composition and its MRO are unchanged.
#
#   If a mixin starts calling a new host method, add it here -- that is the
#   point: the dependency becomes visible instead of implicit.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class HostOps(Protocol):
    # ---- shared state ------------------------------------------------------
    mode: str
    serial: str | None
    tools_dir: str | None
    verboseEnabled: bool
    allow_out_of_spec: bool
    last_params: dict[str, Any] | None

    # ---- the single device-I/O choke point ---------------------------------
    def _run(self, argv: list[Any], *, mode: str = ..., duration: float | None = ...,
             text: bool = ..., check: bool = ..., print_cmd: bool = ...,
             kind: str = ..., read_samples: int = ...) -> Any: ...

    def resolve(self, key: str) -> str: ...

    # ---- diagnostics -------------------------------------------------------
    def warn(self, msg: str) -> None: ...
    def print_message(self, msg: str) -> None: ...

    # ---- operating mode ----------------------------------------------------
    def require_mode(self, needed: str) -> None: ...

    # ---- validation / envelope ---------------------------------------------
    def validate_rx(self, freq: float, sample_rate: float, lna: int,
                    vga: int) -> tuple[float, float, int, int]: ...
    def validate_tx(self, freq: float, sample_rate: float, txvga: int,
                    amp: bool) -> tuple[float, float, int, bool]: ...
    def _check_hard_range(self, name: str, value: float, lo: float, hi: float,
                          warn_below: float | None = ...) -> float: ...
    def _snap_gain(self, name: str, value: int,
                   table: tuple[int, int, int]) -> int: ...
    def _auto_baseband(self, sample_rate: float,
                       explicit: float | None = ...) -> float: ...
    def _record_params(self, **params: Any) -> dict[str, Any]: ...

    # ---- cross-mixin -------------------------------------------------------
    # DeviceMixin.preflight()/features() parse hackrf_info output using
    # InfoMixin.parse_info. Declaring it here makes that sibling dependency
    # explicit rather than an implicit assumption about composition order.
    @staticmethod
    def parse_info(text: str) -> dict[str, Any]: ...

    # ---- data --------------------------------------------------------------
    def decode_iq(self, raw: bytes) -> np.ndarray: ...
    def estimate_capture(self, sample_rate: float, num_samples: int | None = ...,
                         duration: float | None = ...,
                         path: str = ...) -> dict[str, Any]: ...
