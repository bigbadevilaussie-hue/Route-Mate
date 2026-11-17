#!/usr/bin/env python3
"""Collect a Karl/Stripboard Editor project into the legacy solver campaign format.

This ports the useful preparation steps found in stripboard-optimiser:
- validate project JSON shape;
- normalise the fields used by the GUI's prepareProjectState();
- merge missing custom footprints from a KiCad .pretty ZIP/directory;
- compare .net node count with JSON netAssignments (desktop GUI preflight);
- freeze one project as data/projects/<id>.json and write data/index.json.

It deliberately does not invent connectivity. The GUI recalculates nets from
schematic wires, labels and pin geometry; this collector preserves the exported
JSON nets/assignments and reports the .net comparison. Exact connectivity
recalculation will be shared with the engine rather than approximated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_IDS = {
    "def-resistor", "def-capacitor", "def-cap-polarized", "def-led",
    "def-diode", "def-potentiometer", "def-switch", "def-zener",
    "def-pushbutton", "def-inductor", "def-fuse", "def-transformer",
    "def-npn", "def-pnp", "def-nmos", "def-pmos", "def-555",
    "def-esp32-devkit-v1", "def-esp32-devkit-v1-36",
    "def-esp32-devkitc-38", "def-arduino-nano", "def-trimpot",
    "def-opamp", "def-vreg", "def-optocoupler",
    "def-generic-3pin-compact", "def-generic-3pin-spaced",
}
DEFAULT_IDS.update(f"def-connector-{n}" for n in range(1, 21))
DEFAULT_IDS.update(f"def-ic-dip{n}" for n in (4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40))
DEFAULT_IDS.update(f"def-generic-2pin-{n}h" for n in (2, 3, 4, 5, 7))

def is_default_id(value: str | None) -> bool:
    if not value:
        return False
    return (
        value in DEFAULT_IDS
        or value.startswith("def-ic-")
        or bool(re.fullmatch(r"def-generic-2pin-\\d+h", value))
    )

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def norm_name(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).lower()

def component_def_id(component: dict[str, Any]) -> str | None:
    value = component.get("defId") or component.get("componentDefId")
    return str(value) if value else None

def validate_project(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("project JSON root must be an object")
    for key in ("components", "nets", "netAssignments"):
        if key not in data or not isinstance(data[key], list):
            raise ValueError(f"project JSON must contain an array named {key!r}")
    if not isinstance(data.get("board"), dict):
        raise ValueError("project JSON must contain a board object")
    for key in ("components", "nets", "netAssignments"):
        if any(not isinstance(item, dict) for item in data[key]):
            raise ValueError(f"every item in {key!r} must be an object")
    return data

def parse_kicad_mod(text: str) -> dict[str, Any] | None:
    """Port of the old GUI's pad/label-to-stripboard-footprint conversion."""
    pads = []
    for m in re.finditer(
        r'\(pad\s+"([^"]+)"[^(]*\(at\s+(-?[\d.]+)\s+(-?[\d.]+)',
        text,
    ):
        pads.append({"id": m.group(1), "x": float(m.group(2)), "y": float(m.group(3))})
    if not pads:
        return None

    labels = []
    for m in re.finditer(
        r'\(fp_text user\s+"([^"]+)"\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)',
        text,
    ):
        labels.append({"name": m.group(1), "x": float(m.group(2)), "y": float(m.group(3))})

    for pad in pads:
        pad["name"] = next(
            (label["name"] for label in labels
             if abs(pad["x"] - label["x"]) < 0.1 and abs(pad["y"] - label["y"]) < 0.1),
            pad["id"],
        )

    min_x = min(p["x"] for p in pads)
    min_y = min(p["y"] for p in pads)
    max_x = max(p["x"] for p in pads)
    max_y = max(p["y"] for p in pads)
    width = int(round((max_x - min_x) / 2.54)) + 1
    height = int(round((max_y - min_y) / 2.54)) + 1
    pins = [
        {
            "id": p["id"], "name": p["name"],
            "offsetRow": int(round((p["y"] - min_y) / 2.54)),
            "offsetCol": int(round((p["x"] - min_x) / 2.54)),
        }
        for p in pads
    ]
    pin_cells = {(p["offsetRow"], p["offsetCol"]) for p in pins}
    body = [
        {"row": row, "col": col}
        for row in range(height) for col in range(width)
        if (row, col) not in pin_cells
    ]
    return {"width": width, "height": height, "pins": pins, "bodyCells": body}

