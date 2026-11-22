#!/usr/bin/env python3
"""Time the full unittest suite, show each test's wall time, rank bottlenecks.

Run: python3 time_tests.py
Writes: test_timings.json (ignored by git if requested; leave untracked).
Does not modify production code, test ordering, or the test assertions.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings = []
        self._started = {}

    def startTest(self, test):
        self._started[id(test)] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        start = self._started.pop(id(test), None)
        elapsed = time.perf_counter() - start if start is not None else None
        if elapsed is not None:
            self.timings.append({"test": test.id(), "seconds": round(elapsed, 6)})
            self.stream.writeln(f"    TIME {elapsed:9.4f}s  {test.id()}")
        super().stopTest(test)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-dir", default="tests")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--json", default="test_timings.json",
                        help="output report path; set to empty string to disable")
    args = parser.parse_args(argv)
    if args.top < 0:
        parser.error("--top must be >= 0")
    start = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(args.tests_dir, pattern="test*.py")
    runner = unittest.TextTestRunner(
        stream=sys.stdout, verbosity=1, resultclass=TimedResult, buffer=False
    )
    result = runner.run(suite)
    total = time.perf_counter() - start
    ranked = sorted(result.timings, key=lambda row: (-row["seconds"], row["test"]))
    summed = sum(row["seconds"] for row in ranked)
    print("\nSLOWEST TESTS")
    for n, item in enumerate(ranked[:args.top], 1):
        print(f"{n:3d}. {item['seconds']:9.4f}s  {item['test']}")
    print(f"\nTotal wall: {total:.3f}s | sum of individual test times: "
          f"{summed:.3f}s | recorded: {len(ranked)} / ran: {result.testsRun}")
    print(f"Outcome: {'PASS' if result.wasSuccessful() else 'FAIL'} "
          f"({len(result.failures)} failures, {len(result.errors)} errors, "
          f"{len(result.skipped)} skipped)")
    if args.json:
        report = {
            "schema": "route-mate/test-timings/1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version.split()[0],
            "tests_directory": args.tests_dir,
            "wall_seconds": round(total, 6),
            "sum_test_seconds": round(summed, 6),
            "ran": result.testsRun,
            "passed": result.wasSuccessful(),
            "failure_count": len(result.failures),
            "error_count": len(result.errors),
            "skipped_count": len(result.skipped),
            "slowest_first": ranked,
        }
        destination = Path(args.json)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"JSON report: {destination.resolve()}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
