#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/cli.py'
#
#   The CLI shell. One class owns the parser; main(args) dispatches on the
#   subcommand. __init__(a=None) takes argv from sys.argv OR a passed list, so
#   the same class drives from the shell or from a script:
#       app = HackRFCLI(['rx', '-f', '433.92M', '-s', '8M', '-n', '1000000'])
#       app.main(app.getArgs())
#
#   The CLI layer is thin: it parses, resolves the persisted operating mode,
#   instantiates HackRF once, calls the method, and maps typed exceptions to
#   clean stderr + exit codes. All real work lives in core + mixins.
#
#   Author(s): Lauren Linkous
#   Last Update: July 11, 2026
##--------------------------------------------------------------------\

from __future__ import annotations

import argparse
from typing import Any, Sequence
import os
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    _VERSION = _pkg_version("hackrfpy")
except PackageNotFoundError:  # running from a source tree, not installed
    _VERSION = "0+unknown"

from .core import HackRF, parse_freq
from .exceptions import HackRFError, HackRFValueError
from . import constants as C
from . import presets as P


# frequency parsing now lives in core.parse_freq (single source of truth, and
# the typed-exception version) so library callers share it. Imported above.


# ---- mode state file (mode persists across CLI invocations) ------------------
def _print_detect(det: dict[str, Any]) -> None:
    print("hackrfpy detect")
    print("-" * 40)
    if det["problem"] and not det["found"]:
        print(f"  {det['problem']}")
        return
    print(f"  boards found    : {det['count']}")
    if det["tools_version"]:
        print(f"  hackrf-tools    : {det['tools_version']}")
    if det["libhackrf_version"]:
        print(f"  libhackrf       : {det['libhackrf_version']}")
    for b in det["boards"]:
        tag = "HackRF" if b["is_hackrf"] else "UNCONFIRMED"
        print(f"  [{b['index']}] {tag}")
        print(f"      serial   : {b['serial']}")
        print(f"      name     : {b['name']}")
        print(f"      firmware : {b['firmware']}"
              + ("  (stale: <2021, streaming/-N may be unsupported)"
                 if b["firmware_stale"] else ""))
    if det["multiple"]:
        print("  ! multiple boards: select one with --serial <serial>")
    for w in det.get("warnings", []):
        print(f"  ! {w}")
    print(f"  ready           : {'yes' if det['ready'] else 'no'}")
    if det["problem"] and det["found"]:
        print(f"  note            : {det['problem']}")


def _state_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME",
                          os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, C.STATE_DIR_NAME, C.STATE_FILE_NAME)


def read_mode() -> str:
    path = _state_path()
    try:
        with open(path) as f:
            for line in f:
                if line.strip().startswith("mode"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return C.DEFAULT_MODE


def write_mode(mode: str) -> None:
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f'mode = "{mode}"\n')


# Subcommands whose only job is to relay to a device method with **flags.
def _add_common_rf(p: argparse.ArgumentParser,
                   freq_required: bool = True) -> None:
    p.add_argument("-f", "--frequency", type=parse_freq, required=freq_required,
                   help="center frequency (e.g. 433.92M, 1.09G, or Hz)")
    p.add_argument("-s", "--sample-rate", dest="sample_rate", type=parse_freq,
                   default=8e6, help="sample rate (default 8M)")
    p.add_argument("--force", action="store_true",
                   help="downgrade out-of-range rejects to warnings")
    p.add_argument("--print-cmd", dest="print_cmd", action="store_true",
                   help="print the hackrf_* command without running it")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--serial", help="select a board by serial number "
                   "(multi-board setups)")