def read_footprints(source: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read .kicad_mod files from a .pretty directory, ZIP, or single file."""
    result: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    def add(name: str, raw: str) -> None:
        stem = Path(name).name
        if stem.endswith(".kicad_mod"):
            stem = stem[:-len(".kicad_mod")]
        parsed = parse_kicad_mod(raw)
        if parsed:
            result[stem] = parsed

    if source.is_dir():
        for file in sorted(source.rglob("*.kicad_mod")):
            if file.name.startswith("._"):
                continue
            add(file.name, file.read_text(encoding="utf-8", errors="replace"))
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith(".kicad_mod") and not Path(name).name.startswith("._"):
                    add(name, archive.read(name).decode("utf-8", errors="replace"))
    else:
        # Also accept a single modern .kicad_mod file. Legacy KiCad .mod
        # libraries are not silently misread as modern S-expressions.
        if source.suffix == ".kicad_mod":
            add(source.name, source.read_text(encoding="utf-8", errors="replace"))
        else:
            warnings.append(
                f"{source.name}: not a .pretty directory/ZIP or .kicad_mod; "
                "no footprints parsed (legacy .mod syntax is not yet supported)"
            )
    return result, warnings

def merge_footprints(data: dict[str, Any], footprints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    defs = data.setdefault("componentDefs", [])
    if not isinstance(defs, list):
        raise ValueError("componentDefs must be an array")
    existing = {str(d.get("id")) for d in defs if isinstance(d, dict) and d.get("id")}
    parsed_names = list(footprints)

    for component in data["components"]:
        did = component_def_id(component)
        if not did or did in existing:
            continue
        label = str(component.get("label") or component.get("name") or "")
        clean = norm_name(label)
        if not clean:
            continue
        matches = [
            name for name in parsed_names
            if clean in norm_name(name) or norm_name(name) in clean
        ]
        if not matches:
            continue
        # Match the GUI's first-match rule, but keep an audit warning if it
        # could have selected a different footprint.
        chosen = matches[0]
        definition = dict(footprints[chosen])
        definition.update({
            "id": did,
            "name": label,
            "category": "generic",
            "symbol": f"custom-footprint-{did}",
            "defaultLabelPrefix": "?",
        })
        defs.append(definition)
        existing.add(did)
        if len(matches) > 1:
            data.setdefault("_collectWarnings", []).append(
                f"{label}: multiple footprint filename matches {matches}; GUI first-match rule chose {chosen}"
            )
    return data

def normalise_like_gui(data: dict[str, Any]) -> dict[str, Any]:
    """Mirror prepareProjectState() defaults without rewriting source identity."""
    default_ids = DEFAULT_IDS
    saved_defs = data.get("componentDefs") or []
    if not isinstance(saved_defs, list):
        raise ValueError("componentDefs must be an array")
    # The editor combines built-ins + project custom definitions. The solver
    # does the same at runtime, so the campaign JSON stores only custom defs.
    data["componentDefs"] = [
        d for d in saved_defs
        if isinstance(d, dict) and d.get("id") and not is_default_id(str(d["id"]))
    ]
    data["components"] = [
        {**c, "schematicRotation": c.get("schematicRotation", 0)}
        for c in data["components"]
    ]
    data["netLabels"] = data.get("netLabels") or []
    data["schematicWires"] = data.get("schematicWires") or []
    data["wiring"] = data.get("wiring") or "classic"
    board = data["board"]
    board["rows"] = board.get("rows") or 20
    board["cols"] = board.get("cols", board.get("columns")) or 20
    board["cuts"] = board.get("cuts") or []
    board["wires"] = board.get("wires") or []
    return data

def count_netlist_nodes(path: Path) -> int:
    # Same contract as desktop ImportService.count_netlist_nodes().
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"(?m)^\s*\(node\s+\(ref\b", text))

def netlist_hash(data: dict[str, Any]) -> str:
    def_id = {str(c.get("id")): component_def_id(c) for c in data["components"]}
    nets: dict[str, list[str]] = {}
    for assignment in data["netAssignments"]:
        net_id = str(assignment.get("netId", ""))
        nets.setdefault(net_id, []).append(
            f"{def_id.get(str(assignment.get('componentId')), '?')}:{assignment.get('pinId', '?')}"
        )
    signature = sorted("|".join(sorted(pins)) for pins in nets.values())
    return hashlib.sha1(json.dumps(signature, separators=(",", ":")).encode()).hexdigest()[:12]

def layout_hash(data: dict[str, Any]) -> str:
    comps = [
        {key: c.get(key) for key in (
            "id", "defId", "componentDefId", "footprintOverride", "boardPos",
            "flexibleEndPos", "rotation", "boardExcluded", "locked"
        )}
        for c in data["components"]
    ]
    board = data["board"]
    payload = {
        "comps": comps, "assignments": data["netAssignments"],
        "rows": board["rows"], "cols": board["cols"],
        "wires": board["wires"], "cuts": board["cuts"],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]

def campaign_index(data: dict[str, Any], project_id: int) -> dict[str, Any]:
    defs = {str(d["id"]): d for d in data.get("componentDefs", []) if d.get("id")}
    comp_ids = {str(c.get("id")) for c in data["components"]}
    assigned_ids = {str(a.get("componentId")) for a in data["netAssignments"]}
    placeable = [c for c in data["components"] if not c.get("boardExcluded")]
    unresolved = sum(
        1 for c in data["components"]
        if (did := component_def_id(c))
        and did not in defs and did not in DEFAULT_IDS
    )
    net_by_pin = {
        (str(a.get("componentId")), str(a.get("pinId"))): str(a.get("netId"))
        for a in data["netAssignments"]
    }
    shorted = 0
    for component in data["components"]:
        did = component_def_id(component)
        definition = defs.get(did or "")
        if not definition or definition.get("flexible"):
            continue
        seen: dict[tuple[int, int], str] = {}
        for pin in definition.get("pins", []):
            net = net_by_pin.get((str(component.get("id")), str(pin.get("id"))))
            if not net:
                continue
            cell = (int(pin.get("offsetRow", 0)), int(pin.get("offsetCol", 0)))
            if cell in seen and seen[cell] != net:
                shorted += 1
                break
            seen[cell] = net
    board = data["board"]
    return {
        "id": project_id,
        "parts": len(placeable),
        "nets": len(data["nets"]),
        "assignments": len(data["netAssignments"]),
        "rows": board["rows"],
        "cols": board["cols"],
        "wires": len(board["wires"]),
        "cuts": len(board["cuts"]),
        "conflicts": -1,
        "incomplete": -1,
        "unresolvedDefs": unresolved,
        "shortedDefs": shorted,
        "removedParts": len(comp_ids - assigned_ids),
        "netlistHash": netlist_hash(data),
        "layoutHash": layout_hash(data),
        "dupIds": [],
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, required=True, help="Karl/Stripboard Editor project JSON")
    parser.add_argument("--net", type=Path, help="matching KiCad .net export (node-count cross-check)")
    parser.add_argument("--mod", type=Path, help=".pretty directory, ZIP archive, or one .kicad_mod file")
    parser.add_argument("--id", type=int, default=0, help="project id used by the campaign runner")
    parser.add_argument("--out", type=Path, default=Path("campaign-input"), help="campaign data directory")
    args = parser.parse_args()

    for name, path in (("JSON", args.json), ("NET", args.net), ("MOD", args.mod)):
        if path is not None and not path.exists():
            parser.error(f"{name} input does not exist: {path}")

    try:
        data = validate_project(json.loads(args.json.read_text(encoding="utf-8")))
        data = normalise_like_gui(data)
        warnings = list(data.pop("_collectWarnings", []))

        footprint_count = 0
        if args.mod:
            footprints, fp_warnings = read_footprints(args.mod)
            warnings.extend(fp_warnings)
            before = len(data.get("componentDefs", []))
            merge_footprints(data, footprints)
            footprint_count = len(data.get("componentDefs", [])) - before
            warnings.extend(data.pop("_collectWarnings", []))

        missing = []
        known = {str(d.get("id")) for d in data.get("componentDefs", []) if d.get("id")} | DEFAULT_IDS
        for component in data["components"]:
            did = component_def_id(component)
            if did and did not in known and not is_default_id(did):
                missing.append({"component": component.get("label") or component.get("id"), "defId": did})

        net_nodes = None
        if args.net:
            net_nodes = count_netlist_nodes(args.net)
            if net_nodes != len(data["netAssignments"]):
                raise ValueError(
                    f"CRITICAL MISMATCH: JSON has {len(data['netAssignments'])} pin assignments, "
                    f".net has {net_nodes} (node (ref ...) records)"
                )

        entry = campaign_index(data, args.id)
        if missing:
            warnings.append(f"{len(missing)} component definitions remain unresolved")
        if entry["shortedDefs"]:
            warnings.append(f"{entry['shortedDefs']} custom footprint(s) place different-net pins on the same hole")
        warnings.append("Built-in footprint short checks are left to the solver verifier; this collector only has project custom-footprint geometry.")
        if net_nodes is not None:
            entry["netlistNodes"] = net_nodes

        out = args.out.resolve()
        projects = out / "projects"
        projects.mkdir(parents=True, exist_ok=True)
        target = projects / f"{args.id}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(target)
        (out / "index.json").write_text(json.dumps([entry], indent=2) + "\n", encoding="utf-8")

        sources = out / "sources"
        sources.mkdir(exist_ok=True)
        for source in (args.json, args.net, args.mod):
            if source is not None and source.is_file():
                shutil.copy2(source, sources / source.name)

        manifest = {
            "project_id": args.id,
            "source_json": str(args.json.resolve()),
            "source_json_sha256": sha256(args.json),
            "netlist": str(args.net.resolve()) if args.net else None,
            "netlist_sha256": sha256(args.net) if args.net else None,
            "footprint_source": str(args.mod.resolve()) if args.mod else None,
            "footprint_files_parsed": footprint_count,
            "campaign_project": str(target),
            "campaign_index": str(out / "index.json"),
            "netlist_nodes": net_nodes,
            "json_pin_assignments": len(data["netAssignments"]),
            "component_count": len(data["components"]),
            "custom_definition_count": len(data.get("componentDefs", [])),
            "warnings": warnings,
            "connectivity_policy": "preserve exported JSON nets/netAssignments; .net is a node-count cross-check",
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        print(f"COLLECTED project {args.id}")
        print(f"  components: {len(data['components'])}")
        print(f"  nets / pin assignments: {len(data['nets'])} / {len(data['netAssignments'])}")
        print(f"  custom definitions: {len(data.get('componentDefs', []))}")
        print(f"  footprints added: {footprint_count}")
        if net_nodes is not None:
            print(f"  .net node records: {net_nodes} (matched)")
        print(f"  unresolved definitions: {entry['unresolvedDefs']}")
        print(f"  shorted footprints: {entry['shortedDefs']}")
        print(f"  campaign input: {target}")
        for warning in warnings:
            print(f"  WARNING: {warning}")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"collect: ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
