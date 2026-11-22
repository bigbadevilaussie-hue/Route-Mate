"""Verify actual standalone-renderer output against each capacitor collector profile.

Usage:
    python tools/audit_capacitor_renderer.py benchmarks/moto/motomix.json

This invokes the production Node renderer (not the Python fallback). It fails
if rendered shape/type/dimensions disagree with the shared collector and
versioned sidecar. Nominal artwork dimensions are NOT measurements.
"""
from __future__ import annotations

import copy
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capacitor_contract import capacitor_body_spec
from collector_geometry import build_assumed_geometry
from geometry_sidecar import make_document
from render.standalone_bridge import render_project_data


COLOURS = {
    "cap-ceramic": "#c89b4a",
    "cap-film": "#3565a8",
    "cap-elko": "#20395c",
}


def audit_file(source: Path) -> list[dict]:
    project = json.loads(source.read_text(encoding="utf-8"))
    results = []
    for part in project.get("components", []):
        spec = capacitor_body_spec(part)
        if spec is None:
            continue
        isolated = copy.deepcopy(project)
        isolated["components"] = [copy.deepcopy(part)]
        isolated["netAssignments"] = []
        isolated["nets"] = []
        isolated["board"] = {
            "rows": 12, "cols": 12, "cuts": [], "wires": [],
        }
        mounted = isolated["components"][0]
        mounted["boardPos"] = {"row": 4, "col": 4}
        mounted.pop("flexibleEndPos", None)
        mounted.pop("offBoard", None)
        mounted.pop("boardExcluded", None)
        model = build_assumed_geometry(isolated)
        entry = model["components"][0]
        assert entry["render_package"] == spec["package"], entry
        assert entry["body_solids"][0]["shape"] == spec["shape"], entry
        document = make_document(isolated, model)
        assert document["geometry"]["components"][0] == entry

        top, copper, _ = render_project_data(isolated)
        assert "<svg" in top and "<svg" in copper
        xml = ET.fromstring(top)
        colour = COLOURS[spec["package"]]
        body = next(
            (el for el in xml.iter() if el.attrib.get("fill") == colour
             and el.tag.split("}")[-1] in ("circle", "rect")),
            None,
        )
        assert body is not None, (
            f"{part.get('label')} ({spec['package']}): "
            f"production SVG missing expected {colour} body"
        )
        label = part.get("label") or part.get("id")
        if spec["shape"] == "circle":
            actual = float(body.attrib["r"]) * 2
            expected = spec["major_mm"]
            assert abs(actual - expected) < 0.001, (label, actual, expected)
            render_shape = "circle"
        else:
            actual = (float(body.attrib["width"]), float(body.attrib["height"]))
            expected = (spec["major_mm"], spec["minor_mm"])
            assert all(abs(a - b) < 0.001 for a, b in zip(actual, expected)), (
                label, actual, expected,
            )
            render_shape = "rectangle"
        assert f'data-route-mate-cap-package="{spec["package"]}"' in top
        results.append({
            "label": label, "value": part.get("value"),
            "package": spec["package"], "shape": render_shape,
            "collector_profile": entry["profile"], "artwork_mm": actual,
            "preset": model["preset"],
        })
    return results


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "benchmarks/moto/motomix.json"
    )
    rows = audit_file(path)
    assert rows, f"no capacitors to inspect in {path}"
    for row in rows:
        print("CAP_RENDER=PASS " + " ".join(
            f"{k}={v}" for k, v in row.items()
        ), flush=True)
    print(f"CAP_RENDER_TOTAL=PASS {len(rows)} part(s); "
          "nominal dimensions, not measured physical clearance", flush=True)