class HackRFCLI:
    def __init__(self, a: Sequence[str] | None = None) -> None:
        main_parser = argparse.ArgumentParser(prog="hrf", description="hackrfpy")
        main_parser.add_argument("--version", action="version",
                                 version=f"%(prog)s {_VERSION}")
        sub = main_parser.add_subparsers(dest="subparser_name")

        # info
        sp = sub.add_parser("info", help="device + firmware info")
        sp.add_argument("--raw", action="store_true")
        sp.add_argument("-v", "--verbose", action="store_true")
        sp.add_argument("--print-cmd", dest="print_cmd", action="store_true")

        # detect
        sp = sub.add_parser("detect",
                            help="autodetect + identify connected HackRF(s)")
        sp.add_argument("-v", "--verbose", action="store_true")

        # doctor
        sp = sub.add_parser("doctor", help="environment / preflight check")
        sp.add_argument("--path", default=".", help="disk to check for capture")

        # mode
        sp = sub.add_parser("mode", help="get/set operating mode (rx|tx)")
        sp.add_argument("value", nargs="?", choices=C.MODES,
                        help="omit to print current mode")

        # rx / capture (-f optional HERE because --preset can supply it;
        # main() enforces that one of the two resolves a frequency)
        sp = sub.add_parser("rx", help="receive IQ to a file")
        _add_common_rf(sp, freq_required=False)
        sp.add_argument("-o", "--out", default="capture.iq")
        sp.add_argument("-n", "--num-samples", dest="num_samples", type=int)
        sp.add_argument("-d", "--duration", type=float, help="seconds")
        sp.add_argument("-l", "--lna", type=int, default=16)
        sp.add_argument("-g", "--vga", type=int, default=20)
        sp.add_argument("-a", "--amp", action="store_true")
        sp.add_argument("--bias-tee", dest="bias_tee", action="store_true")
        sp.add_argument("--bw", dest="baseband_bw", type=parse_freq)
        sp.add_argument("--segment", dest="segment_secs", type=float,
                        help="rolling files of N seconds each")
        sp.add_argument("--no-sigmf", dest="sigmf", action="store_false")
        sp.add_argument("--preset", help="apply a band preset for freq/rate")

        # tx
        sp = sub.add_parser("tx", help="transmit IQ from a file, or a CW "
                                       "test tone with --cw (TX mode only)")
        _add_common_rf(sp)
        sp.add_argument("source", nargs="?", default=None,
                        help="int8 I/Q file to transmit (omit with --cw)")
        sp.add_argument("--cw", action="store_true",
                        help="transmit a constant-wave test tone instead of "
                             "a file; requires -d/--duration")
        sp.add_argument("--cw-amplitude", dest="cw_amplitude", type=int,
                        default=64, help="CW DAC amplitude 0-127 (default 64, "
                                         "deliberately below full scale)")
        sp.add_argument("-x", "--txvga", type=int, default=20)
        sp.add_argument("-a", "--amp", action="store_true")
        sp.add_argument("--bias-tee", dest="bias_tee", action="store_true")
        sp.add_argument("--bw", dest="baseband_bw", type=parse_freq)
        sp.add_argument("-R", "--repeat", action="store_true")
        sp.add_argument("-n", "--num-samples", dest="num_samples", type=int)
        sp.add_argument("-d", "--duration", type=float)
        sp.add_argument("--max-duration", dest="max_duration", type=float,
                        help="hard time cap (s), enforced even for --repeat")

        # sweep
        sp = sub.add_parser("sweep", help="spectrum sweep (CSV to stdout)")
        sp.add_argument("--f-min", dest="f_min", type=parse_freq, required=True)
        sp.add_argument("--f-max", dest="f_max", type=parse_freq, required=True)
        sp.add_argument("-w", "--bin-width", dest="bin_width", type=parse_freq)
        sp.add_argument("-l", "--lna", type=int, default=16)
        sp.add_argument("-g", "--vga", type=int, default=20)
        sp.add_argument("-a", "--amp", action="store_true")
        sp.add_argument("-1", "--one-shot", dest="one_shot", action="store_true")
        sp.add_argument("-N", "--num-sweeps", dest="num_sweeps", type=int)
        sp.add_argument("-o", "--out", default=None,
                        help="write via hackrf_sweep -r FILE instead of "
                             "parsing to stdout (required for -B / -I)")
        sp.add_argument("-B", "--binary", action="store_true",
                        help="raw binary bins (unparsed passthrough)")
        sp.add_argument("-I", "--inverse-fft", dest="inverse_fft",
                        action="store_true",
                        help="inverse FFT binary output (unparsed passthrough)")
        sp.add_argument("--force", action="store_true")
        sp.add_argument("--print-cmd", dest="print_cmd", action="store_true")
        sp.add_argument("-v", "--verbose", action="store_true")
        sp.add_argument("--serial", help="select a board by serial number")

        # monitor
        sp = sub.add_parser("monitor", help="power over time on several "
                                            "frequencies via one sweep")
        sp.add_argument("freqs", nargs="+", type=parse_freq,
                        help="frequencies to watch (parse_freq notation)")
        sp.add_argument("--span", type=parse_freq, default=2e6,
                        help="sweep margin around watched freqs (default 2M)")
        sp.add_argument("-d", "--duration", type=float, default=None,
                        help="seconds to run (default: until Ctrl-C)")
        sp.add_argument("-l", "--lna", type=int, default=16)
        sp.add_argument("-g", "--vga", type=int, default=20)
        sp.add_argument("-a", "--amp", action="store_true")
        sp.add_argument("--force", action="store_true")
        sp.add_argument("-v", "--verbose", action="store_true")
        sp.add_argument("--serial", help="select a board by serial number")

        # scan
        sp = sub.add_parser("scan", help="capture IQ at several frequencies; "
                                         "print power per frequency")
        sp.add_argument("freqs", nargs="+", type=parse_freq,
                        help="frequencies to visit (parse_freq notation)")
        sp.add_argument("-s", "--sample-rate", dest="sample_rate",
                        type=parse_freq, default=8e6)
        sp.add_argument("-n", "--num-samples", dest="num_samples", type=int,
                        default=262144)
        sp.add_argument("-l", "--lna", type=int, default=16)
        sp.add_argument("-g", "--vga", type=int, default=20)
        sp.add_argument("-a", "--amp", action="store_true")
        sp.add_argument("--force", action="store_true")
        sp.add_argument("-v", "--verbose", action="store_true")
        sp.add_argument("--serial", help="select a board by serial number")

        # presets
        sp = sub.add_parser("presets", help="list band presets")

        self.args = main_parser.parse_args(a)
        self._parser = main_parser

    def getArgs(self) -> argparse.Namespace:
        return self.args

    def _make_device(self, args: argparse.Namespace) -> HackRF:
        h = HackRF(verbose=getattr(args, "verbose", False),
                   serial=getattr(args, "serial", None))
        h.allow_out_of_spec = getattr(args, "force", False)
        # restore persisted mode so rx/tx/sweep honor it across invocations
        h.restore_mode(read_mode())
        return h

    def main(self, args: argparse.Namespace) -> None:
        name = args.subparser_name
        if name is None:
            self._parser.print_help()
            return

        if name == "presets":
            for k, v in sorted(P.load_presets().items()):
                print(f"  {k:10} {v.get('desc','')}")
            return

        if name == "mode":
            if args.value is None:
                print(read_mode())
            else:
                h = HackRF()
                h.restore_mode(read_mode())  # so the banner fires only on a
                h.set_mode(args.value)       # real rx -> tx switch
                write_mode(args.value)
            return

        h = self._make_device(args)

        if name == "info":
            res = h.info(raw=args.raw, print_cmd=args.print_cmd)
            if not args.print_cmd:
                print(res)

        elif name == "detect":
            det = h.detect()
            _print_detect(det)
            # exit non-zero when not ready, so `hrf detect && hrf rx ...` works
            if not det["ready"]:
                sys.exit(1)

        elif name == "doctor":
            report = h.doctor(capture_path=args.path)
            if report["problems"]:
                sys.exit(1)   # make preflight usable in `doctor && capture`

        elif name == "rx":
            if getattr(args, "preset", None):
                pre = P.get_preset(args.preset)
                if args.frequency is None:
                    args.frequency = pre.get("center") or pre.get("f_min")
                args.sample_rate = pre.get("sample_rate", args.sample_rate)
            if args.frequency is None:
                raise HackRFValueError(
                    "rx needs a frequency: pass -f/--frequency or --preset")
            h.capture(args.frequency, args.sample_rate, out=args.out,
                      num_samples=args.num_samples, duration=args.duration,
                      lna=args.lna, vga=args.vga, amp=args.amp,
                      bias_tee=args.bias_tee, baseband_bw=args.baseband_bw,
                      sigmf=args.sigmf, segment_secs=args.segment_secs,
                      print_cmd=args.print_cmd)

        elif name == "tx":
            if args.cw and args.source:
                raise HackRFValueError("--cw and a source file are mutually "
                                       "exclusive")
            if args.cw:
                if not args.duration and not args.print_cmd:
                    raise HackRFValueError(
                        "tx --cw requires -d/--duration: a CW carrier with "
                        "no time bound is exactly the orphan-transmitter "
                        "risk the library exists to prevent")
                h.transmit_cw(args.frequency, args.sample_rate,
                              amplitude=args.cw_amplitude, txvga=args.txvga,
                              amp=args.amp, bias_tee=args.bias_tee,
                              baseband_bw=args.baseband_bw,
                              duration=args.duration,
                              max_duration=args.max_duration,
                              print_cmd=args.print_cmd)
                return
            if not args.source:
                raise HackRFValueError("tx needs a source file (or --cw)")
            h.transmit(args.frequency, args.sample_rate, args.source,
                       txvga=args.txvga, amp=args.amp, bias_tee=args.bias_tee,
                       baseband_bw=args.baseband_bw, repeat=args.repeat,
                       num_samples=args.num_samples, duration=args.duration,
                       max_duration=args.max_duration,
                       print_cmd=args.print_cmd)

        elif name == "sweep":
            if (args.binary or args.inverse_fft) and not args.out:
                raise HackRFValueError(
                    "-B / -I produce unparsed binary that cannot go to the "
                    "CSV stdout path; pass -o/--out FILE")
            if args.out:
                h.sweep_to_file(args.f_min, args.f_max, args.out,
                                binary=args.binary,
                                inverse_fft=args.inverse_fft,
                                bin_width=args.bin_width, lna=args.lna,
                                vga=args.vga, amp=args.amp,
                                one_shot=args.one_shot,
                                num_sweeps=args.num_sweeps,
                                print_cmd=args.print_cmd)
                return
            gen = h.sweep(args.f_min, args.f_max, bin_width=args.bin_width,
                          lna=args.lna, vga=args.vga, amp=args.amp,
                          one_shot=args.one_shot, num_sweeps=args.num_sweeps,
                          print_cmd=args.print_cmd)
            if gen is not None:
                # CSV to stdout, as documented -- same shape hackrf_sweep
                # emits, so it round-trips through parse_sweep_line and pipes
                # cleanly into other tools.
                for row in gen:
                    print(", ".join(
                        [row["date"], row["time"],
                         str(row["hz_low"]), str(row["hz_high"]),
                         f"{row['bin_width']:.2f}", str(row["num_samples"])]
                        + [f"{d:.2f}" for d in row["db"]]))

        elif name == "monitor":
            def _print_update(update: dict[float, Any]) -> None:
                for f, db in sorted(update.items()):
                    val = "--" if db is None else f"{db:.1f}"
                    print(f"{f/1e6:.3f} MHz  {val} dB", flush=True)
            h.monitor_frequencies(list(args.freqs), span_hz=args.span,
                                  duration=args.duration,
                                  on_update=_print_update, lna=args.lna,
                                  vga=args.vga, amp=args.amp)

        elif name == "scan":
            results = h.scan_frequencies(list(args.freqs), args.sample_rate,
                                         args.num_samples, lna=args.lna,
                                         vga=args.vga, amp=args.amp)
            for f in args.freqs:
                iq = (results or {}).get(f)
                if iq is None or not len(iq):
                    print(f"{f/1e6:.3f} MHz  --")
                else:
                    print(f"{f/1e6:.3f} MHz  {h.power_dbfs(iq):.1f} dBFS")


def main() -> None:
    app = HackRFCLI()
    try:
        app.main(app.getArgs())
    except HackRFError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
