#! /usr/bin/python3
##--------------------------------------------------------------------\
#   hackrfpy  'examples/benchmark.py'
#   Measure the real performance gaps, replacing the comparison doc's
#   hand-waving with numbers from YOUR hardware + machine. Read-only.
#
#   Measures three things:
#     1. Decode throughput (MB/s) -- pure CPU, no device. How fast the
#        int8->complex64 path runs vs the ~40 MB/s the device maxes at.
#     2. Sustained-rate drop test -- the important one. Capture at a target
#        sample rate and report whether hackrf_transfer dropped samples
#        (it warns on buffer overrun) and whether the consumer kept up.
#     3. Callback block cadence -- inter-block timing + jitter, the practical
#        proxy for "latency floor is the pipe."
#
#   IMPORTANT: results are specific to THIS board, machine, USB stack, and
#   system load. They are honest measurements, not universal claims. Run it a
#   few times; close other heavy apps for the drop test.
#
#   Usage:
#     uv run python examples/benchmark.py
#     uv run python examples/benchmark.py --rate 20e6 --seconds 3
#     uv run python examples/benchmark.py --tools-dir "C:\hackrf-tools-windows"
##--------------------------------------------------------------------\
import argparse
import sys
import time
import numpy as np
from hackrfpy import HackRF


def bench_decode(h):
    # pure decode throughput; no device needed
    print("\n== 1. decode throughput (CPU only) ==")
    block = np.random.randint(0, 256, 262144, dtype=np.uint8).tobytes()  # 256KB
    N = 2000
    mb = N * len(block) / 1e6
    t0 = time.perf_counter()
    for _ in range(N):
        h.decode_iq(block)
    dt = time.perf_counter() - t0
    rate = mb / dt
    print(f"   {rate:.0f} MB/s  ({rate/40:.1f}x the 40 MB/s device max @ 20 Msps)")
    print(f"   -> decode is {'NOT ' if rate > 80 else ''}a bottleneck at full rate")
    return rate


def bench_drop_test(h, rate, seconds):
    # the important one: does a sustained capture drop samples?
    #
    # MEASUREMENT NOTE: process spin-up (launching hackrf_transfer, USB setup,
    # device settling) is a fixed ~1-2s cost. Dividing total samples by total
    # wall-clock makes a short capture look slow even when every sample
    # arrived. So we measure STEADY STATE: discard a warm-up window, then time
    # only the samples after it. We also report whether the full requested
    # count actually arrived (no real loss).
    print(f"\n== 2. sustained drop test @ {rate/1e6:g} Msps for {seconds}s ==")
    n = int(rate * seconds)
    warmup_s = 1.5
    got = 0
    warm_got = 0
    warm_t0 = None
    t_start = time.perf_counter()
    try:
        with h.capture_stream(100_000_000, rate) as stream:
            for iq in stream:
                got += len(iq)
                now = time.perf_counter()
                if warm_t0 is None and (now - t_start) >= warmup_s:
                    warm_t0 = now
                    warm_got = 0
                elif warm_t0 is not None:
                    warm_got += len(iq)
                if got >= n:
                    break
    except Exception as e:
        print(f"   capture error: {e}", file=sys.stderr)
        return
    total_dt = time.perf_counter() - t_start
    steady_dt = (time.perf_counter() - warm_t0) if warm_t0 else None

    print(f"   received {got:,} of {n:,} requested ({100*got/n:.1f}%) "
          f"in {total_dt:.2f}s wall")
    if steady_dt and steady_dt > 0.2:
        steady_rate = warm_got / steady_dt / 1e6
        print(f"   STEADY-STATE rate (after {warmup_s}s warm-up): "
              f"{steady_rate:.1f} Msps  (target {rate/1e6:g})")
        if steady_rate >= rate / 1e6 * 0.95:
            print(f"   -> sustains {rate/1e6:g} Msps in steady state")
        else:
            print(f"   -> steady rate below target; possible real limit here")

    # Drop detection: authoritative hackrf_debug -S shortfall count + the
    # hackrf_transfer 'overruns' count from stderr.
    import re
    err = "".join(getattr(h, "_err_chunks", []))
    overruns = sum(int(m) for m in re.findall(r"(\d+)\s+overruns", err))
    shortfall = None
    try:
        out, _, _ = h._run(["debug", "-S"], mode="blocking", text=True)
        m = re.search(r"shortfall[^0-9]*(\d+)", out, re.I)
        if m:
            shortfall = int(m.group(1))
    except Exception:
        pass

    if got >= n * 0.999:
        print(f"   note: ~100% of requested samples received -- no bulk loss")
    if shortfall is not None:
        if shortfall == 0:
            print(f"   hackrf_debug -S: 0 shortfalls -- clean")
        elif shortfall <= 3:
            print(f"   hackrf_debug -S: {shortfall} shortfall(s) -- likely a "
                  f"startup transient, not sustained loss")
        else:
            print(f"   ! hackrf_debug -S: {shortfall} shortfalls -- real "
                  f"sustained drops at {rate/1e6:g} Msps on this machine")
    elif overruns:
        print(f"   hackrf_transfer reported {overruns} overruns")


def bench_callback_jitter(h, rate, seconds):
    # inter-block cadence + jitter -- the practical latency-floor proxy
    print(f"\n== 3. callback cadence @ {rate/1e6:g} Msps ==")
    stamps = []

    def on_block(iq, total):
        stamps.append(time.perf_counter())

    n = int(rate * seconds)
    try:
        h.capture_callback(100_000_000, rate, on_block=on_block, max_samples=n)
    except Exception as e:
        print(f"   error: {e}", file=sys.stderr)
        return
    if len(stamps) < 3:
        print("   too few blocks to measure")
        return
    gaps = np.diff(stamps) * 1000.0    # ms between callbacks
    print(f"   {len(stamps)} blocks; inter-block gap "
          f"mean {gaps.mean():.2f} ms, median {np.median(gaps):.2f} ms, "
          f"max {gaps.max():.2f} ms")
    print(f"   jitter (std): {gaps.std():.2f} ms")
    print(f"   -> practical block-delivery latency is ~{np.median(gaps):.1f} ms "
          f"on this machine (NOT antenna-to-callback; that needs a reference)")


def main():
    p = argparse.ArgumentParser(description="Measure real performance (read-only).")
    p.add_argument("--tools-dir", default=None)
    p.add_argument("--rate", type=float, default=20e6,
                   help="sample rate for the drop/jitter tests (default 20e6)")
    p.add_argument("--seconds", type=float, default=6.0,
                   help="capture duration for drop/jitter tests (default 6s; "
                        "the first ~1.5s is discarded as warm-up)")
    p.add_argument("--no-device", action="store_true",
                   help="decode benchmark only; no board needed")
    args = p.parse_args()

    h = HackRF(tools_dir=args.tools_dir)
    bench_decode(h)

    if args.no_device:
        return 0

    det = h.detect()
    if not det["ready"]:
        print(f"\nno usable HackRF for device tests: {det['problem']}",
              file=sys.stderr)
        return 1
    print(f"\n[*] board: firmware {det['boards'][0].get('firmware')}, "
          f"tools {det['tools_version']}")
    for w in det.get("warnings", []):
        print(f"   ! {w}  (relevant -- USB contention affects drop tests)")

    bench_drop_test(h, args.rate, args.seconds)
    bench_callback_jitter(h, args.rate, min(args.seconds, 2.0))

    print("\n== done ==")
    print("   These numbers are specific to this board/machine/USB/load.")
    print("   Re-run a few times; they're honest measurements, not universal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())