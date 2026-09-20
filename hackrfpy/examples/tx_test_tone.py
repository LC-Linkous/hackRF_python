#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/tx_test_tone.py'
#   The library's TX side, demonstrated the SAFE way: the deliberate
#   RX->TX mode switch (which prints the safety banner), a constant-wave
#   test tone via transmit_cw, and the dead-man duration bound so the
#   transmitter can never outlive the script.
#
#   This is the only example that transmits. It is deliberately timid:
#     - duration is REQUIRED and capped at 10 s
#     - txvga defaults low; the RF amp is never enabled here
#     - --print-cmd previews the exact hackrf_transfer command w/o running
#
#   TRANSMITTING IS REGULATED. Use a dummy load or a shielded setup, and
#   operate only within your license privileges and local law. A CW
#   carrier is useful for antenna checks and for giving a nearby receiver
#   (or your own second SDR) a known signal to find.
#
#   Usage:
#     uv run python examples/tx_test_tone.py --freq 433.92M --seconds 2
#     uv run python examples/tx_test_tone.py --freq 915M --seconds 2 --print-cmd
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\
import argparse
import sys

from hackrfpy import HackRF, parse_freq

MAX_SECONDS = 10.0


def main():
    p = argparse.ArgumentParser(
        description="Bounded CW test-tone transmit (TX-gated).")
    p.add_argument("--freq", required=True,
                   help="carrier frequency (parse_freq notation, e.g. 433.92M)")
    p.add_argument("--rate", default="2M", help="sample rate (default 2M)")
    p.add_argument("--seconds", type=float, required=True,
                   help=f"transmit duration; required, max {MAX_SECONDS:g}s")
    p.add_argument("--txvga", type=int, default=4,
                   help="TX VGA gain dB (default 4, deliberately low)")
    p.add_argument("--amplitude", type=int, default=64,
                   help="CW DAC amplitude 0-127 (default 64)")
    p.add_argument("--print-cmd", action="store_true",
                   help="preview the command without transmitting")
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()

    if not args.print_cmd and not 0 < args.seconds <= MAX_SECONDS:
        print(f"--seconds must be in (0, {MAX_SECONDS:g}]", file=sys.stderr)
        return 2

    h = HackRF(tools_dir=args.tools_dir, verbose=True)
    freq, rate = parse_freq(args.freq), parse_freq(args.rate)

    # The deliberate confirmation: transmit() refuses in the default RX
    # mode, and this switch prints the one-time TX safety banner.
    h.set_mode("tx")
    h.transmit_cw(freq, rate, amplitude=args.amplitude, txvga=args.txvga,
                  duration=args.seconds, print_cmd=args.print_cmd)
    h.set_mode("rx")            # leave the object safe for whatever follows
    if not args.print_cmd:
        print(f"[*] transmitted {args.seconds:g}s CW at {freq/1e6:g} MHz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
