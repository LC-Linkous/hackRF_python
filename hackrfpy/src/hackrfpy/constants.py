#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/constants.py'
#
#   Single source of truth for the HackRF One operating envelope: hard
#   frequency / sample-rate ranges, the stepped gain tables, the discrete
#   baseband-filter bandwidths, and library defaults. EVERYTHING that is a
#   "limit" lives here so that:
#       1. there is exactly one place to edit as hardware/firmware evolves,
#       2. the validation code and the test suite import the SAME numbers and
#          therefore can never silently drift apart.
#
#   WARNING: these describe the LIBRARY's checking envelope, not live device
#   state. Editing them changes what the library will accept/reject; it does
#   not change anything on the board.
#
#   Author(s): <you>
##--------------------------------------------------------------------\

# ---- hard ranges (reject-by-default; --force / allow_out_of_spec downgrades
#      a reject to a warning) -------------------------------------------------
# HackRF One tunes 1 MHz - 6 GHz. Values outside this are almost always a
# fat-finger (typing 60e9 for 6e9), which is exactly what reject-by-default
# is meant to catch.
FREQ_MIN_HZ = 1_000_000          # 1 MHz
FREQ_MAX_HZ = 6_000_000_000      # 6 GHz

# Usable sample rates. The device technically accepts 2-20 Msps; 8-20 is the
# commonly recommended band. We reject outside 2-20 and warn below 8.
SR_MIN = 2_000_000               # 2 Msps
SR_MAX = 20_000_000              # 20 Msps
SR_WARN_BELOW = 8_000_000        # warn (don't reject) under 8 Msps

# ---- stepped gains (snap-and-notify, round DOWN to the honest device value) -
# Each entry: (min_db, max_db, step_db). The silicon rounds to a step anyway,
# so snapping is just telling the truth about what you'll actually get.
LNA_GAIN = (0, 40, 8)            # IF gain  (MAX2837)
VGA_GAIN = (0, 62, 2)            # baseband RX gain
TXVGA_GAIN = (0, 47, 1)          # TX IF gain

# Front-end amplifier is a fixed ~14 dB block, on/off only.
AMP_DB = 14

# ---- TX safety ceilings (default at true device max so an order-of-magnitude
#      typo rejects; tighten these for a specific bench) ----------------------
TX_VGA_CEILING_DB = TXVGA_GAIN[1]    # 47; lower this to cap output on a bench
TX_AMP_ALLOWED = True                # set False to forbid the 14 dB amp on TX

# ---- discrete baseband filter bandwidths (Hz), MAX2837 supported set --------
# hackrf_transfer auto-selects one if unset; we replicate a sensible default
# (~0.75 x sample_rate, snapped to nearest supported) and snap explicit values.
BASEBAND_FILTER_BW_HZ = (
    1_750_000, 2_500_000, 3_500_000, 5_000_000, 5_500_000, 6_000_000,
    7_000_000, 8_000_000, 9_000_000, 10_000_000, 12_000_000, 14_000_000,
    15_000_000, 20_000_000, 24_000_000, 28_000_000,
)
BASEBAND_AUTO_FRACTION = 0.75    # default BW as a fraction of sample rate

# ---- sample format ----------------------------------------------------------
# HackRF native capture format: interleaved signed 8-bit I, Q, I, Q ...
BYTES_PER_SAMPLE = 2             # one int8 I + one int8 Q
IQ_DTYPE = "int8"

# ---- disk / capture lifecycle ----------------------------------------------
# Used by the capture estimator + guard. Bytes/sec = sample_rate * 2.
DEFAULT_DISK_HEADROOM = 0.95     # refuse if capture would exceed 95% of free
DEFAULT_SEGMENT_SECONDS = None   # None = single file; set for rolling segments

# ---- external binaries ------------------------------------------------------
# Resolved via shutil.which by default; override the directory in config for
# Windows installs where hackrf-tools aren't on PATH.
TOOLS = {
    "info": "hackrf_info",
    "transfer": "hackrf_transfer",
    "sweep": "hackrf_sweep",
    "clock": "hackrf_clock",
    "spiflash": "hackrf_spiflash",
    "operacake": "hackrf_operacake",
    "cpldjtag": "hackrf_cpldjtag",
    "debug": "hackrf_debug",
}

# Tools that accept `-d <serial>` for multi-board selection. hackrf_info
# always lists every board and hackrf_cpldjtag predates the convention, so
# both are excluded; HackRF(serial=...) injects -d for the rest.
TOOLS_WITH_SERIAL = ("transfer", "sweep", "clock", "spiflash",
                     "operacake", "debug")

# The minimum set required for the common capture/sweep workflow. doctor()
# treats only these as hard problems when missing; the rest are optional
# device-management extras that not every install ships.
CORE_TOOLS = ("info", "transfer", "sweep")

# ---- operating modes --------------------------------------------------------
MODE_RX = "rx"
MODE_TX = "tx"
MODES = (MODE_RX, MODE_TX)
DEFAULT_MODE = MODE_RX

# CLI state-file location (mode persists across invocations here).
STATE_DIR_NAME = "hackrfpy"
STATE_FILE_NAME = "state.toml"
