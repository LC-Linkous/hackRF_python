#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_cli.py'
#
#   End-to-end CLI coverage that DOES NOT need real hackrf-tools or a board.
#   The trick (same one conftest uses for lifecycle tests): point the CLI's
#   HackRF at a tools_dir of cross-platform STUB binaries, so resolve()
#   succeeds and the shell exercises its full dispatch/parse/exit surface on
#   Windows and POSIX alike. rx/tx/sweep use --print-cmd (nothing executes);
#   info/detect/doctor run a functional hackrf_info stub; sweep's CSV loop
#   runs a functional hackrf_sweep stub. State + presets are made hermetic by
#   redirecting XDG_CONFIG_HOME to a tmp dir.
#
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

import os
import stat
import sys
from types import SimpleNamespace

import pytest

from hackrfpy import cli
from hackrfpy.exceptions import HackRFValueError


# --- realistic hackrf_info output (mirrors tests/fixtures/hackrf_info.txt) ---
INFO_TEXT = (
    "hackrf_info version: 2024.02.1\n"
    "libhackrf version: 2024.02.1 (0.9)\n"
    "Found HackRF\n"
    "Index: 0\n"
    "Serial number: 0000000000000000457863c82b4f3f\n"
    "Board ID Number: 2 (HackRF One)\n"
    "Firmware Version: 2024.02.1 (API:1.08)\n"
    "Part ID Number: 0xa000cb3c 0x004f4762\n"
    "Hardware Revision: r9\n"
)

# two well-formed hackrf_sweep CSV rows (date, time, lo, hi, binw, nsamp, db...)
SWEEP_ROWS = (
    "2026-06-10, 12:00:00.000000, 88000000, 88500000, 100000.00, 8192, "
    "-71.23, -70.10, -69.95, -72.40, -71.88\n"
    "2026-06-10, 12:00:00.000000, 88500000, 89000000, 100000.00, 8192, "
    "-70.01, -71.12, -72.23, -73.34, -74.45\n"
)


