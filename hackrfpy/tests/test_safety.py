#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_safety.py'
#   The safety envelope that must hold WITHOUT hardware: brick-guards on
#   firmware ops, the non-verbose warn channel, typed frequency parsing,
#   and the TX gain ceiling. These guard the worst outcomes (bricked board,
#   silent out-of-spec operation, illegal transmit), so they are pinned
#   explicitly rather than left to integration coverage.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

import logging

import pytest

from hackrfpy import HackRF, parse_freq, constants as C
from hackrfpy.exceptions import HackRFValueError


# ---- brick-guards: the only operations that can permanently kill a board ----
def test_spiflash_write_requires_confirm():
    h = HackRF()
    # must refuse BEFORE touching any subprocess / resolving a binary
    with pytest.raises(HackRFValueError, match="BRICK"):
        h.spiflash_write("firmware.bin")


def test_cpldjtag_requires_confirm():
    h = HackRF()
    with pytest.raises(HackRFValueError, match="brick"):
        h.cpldjtag("firmware.xsvf")


def test_spiflash_write_confirm_passes_guard(monkeypatch):
    # With confirm=True the guard is cleared and it proceeds to _run; stub _run
    # so we don't need a binary. Proves confirm is the ONLY thing gating it.
    h = HackRF()
    called = {}

    def fake_run(argv, **k):
        called["argv"] = argv
        return ("", "", 0)

    monkeypatch.setattr(h, "_run", fake_run)
    h.spiflash_write("firmware.bin", confirm=True)
    assert called["argv"][0] == "spiflash"
    assert "-w" in called["argv"]


# ---- warn channel: safety warnings must fire regardless of verbose ----------
# Warnings now go through logging ("hackrfpy" logger, WARNING level) instead of
# a raw stderr write, so these assert on caplog. The stdout-purity invariant is
# still checked with capsys: diagnostics must NEVER land on stdout.
def test_snap_gain_warns_when_not_verbose(caplog):
    h = HackRF(verbose=False)
    with caplog.at_level(logging.WARNING, logger="hackrfpy"):
        snapped = h._snap_gain("lna", 7, C.LNA_GAIN)   # 7 -> 0, a silent 7 dB loss
    assert snapped == 0
    msgs = "\n".join(r.message for r in caplog.records)
    assert "lna" in msgs and "-> 0" in msgs         # user was told, despite verbose=False


def test_sub_recommended_sample_rate_warns_not_silent(caplog):
    h = HackRF(verbose=False)
    with caplog.at_level(logging.WARNING, logger="hackrfpy"):
        h._check_hard_range("sample_rate", 4e6, C.SR_MIN, C.SR_MAX, C.SR_WARN_BELOW)
    assert "below the recommended" in "\n".join(r.message for r in caplog.records)


def test_forced_out_of_spec_warns_and_never_touches_stdout(caplog, capsys):
    h = HackRF()
    h.allow_out_of_spec = True
    with caplog.at_level(logging.WARNING, logger="hackrfpy"):
        h._check_hard_range("frequency", 60e9, C.FREQ_MIN_HZ, C.FREQ_MAX_HZ)
    assert "forced out-of-spec" in "\n".join(r.message for r in caplog.records)
    assert capsys.readouterr().out == ""            # never pollutes stdout


def test_warnings_are_warning_level(caplog):
    # Level matters: a consumer filtering at WARNING must still receive safety
    # notices. Pinned so a future refactor can't quietly demote these to INFO.
    h = HackRF(verbose=False)
    with caplog.at_level(logging.WARNING, logger="hackrfpy"):
        h._snap_gain("lna", 7, C.LNA_GAIN)
    assert caplog.records
    assert all(r.levelno == logging.WARNING for r in caplog.records)


# ---- typed frequency parsing ------------------------------------------------
@pytest.mark.parametrize("text,hz", [
    ("433.92M", 433_920_000),
    ("88M", 88_000_000),
    ("1.09G", 1_090_000_000),
    ("2.5k", 2_500),
    ("100", 100),
    (" 8M ", 8_000_000),
    ("1e6", 1_000_000),
    ("433.92MHz", 433_920_000),    # trailing Hz tolerated
    ("137mhz", 137_000_000),
])
def test_parse_freq_units(text, hz):
    assert parse_freq(text) == hz


def test_parse_freq_bad_input_is_typed():
    # a bad value must raise the LIBRARY's typed error so the CLI handler
    # catches it and prints a clean line, not a bare ValueError traceback
    with pytest.raises(HackRFValueError):
        parse_freq("not-a-freq")


# ---- TX ceiling: order-of-magnitude fat-finger rejects ----------------------
def test_tx_ceiling_rejects_before_snap():
    h = HackRF()
    with pytest.raises(HackRFValueError, match="ceiling"):
        # 470 instead of 47 -> must reject, not silently clamp to device max
        h.validate_tx(433.92e6, 8e6, 470, False)


def test_tx_at_ceiling_is_allowed():
    h = HackRF()
    freq, sr, txvga, amp = h.validate_tx(433.92e6, 8e6, C.TX_VGA_CEILING_DB,
                                         False)
    assert txvga == C.TX_VGA_CEILING_DB


