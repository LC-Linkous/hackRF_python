#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/collect_real_data.py'
#
#   Drive a REAL HackRF One through read-only commands and freeze the
#   verbatim output as test fixtures. The parsing tests then replay these
#   exact device bytes through the library's real parse/decode logic, so
#   the suite is validated against true hardware output rather than an
#   idealized synthetic version.
#
#   This is a HELPER, not a pytest test. It REQUIRES a connected HackRF and
#   the hackrf-tools binaries. It is the HackRF analog of the tinySA repo's
#   collect_readme_data.py.
#
#   SAFETY: this script is strictly READ-ONLY. It runs hackrf_info,
#   hackrf_sweep (receive), a short receive capture, and read-only device
#   queries. It NEVER transmits, NEVER writes firmware, NEVER flashes. The
#   device stays in RX mode throughout.
#
#   Usage:
#       python tests/collect_real_data.py
#       python tests/collect_real_data.py --tools-dir "C:\hackrf-tools-windows"
#       python tests/collect_real_data.py --anonymize        # scrub serials
#       python tests/collect_real_data.py --sweep-band 88:108 --rx-freq 100e6
##--------------------------------------------------------------------\

import argparse
import datetime
import os
import re
import sys

# Allow running from the repo without installing: add src/ to the path.
_HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(_HERE, "..", "src"), os.path.join(_HERE, "src")):
    if os.path.isdir(os.path.join(cand, "hackrfpy")):
        sys.path.insert(0, os.path.abspath(cand))
        break

from hackrfpy import HackRF                       # noqa: E402
from hackrfpy.exceptions import HackRFError       # noqa: E402

try:
    import numpy as np                            # noqa: E402
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: numpy is not available in this environment.\n"
        "  This usually means the script is running OUTSIDE the uv project "
        "environment.\n"
        "  Run it through uv so it uses the synced env that has numpy:\n"
        "      uv run python tests/collect_real_data.py [args]\n"
        "  (Plain `python ...` can pick up a different/activated .venv that "
        "lacks the project deps.)\n")
    sys.exit(1)

FIXTURES = os.path.join(_HERE, "fixtures")


def _anonymize(text):
    # Replace real serial numbers and part IDs with stable placeholders so a
    # fixture can live in a public repo. The parsing logic doesn't depend on
    # the specific values.
    # 32-hex-char serials (the trailing 16 are the unique part)
    text = re.sub(r"(Serial number:\s*0{16})[0-9a-fA-F]{16}",
                  r"\g<1>0123456789abcdef", text)
    # Part ID second word (device-unique)
    text = re.sub(r"(Part ID Number:\s*0x[0-9a-fA-F]{8}\s+0x)[0-9a-fA-F]{8}",
                  r"\g<1>00000000", text)
    return text


def _write(name, data, anonymize, *, binary=False):
    path = os.path.join(FIXTURES, name)
    if binary:
        with open(path, "wb") as f:
            f.write(data)
        print(f"  wrote {name}  ({len(data)} bytes)")
    else:
        if anonymize:
            data = _anonymize(data)
        with open(path, "w", newline="\n") as f:
            f.write(data)
        print(f"  wrote {name}  ({len(data.splitlines())} lines)")
    return path


