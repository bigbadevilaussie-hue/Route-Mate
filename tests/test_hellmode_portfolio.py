"""Multi-seed electrical-alpha search and deterministic output contract."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from hellmode.demo import (
    optimize, optimize_portfolio, run_files, _priority, _electrically_valid,
)


ROOT = Path(__file__).resolve().parent.parent
MOTOMIX = ROOT / "benchmarks/moto/motomix-autorouted.json"


class PortfolioSmokeTests(unittest.TestCase):
    def test_seed_sweep_selects_best_actual_candidate_without_mutating_input(self):
        project = json.loads(MOTOMIX.read_text())
        original = copy.deepcopy(project)
        winner, record = optimize_portfolio(
            project, moves=16, seed=10, seeds=3
        )
        samples = [
            optimize(project, moves=16, seed=index)
            for index in (10, 11, 12)
        ]
        index = min(range(3), key=lambda i: (
            _priority(samples[i][1]["best_exploratory"]), 10 + i
        ))
        self.assertEqual(winner, samples[index][0])
        self.assertEqual(record["seed"], 10 + index)
        self.assertEqual(record["portfolio"]["seeds_tested"], 3)
        self.assertEqual(record["portfolio"]["total_moves_requested"], 48)
        self.assertEqual(project, original)
        self.assertTrue(_electrically_valid(winner))
        self.assertFalse(record["record_eligible"])
        self.assertFalse(record["physical_pass"])

    def test_portfolio_repeats_same_output_and_selection(self):
        project = json.loads(MOTOMIX.read_text())
        a, report_a = optimize_portfolio(
            project, moves=10, seed=31, seeds=2
        )
        b, report_b = optimize_portfolio(
            project, moves=10, seed=31, seeds=2
        )
        self.assertEqual(a, b)
        self.assertEqual(report_a, report_b)

    def test_rejects_zero_or_negative_restart_count(self):
        project = json.loads(MOTOMIX.read_text())
        for count in (0, -1):
            with self.subTest(count=count), self.assertRaises(ValueError):
                optimize_portfolio(project, moves=0, seed=1, seeds=count)

    def test_writes_winning_seed_in_replayable_manifest(self):
        project = json.loads(MOTOMIX.read_text())
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "motomix.json"
            source.write_text(json.dumps(project))
            result = base / "output"
            report = run_files(source, result, moves=5, seed=3, seeds=2)
            written = json.loads((result / "run.json").read_text())
            self.assertEqual(written["portfolio"]["start_seed"], 3)
            self.assertEqual(written["portfolio"]["seeds_tested"], 2)
            self.assertEqual(written["portfolio"]["winning_seed"], report["seed"])
            self.assertTrue(_electrically_valid(
                json.loads((result / "best_electrical.json").read_text())
            ))
            self.assertFalse((result / "best_solved.json").exists())


if __name__ == "__main__":
    unittest.main()
