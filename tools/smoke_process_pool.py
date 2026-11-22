"""CLI smoke test proving Quick Solve executes in separate OS processes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from solve.parallel_quick import solve_parallel_for_display


def main() -> None:
    source = json.loads((ROOT / "benchmarks/audio/audio.json").read_text(encoding="utf-8"))
    result = solve_parallel_for_display(
        source, workers=3, attempts=3, body_spacing_holes=0,
    )
    info = result.get("portfolio") or {}
    pids = info.get("worker_pids") or []
    print(
        "MULTIPROCESS_SMOKE status=%s budget=%s used=%s pids=%s solutions=%s"
        % (result["status"], info.get("attempts_budget"),
           info.get("attempts_used"), pids, info.get("solutions_found")),
        flush=True,
    )
    assert info.get("workers") == 3, info
    assert info.get("attempts_budget") == 3, info
    assert 0 <= info.get("attempts_used", -1) <= 3, info
    assert len(set(pids)) == 3, (
        "Quick Solve must really run in three separate OS processes", info
    )


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    main()
