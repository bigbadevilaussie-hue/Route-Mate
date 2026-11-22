"""Reproduce automated AUDIO placement, routing, verification and export.

Usage: python3 benchmark_audio_feedback.py --attempts 8 --out /tmp/audio-autorouted.json
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
from pathlib import Path

from placement_policy import is_off_board_component
from solve.placement_feedback import solve_with_feedback

ROOT = Path(__file__).resolve().parent


def run(attempts: int, backtracks: int, *, use_sidecar: bool = False) -> dict:
    reference = json.loads((ROOT / "benchmarks/audio/audio10wires38cuts.json").read_text(encoding="utf-8"))
    if use_sidecar:
        sidecar = ROOT / "benchmarks/audio/audio.routemate-state.json"
        state = json.loads(sidecar.read_text(encoding="utf-8"))
        project = copy.deepcopy(state["pipeline"]["stages"]["SOLVE.quick_fit"]["report"]["result"]["project"])
    else:
        # ALWAYS strip component positions: the reference supplies the netlist,
        # footprint definitions and off-board lead pads, NOT its placement.
        project = copy.deepcopy(reference)
    reference_by_id = {str(c.get("id")): c for c in reference.get("components", []) if isinstance(c, dict)}
    for component in project.get("components", []):
        if not isinstance(component, dict):
            continue
        cid = str(component.get("id"))
        if is_off_board_component(component):
            source = reference_by_id.get(cid, {})
            if component.get("boardExcluded") is None and source.get("boardExcluded") is True and source.get("offBoard") is not True:
                component["boardExcluded"] = True
            if not isinstance(component.get("leads"), dict) and isinstance(source.get("leads"), dict):
                component["leads"] = copy.deepcopy(source["leads"])
        elif component.get("locked") is not True:
            component.pop("boardPos", None)
            component.pop("flexibleEndPos", None)
    project.setdefault("board", {})["cuts"] = []
    project["board"]["wires"] = []
    return solve_with_feedback(project, attempts=attempts, quick_backtracks=backtracks)


def _benchmark_worker(queue, attempts, backtracks, use_sidecar, out):
    try:
        result = run(attempts, backtracks, use_sidecar=use_sidecar)
        summary = {k: v for k, v in result.items() if k != "project"}
        if out and result["status"] == "ROUTED":
            destination = Path(out)
            destination.write_text(json.dumps(result["project"], indent=2) + "\n", encoding="utf-8")
            summary["output"] = str(destination)
        queue.put(summary)
    except Exception as exc:
        queue.put({"status": "EXCEPTION", "error": str(exc), "attempts_used": 0})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--backtracks", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--use-sidecar", action="store_true")
    parser.add_argument("--out", type=Path, help="write fully verified routed project JSON")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    queue = mp.Queue()
    process = mp.Process(target=_benchmark_worker, args=(queue, args.attempts, args.backtracks,
                                                   args.use_sidecar, str(args.out) if args.out else None))
    process.start()
    process.join(args.timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        print(f"STATUS=TIMEOUT LIMIT_SECONDS={args.timeout}")
        raise SystemExit(124)
    if queue.empty():
        print(f"STATUS=PROCESS_EXITED EXIT_CODE={process.exitcode}")
        raise SystemExit(1)
    result = queue.get()
    print(f"STATUS={result['status']} ATTEMPTS={result['attempts_used']}")
    if result["status"] == "ROUTED":
        print(f"VERIFICATION={result['verification'].get('status')} VARIANT={result['placement_variant']}")
        if result.get("output"):
            print(f"ROUTED_BOARD={result['output']}")
    else:
        print(f"BEST_FAILURE={result.get('best_failure')}")
        if result.get("error"):
            print(f"ERROR={result['error']}")
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "project"}, indent=2))
    raise SystemExit(0 if result["status"] == "ROUTED" else 1)
