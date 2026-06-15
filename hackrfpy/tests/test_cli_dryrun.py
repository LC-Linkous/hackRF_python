#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_cli_dryrun.py'
#   --print-cmd builds the right hackrf_* argv without running anything.
#   Skips cleanly if hackrf-tools aren't installed (resolve() would raise).
##--------------------------------------------------------------------\

import shutil
import pytest
from hackrfpy.cli import HackRFCLI


needs_tools = pytest.mark.skipif(
    shutil.which("hackrf_transfer") is None,
    reason="hackrf-tools not installed")


@needs_tools
def test_rx_print_cmd(capsys):
    app = HackRFCLI(["rx", "-f", "433.92M", "-s", "8M",
                     "-n", "1000000", "--print-cmd"])
    app.main(app.getArgs())
    out = capsys.readouterr().out
    assert "hackrf_transfer" in out
    assert "-f 433920000" in out
    assert "-n 1000000" in out
