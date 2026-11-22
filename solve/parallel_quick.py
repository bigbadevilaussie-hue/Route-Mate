"""Fixed-budget, multi-process Quick Solve portfolio for the desktop GUI.

Each process uses the existing placement-feedback, routing and independent
verification engine. Worker count changes latency, not the attempt budget.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import get_context
from os import getpid
from queue import Empty
from typing import Any, Callable

from .solution_quality import candidate_quality, solution_signature


def choose_workers(recommended: int, logical_cpus: int) -> int:
    """User-requested three/four-process desktop policy, capped by CPU count."""
    available = max(1, min(4, int(logical_cpus)))
    if available < 3:
        return available
    return min(available, max(3, int(recommended)))


def partition_attempts(attempts: int, workers: int) -> list[tuple[int, int]]:
    """Disjoint deterministic placement-variant ranges, no extra evaluations."""
    if attempts < 1 or workers < 1:
        raise ValueError("attempts and workers must be positive")
    workers = min(workers, attempts)
    base, remainder = divmod(attempts, workers)
    plan, offset = [], 0
    for index in range(workers):
        count = base + int(index < remainder)
        plan.append((offset, count))
        offset += count
    return plan


def _process_job(project: dict[str, Any], quota: int, offset: int,
                 body_spacing_holes: int, job_index: int,
                 messages: Any, stop_flag: Any) -> dict[str, Any]:
    """Picklable top-level function executed in a real OS process."""
    from .desktop_integration import solve_for_display

    def notify(event: dict[str, Any]) -> None:
        # Keep IPC small: the GUI needs status, timing and current anchor,
        # not full per-route graph expansion diagnostics on every attempt.
        brief = {key: value for key, value in event.items()
                 if key != "last"}
        last = event.get("last") or {}
        brief["last"] = {
            key: last.get(key) for key in (
                "variant", "placement", "routing", "error",
                "cuts", "wires", "slide_positions",
            ) if key in last
        }
        messages.put((job_index, brief))

    result = solve_for_display(
        project, attempts=quota, variant_offset=offset,
        body_spacing_holes=body_spacing_holes, solutions_target=2,
        progress=notify, cancelled=stop_flag.is_set,
    )
    result["_worker_pid"] = getpid()
    return result


def solve_parallel_for_display(
    project: dict[str, Any], *, workers: int = 3,
    attempts: int = 24, body_spacing_holes: int = 1,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Find up to two distinct verified solutions per worker; rank only PASSes.

    The entire portfolio owns exactly `attempts` placement-evaluation slots.
    A second layout cannot be guaranteed when none exists within that budget.
    """
    from .desktop_integration import solve_for_display

    if not 1 <= attempts <= 100:
        raise ValueError("attempts must be between 1 and 100")
    if body_spacing_holes not in (0, 1, 2):
        raise ValueError("body_spacing_holes must be 0, 1 or 2")
    plan = partition_attempts(attempts, workers)
    if cancelled is not None and cancelled():
        return {"status": "CANCELLED", "project": None, "attempts_used": 0,
                "errors": ["Quick Solve stopped by user."], "history": []}
    if len(plan) == 1:
        result = solve_for_display(
            project, attempts=attempts, body_spacing_holes=body_spacing_holes,
            solutions_target=2, progress=progress, cancelled=cancelled,
        )
        signatures = list(dict.fromkeys(result.get("solution_signatures") or
                                         ([solution_signature(result["project"])]
                                          if result.get("status") == "ROUTED" else [])))
        result["portfolio"] = {
            "workers": 1, "attempts_budget": attempts,
            "attempts_used": result.get("attempts_used", 0),
            "solutions_found": len(signatures),
            "target": 2, "verified_candidates": int(result.get("status") == "ROUTED"),
        }
        return result

    context = get_context("spawn")
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    completed = [0] * len(plan)
    budgets = [quota for _, quota in plan]

    with context.Manager() as manager:
        messages = manager.Queue()
        stop_flag = manager.Event()
        with ProcessPoolExecutor(max_workers=len(plan), mp_context=context) as pool:
            future_to_job = {
                pool.submit(_process_job, project, quota, offset,
                            body_spacing_holes, index, messages, stop_flag): index
                for index, (offset, quota) in enumerate(plan)
            }
            pending = set(future_to_job)
            while pending:
                if cancelled is not None and cancelled():
                    stop_flag.set()
                # Deliver per-attempt progress without blocking the Qt GUI.
                try:
                    index, update = messages.get(timeout=0.12)
                    completed[index] = max(completed[index],
                                           int(update.get("completed", 0)))
                    budgets[index] = max(budgets[index],
                                          int(update.get("budget", budgets[index])))
                    if progress is not None:
                        progress({
                            **update, "mode": "parallel",
                            "worker": index + 1, "workers": len(plan),
                            "completed": sum(completed), "budget": sum(budgets),
                            "worker_completed": completed[index],
                            "worker_budget": budgets[index],
                        })
                except Empty:
                    pass
                finished, pending = wait(pending, timeout=0.02,
                                         return_when=FIRST_COMPLETED)
                for future in finished:
                    index = future_to_job[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        failures.append(f"worker {index + 1}: {exc}")
                        result = {"status": "WORKER_FAILED", "project": None,
                                  "attempts_used": 0, "errors": [str(exc)]}
                    results.append(result)
                    completed[index] = max(completed[index],
                                           int(result.get("attempts_used", 0)))
                    if progress is not None:
                        progress({
                            "mode": "parallel", "worker": index + 1,
                            "workers": len(plan), "worker_finished": True,
                            "completed": sum(completed), "budget": sum(budgets),
                            "solutions_found": sum(
                                int(r.get("solutions_found", 0))
                                for r in results if r.get("status") == "ROUTED"
                            ),
                            "last": {"placement": result.get("status"),
                                     "routing": result.get("status")},
                            "seconds": 0.0,
                        })

    total_used = sum(int(r.get("attempts_used", 0)) for r in results)
    if cancelled is not None and cancelled():
        return {"status": "CANCELLED", "project": None,
                "attempts_used": total_used, "history": [],
                "errors": ["Quick Solve stopped by user."]}
    verified = [r for r in results if r.get("status") == "ROUTED"
                and isinstance(r.get("project"), dict)]
    signatures = set()
    ranked = []
    for result in verified:
        signatures.update(result.get("solution_signatures") or
                          [solution_signature(result["project"])])
        ranked.append((candidate_quality(result["project"])["rank"], result))
    portfolio = {
        "workers": len(plan), "attempts_budget": attempts,
        "attempts_used": total_used, "target": 2,
        "solutions_found": len(signatures),
        "verified_candidates": len(verified),
        "worker_failures": failures,
        "worker_pids": sorted({int(r["_worker_pid"]) for r in results
                               if r.get("_worker_pid") is not None}),
        "strategy": "fixed-budget deterministic variant partition",
    }
    if ranked:
        ranked.sort(key=lambda item: item[0])
        chosen = ranked[0][1]
        chosen["attempts_used"] = total_used
        chosen["portfolio"] = portfolio
        chosen["solutions_found"] = len(signatures)
        chosen["warnings"] = list(chosen.get("warnings") or [])
        if len(signatures) < 2:
            chosen["warnings"].append(
                "Only one distinct verified layout was found within the fixed "
                "Quick Solve budget; a second cannot be guaranteed."
            )
        if failures:
            chosen["warnings"].append("; ".join(failures))
        return chosen
    if failures and len(failures) == len(plan):
        raise RuntimeError("All Quick Solve processes failed: " + "; ".join(failures))
    return {
        "status": "ROUTING_FAILED", "project": None, "history": [],
        "attempts_used": total_used, "portfolio": portfolio,
        "errors": ["No independently verified route found in the fixed "
                   f"{attempts}-attempt portfolio."] + failures,
    }


__all__ = ["choose_workers", "partition_attempts", "solve_parallel_for_display"]