def _write_tool(tools_dir, name, *, emit=""):
    """Write a resolvable stub binary that prints `emit` then exits 0.

    POSIX  : a shebang'd executable file `<name>` (chmod +x)
    Windows: a `<name>.py` plus a `<name>.bat` launcher on PATHEXT
    resolve() only needs isfile + X_OK; the functional stubs additionally
    emit canned stdout so info/detect/doctor/sweep have something to parse.
    """
    prog = "import sys\n"
    if emit:
        prog += f"sys.stdout.write({emit!r})\n"
    prog += "sys.exit(0)\n"

    if os.name == "nt":
        py = os.path.join(tools_dir, name + ".py")
        with open(py, "w") as f:
            f.write(prog)
        launcher = os.path.join(tools_dir, name + ".bat")
        with open(launcher, "w") as f:
            f.write(f'@echo off\r\n"{sys.executable}" "{py}" %*\r\n')
        return launcher

    launcher = os.path.join(tools_dir, name)
    with open(launcher, "w") as f:
        f.write(f"#!{sys.executable}\n")
        f.write(prog)
    os.chmod(launcher, os.stat(launcher).st_mode
             | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return launcher


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Hermetic CLI environment: stub tools + a private config/state dir."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    tools = tmp_path / "tools"
    tools.mkdir()
    _write_tool(str(tools), "hackrf_info", emit=INFO_TEXT)
    _write_tool(str(tools), "hackrf_transfer")           # only resolved
    _write_tool(str(tools), "hackrf_sweep", emit=SWEEP_ROWS)

    real_cls = cli.HackRF

    def _factory(*a, **k):
        k.setdefault("tools_dir", str(tools))
        return real_cls(*a, **k)

    monkeypatch.setattr(cli, "HackRF", _factory)
    return SimpleNamespace(tools=str(tools), tmp=tmp_path)


def _run_cli(argv):
    app = cli.HackRFCLI(argv)
    app.main(app.getArgs())


# =====================================================================
# argument parsing / help / version
# =====================================================================
def test_version_action_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.HackRFCLI(["--version"])
    assert exc.value.code == 0
    assert "hrf" in capsys.readouterr().out


def test_no_subcommand_prints_help(capsys):
    _run_cli([])
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_bad_mode_choice_is_rejected():
    # argparse enforces the choices=C.MODES constraint
    with pytest.raises(SystemExit):
        cli.HackRFCLI(["mode", "sideways"])


def test_sweep_requires_edges():
    with pytest.raises(SystemExit):
        cli.HackRFCLI(["sweep"])          # --f-min / --f-max are required


# =====================================================================
# mode state file (read/write round-trip, get/set dispatch)
# =====================================================================
def test_mode_state_roundtrip(cli_env, capsys):
    # default when no state file exists
    _run_cli(["mode"])
    assert capsys.readouterr().out.strip() == "rx"

    # setting tx fires the safety banner and persists
    _run_cli(["mode", "tx"])
    assert "TX MODE ARMED" in capsys.readouterr().out

    # a fresh read sees the persisted mode
    _run_cli(["mode"])
    assert capsys.readouterr().out.strip() == "tx"


def test_read_mode_default_without_file(cli_env):
    assert cli.read_mode() == "rx"


def test_write_then_read_mode(cli_env):
    cli.write_mode("tx")
    assert cli.read_mode() == "tx"


# =====================================================================
# presets
# =====================================================================
def test_presets_listing(cli_env, capsys):
    _run_cli(["presets"])
    out = capsys.readouterr().out
    assert "fm" in out
    assert "ads-b" in out


# =====================================================================
# info / detect / doctor (functional hackrf_info stub)
# =====================================================================
def test_info_parsed_output(cli_env, capsys):
    _run_cli(["info"])
    out = capsys.readouterr().out
    assert "457863c82b4f3f" in out          # serial from the stub


def test_info_print_cmd_does_not_parse(cli_env, capsys):
    _run_cli(["info", "--print-cmd"])
    out = capsys.readouterr().out
    assert "hackrf_info" in out
    assert "457863c82b4f3f" not in out       # nothing was executed/parsed


def test_detect_reports_ready_board(cli_env, capsys):
    _run_cli(["detect"])
    out = capsys.readouterr().out
    assert "hackrfpy detect" in out
    assert "ready" in out


def test_detect_exits_nonzero_when_no_board(cli_env):
    # rewrite the info stub to report no board; detect must exit 1 so that
    # `hrf detect && hrf rx ...` short-circuits.
    no_board = ("hackrf_info version: 2024.02.1\n"
                "libhackrf version: 2024.02.1 (0.9)\n"
                "No HackRF boards found.\n")
    _write_tool(cli_env.tools, "hackrf_info", emit=no_board)
    with pytest.raises(SystemExit) as exc:
        _run_cli(["detect"])
    assert exc.value.code == 1


def test_doctor_ok_with_core_tools(cli_env):
    # all three core tools present -> no problems -> no exit
    _run_cli(["doctor"])


def test_doctor_exits_when_core_tool_missing(cli_env, monkeypatch):
    # Force resolve() to fail for the sweep tool so preflight reports a missing
    # CORE binary -> exit 1.
    #
    # NOTE: deleting the stub from tools_dir is NOT enough. resolve() falls back
    # to shutil.which(), so on a machine with real hackrf-tools on PATH (i.e.
    # any actual dev box) it would find the real hackrf_sweep and report no
    # problems. Patching resolve makes this deterministic everywhere.
    from hackrfpy.core import HackRF as _HackRF
    from hackrfpy import constants as C
    from hackrfpy.exceptions import HackRFDeviceError

    real_resolve = _HackRF.resolve

    def _resolve(self, key):
        if key == "sweep":
            raise HackRFDeviceError(f"missing binary: {C.TOOLS['sweep']}")
        return real_resolve(self, key)

    monkeypatch.setattr(_HackRF, "resolve", _resolve)

    with pytest.raises(SystemExit) as exc:
        _run_cli(["doctor"])
    assert exc.value.code == 1


# =====================================================================
# rx dispatch (--print-cmd builds argv; --preset resolves freq)
# =====================================================================
def test_rx_print_cmd_builds_transfer(cli_env, capsys):
    _run_cli(["rx", "-f", "433.92M", "-s", "8M", "-n", "1000000",
              "--print-cmd"])
    out = capsys.readouterr().out
    assert "hackrf_transfer" in out
    assert "-f 433920000" in out
    assert "-n 1000000" in out


def test_rx_preset_supplies_frequency(cli_env, capsys):
    _run_cli(["rx", "--preset", "fm", "-n", "1000", "--print-cmd"])
    out = capsys.readouterr().out
    # fm preset: f_min 88 MHz becomes the center when -f is omitted
    assert "-f 88000000" in out


def test_rx_without_freq_or_preset_raises(cli_env):
    app = cli.HackRFCLI(["rx", "-s", "8M", "-n", "1000"])
    with pytest.raises(HackRFValueError):
        app.main(app.getArgs())


# =====================================================================
# tx dispatch (requires persisted TX mode)
# =====================================================================
def test_tx_print_cmd_requires_tx_mode(cli_env, tmp_path, capsys):
    src = tmp_path / "sig.iq"
    src.write_bytes(b"\x00\x01" * 16)

    cli.write_mode("tx")                     # arm TX for this invocation
    _run_cli(["tx", str(src), "-f", "433.92M", "-s", "8M", "-x", "20",
              "--print-cmd"])
    out = capsys.readouterr().out
    assert "hackrf_transfer" in out
    assert "-t" in out and "-x 20" in out


def test_tx_blocked_in_rx_mode(cli_env, tmp_path):
    from hackrfpy.exceptions import HackRFModeError
    src = tmp_path / "sig.iq"
    src.write_bytes(b"\x00\x01" * 16)
    # mode defaults to rx; the gate must reject transmit
    app = cli.HackRFCLI(["tx", str(src), "-f", "433.92M", "-s", "8M"])
    with pytest.raises(HackRFModeError):
        app.main(app.getArgs())


# =====================================================================
# sweep dispatch (print_cmd path + the CSV printing loop)
# =====================================================================
def test_sweep_print_cmd(cli_env, capsys):
    _run_cli(["sweep", "--f-min", "88M", "--f-max", "108M", "--print-cmd"])
    out = capsys.readouterr().out
    assert "hackrf_sweep" in out
    assert "-f 88:108" in out


def test_sweep_streams_csv_rows(cli_env, capsys):
    # functional hackrf_sweep stub emits two rows then exits; the CLI parses
    # and re-prints them as CSV.
    _run_cli(["sweep", "--f-min", "88M", "--f-max", "89M"])
    out = capsys.readouterr().out
    assert "88000000" in out
    assert out.count("\n") >= 2              # both rows printed


# =====================================================================
# module-level main(): exception -> exit code mapping
# =====================================================================
def test_module_main_success(cli_env, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hrf", "presets"])
    cli.main()                               # returns cleanly, no SystemExit


def test_module_main_maps_value_error(cli_env, monkeypatch):
    # rx with no frequency -> HackRFValueError (exit code 2)
    monkeypatch.setattr(sys, "argv", ["hrf", "rx", "-s", "8M", "-n", "1000"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_module_main_keyboard_interrupt(monkeypatch):
    def _boom(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli.HackRFCLI, "main", _boom)
    monkeypatch.setattr(sys, "argv", ["hrf", "info"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 130


# =====================================================================
# _print_detect formatting (pure function; both branches)
# =====================================================================
def test_print_detect_not_found(capsys):
    cli._print_detect({
        "found": False, "problem": "no HackRF boards found",
        "count": 0, "boards": [], "tools_version": None,
        "libhackrf_version": None, "multiple": False, "ready": False,
    })
    assert "no HackRF boards found" in capsys.readouterr().out


def test_print_detect_rich_report(capsys):
    cli._print_detect({
        "found": True, "problem": "", "count": 2,
        "tools_version": "2024.02.1", "libhackrf_version": "2024.02.1 (0.9)",
        "boards": [
            {"index": 0, "is_hackrf": True, "serial": "abc",
             "name": "HackRF One", "firmware": "2024.02.1",
             "firmware_stale": False},
            {"index": 1, "is_hackrf": False, "serial": "def",
             "name": "?", "firmware": "2019.01.1",
             "firmware_stale": True},
        ],
        "multiple": True, "ready": True,
        "warnings": ["one board has stale firmware"],
    })
    out = capsys.readouterr().out
    assert "UNCONFIRMED" in out              # the non-HackRF board
    assert "stale" in out                    # firmware_stale branch
    assert "multiple boards" in out          # multiple branch
    assert "one board has stale firmware" in out  # warnings branch
