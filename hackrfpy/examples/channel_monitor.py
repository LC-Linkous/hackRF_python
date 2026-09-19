#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/channel_monitor.py'
#   Watch POWER over time on several frequencies at once, backed by one
#   continuous hackrf_sweep (monitor_frequencies). Demonstrates the
#   library's third acquisition style, distinct from the other two:
#     - capture()/open_receiver()  -> IQ samples at ONE frequency
#     - scan_frequencies()         -> IQ samples at several (re-open gaps)
#     - monitor_frequencies() this -> POWER ONLY at several, gap-free via
#                                     the sweep's fast hardware retuning
#
#   Prints a live per-channel bar meter; no plotting extra needed.
#   Read-only / receive-only.
#
#   Usage:
#     uv run python examples/channel_monitor.py
#     uv run python examples/channel_monitor.py --freq 433.92M --freq 915M \
#         --duration 30
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\
import argparse
import os
import sys

from hackrfpy import HackRF, parse_freq

BAR_FLOOR, BAR_CEIL, BAR_WIDTH = -80.0, -20.0, 40


def bar(db):
    if db is None:
        return "?" * 3
    frac = (min(max(db, BAR_FLOOR), BAR_CEIL) - BAR_FLOOR) / (BAR_CEIL - BAR_FLOOR)
    n = int(frac * BAR_WIDTH)
    return "#" * n + "." * (BAR_WIDTH - n)


def main():
    p = argparse.ArgumentParser(
        description="Multi-channel power monitor via one sweep (read-only).")
    p.add_argument("--freq", action="append",
                   help="frequency to watch (repeatable; parse_freq notation "
                        "like 433.92M). Default: 98M, 433.92M, 915M")
    p.add_argument("--span", default="2M",
                   help="sweep margin around min/max watched freq (default 2M)")
    p.add_argument("--duration", type=float, default=None,
                   help="seconds to run (default: until Ctrl-C)")
    p.add_argument("--lna", type=int, default=16)
    p.add_argument("--vga", type=int, default=20)
    p.add_argument("--tools-dir", default=None)
    args = p.parse_args()
    freqs = [parse_freq(f) for f in (args.freq or ["98M", "433.92M", "915M"])]

    h = HackRF(tools_dir=args.tools_dir)
    labels = {f: f"{f/1e6:9.3f} MHz" for f in freqs}
    print("[*] monitoring "
          + ", ".join(l.strip() for l in labels.values())
          + "   (Ctrl-C to stop)")

    # In-place redraw: this is a live METER, so each update overwrites the
    # previous frame instead of scrolling a log. os.system("") on Windows
    # switches the classic console into ANSI/VT mode (a documented quirk:
    # spawning any shell command enables VT processing); it is a no-op
    # elsewhere. Piped/redirected output falls back to scrolling so logs
    # stay readable.
    if os.name == "nt":
        os.system("")
    redraw_in_place = sys.stdout.isatty()
    frame_state = {"drawn": False}

    def on_update(update):
        lines = [f"  {labels[f]}  {bar(db)}  "
                 f"{'--' if db is None else f'{db:6.1f} dB'}"
                 for f, db in update.items()]
        if redraw_in_place:
            if frame_state["drawn"]:
                # move the cursor up over the previous frame
                sys.stdout.write(f"\x1b[{len(lines)}A")
            # \x1b[2K clears each line so shorter bars leave no residue
            sys.stdout.write("\n".join("\x1b[2K" + ln for ln in lines) + "\n")
            sys.stdout.flush()
            frame_state["drawn"] = True
        else:
            print("\n".join(lines) + "\n")

    try:
        h.monitor_frequencies(freqs, span_hz=parse_freq(args.span),
                              duration=args.duration, on_update=on_update,
                              lna=args.lna, vga=args.vga)
    except KeyboardInterrupt:
        pass
    print("[*] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
