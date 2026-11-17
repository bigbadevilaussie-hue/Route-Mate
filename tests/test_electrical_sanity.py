"""Regression tests for Route-Mate Electrical Sanity."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prepare.sanity.electrical import run_electrical_sanity


ROOT = Path(__file__).resolve().parents[1]


def load_project(name: str) -> dict:
    path = ROOT / "benchmarks" / name / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_netlist(name: str) -> str:
    path = ROOT / "benchmarks" / name / f"{name}.net"
    return path.read_text(encoding="utf-8")


class ElectricalSanityTests(unittest.TestCase):
    def test_moto_json_only_passes(self):
        report = run_electrical_sanity(load_project("moto"))
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertFalse(report["netlist_checked"])

    def test_audio_json_only_passes(self):
        report = run_electrical_sanity(load_project("audio"))
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertFalse(report["netlist_checked"])

    def test_moto_json_matches_netlist(self):
        report = run_electrical_sanity(load_project("moto"), load_netlist("moto"))
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertTrue(report["netlist_checked"])

    def test_audio_json_matches_netlist(self):
        report = run_electrical_sanity(load_project("audio"), load_netlist("audio"))
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertTrue(report["netlist_checked"])

    def test_rejects_duplicate_component_id(self):
        project = load_project("moto")
        project["components"][1]["id"] = project["components"][0]["id"]
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("duplicate component ID" in item for item in report["errors"]))

    def test_rejects_duplicate_net_id(self):
        project = load_project("moto")
        project["nets"][1]["id"] = project["nets"][0]["id"]
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("duplicate net ID" in item for item in report["errors"]))

    def test_rejects_assignment_to_missing_component(self):
        project = load_project("moto")
        project["netAssignments"][0]["componentId"] = "not-a-component"
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("unknown component" in item for item in report["errors"]))

    def test_rejects_assignment_to_missing_net(self):
        project = load_project("moto")
        project["netAssignments"][0]["netId"] = "not-a-net"
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("unknown net" in item for item in report["errors"]))

    def test_rejects_pin_assigned_to_two_nets(self):
        project = load_project("moto")
        duplicate = copy.deepcopy(project["netAssignments"][0])
        duplicate["netId"] = project["nets"][1]["id"]
        project["netAssignments"].append(duplicate)
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("assigned to multiple nets" in item for item in report["errors"]))

    def test_rejects_duplicate_assignment_to_same_net(self):
        project = load_project("moto")
        project["netAssignments"].append(copy.deepcopy(project["netAssignments"][0]))
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("duplicate assignment" in item for item in report["errors"]))

    def test_rejects_pin_absent_from_known_custom_footprint(self):
        project = load_project("moto")
        component = next(c for c in project["components"]
                         if c.get("defId") in {d["id"] for d in project["componentDefs"]})
        project["netAssignments"].append({
            "componentId": component["id"],
            "netId": project["nets"][0]["id"],
            "pinId": "__not_a_real_pin__",
        })
        report = run_electrical_sanity(project)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("unknown footprint pin" in item for item in report["errors"]))

    def test_rejects_netlist_connectivity_mismatch_even_when_node_count_is_unchanged(self):
        project = load_project("moto")
        netlist = load_netlist("moto")
        # Move one node to another net without changing the total node count.
        marker = '(node (ref "AGM -in") (pin "1")'
        self.assertIn(marker, netlist)
        altered = netlist.replace(marker, '(node (ref "AGM -in") (pin "99")', 1)
        report = run_electrical_sanity(project, altered)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(".net connectivity does not match JSON" in item
                            for item in report["errors"]))

    def test_rejects_netlist_unknown_component_reference(self):
        project = load_project("moto")
        netlist = load_netlist("moto").replace(
            '(node (ref "AGM -in")',
            '(node (ref "NO SUCH PART")',
            1,
        )
        report = run_electrical_sanity(project, netlist)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("unknown component label" in item for item in report["errors"]))

    def test_rejects_malformed_netlist(self):
        report = run_electrical_sanity(load_project("moto"), '(export (nets (net')
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(".net parse error" in item for item in report["errors"]))

    def test_rejects_non_object_project(self):
        report = run_electrical_sanity([])
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("project root must be an object", report["errors"])


if __name__ == "__main__":
    unittest.main()
