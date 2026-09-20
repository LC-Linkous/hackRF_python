#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'src/hackrfpy/__init__.py'
#   Public API surface.
##--------------------------------------------------------------------\
from .core import HackRF, load_iq, parse_freq
from .sigmf import write_sigmf_meta, read_sigmf_meta
from .exceptions import (
    HackRFError, HackRFValueError, HackRFModeError,
    HackRFDeviceError, HackRFEnvironmentError,
)
from . import constants

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    __version__ = _pkg_version("hackrfpy")
except PackageNotFoundError:                     # running from a checkout
    __version__ = "0.0.0+unknown"

__all__ = [
    "HackRF", "load_iq", "parse_freq", "constants", "__version__",
    "write_sigmf_meta", "read_sigmf_meta",
    "HackRFError", "HackRFValueError", "HackRFModeError",
    "HackRFDeviceError", "HackRFEnvironmentError",
]
