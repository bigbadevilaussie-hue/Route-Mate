"""Collector geometry defaults: deterministic, explicit assumptions, no safety forgery."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector_geometry import build_assumed_geometry, CLEARANCE, PRESET_VERSION


def part(cid, definition, **kwargs):
    return {"id": cid, "defId": definition, "label": cid, **kwargs}


def project(*parts, defs=None):
    return {"components": list(parts), "componentDefs": defs or []}


class CollectorGeometryTests(unittest.TestCase):
    def test_reproducible_and_source_immutable(self):
        data = project(part("C1", "def-cap-polarized", value="1000uF"),
                       part("Q1", "def-pmos", package="to220"))
        before = copy.deepcopy(data)
        one = build_assumed_geometry(data)
        two = build_assumed_geometry(data)
        self.assertEqual(json.dumps(one, sort_keys=True), json.dumps(two, sort_keys=True))
        self.assertEqual(data, before)
        self.assertEqual(one["preset"], PRESET_VERSION)
        self.assertEqual(one["policy"]["routing_use"],
                         "advisory_only_until_placement_transforms_and_spec_amendment")

    def test_assumed_large_cap_and_to220_are_not_measured(self):
        output = build_assumed_geometry(project(
            part("C1", "def-cap-polarized", value="1000uF"),
            part("Q1", "def-pmos", package="to220",
                 footprintOverride={"pins": [
                     {"id": "1", "offsetRow": 1, "offsetCol": 0},
                     {"id": "2", "offsetRow": 2, "offsetCol": 0},
                     {"id": "3", "offsetRow": 3, "offsetCol": 0},
                 ]}),
        ))
        components = {x["id"]: x for x in output["components"]}
        can = components["C1"]["body_solids"][0]
        mosfet = components["Q1"]["body_solids"][0]
        self.assertEqual(can["radius_mm"], 5.0)
        self.assertEqual(can["assumed_standoff_mm"], 1.5)
        self.assertEqual(mosfet["assumed_standoff_mm"], 2.5)
        self.assertEqual(mosfet["shape"], "rectangle")
        self.assertEqual(len(components["Q1"]["pins"]), 3)
        self.assertEqual(components["Q1"]["status"], "ASSUMED_UNVERIFIED")
        self.assertEqual(mosfet["provenance"]["kind"], "assumed_standard")

    def test_custom_footprint_preserves_pin_grid_but_does_not_invent_body(self):
        custom = {"id": "custom-1", "width": 4, "height": 2,
                  "pins": [{"id": "A", "offsetRow": 0, "offsetCol": 0},
                           {"id": "B", "offsetRow": 1, "offsetCol": 3}],
                  "bodyCells": [{"row": 0, "col": 1}]}
        result = build_assumed_geometry(project(part("U1", "custom-1"), defs=[custom]))
        obj = result["components"][0]
        self.assertEqual(obj["pins"][1]["x_mm"], 7.62)
        self.assertEqual(obj["status"], "UNVERIFIED")
        self.assertEqual(obj["body_solids"], [])
        self.assertEqual(result["unverified_count"], 1)

    def test_unknown_footprint_stays_unknown(self):
        result = build_assumed_geometry(project(part("?", "custom-missing")))
        self.assertEqual(result["components"][0]["reason"], "footprint_unresolved")
        self.assertEqual(result["components"][0]["body_solids"], [])

    def test_clearance_defaults_are_fixed_and_nonnegative(self):
        self.assertEqual(CLEARANCE["wire_od_mm"], 0.9)
        self.assertEqual(CLEARANCE["min_clearance_mm"], 0.3)
        self.assertEqual(CLEARANCE["search_preference_margin_mm"], 0.0)
        self.assertEqual(build_assumed_geometry(project())["component_count"], 0)

    def test_collector_cli_writes_sidecar_and_hash_to_manifest(self):
        from collect import main
        import hashlib
        import sys
        data = project(part("C1", "def-cap-polarized", value="10uF"))
        data.update({
            "board": {"rows": 10, "cols": 15, "cuts": [], "wires": []},
            "nets": [], "netAssignments": [],
        })
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            source = path / "input.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            out = path / "collection"
            args = [
                "collect.py", "--json", str(source),
                "--actual-rows", "10", "--actual-cols", "15",
                "--wanted-rows-mode", "max", "--wanted-rows", "10",
                "--wanted-cols-mode", "max", "--wanted-cols", "15",
                "--out", str(out),
            ]
            with patch.object(sys, "argv", args):
                self.assertEqual(main(), 0)
            geometry_file = out / "physical_geometry.json"
            manifest = json.loads((out / "manifest.json").read_text())
            sidecar = json.loads(geometry_file.read_text())
            self.assertEqual(manifest["physical_geometry_sidecar"], str(geometry_file))
            self.assertEqual(
                manifest["physical_geometry_sidecar_sha256"],
                hashlib.sha256(geometry_file.read_bytes()).hexdigest(),
            )
            self.assertEqual(sidecar["components"][0]["status"], "ASSUMED_UNVERIFIED")
            self.assertEqual(sidecar["components"][0]["body_solids"][0]["radius_mm"], 2.5)
            self.assertNotIn("physicalClearance",
                             json.loads((out / "projects" / "0.json").read_text()))

    def test_duplicate_ids_and_bad_pin_coordinates_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate component IDs"):
            build_assumed_geometry(project(part("C1", "def-resistor"),
                                           part("C1", "def-diode")))
        custom = {"id": "bad", "pins": [{"id": "1", "offsetCol": float("nan")}]}
        with self.assertRaisesRegex(ValueError, "finite"):
            build_assumed_geometry(project(part("P1", "bad"), defs=[custom]))


if __name__ == "__main__":
    unittest.main()