def collect(args):
    os.makedirs(FIXTURES, exist_ok=True)
    h = HackRF(tools_dir=args.tools_dir, verbose=True)

    print("== preflight (confirming a real board before collecting) ==")
    det = h.detect()
    if not det["ready"]:
        print(f"  NO USABLE HACKRF: {det['problem']}", file=sys.stderr)
        print("  (collection needs a connected, confirmed HackRF.)",
              file=sys.stderr)
        return 1
    fw = det["boards"][0].get("firmware")
    print(f"  board ready: firmware {fw}, tools {det['tools_version']}")
    for w in det.get("warnings", []):
        print(f"  ! device warning: {w}")

    # ---- 1. hackrf_info (verbatim text) ----
    print("\n== hackrf_info ==")
    raw_info = h.info(raw=True)
    _write("hackrf_info_real.txt", raw_info, args.anonymize)

    # ---- 2. hackrf_sweep CSV rows (real, bounded) ----
    print(f"\n== hackrf_sweep {args.sweep_band} (one sweep) ==")
    lo, hi = args.sweep_band.split(":")
    sweep_lines = []
    try:
        # bounded so it terminates; collect the raw CSV the device emits
        rows = h.sweep_collect(float(lo) * 1e6, float(hi) * 1e6, num_sweeps=1)
        # re-render the parsed rows back to the on-the-wire CSV shape so the
        # fixture round-trips through parse_sweep_line; also capture a couple
        # of garbage/edge cases the parser must reject
        for r in rows:
            sweep_lines.append(", ".join(
                [r["date"], r["time"], str(r["hz_low"]), str(r["hz_high"]),
                 f"{r['bin_width']:.2f}", str(r["num_samples"])]
                + [f"{d:.2f}" for d in r["db"]]))
        print(f"  collected {len(rows)} sweep rows")
    except HackRFError as e:
        print(f"  sweep failed (recording the error, not fatal): {e}",
              file=sys.stderr)
    if sweep_lines:
        # add the two edge cases the parser tests rely on
        sweep_lines.append("this line is garbled and must parse to None")
        _write("sweep_sample_real.csv", "\n".join(sweep_lines) + "\n",
               args.anonymize)

    # ---- 3. real IQ bytes (short receive) ----
    print(f"\n== receive {args.rx_samples} samples @ {args.rx_freq} ==")
    try:
        # capture_array returns complex64; but the fixture must be the RAW
        # int8 interleaved bytes the device emits, so capture to a temp file
        # and read the bytes back verbatim.
        tmp = os.path.join(FIXTURES, "_tmp_capture.iq")
        h.capture(float(args.rx_freq), float(args.rx_rate),
                  num_samples=int(args.rx_samples), out=tmp, sigmf=False)
        with open(tmp, "rb") as f:
            raw_iq = f.read()
        # keep a SMALL slice as the committed fixture. Take it from the MIDDLE
        # of the capture, not the head: the first samples at a fresh tune are
        # often a settling transient or silence (all-zero), which parses but
        # doesn't prove decode works on real signal. Align to an even byte so
        # we never split an I/Q pair.
        nbytes = args.iq_fixture_bytes
        mid = (len(raw_iq) // 2) & ~1            # even offset
        slice_iq = raw_iq[mid:mid + nbytes]
        if len(slice_iq) < nbytes:               # tiny capture fallback
            slice_iq = raw_iq[:nbytes]
        _write("sample_real.iq", slice_iq, False, binary=True)
        # report whether the slice has real signal (non-zero) so the user
        # knows the fixture is meaningful, not silence
        nonzero = any(b not in (0,) for b in slice_iq)
        os.remove(tmp)
        print(f"  captured {len(raw_iq)} bytes, kept {nbytes} from offset "
              f"{mid} (nonzero signal: {nonzero})")
    except HackRFError as e:
        print(f"  capture failed (recording the error, not fatal): {e}",
              file=sys.stderr)

    # ---- 4. read-only device-management queries (best-effort) ----
    print("\n== read-only device queries (best-effort) ==")
    extras = []
    for label, fn in [("operacake -l", lambda: h.operacake_list()),
                      ("clock -a", lambda: h.clock("-a"))]:
        try:
            out = fn()
            text = out[0] if isinstance(out, tuple) else str(out)
            extras.append(f"### {label}\n{text}")
            print(f"  {label}: ok")
        except HackRFError as e:
            extras.append(f"### {label}\n(error: {e})")
            print(f"  {label}: {e}")
    if extras:
        _write("device_queries_real.txt", "\n\n".join(extras), args.anonymize)

    # ---- 5. provenance manifest ----
    manifest = (
        f"# hackrfpy real-data fixtures\n"
        f"# collected: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"# tools_version: {det['tools_version']}\n"
        f"# libhackrf_version: {det['libhackrf_version']}\n"
        f"# firmware: {fw}\n"
        f"# board_id: {det['boards'][0].get('name')}\n"
        f"# anonymized: {args.anonymize}\n"
        f"# sweep_band_mhz: {args.sweep_band}\n"
        f"# rx_freq_hz: {args.rx_freq}  rx_rate_sps: {args.rx_rate}\n"
        f"#\n"
        f"# These are VERBATIM outputs from a real HackRF One, frozen so the\n"
        f"# parsing tests replay true hardware bytes. Regenerate with:\n"
        f"#   python tests/collect_real_data.py\n")
    _write("REAL_DATA_PROVENANCE.txt", manifest, False)

    print("\n== done ==")
    print(f"  fixtures written to {FIXTURES}")
    print("  review them, then point the parsing tests at the *_real.* files.")
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Collect verbatim real-HackRF output as test fixtures "
                    "(READ-ONLY; never transmits).")
    p.add_argument("--tools-dir", default=None,
                   help="path to hackrf-tools if not on PATH "
                        r'(e.g. "C:\hackrf-tools-windows")')
    p.add_argument("--anonymize", action="store_true",
                   help="scrub serial numbers and part IDs for a public repo")
    p.add_argument("--sweep-band", default="88:108",
                   help="sweep band in MHz as lo:hi (default 88:108, FM)")
    p.add_argument("--rx-freq", default="100e6",
                   help="receive center frequency in Hz (default 100e6)")
    p.add_argument("--rx-rate", default="8e6",
                   help="receive sample rate in sps (default 8e6)")
    p.add_argument("--rx-samples", default="2000000",
                   help="how many samples to receive (default 2,000,000)")
    p.add_argument("--iq-fixture-bytes", type=int, default=16,
                   help="bytes of IQ to keep as the committed fixture "
                        "(default 16 = 8 complex samples)")
    args = p.parse_args()
    try:
        return collect(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
