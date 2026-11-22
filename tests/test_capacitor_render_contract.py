"""End-to-end capacitor value, package, collector, sidecar and SVG contracts."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from capacitor_contract import (
    capacitance_farads, capacitor_body_spec,
    capacitor_contract_notes, resolved_capacitor_package,
)
from collector_geometry import PRESET_VERSION, build_assumed_geometry
from geometry_sidecar import (
    assumed_body_pad_keepouts, inspect_assumed_contacts,
    assess_saved_board, make_document,
)
from render.standalone_bridge import (
    _renderer_input, add_assumed_contact_highlights,
)

ROOT = Path(__file__).resolve().parent.parent
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500"></svg>'


def touching_project():
    return {
        "board": {"rows": 12, "cols": 12, "cuts": [], "wires": []},
        "componentDefs": [],
        "components": [
            {"id": "CER", "label": "C4", "defId": "def-capacitor",
             "value": "15pf", "boardPos": {"row": 3, "col": 4}, "rotation": 0},
            {"id": "CAN", "label": "C1", "defId": "def-cap-polarized",
             "value": "1000uF", "boardPos": {"row": 3, "col": 6}, "rotation": 0},
            {"id": "EXT", "label": "J1", "defId": "def-connector-1",
             "offBoard": True, "leads": {"1": {"row": 3, "col": 7}}},
        ],
    }


class CapacitorEndToEndTests(unittest.TestCase):
    def test_upstream_capacitance_parser_cases(self):
        for text, expected in (
            ("15pf", 15e-12), ("100nf", 100e-9),
            ("470µF", 470e-6), ("1000uF", 1e-3),
            ("4u7", 4.7e-6), ("0,1 uF", 1e-7),
        ):
            with self.subTest(value=text):
                self.assertAlmostEqual(capacitance_farads(text), expected)
        self.assertIsNone(capacitance_farads("unknown"))

    def test_real_motomix_ceramics_and_electrolytics_match_renderer(self):
        project = json.loads((ROOT / "benchmarks/moto/motomix.json").read_text())
        original = copy.deepcopy(project)
        parts = {p["label"]: p for p in project["components"]}
        model = build_assumed_geometry(project)
        entries = {p["label"]: p for p in model["components"]}
        self.assertEqual(model["preset"], PRESET_VERSION)
        for label in ("C3", "C4"):
            self.assertEqual(parts[label]["defId"], "def-capacitor")
            self.assertEqual(parts[label]["value"], "15pf")
            self.assertEqual(resolved_capacitor_package(parts[label]), "cap-ceramic")
            self.assertEqual(entries[label]["render_package"], "cap-ceramic")
            self.assertEqual(entries[label]["profile"], "ceramic")
            self.assertEqual(entries[label]["body_solids"][0]["shape"], "rectangle")
            self.assertEqual(
                entries[label]["body_solids"][0]["x_max_mm"]
                - entries[label]["body_solids"][0]["x_min_mm"],
                1.8,
            )
        for label in ("C1", "C6"):
            self.assertEqual(resolved_capacitor_package(parts[label]), "cap-elko")
            self.assertEqual(entries[label]["render_package"], "cap-elko")
            self.assertEqual(entries[label]["profile"], "electrolytic_large")
            self.assertEqual(entries[label]["body_solids"][0]["radius_mm"], 5.0)
        self.assertEqual(project, original)

    def test_render_input_explicitly_resolves_packages_without_source_mutation(self):
        project = json.loads((ROOT / "benchmarks/moto/motomix.json").read_text())
        original = copy.deepcopy(project)
        to_render = _renderer_input(project)
        actual = {p["label"]: p for p in to_render["components"]}
        self.assertEqual(actual["C3"]["package"], "cap-ceramic")
        self.assertEqual(actual["C4"]["package"], "cap-ceramic")
        self.assertEqual(actual["C1"]["package"], "cap-elko")
        self.assertEqual(actual["C6"]["package"], "cap-elko")
        self.assertEqual(project, original)
        self.assertNotIn("package", next(
            p for p in project["components"] if p["label"] == "C4"
        ))

    def test_explicit_package_changes_collector_and_renderer_together(self):
        source = touching_project()
        part = source["components"][0]
        part["package"] = "cap-film"
        model = build_assumed_geometry(source)
        c4 = next(p for p in model["components"] if p["id"] == "CER")
        self.assertEqual(c4["profile"], "film")
        self.assertEqual(c4["render_package"], "cap-film")
        self.assertEqual(capacitor_body_spec(part)["major_mm"], 7.2)
        self.assertEqual(_renderer_input(source)["components"][0]["package"], "cap-film")
        part["package"] = "cap-elko"
        model = build_assumed_geometry(source)
        c4 = next(p for p in model["components"] if p["id"] == "CER")
        self.assertEqual(c4["render_package"], "cap-elko")
        self.assertEqual(c4["body_solids"][0]["shape"], "circle")
        self.assertIn(
            "nonpolarized_symbol_with_electrolytic_body_user_selected",
            capacitor_contract_notes(part),
        )

    def test_nominal_body_touch_and_external_pad_are_advisory_and_red(self):
        project = touching_project()
        source = copy.deepcopy(project)
        solids = assumed_body_pad_keepouts(project)
        self.assertEqual({p["label"] for p in solids}, {"C1", "C4"})
        contacts = inspect_assumed_contacts(project)
        self.assertTrue(any(c["kind"] == "body_body" and
                            set(c["components"]) == {"C1", "C4"}
                            for c in contacts), contacts)
        self.assertTrue(any(c["kind"] == "external_pad_body" and
                            c["components"] == ["J1", "C1"] and
                            c["pad"]["col"] == 7 for c in contacts), contacts)
        self.assertTrue(all(c["certainty"] == "ASSUMED_UNVERIFIED"
                            for c in contacts))
        document = make_document(project)
        report = assess_saved_board(project, document)
        self.assertEqual(report["contacts_status"], "ASSUMED_CONTACT_RISK")
        self.assertEqual(report["contact_findings"], contacts)
        self.assertFalse(report["physical_signoff"])
        top = add_assumed_contact_highlights(SVG, project)
        copper = add_assumed_contact_highlights(SVG, project, mirrored=True)
        self.assertIn('data-route-mate-cap-package="cap-ceramic"', top)
        self.assertIn('data-route-mate-cap-package="cap-elko"', top)
        self.assertIn('data-route-mate-nominal-contact="body"', top)
        self.assertIn('data-route-mate-nominal-contact="pad"', top)
        self.assertIn('stroke="#e11d48"', top)
        self.assertIn('data-route-mate-nominal-contact="body"', copper)
        self.assertEqual(project, source)

    def test_clearance_on_distant_parts_never_raises_contact_alarm(self):
        project = touching_project()
        project["components"][1]["boardPos"] = {"row": 10, "col": 10}
        project["components"][2]["leads"]["1"] = {"row": 0, "col": 0}
        self.assertEqual(inspect_assumed_contacts(project), [])
        svg = add_assumed_contact_highlights(SVG, project)
        self.assertNotIn("data-route-mate-nominal-contact", svg)
        self.assertIn('data-route-mate-cap-package="cap-ceramic"', svg)


if __name__ == "__main__":
    unittest.main()
