"""End-to-end automatic placement and routing of benchmarks/moto/moto.json.

Uses the raw MOTO benchmark, without a saved reference placement. The test
fails unless the independent electrical verifier and grid geometry audits pass.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from pathlib import Path

from solve.placement_feedback import solve_with_feedback
from solve.verify import verify_project
from solve.quick_rules import quick_audit
from solve.quality_audit import audit_project

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "benchmarks/moto/moto.json"


def run(attempts: int = 24, clearance: int = 1) -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if source.get("board", {}).get("cuts") or source.get("board", {}).get("wires"):
        raise ValueError("MOTO test fixture must have no pre-existing routing")
    return solve_with_feedback(source, attempts=attempts, clearance=clearance,
                               router="hole_graph", quick_backtracks=0)


def _worker(queue, attempts, clearance, output):
    try:
        result = run(attempts=attempts, clearance=clearance)
        summary = {key: value for key, value in result.items() if key != "project"}
        if result["status"] == "ROUTED":
            project = result["project"]
            electrical = verify_project(project)
            geometry = quick_audit(project)
            physical = audit_project(project)
            summary["independent_verification"] = electrical["status"]
            summary["grid_geometry"] = geometry["status"]
            summary["physical_audit"] = physical["status"]
            if (electrical["status"] != "PASS" or geometry["status"] == "FAIL"
                    or physical["status"] != "PASS"):
                summary["status"] = "VERIFICATION_FAILED"
                summary["error"] = (electrical["errors"] + geometry["errors"] +
                                    physical["errors"])[:8]
            else:
                summary["cuts"] = len(project["board"]["cuts"])
                summary["wires"] = len(project["board"]["wires"])
                if output:
                    Path(output).write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
                    summary["output"] = output
        queue.put(summary)
    except Exception as exc:
        queue.put({"status": "EXCEPTION", "attempts_used": 0,
                   "error": f"{type(exc).__name__}: {exc}"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--clearance", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    queue = mp.Queue()
    process = mp.Process(target=_worker, args=(queue, args.attempts, args.clearance,
                                               str(args.out) if args.out else None))
    process.start()
    process.join(args.timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        print(f"STATUS=TIMEOUT LIMIT_SECONDS={args.timeout}")
        return 124
    if queue.empty():
        print(f"STATUS=PROCESS_EXITED EXIT_CODE={process.exitcode}")
        return 1
    result = queue.get()
    print(f"STATUS={result['status']} ATTEMPTS={result.get('attempts_used')}")
    if result["status"] == "ROUTED":
        print(f"VERIFICATION={result['independent_verification']} "
              f"CUTS={result['cuts']} JUMPERS={result['wires']} "
              f"VARIANT={result['placement_variant']}")
        if result.get("output"):
            print(f"ROUTED_BOARD={result['output']}")
    else:
        print(f"BEST_FAILURE={result.get('best_failure')}")
        if result.get("error"):
            print(f"ERROR={result['error']}")
    if args.json:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ROUTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
