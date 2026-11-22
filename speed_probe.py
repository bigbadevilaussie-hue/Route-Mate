"""Small, bounded CPU scaling probe for Route-Mate development machines.

No project files are read or written. Uses standard-library Python only.
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from time import perf_counter


def cpu_work(iterations: int) -> int:
    """Deterministic Python integer work, similar to CPU-bound search loops."""
    value = 0x12345678
    for i in range(iterations):
        value = ((value * 1664525 + 1013904223) ^ (i & 65535)) & 0xFFFFFFFF
    return value


def calibrate(seconds: float = 0.30) -> int:
    """Choose a total workload without assuming the user's CPU speed."""
    n = 100_000
    started = perf_counter()
    cpu_work(n)
    elapsed = max(perf_counter() - started, 0.001)
    estimated = int(n * (seconds / elapsed))
    return max(100_000, min(estimated, 5_000_000))


def run_processes(workers: int, total: int) -> tuple[float, int]:
    # Spawn is supported on macOS and avoids copying application state.
    chunks = [total // workers + (i < total % workers) for i in range(workers)]
    started = perf_counter()
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        results = list(pool.map(cpu_work, chunks))
    return perf_counter() - started, sum(results) & 0xFFFFFFFF


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Python CPU throughput with 1, 2, and 4 processes")
    parser.add_argument("--seconds", type=float, default=1.5,
                        help="target single-core workload seconds (default 1.5; max 3)")
    args = parser.parse_args()
    if not 0.2 <= args.seconds <= 3:
        parser.error("--seconds must be between 0.2 and 3")
    count = os.cpu_count() or 1
    print(f"[MAC] {platform.platform()} | Python {platform.python_version()} | logical CPUs={count}", flush=True)
    print("[PROBE] Warming up and calibrating a fixed Python workload...", flush=True)
    warm = calibrate()
    # Calibrate again using longer input to reduce clock-granularity error.
    started = perf_counter()
    cpu_work(warm)
    rate = warm / max(perf_counter() - started, 0.001)
    total = max(100_000, min(int(rate * args.seconds), 30_000_000))
    print(f"[PROBE] fixed work={total:,} iterations; same total work for each test", flush=True)

    timings = {}
    for workers in (1, 2, 4):
        if workers > count:
            continue
        print(f"[PROBE] {workers} worker(s) ...", flush=True)
        elapsed, checksum = run_processes(workers, total)
        timings[workers] = elapsed
        print(f"  {workers} worker(s): {elapsed:.3f}s | throughput={total / elapsed:,.0f} iterations/s "
              f"| checksum={checksum:08x}", flush=True)
    base = timings[1]
    print("[SCALING] speedup relative to 1 process (includes startup overhead):", flush=True)
    for workers, elapsed in timings.items():
        print(f"  {workers} worker(s): {base / elapsed:.2f}x", flush=True)
    print("[NOTE] This tests CPU scaling, not Route-Mate solver correctness or actual parallel speedup.", flush=True)


if __name__ == "__main__":
    main()
