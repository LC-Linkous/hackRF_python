#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_examples.py'
#   Guards the examples/ scripts against API drift: every name they import
#   from hackrfpy must exist in the public surface, and each file must
#   parse. This catches the "example imports something not exported" class
#   of bug (e.g. read_sigmf_meta) without needing hardware. Also covers
#   sweep_stream, the context manager the waterfall example relies on.
##--------------------------------------------------------------------\

import ast
import os
import time

import pytest

import hackrfpy

# examples/ sits at <repo>/examples, two levels up from this test file's
# package-relative location; resolve robustly whether run from the project
# dir or elsewhere.
_HERE = os.path.dirname(__file__)
_CANDIDATES = [
    os.path.abspath(os.path.join(_HERE, "..", "examples")),
    os.path.abspath(os.path.join(_HERE, "..", "..", "examples")),
]
EXAMPLES_DIR = next((p for p in _CANDIDATES if os.path.isdir(p)), None)


def _example_files():
    if not EXAMPLES_DIR:
        return []
    return [os.path.join(EXAMPLES_DIR, f)
            for f in os.listdir(EXAMPLES_DIR) if f.endswith(".py")]


@pytest.mark.skipif(not EXAMPLES_DIR, reason="examples/ dir not found")
@pytest.mark.parametrize("path", _example_files(),
                         ids=lambda p: os.path.basename(p))
def test_example_parses_and_imports_resolve(path):
    src = open(path).read()
    tree = ast.parse(src)                    # raises SyntaxError on bad parse
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "hackrfpy":
            for alias in node.names:
                assert hasattr(hackrfpy, alias.name), (
                    f"{os.path.basename(path)} imports hackrfpy.{alias.name} "
                    f"which is not in the public API")


# ---- sweep_stream: the waterfall's clean-exit mechanism --------------------
def test_sweep_stream_reaps_on_exception(stub_device, tmp_path):
    marker = str(tmp_path / "stopped")
    rows = [
        "2026-06-10, 12:00:00, 88000000, 93000000, 1000000.00, 8192, -70.00",
        "2026-06-10, 12:00:00, 93000000, 98000000, 1000000.00, 8192, -71.00",
    ]
    h = stub_device(sweep=dict(stdout_lines=rows, idle=True, marker=marker))
    with pytest.raises(RuntimeError):
        with h.sweep_stream(88e6, 108e6) as gen:
            for _ in gen:
                raise RuntimeError("waterfall consumer blew up")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not os.path.exists(marker):
        time.sleep(0.05)
    assert os.path.exists(marker), "sweep child not reaped on exception"


def test_sweep_stream_normal_iteration(stub_device):
    rows = [
        "2026-06-10, 12:00:00, 88000000, 93000000, 1000000.00, 8192, -70.00",
        "2026-06-10, 12:00:00, 93000000, 98000000, 1000000.00, 8192, -71.00",
    ]
    h = stub_device(sweep=dict(stdout_lines=rows))   # not idle -> ends
    with h.sweep_stream(88e6, 108e6) as gen:
        got = [r["hz_low"] for r in gen]
    assert got == [88000000, 93000000]
