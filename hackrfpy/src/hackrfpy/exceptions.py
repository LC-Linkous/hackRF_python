#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/exceptions.py'
#
#   Typed exception hierarchy. The API layer (core + mixins) RAISES these;
#   the CLI layer catches the base class once in main() and pretty-prints to
#   stderr with a clean exit code. Importing scripts get real, catchable
#   exceptions instead of sentinel return values.
#
#   Author(s): <you>
##--------------------------------------------------------------------\


class HackRFError(Exception):
    """Base for everything this library raises. Catch this to catch all."""
    exit_code = 1


class HackRFValueError(HackRFError):
    """A parameter is outside the operating envelope (freq, sample rate, gain).
    Raised by the validation layer when reject-by-default fires and --force
    was not given."""
    exit_code = 2


class HackRFModeError(HackRFError):
    """An operation was attempted in the wrong mode -- e.g. transmit() while
    the device is in RX mode. Switch modes first (the deliberate TX gate)."""
    exit_code = 3


class HackRFDeviceError(HackRFError):
    """The device or its tooling failed: a hackrf_* binary is missing, no board
    was found, or a subprocess exited non-zero."""
    exit_code = 4


class HackRFEnvironmentError(HackRFError):
    """The host environment can't support the request: insufficient disk for a
    capture, missing permissions, etc. Surfaced mostly by doctor/estimator."""
    exit_code = 5