# ---- newly-wrapped tool flags: construction tests ---------------------------
def test_sweep_to_file_text_and_binary(tmp_path, monkeypatch):
    h = HackRF(tools_dir=str(tmp_path))
    # stub resolve so no real binary needed
    monkeypatch.setattr(h, "resolve", lambda key: "/x/hackrf_sweep")
    seen = {}
    monkeypatch.setattr(h, "_run",
                        lambda argv, **k: seen.setdefault("argv", argv))
    h.sweep_to_file(2400e6, 2490e6, "s.csv")
    assert seen["argv"][-2:] == ["-r", "s.csv"]
    assert "-B" not in seen["argv"] and "-I" not in seen["argv"]
    seen.clear()
    h.sweep_to_file(2400e6, 2490e6, "s.bin", binary=True)
    assert "-B" in seen["argv"]
    seen.clear()
    h.sweep_to_file(2400e6, 2490e6, "s.bin", inverse_fft=True)
    assert "-I" in seen["argv"] and "-B" not in seen["argv"]   # -I wins


def test_transmit_cw_requires_tx_mode():
    from hackrfpy.exceptions import HackRFModeError
    h = HackRF()
    assert h.mode == C.MODE_RX
    with pytest.raises(HackRFModeError):
        h.transmit_cw(433.92e6, 8e6, amplitude=100)


def test_transmit_cw_builds_c_flag(monkeypatch):
    h = HackRF()
    h.set_mode(C.MODE_TX)
    seen = {}
    monkeypatch.setattr(h, "_run",
                        lambda argv, **k: seen.update(argv=argv) or ("", "", 0))
    h.transmit_cw(433.92e6, 8e6, amplitude=200, duration=1.0)   # 200 clamps
    assert seen["argv"][0] == "transfer"
    assert seen["argv"][1] == "-c"
    assert seen["argv"][2] == 127                                # clamped 0-127


# ---- transmit source-file guard: fail fast before spawning ------------------
def test_transmit_missing_source_rejected(monkeypatch):
    from hackrfpy.exceptions import HackRFEnvironmentError
    h = HackRF()
    h.set_mode(C.MODE_TX)
    monkeypatch.setattr(h, "_run",
                        lambda *a, **k: pytest.fail("must not spawn on bad source"))
    with pytest.raises(HackRFEnvironmentError, match="source not found"):
        h.transmit(433.92e6, 8e6, "/no/such/file.iq")


def test_transmit_mode_gate_precedes_source_check(monkeypatch):
    # With BOTH a wrong mode and a missing file, the TX-mode gate must win --
    # the safety invariant is checked before input validation.
    from hackrfpy.exceptions import HackRFModeError
    h = HackRF()                                 # defaults to RX
    assert h.mode == C.MODE_RX
    monkeypatch.setattr(h, "_run",
                        lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(HackRFModeError):
        h.transmit(433.92e6, 8e6, "/no/such/file.iq")


def test_transmit_print_cmd_skips_source_check(monkeypatch):
    # A dry-run preview must not require the file to exist (it may be a file
    # you haven't generated yet).
    h = HackRF()
    h.set_mode(C.MODE_TX)
    seen = {}
    monkeypatch.setattr(h, "_run",
                        lambda argv, **k: seen.update(argv=argv))
    h.transmit(433.92e6, 8e6, "/no/such/file.iq", print_cmd=True)
    assert seen["argv"][0] == "transfer"
    assert "-t" in seen["argv"]


# ---- logging contract: what a consumer is entitled to rely on ---------------
def test_diagnostics_never_reach_stdout(capsys, caplog):
    # The reason print_message moved off stdout: `hrf sweep -v > out.csv` used
    # to prepend "[*] mode: rx" INTO the CSV. stdout is data; stderr is chatter.
    h = HackRF(verbose=True)
    with caplog.at_level(logging.INFO, logger="hackrfpy"):
        h.print_message("[*] progress chatter")
        h.warn("a safety warning")
    assert capsys.readouterr().out == ""
    assert len(caplog.records) == 2


def test_consumer_can_silence_the_library(caplog):
    # Raising the level on the "hackrfpy" logger must suppress our records --
    # impossible back when these were bare print() calls.
    h = HackRF(verbose=False)
    logger = logging.getLogger("hackrfpy")
    with caplog.at_level(logging.CRITICAL, logger="hackrfpy"):
        logger.setLevel(logging.CRITICAL)
        try:
            h.warn("should be suppressed")
        finally:
            logger.setLevel(logging.NOTSET)      # restore; logger is global
    assert not [r for r in caplog.records if "suppressed" in r.message]


def test_verbose_gating_still_holds(caplog):
    # verbose=False -> no INFO; verbose=True -> INFO flows.
    with caplog.at_level(logging.INFO, logger="hackrfpy"):
        quiet = HackRF(verbose=False)
        quiet.print_message("[*] invisible")
        assert not caplog.records
        quiet.set_verbose(True)
        quiet.print_message("[*] now visible")
    assert any("now visible" in r.message for r in caplog.records)