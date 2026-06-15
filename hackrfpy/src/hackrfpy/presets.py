#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/presets.py'
#
#   Band / frequency presets. These are a USER CONVENIENCE for scanning and
#   selecting -- named center/edge frequencies and sensible sample rates so you
#   don't memorize numbers. They are NOT a TX gate; transmit uses the full
#   device range regardless of presets.
#
#   Built-ins can be extended/overridden from a user TOML
#   (~/.config/hackrfpy/presets.toml) via load_presets().
#
#   Author(s): <you>
##--------------------------------------------------------------------\

import os

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

# Each preset: center or (f_min, f_max) for sweeps, plus a default sample rate.
BUILTIN_PRESETS = {
    "fm":       {"f_min": 88_000_000,   "f_max": 108_000_000, "sample_rate": 10_000_000,
                 "desc": "FM broadcast band"},
    "airband":  {"f_min": 118_000_000,  "f_max": 137_000_000, "sample_rate": 8_000_000,
                 "desc": "VHF airband (AM voice)"},
    "ads-b":    {"center": 1_090_000_000, "sample_rate": 8_000_000,
                 "desc": "ADS-B (1090 MHz)"},
    "ism-433":  {"center": 433_920_000, "sample_rate": 2_000_000,
                 "desc": "433 MHz ISM"},
    "ism-915":  {"center": 915_000_000, "sample_rate": 8_000_000,
                 "desc": "915 MHz ISM (US)"},
    "noaa-apt": {"f_min": 137_000_000,  "f_max": 138_000_000, "sample_rate": 2_000_000,
                 "desc": "NOAA weather satellites"},
    "gps-l1":   {"center": 1_575_420_000, "sample_rate": 10_000_000,
                 "desc": "GPS L1"},
}


def _config_path():
    base = os.environ.get("XDG_CONFIG_HOME",
                          os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "hackrfpy", "presets.toml")


def load_presets():
    # Built-ins overlaid with the user's TOML (user wins on key collisions).
    presets = {k: dict(v) for k, v in BUILTIN_PRESETS.items()}
    path = _config_path()
    if tomllib and os.path.isfile(path):
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for name, cfg in user.get("presets", {}).items():
            presets[name] = cfg
    return presets


def get_preset(name):
    presets = load_presets()
    if name not in presets:
        from .exceptions import HackRFValueError
        raise HackRFValueError(
            f"unknown preset {name!r}; known: {', '.join(sorted(presets))}")
    return presets[name]
